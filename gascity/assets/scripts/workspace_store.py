#!/usr/bin/env python3
"""Exact-store workspace records through one native guarded metadata batch.

This module does not allocate native work, claim a session, or enable new-mode
formulas. Dedicated record and grant IDs must already name closed, unassigned
placeholders. Workflow-specific source, Git, evidence and publication decisions
remain the responsibilities of their designated writers.
"""
from __future__ import annotations

import contextlib
import contextvars
import copy
import errno
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workspace_records import (RecordError, canonical_bytes, contracts, parse_record,
                               record_identity, record_sha256, validate_record,
                               verify_replay)

MISSING = object()
GRANT_KEY = "gc.workspace_write_grant"
GRANT_REFS_KEY = "gc.workspace_write_grant_refs"
CLAIM_NONCE_KEY = "gc.workspace_write_nonce"
TRANSITION_NONCE_KEY = "gc.workspace_transition_nonce"
MAX_ROWS = 100
TOPOLOGY = "gc.native_step_dependencies.v1"
ROOT_KEYS = ("workflow_id", "molecule_id", "gc.root_bead_id")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
STORE_REF = re.compile(r"(?:city|rig):[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SCOPE_FIELDS = {"workflow_root_id", "generation", "writer_scope_id", "record_kind"}
REFERENCE_KEYS = {value["metadata_key"] + "_ref": kind for kind, value in contracts().items()}
SCOPE_OWNER = {"run": "workflow_root_id", "source-plan": "source_plan_owner_id",
               "workspace": "workspace_owner_id", "member-result": "member_id",
               "owner-output": "workspace_owner_id", "canonical": "source_plan_owner_id",
               "review": "review_id", "publish": "publish_id", "blocker": "workspace_owner_id"}
ROUTING_ENV = ("GC_CITY_URL", "GC_CITY_CONTEXT", "GC_CITY", "GC_CITY_PATH",
               "GC_CITY_ROOT", "GC_RIG")
_HELD_LOCKS = contextvars.ContextVar("workspace_transition_locks", default=frozenset())
_SUBMITTED_REQUESTS = set()
OWNER_PROJECTION_KEYS = {"gc.root_bead_id", "gc.root_store_ref", "gc.work_dir", "gc.work_branch",
    "gc.worktree_repo", "gc.worktree_root", "gc.worktree_base_ref", "gc.worktree_base_sha",
    "gc.worktree_creator", "gc.worktree_owner", "gc.worktree_generation", "gc.worktree_lifecycle",
    "gc.worktree_mode", "gc.worktree_placement"}


class StoreError(RecordError):
    pass


@dataclass(frozen=True)
class CookedWriterMap:
    """Exact physical occurrences and responsibilities from one native expansion."""
    declaration_bytes: bytes

    @property
    def declaration(self) -> dict:
        require(isinstance(self.declaration_bytes, bytes), "map requires canonical declaration bytes")
        try:
            return parse_record(self.declaration_bytes.decode("utf-8"))
        except (UnicodeError, RecordError) as exc:
            raise StoreError("cooked writer admission: malformed occurrence map") from exc


def require(condition, message):
    if not condition:
        raise StoreError("cooked writer admission: " + message)


def _root(row):
    metadata = row["metadata"]
    return next((metadata[key] for key in ROOT_KEYS if metadata.get(key)), None)


def _native_step_id(value):
    try:
        return isinstance(value, str) and bool(value.strip()) and len(value.encode("utf-8")) <= 256
    except UnicodeError:
        return False


def _dependencies(metadata):
    raw = metadata.get(TOPOLOGY)
    require(isinstance(raw, str), "native dependency fact is absent")
    try:
        dependencies = json.loads(raw)
    except ValueError as exc:
        raise StoreError("cooked writer admission: malformed native dependency fact") from exc
    require(isinstance(dependencies, list) and all(_native_step_id(item) for item in dependencies),
            "native dependency fact is unknown or noncanonical")
    # Match encoding/json.Marshal, including its default HTML and line escaping.
    encoded = json.dumps(dependencies, ensure_ascii=False, separators=(",", ":"))
    for character, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                              ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        encoded = encoded.replace(character, escape)
    require(dependencies == sorted(set(dependencies)) and metadata.get("gc.step_id") not in dependencies
            and encoded == raw, "native dependency fact is unknown or noncanonical")
    return dependencies


def _kinds(metadata, step_ref):
    """Fixed pack responsibilities; native control beads never write payloads."""
    if metadata.get("gc.kind") in ("retry", "ralph", "check", "source-spec"):
        return []
    stage = metadata.get("gc.step_id", step_ref).rsplit(".", 1)[-1]
    schema = metadata.get("gc.build.artifact_schema")
    if stage in ("prepare", "prepare-requirements") and metadata.get("gc.lifecycle") in ("legacy", "new"):
        return ["run"]
    if stage == "decompose" and schema == "gc.build.decomposition.v1":
        return ["source-plan"]
    if stage == "plan-fixes" and metadata.get("gc.run_target") == "gc.run-operator":
        return ["source-plan"]
    if stage == "prepare-worktree" and metadata.get("gc.run_target") == "gc.run-operator":
        return ["blocker", "workspace"]
    if stage in ("implement", "implement-item", "record-item-result", "apply-story-findings") and schema == "gc.build.implementation-summary.v1":
        return ["workspace"]
    if stage in ("qualify", "record-member-result", "record-result") and metadata.get("gc.run_target") == "gc.run-operator":
        return ["member-result", "owner-output", "workspace"]
    if stage in ("review", "review-result", "independent-acceptance") and metadata.get("gc.run_target") == "gc.implementation-reviewer":
        return ["review"]
    if stage in ("record-canonical", "summarize-implementation") and metadata.get("gc.run_target") == "gc.run-operator":
        return ["canonical"]
    if stage == "publish" and metadata.get("gc.run_target") == "gc.publisher":
        return ["publish"]
    if stage == "close-source-anchor" and metadata.get("gc.run_target") == "gc.run-operator":
        return ["workspace"]
    return []


def _formula_identity(root):
    metadata = root["metadata"]
    name, digest, source = (metadata.get(key) for key in
                            ("gc.formula_name", "gc.formula_hash", "gc.formula_source"))
    require(all(isinstance(value, str) and value for value in (name, digest, source)),
            "native expansion lacks formula name/hash/source")
    require(Path(source).is_absolute() and re.fullmatch(r"[0-9a-f]{64}", digest),
            "native formula identity is malformed")
    return name, digest, source


def validate_cooked_writer_map(writer_map, snapshots, *, store_ref, workflow_root_id,
                              record_kind, claimed_step_id, read_only=False):
    require(type(read_only) is bool, "read_only requires an explicit boolean")
    require((isinstance(record_kind, str) and record_kind in contracts()) or (read_only and record_kind is None),
            "a designated record kind is required outside explicit read-only admission")
    require(isinstance(writer_map, CookedWriterMap), "typed native occurrence map is required")
    data = writer_map.declaration
    require(set(data) == {"version", "workflow_root_id", "store_ref", "source_member_id", "expansion_root_id",
                         "formula_name", "formula_hash", "formula_source", "steps"}
            and type(data["version"]) is int and data["version"] == 1
            and data["workflow_root_id"] == workflow_root_id and data["store_ref"] == store_ref
            and canonical_bytes(data) == writer_map.declaration_bytes, "native occurrence map scope changed")
    for field in ("workflow_root_id", "source_member_id", "expansion_root_id"):
        _id(data[field], field)
    require(isinstance(data["steps"], list) and 1 <= len(data["steps"]) <= MAX_ROWS,
            "native physical occurrence list is absent or oversized")
    require(data["expansion_root_id"] in snapshots and data["source_member_id"] in snapshots,
            "native expansion or source member is absent from the guarded operation")
    expansion = snapshots[data["expansion_root_id"]]
    require(_formula_identity(expansion) == (data["formula_name"], data["formula_hash"], data["formula_source"]),
            "native expansion identity changed")
    require(_root(expansion) in (None, workflow_root_id) and expansion["metadata"].get("gc.root_store_ref") == store_ref,
            "native expansion belongs to another root/store")
    member_row = snapshots[data["source_member_id"]]
    require((data["source_member_id"] == workflow_root_id or _root(member_row) == workflow_root_id)
            and member_row["metadata"].get("gc.root_store_ref") == store_ref,
            "source member belongs to another native root/store")
    seen_ids, seen_refs, semantic = set(), set(), {}
    for item in data["steps"]:
        require(isinstance(item, dict) and set(item) == {"bead_id", "step_id", "step_ref", "dependencies", "record_kinds"},
                "native physical occurrence is malformed")
        _id(item["bead_id"], "occurrence bead_id")
        require(_native_step_id(item["step_id"]) and isinstance(item["step_ref"], str) and item["step_ref"].strip()
                and item["bead_id"] not in seen_ids and item["step_ref"] not in seen_refs
                and item["bead_id"] in snapshots, "native physical occurrences are ambiguous or absent")
        seen_ids.add(item["bead_id"])
        seen_refs.add(item["step_ref"])
        row = snapshots[item["bead_id"]]
        metadata = row["metadata"]
        require(_root(row) == workflow_root_id and metadata.get("gc.root_store_ref") == store_ref,
                "native step belongs to another root/store")
        require((metadata.get("gc.attach_root_id") or workflow_root_id) == data["expansion_root_id"],
                "native step belongs to a sibling expansion")
        member = metadata.get("gc.source_anchor_id", metadata.get("gc.drain_member_id", workflow_root_id))
        require(member == data["source_member_id"] and metadata.get("gc.drain_member_id", member) == member,
                "native step belongs to another source member")
        require(item["step_id"] == metadata.get("gc.step_id") and item["step_ref"] == metadata.get("gc.step_ref")
                and item["dependencies"] == _dependencies(metadata)
                and item["record_kinds"] == _kinds(metadata, item["step_ref"]),
                "native writer facts or responsibilities changed")
        semantic.setdefault(item["step_id"], []).append(item)
    for step_id, occurrences in semantic.items():
        if len(occurrences) == 1:
            continue
        controls = [item for item in occurrences if snapshots[item["bead_id"]]["metadata"].get("gc.kind") == "retry"]
        attempts = [item for item in occurrences if snapshots[item["bead_id"]]["metadata"].get("gc.control_for") == step_id
                    and snapshots[item["bead_id"]]["metadata"].get("gc.kind") != "retry"]
        require(len(occurrences) == 2 and len(controls) == len(attempts) == 1
                and controls[0]["dependencies"] == attempts[0]["dependencies"],
                "multiple semantic writer occurrences lack exact native retry lineage")
    require(claimed_step_id in seen_ids, "claimed native step has no exact physical occurrence")
    if not (read_only and record_kind is None):
        require(record_kind in next(item["record_kinds"] for item in data["steps"]
                                    if item["bead_id"] == claimed_step_id),
                "claimed native step is not designated for this record kind")
    require(all(set(item["dependencies"]).issubset(semantic) for item in data["steps"]),
            "native dependency has no exact physical occurrence in this expansion")
    return data


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) > 512 or not ID.fullmatch(value):
        raise StoreError(f"{field} requires an exact physical identifier")
    return value


def _scope(scope: dict) -> dict:
    if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
        raise StoreError("scope requires workflow_root_id, generation, writer_scope_id and record_kind")
    _id(scope["workflow_root_id"], "workflow_root_id")
    _id(scope["writer_scope_id"], "writer_scope_id")
    if type(scope["generation"]) is not int or scope["generation"] < 1:
        raise StoreError("generation requires a positive integer")
    if not isinstance(scope["record_kind"], str) or scope["record_kind"] not in contracts():
        raise StoreError("scope has an unknown record_kind namespace")
    return copy.deepcopy(scope)


@dataclass(frozen=True)
class Attempt:
    session_id: str
    instance_token: str
    claimed_bead_id: str

    def __post_init__(self):
        _id(self.session_id, "session_id")
        _id(self.claimed_bead_id, "claimed_bead_id")
        if not isinstance(self.instance_token, str) or not self.instance_token.strip() or any(ord(c) < 32 for c in self.instance_token):
            raise StoreError("instance_token requires the retained nonempty native token")

    @classmethod
    def from_env(cls, claimed_bead_id: str):
        return cls(os.environ.get("GC_SESSION_ID", ""), os.environ.get("GC_INSTANCE_TOKEN", ""), claimed_bead_id)

    @property
    def admission(self) -> dict:
        return {"session_id": self.session_id, "instance_token": self.instance_token,
                "claimed_bead_id": self.claimed_bead_id}

    @property
    def writer_attempt_id(self) -> str:
        return "writer-" + hashlib.sha256(canonical_bytes(self.admission)).hexdigest()


@dataclass(frozen=True)
class RecordWrite:
    kind: str
    bead_id: str
    payload: dict


@dataclass(frozen=True)
class ReferenceWrite:
    bead_id: str
    key: str
    value: dict


@dataclass(frozen=True)
class GuardRead:
    bead_id: str
    key: str
    expected_value: Any


@dataclass(frozen=True)
class NativeOwnerProjection:
    workspace_bead_id: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class NativeWorktreeReference:
    bead_id: str
    workspace_bead_id: str
    reference: dict


@dataclass(frozen=True)
class SourceMembershipProjection:
    bead_id: str
    root_id: str
    generation: int


@dataclass(frozen=True)
class SourcePlanConvoyBinding:
    convoy_id: str


@dataclass(frozen=True)
class RunCheckPolicyProjection:
    run_record_id: str
    payload: dict


@dataclass(frozen=True)
class SuccessorRelation:
    source_plan_bead_id: str
    reference_bead_id: str


@dataclass(frozen=True)
class PreparedWrite:
    """Frozen request/readback intent: never refresh a paused writer's guards."""
    request_bytes: bytes
    before_bytes: bytes
    after_bytes: bytes
    scope_bytes: bytes
    binding_bytes: bytes
    replay: bool

    @property
    def request(self) -> dict:
        return parse_record(self.request_bytes.decode("utf-8"))

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.request_bytes).hexdigest()


def record_reference(kind: str, bead_id: str, payload: dict) -> dict:
    return {"kind": kind, "identity": list(record_identity(kind, payload)),
            "bead_id": _id(bead_id, "record bead_id")}


def _reference(value: Any) -> dict:
    if not isinstance(value, dict) or set(value) != {"kind", "identity", "bead_id"}:
        raise StoreError("reference requires exact kind, ordered identity and bead_id")
    if value["kind"] not in contracts() or not isinstance(value["identity"], list):
        raise StoreError("unknown or malformed record reference")
    identity = value["identity"]
    if len(identity) != len(contracts()[value["kind"]]["identity"]):
        raise StoreError("reference identity is incomplete")
    for name, entry in zip(contracts()[value["kind"]]["identity"], identity):
        if name == "generation":
            if type(entry) is not int or entry < 1:
                raise StoreError("reference generation requires a positive integer")
        elif name in ("rig_root", "common_git_dir"):
            if not isinstance(entry, str) or not entry.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in entry):
                raise StoreError("reference path requires an absolute spelling")
        else:
            _id(entry, "reference " + name)
    _id(value["bead_id"], "reference bead_id")
    canonical_bytes(value)
    return value


def _metadata_record(row: dict, key: str) -> dict | None:
    raw = row["metadata"].get(key, MISSING)
    if raw is MISSING:
        return None
    if not isinstance(raw, str):
        raise StoreError(f"{row['id']} {key}: pack payload must be a JSON string")
    return parse_record(raw)


def validate_transition(kind: str, stored: dict, candidate: dict) -> bool:
    """Admit only the bounded mutable v1 transitions; immutable records replay."""
    validate_record(kind, stored)
    validate_record(kind, candidate)
    if record_identity(kind, stored) != record_identity(kind, candidate):
        raise StoreError("transition cannot change record identity")
    if canonical_bytes(stored) == canonical_bytes(candidate):
        return True
    if kind not in ("workspace", "publish", "blocker"):
        try:
            verify_replay(kind, stored, candidate)
        except RecordError as exc:
            raise StoreError(str(exc)) from exc
    elif kind == "publish":
        if any(stored[k] != candidate[k] for k in stored if k not in ("writer_step_id", "status", "observed_oid", "pr_url")):
            raise StoreError("publish transition cannot change its intent or authorization")
        if (stored["status"], candidate["status"]) not in {
            ("intended", "uncertain"), ("intended", "observed"), ("uncertain", "observed")}:
            raise StoreError("unsupported publish transition")
    elif kind == "blocker":
        if stored["status"] != "open" or candidate["status"] != "resolved":
            raise StoreError("only an explicit open-to-resolved blocker transition is supported")
        if any(stored[k] != candidate[k] for k in stored if k not in ("writer_step_id", "status", "resolution")) or candidate["resolution"] is None:
            raise StoreError("blocker transition must retain the original blocker and add its decision")
    else:
        stable = ("source_plan_owner_id", "workspace_owner_id", "workspace_bead_id", "strategy", "work_dir", "work_branch")
        if any(stored[k] != candidate[k] for k in stable):
            raise StoreError("workspace transition cannot relocate or change its stable owner")
        if stored["native_provenance"] is not None and any(stored[k] != candidate[k] for k in ("native_attempt_id", "native_provenance")):
            raise StoreError("native provisioning provenance is immutable for its attempt")
        phases = {("preparing", "entry"), ("entry", "active"), ("active", "result"), ("result", "entry")}
        before, after = stored["phase"], candidate["phase"]
        if before != after and (before, after) not in phases and before != "blocked" and after != "blocked":
            raise StoreError("unsupported workspace phase transition")
        if candidate["next_member_position"] < stored["next_member_position"]:
            raise StoreError("workspace member position cannot move backwards")
        if (before, after) == ("result", "entry"):
            if candidate["next_member_position"] != stored["next_member_position"] + 1 or candidate["input_oid"] != stored["current_oid"]:
                raise StoreError("chain advance requires the next member and preceding checkpoint")
        elif candidate["next_member_position"] != stored["next_member_position"] or candidate["active_member_id"] != stored["active_member_id"]:
            raise StoreError("only a result-to-entry transition can advance the active member")
        if before == after and any(stored[k] != candidate[k] for k in ("input_oid", "current_oid", "output_oid", "integration_inputs")):
            raise StoreError("same-phase replay cannot change workspace source state")
    return False


def _filesystem(path: Path) -> str:
    """Linux local-filesystem admission. Unknown platforms/mounts refuse."""
    try:
        entries = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError as exc:
        raise StoreError("local filesystem locking is unsupported on this platform") from exc
    selected = None
    for line in entries:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        fields = left.split()
        mount = fields[4]
        for escape, value in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
            mount = mount.replace(escape, value)
        try:
            path.relative_to(mount)
        except ValueError:
            continue
        if selected is None or len(mount) > len(selected[0]):
            selected = (mount, right.split()[0])
    if selected is None or selected[1] not in ("ext4", "xfs", "btrfs", "zfs", "tmpfs"):
        raise StoreError("transition locks require a verified supported local filesystem")
    return selected[1]


@contextlib.contextmanager
def transition_locks(common_git_dir: Path | str, scope: dict, timeout: float = 30.0):
    """Owner-before-root flock, one total deadline, no unlinked lock inode."""
    try:
        import fcntl
    except ImportError as exc:
        raise StoreError("local transition locking is unsupported on this platform") from exc

    scope = _scope(scope)
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 300:
        raise StoreError("lock timeout must be positive and at most 300 seconds")
    common = Path(common_git_dir)
    if not common.is_absolute() or common != common.resolve(strict=True) or not common.is_dir():
        raise StoreError("common_git_dir requires its canonical existing absolute directory")
    owner_scope = {k: scope[k] for k in SCOPE_FIELDS - {"record_kind"}}
    held_key = (str(common), canonical_bytes(owner_scope))
    if held_key in _HELD_LOCKS.get():
        yield
        return
    _filesystem(common)
    lock_dir = common / "gc-workspace-locks"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    if lock_dir.is_symlink() or not lock_dir.is_dir() or lock_dir.stat().st_uid != os.geteuid():
        raise StoreError("workspace lock directory has unknown ownership")
    if stat.S_IMODE(lock_dir.stat().st_mode) & 0o077:
        raise StoreError("workspace lock directory must be private")
    root = {k: scope[k] for k in ("workflow_root_id", "generation")}
    names = ["owner-" + hashlib.sha256(canonical_bytes(owner_scope)).hexdigest(),
             "root-" + hashlib.sha256(canonical_bytes(root)).hexdigest()]
    opened = []
    directory_fd = os.open(lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    token = None
    deadline = time.monotonic() + timeout
    try:
        for name in names:
            descriptor = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
            opened.append(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
                raise StoreError("workspace lock file has unknown ownership or permissions")
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN):
                        raise StoreError("filesystem refused transition locking") from exc
                    if time.monotonic() >= deadline:
                        raise StoreError("workspace transition lock timeout")
                    time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        directory_info, directory_path = os.fstat(directory_fd), lock_dir.stat()
        if (directory_info.st_dev, directory_info.st_ino) != (directory_path.st_dev, directory_path.st_ino):
            raise StoreError("workspace lock directory changed during acquisition")
        for name, descriptor in zip(names, opened):
            original, current = os.fstat(descriptor), os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
                raise StoreError("workspace lock inode changed during acquisition")
        token = _HELD_LOCKS.set(_HELD_LOCKS.get() | {held_key})
        yield
    finally:
        if token is not None:
            _HELD_LOCKS.reset(token)
        for descriptor in reversed(opened):
            os.close(descriptor)
        os.close(directory_fd)


class WorkspaceStore:
    def __init__(self, store_ref: str, gc: str = "gc", cwd: Path | str | None = None,
                 common_git_dir: Path | str | None = None, timeout: float = 30.0):
        if not isinstance(store_ref, str) or len(store_ref) > 512 or not STORE_REF.fullmatch(store_ref):
            raise StoreError("store_ref requires explicit local city:<name> or rig:<name>")
        if cwd is None or not Path(cwd).is_absolute():
            raise StoreError("cwd must name the explicit absolute city root")
        self.cwd = str(Path(cwd).resolve(strict=True))
        self.store_ref, self.gc = store_ref, str(gc)
        self.common_git_dir, self.timeout = common_git_dir, timeout

    def _binding(self):
        if self.common_git_dir is None:
            raise StoreError("write requires the canonical common Git directory")
        common = Path(self.common_git_dir)
        if not common.is_absolute() or common != common.resolve(strict=True):
            raise StoreError("common Git identity must be an exact canonical existing path")
        return canonical_bytes({"city_root": self.cwd, "store_ref": self.store_ref,
                                "common_git_dir": str(common)})

    def _prepared(self, prepared):
        if not isinstance(prepared, PreparedWrite) or prepared.binding_bytes != self._binding():
            raise StoreError("frozen request belongs to a different city, store or common Git directory")

    def _command(self, arguments: list[str], attempt: Attempt | None = None) -> dict:
        env = os.environ.copy()
        for key in ROUTING_ENV:
            env.pop(key, None)
        if attempt is not None:
            env.update(GC_SESSION_ID=attempt.session_id, GC_INSTANCE_TOKEN=attempt.instance_token)
        command = [self.gc, "--city=" + self.cwd, "beads", "guarded-metadata-batch",
                   "--store-ref=" + self.store_ref, *arguments, "--json"]
        try:
            result = subprocess.run(command, cwd=self.cwd, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="strict", timeout=self.timeout, check=False)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise StoreError(f"native command outcome unavailable: {exc}") from exc
        if result.returncode != 0:
            raise StoreError(f"native command failed ({result.returncode}): {result.stderr.strip()}")
        try:
            response = parse_record(result.stdout)
        except RecordError as exc:
            raise StoreError(f"malformed native command response: {exc}") from exc
        return response

    def _result(self, response: dict) -> list:
        if (not isinstance(response, dict) or set(response) != {"schema_version", "ok", "store_ref", "rows"}
                or response["schema_version"] != "1" or response["ok"] is not True
                or response["store_ref"] != self.store_ref or not isinstance(response["rows"], list)):
            raise StoreError("native response does not match the exact selected store contract")
        return response["rows"]

    def snapshot(self, ids: list[str]) -> dict[str, dict]:
        if not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= MAX_ROWS or len(set(ids)) != len(ids):
            raise StoreError("snapshot requires 1-100 unique physical IDs")
        for bead_id in ids:
            _id(bead_id, "snapshot bead_id")
        rows = self._result(self._command(["--snapshot=" + ",".join(ids)]))
        if len(rows) != len(ids):
            raise StoreError("incomplete native snapshot")
        result = {}
        for bead_id, row in zip(ids, rows):
            if (not isinstance(row, dict) or set(row) != {"id", "revision", "status", "assignee", "type", "labels", "metadata"}
                    or row["id"] != bead_id or not isinstance(row["revision"], str)
                    or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", row["revision"])
                    or not -(2**63) <= int(row["revision"]) < 2**63
                    or any(not isinstance(row[k], str) for k in ("status", "assignee", "type"))
                    or not isinstance(row["metadata"], dict)
                    or (row["labels"] is not None and (not isinstance(row["labels"], list) or any(not isinstance(v, str) for v in row["labels"])))):
                raise StoreError("malformed or out-of-order native snapshot row")
            canonical_bytes(row)
            result[bead_id] = copy.deepcopy(row)
        return result

    def read_record(self, kind: str, bead_id: str, identity: list | tuple | None = None) -> dict | None:
        if kind not in contracts():
            raise StoreError("unknown record kind")
        row = self.snapshot([bead_id])[bead_id]
        record = _metadata_record(row, contracts()[kind]["metadata_key"])
        if record is not None:
            validate_record(kind, record)
            self._dedicated(row, record if kind == "workspace" else None)
            if identity is not None and list(record_identity(kind, record)) != list(identity):
                raise StoreError("record identity does not match its exact reference")
        return record

    def install_grant(self, attempt: Attempt, scope: dict, authority_id: str,
                      writes: list[RecordWrite], references=(), *, writer_map: CookedWriterMap, guards=(), expected_rows=None,
                      operation_nonce: str | None = None, projections=()) -> PreparedWrite:
        return self._prepare("install", attempt, scope, authority_id, writes, references,
                             guards, expected_rows, operation_nonce, projections=projections, writer_map=writer_map)

    def write_records(self, attempt: Attempt, scope: dict, authority_id: str,
                      writes: list[RecordWrite], references=(), *, writer_map: CookedWriterMap, guards=(), expected_rows=None,
                      operation_nonce: str | None = None, projections=()) -> PreparedWrite:
        return self._prepare("write", attempt, scope, authority_id, writes, references,
                             guards, expected_rows, operation_nonce, projections=projections, writer_map=writer_map)

    def accept_replacement(self, attempt: Attempt, scope: dict, authority_id: str,
                           writes: list[RecordWrite], references=(), *, expected_grant: dict, writer_map: CookedWriterMap,
                           successor_relation: SuccessorRelation | None = None, guards=(),
                           expected_rows=None, operation_nonce: str | None = None, projections=()) -> PreparedWrite:
        return self._prepare("replace", attempt, scope, authority_id, writes, references,
                             guards, expected_rows, operation_nonce, expected_grant, successor_relation, projections, writer_map)

    def _prepare(self, operation, attempt, scope, authority_id, writes, references,
                 guards, expected_rows, operation_nonce, expected_grant=None, successor_relation=None, projections=(), writer_map=None):
        scope = _scope(scope)
        if not isinstance(attempt, Attempt):
            raise StoreError("write requires the retained native Attempt")
        _id(authority_id, "authority_id")
        root_id = scope["workflow_root_id"]
        if any(not isinstance(values, (list, tuple)) for values in (writes, references, guards, projections)):
            raise StoreError("operation collections must be retained lists or tuples")
        if authority_id in (root_id, attempt.claimed_bead_id):
            raise StoreError("write authority must be a dedicated physical control row")
        if any(not isinstance(w, RecordWrite) for w in writes) or any(not isinstance(r, ReferenceWrite) for r in references):
            raise StoreError("write requires typed record and reference operations")
        if any(not isinstance(g, GuardRead) for g in guards):
            raise StoreError("write requires typed read guards")
        if any(not isinstance(p, (NativeOwnerProjection, NativeWorktreeReference, SourceMembershipProjection,
                                  SourcePlanConvoyBinding, RunCheckPolicyProjection)) for p in projections):
            raise StoreError("unknown native projection operation")
        if operation == "install" and not writes:
            raise StoreError("initial grant publication must join its first lifecycle payload")
        nonce = operation_nonce or secrets.token_hex(32)
        if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{64}", nonce):
            raise StoreError("operation_nonce requires a stable 64-character lowercase hex nonce")
        if operation == "replace":
            self._grant(expected_grant, scope, authority_id)
        require(isinstance(writer_map, CookedWriterMap), "typed native occurrence map is required")
        declaration = writer_map.declaration
        require(isinstance(declaration.get("steps"), list)
                and all(isinstance(item, dict) and "bead_id" in item for item in declaration["steps"])
                and "expansion_root_id" in declaration and "source_member_id" in declaration,
                "native occurrence map is incomplete")
        map_ids = [declaration["expansion_root_id"], declaration["source_member_id"],
                   *(item["bead_id"] for item in declaration["steps"])]
        for bead_id in map_ids:
            _id(bead_id, "writer map bead_id")
        ids = list(dict.fromkeys([authority_id, attempt.claimed_bead_id, root_id,
                                 *map_ids,
                                 *(w.bead_id for w in writes), *(r.bead_id for r in references),
                                 *(g.bead_id for g in guards),
                                 *(p.workspace_bead_id for p in projections if isinstance(p, (NativeOwnerProjection, NativeWorktreeReference))),
                                 *(p.bead_id for p in projections if isinstance(p, (NativeWorktreeReference, SourceMembershipProjection))),
                                 *(p.convoy_id for p in projections if isinstance(p, SourcePlanConvoyBinding)),
                                 *(p.run_record_id for p in projections if isinstance(p, RunCheckPolicyProjection)),
                                 *([expected_grant["attempt"]["claimed_bead_id"],
                                    expected_grant["writer_occurrence"]["expansion_root_id"]] if operation == "replace" else []),
                                 *([successor_relation.source_plan_bead_id, successor_relation.reference_bead_id] if successor_relation else [])]))
        if len(ids) > MAX_ROWS:
            raise StoreError("complete guarded request exceeds 100 physical rows; chunking is forbidden")
        rows = self.snapshot(ids) if expected_rows is None else copy.deepcopy(expected_rows)
        if not isinstance(rows, dict) or any(i not in rows or rows[i].get("id") != i for i in ids):
            raise StoreError("expected_rows must contain every exact original snapshot")
        rows = {i: rows[i] for i in ids}
        claim = rows[attempt.claimed_bead_id]
        native = claim["metadata"]
        native_root = next((native[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if native.get(k)), None)
        if (claim["status"] != "in_progress" or not claim["assignee"]
                or native.get("gc.session_id") != attempt.session_id or native_root != root_id
                or native.get("gc.root_store_ref") != self.store_ref
                or not isinstance(native.get("gc.step_ref"), str) or not native["gc.step_ref"].strip()):
            raise StoreError("retained claimed step lacks exact native session, root, store or step binding")
        declaration = validate_cooked_writer_map(writer_map, rows, store_ref=self.store_ref,
            workflow_root_id=root_id, record_kind=scope["record_kind"], claimed_step_id=attempt.claimed_bead_id)
        map_sha256 = hashlib.sha256(writer_map.declaration_bytes).hexdigest()
        authority = rows[authority_id]
        self._dedicated(authority)
        old_grant = _metadata_record(authority, GRANT_KEY)
        scope_key = hashlib.sha256(canonical_bytes(scope)).hexdigest()
        index = _metadata_record(rows[root_id], GRANT_REFS_KEY)
        if index is None:
            index = {"version": 1, "scopes": {}}
        if set(index) != {"version", "scopes"} or type(index["version"]) is not int or index["version"] != 1 or not isinstance(index["scopes"], dict):
            raise StoreError("malformed root authority references")
        seen_authorities = set()
        for reference_hash, reference in index["scopes"].items():
            if not isinstance(reference, dict) or set(reference) != {"scope", "authority_id"}:
                raise StoreError("unknown root authority reference")
            reference_scope = _scope(reference["scope"])
            _id(reference["authority_id"], "referenced authority_id")
            if (reference_scope["workflow_root_id"] != root_id
                    or reference_hash != hashlib.sha256(canonical_bytes(reference_scope)).hexdigest()
                    or reference["authority_id"] in seen_authorities):
                raise StoreError("conflicting root authority reference")
            seen_authorities.add(reference["authority_id"])
        grant_ref = {"scope": scope, "authority_id": authority_id}
        if operation == "install":
            if old_grant is not None or authority["metadata"] or scope_key in index["scopes"] or authority_id in seen_authorities:
                raise StoreError("initial grant requires an empty dedicated authority and absent exact scope reference")
            index["scopes"][scope_key] = grant_ref
        else:
            self._grant(old_grant, scope, authority_id)
            if index["scopes"].get(scope_key) != grant_ref:
                raise StoreError("authority is missing its exact root reference")
            if operation == "write":
                if old_grant["attempt"] != attempt.admission:
                    raise StoreError("current grant belongs to a different native writer attempt")
                if old_grant["writer_map_sha256"] != map_sha256:
                    raise StoreError("current grant belongs to a different cooked writer map")
            else:
                if old_grant != expected_grant:
                    raise StoreError("replacement requires the exact recorded predecessor grant")
                self._successor(old_grant, attempt, scope, successor_relation, rows, declaration, map_sha256)
        if old_grant is not None and old_grant["operation_nonce"] == nonce:
            raise StoreError("a consumed operation nonce cannot be reused for a new transaction")
        grant = {"version": 1, "scope": scope, "authority_id": authority_id,
                 "attempt": attempt.admission, "operation_nonce": nonce, "writer_map_sha256": map_sha256,
                 "writer_occurrence": {key: declaration[key] for key in
                    ("source_member_id", "expansion_root_id", "formula_name", "formula_hash", "formula_source")}}
        designated = next(item for item in declaration["steps"] if item["bead_id"] == attempt.claimed_bead_id)
        grant["writer_occurrence"].update({key: designated[key] for key in ("step_id", "step_ref")})
        patches = {i: {"id": i, "expected_revision": rows[i]["revision"],
                       "expected_status": rows[i]["status"], "expected_assignee": rows[i]["assignee"],
                       "require_change": True, "set": {TRANSITION_NONCE_KEY: nonce}} for i in ids}

        def put(bead_id, key, value):
            patch = patches[bead_id]["set"]
            if key in patch and patch[key] != value:
                raise StoreError("conflicting metadata patches for the same physical row")
            patch[key] = value

        put(authority_id, GRANT_KEY, canonical_bytes(grant).decode())
        put(attempt.claimed_bead_id, CLAIM_NONCE_KEY, nonce)
        put(root_id, GRANT_REFS_KEY, canonical_bytes(index).decode())
        replay = bool(writes)
        published = {}
        previous_payloads = {}
        record_rows = set()
        record_identities = set()
        for write in writes:
            if not isinstance(write, RecordWrite) or write.kind not in contracts():
                raise StoreError("write requires a known RecordWrite kind")
            if write.bead_id in (authority_id, attempt.claimed_bead_id, root_id):
                raise StoreError("lifecycle payload requires a dedicated physical record row")
            if write.bead_id in record_rows:
                raise StoreError("one dedicated physical record row cannot contain multiple payload writes")
            record_rows.add(write.bead_id)
            payload = validate_record(write.kind, write.payload)
            identity = (write.kind, record_identity(write.kind, payload))
            if identity in record_identities:
                raise StoreError("one logical record cannot publish multiple physical payloads in the same batch")
            record_identities.add(identity)
            if write.kind != scope["record_kind"] and not (scope["record_kind"] == "workspace" and write.kind == "blocker"):
                raise StoreError("payload kind is outside the grant's designated writer responsibility")
            self._dedicated(rows[write.bead_id], payload if write.kind == "workspace" else None)
            if (payload["workflow_root_id"] != root_id or payload["generation"] != scope["generation"]
                    or payload[SCOPE_OWNER[write.kind]] != scope["writer_scope_id"]):
                raise StoreError("payload is outside the designated writer scope")
            key = contracts()[write.kind]["metadata_key"]
            stored = _metadata_record(rows[write.bead_id], key)
            previous_payloads[(write.kind, write.bead_id)] = stored
            if operation == "install" and stored is not None:
                raise StoreError("initial grant cannot adopt a previously published lifecycle payload")
            if stored is None:
                if any(k in rows[write.bead_id]["metadata"] for k in (GRANT_KEY, *[c["metadata_key"] for c in contracts().values()])):
                    raise StoreError("record allocation already contains another lifecycle identity")
                exact_replay = False
            else:
                exact_replay = validate_transition(write.kind, stored, payload)
            if write.kind == "workspace" and OWNER_PROJECTION_KEYS.intersection(rows[write.bead_id]["metadata"]):
                self._owner_projection(payload, {k: rows[write.bead_id]["metadata"].get(k) for k in OWNER_PROJECTION_KEYS}, rows)
            replay &= exact_replay
            if not exact_replay and payload["writer_step_id"] != attempt.claimed_bead_id:
                raise StoreError("changed payload must name the admitted exact writer step")
            if write.kind == "workspace" and not exact_replay and payload["writer_attempt_id"] != attempt.writer_attempt_id:
                raise StoreError("workspace claim binding must name the retained native writer attempt")
            value = canonical_bytes(payload).decode()
            put(write.bead_id, key, value)
            published[(write.kind, write.bead_id)] = payload
        for (kind, bead_id), workspace in published.items():
            if kind != "workspace":
                continue
            before = previous_payloads[(kind, bead_id)]
            if workspace["phase"] == "blocked" and (before is None or before["phase"] != "blocked"):
                blockers = [b for (k, _), b in published.items() if k == "blocker"]
                if before is None or len(blockers) != 1 or blockers[0]["status"] != "open":
                    raise StoreError("blocking requires the preceding workspace and one open blocker in the same batch")
                blocker = blockers[0]
                for key in ("input_oid", "current_oid", "output_oid", "integration_inputs"):
                    if before[key] != workspace[key]:
                        raise StoreError("blocking must preserve the workspace source checkpoint")
                expected = {"blocked_from_phase": before["phase"], "blocked_member_id": before["active_member_id"],
                            "blocked_member_position": before["next_member_position"], "blocked_current_oid": before["current_oid"],
                            "expected_input_oid": before["input_oid"], "work_dir": before["work_dir"],
                            "source_plan_owner_id": before["source_plan_owner_id"]}
                if any(blocker[k] != v for k, v in expected.items()):
                    raise StoreError("blocker must describe the exact preceding workspace checkpoint")
            elif before is not None and before["phase"] == "blocked" and workspace["phase"] != "blocked":
                owner = rows.get(workspace["workspace_owner_id"])
                reference = _metadata_record(owner, "gc.workspace_blocker_ref") if owner else None
                if reference is None:
                    raise StoreError("resume requires the exact guarded workspace blocker reference")
                _reference(reference)
                blocker = published.get(("blocker", reference["bead_id"]))
                if blocker is None and reference["bead_id"] in rows:
                    self._dedicated(rows[reference["bead_id"]])
                    blocker = _metadata_record(rows[reference["bead_id"]], contracts()["blocker"]["metadata_key"])
                if blocker is None:
                    raise StoreError("resume requires its resolved blocker as a guarded transaction row")
                validate_record("blocker", blocker)
                if (reference != record_reference("blocker", reference["bead_id"], blocker) or blocker["status"] != "resolved"
                        or blocker["workflow_root_id"] != root_id or blocker["generation"] != scope["generation"]
                        or blocker["workspace_owner_id"] != workspace["workspace_owner_id"]
                        or blocker["source_plan_owner_id"] != workspace["source_plan_owner_id"]
                        or blocker["blocked_current_oid"] != before["current_oid"]
                        or blocker["blocked_member_id"] != before["active_member_id"]
                        or blocker["blocked_member_position"] != before["next_member_position"]
                        or blocker["work_dir"] != before["work_dir"]
                        or workspace["phase"] != blocker["blocked_from_phase"]
                        or workspace["active_member_id"] != blocker["blocked_member_id"]
                        or workspace["next_member_position"] != blocker["blocked_member_position"]
                        or workspace["input_oid"] != blocker["expected_input_oid"]
                        or workspace["current_oid"] != blocker["resolution"]["expected_head_oid"]):
                    raise StoreError("resume must restore the declared paused phase/member and decision-bound HEAD")
        for reference in references:
            if not isinstance(reference, ReferenceWrite) or reference.key not in REFERENCE_KEYS:
                raise StoreError("only explicit pack record-reference keys may be published")
            value = _reference(reference.value)
            if reference.bead_id != root_id and reference.bead_id not in record_rows:
                target = rows[reference.bead_id]["metadata"]
                target_root = next((target[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if target.get(k)), None)
                if target_root != root_id or target.get("gc.root_store_ref") != self.store_ref:
                    raise StoreError("reference target is outside the exact native workflow/store")
            if REFERENCE_KEYS[reference.key] != value["kind"] or value["identity"][:2] != [root_id, scope["generation"]]:
                raise StoreError("reference kind or scope conflicts with its publication key")
            payload = published.get((value["kind"], value["bead_id"]))
            if payload is None:
                raise StoreError("reference publication must join its validated lifecycle payload in the batch")
            if value != record_reference(value["kind"], value["bead_id"], payload):
                raise StoreError("reference conflicts with the exact payload identity")
            previous = _metadata_record(rows[reference.bead_id], reference.key)
            if previous is not None:
                _reference(previous)
                if previous["identity"] == value["identity"] and previous != value:
                    raise StoreError("same logical identity cannot adopt a different physical record")
                if previous != value and (previous["kind"] != value["kind"] or previous["identity"][0] != root_id
                                          or previous["identity"][1] + 1 != scope["generation"]):
                    raise StoreError("reference replacement requires the explicit next generation")
            put(reference.bead_id, reference.key, canonical_bytes(value).decode())
        policies = [p for p in projections if isinstance(p, RunCheckPolicyProjection)]
        runs = [(bead_id, payload) for (kind, bead_id), payload in published.items() if kind == "run"]
        new_run = bool(runs) and (native.get("gc.lifecycle") == "new"
            or rows[root_id]["metadata"].get("gc.var.worktree_lifecycle") == "new"
            or any(run["worktree_lifecycle"] == "new" for _, run in runs))
        if new_run and len(policies) != 1:
            raise StoreError("new-mode run publication requires one captured required-check policy")
        for projection in projections:
            if isinstance(projection, RunCheckPolicyProjection):
                run = published.get(("run", projection.run_record_id))
                policy = projection.payload
                if (scope["record_kind"] != "run" or run is None or not isinstance(policy, dict)
                        or set(policy) != {"version", "workflow_root_id", "run_record_id", "run_identity", "base_oid",
                                           "required_checks", "policy_sha256"}
                        or type(policy["version"]) is not int or policy["version"] != 1
                        or policy["workflow_root_id"] != root_id or policy["run_record_id"] != projection.run_record_id
                        or policy["run_identity"] != list(record_identity("run", run)) or policy["base_oid"] != run["base_oid"]):
                    raise StoreError("required-check policy must join its exact run publication and base")
                checks, seen = policy["required_checks"], set()
                if not isinstance(checks, list) or not checks:
                    raise StoreError("required project checks cannot be absent")
                for check in checks:
                    if (not isinstance(check, dict) or set(check) != {"id", "argv"}
                            or not isinstance(check["id"], str) or not check["id"] or check["id"] in seen
                            or not isinstance(check["argv"], list) or not check["argv"]
                            or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in check["argv"])):
                        raise StoreError("required check scope must contain unique IDs and explicit argv")
                    seen.add(check["id"])
                source = {"required_checks": checks}
                if (policy["policy_sha256"] != record_sha256(source)
                        or rows[root_id]["metadata"].get("gc.var.worktree_checks", MISSING) != canonical_bytes(source).decode()):
                    raise StoreError("required-check policy conflicts with its original native configuration")
                key, value = "gc.workspace_required_checks.v1", canonical_bytes(policy).decode()
                old = rows[projection.run_record_id]["metadata"].get(key, MISSING)
                prior_run = previous_payloads[("run", projection.run_record_id)]
                if (old is not MISSING and old != value) or (prior_run is not None and old is MISSING):
                    raise StoreError("captured required-check policy is immutable and cannot be added on replay")
                put(projection.run_record_id, key, value)
                continue
            if isinstance(projection, SourcePlanConvoyBinding):
                plans = [payload for (kind, _), payload in published.items() if kind == "source-plan"]
                if scope["record_kind"] != "source-plan" or len(plans) != 1:
                    raise StoreError("convoy binding must join its source-plan publication")
                plan = plans[0]
                convoy = rows[projection.convoy_id]
                native = convoy["metadata"]
                native_root = next((native[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if native.get(k)), None)
                if (convoy["type"] != "convoy" or native_root != root_id or native.get("gc.root_store_ref") != self.store_ref
                        or native.get("gc.source_root_id") != root_id or native.get("gc.source_generation") != str(scope["generation"])):
                    raise StoreError("convoy binding requires the exact native convoy/root/store/source generation")
                run_ref = _metadata_record(rows[root_id], "gc.implementation_run_ref")
                if run_ref is None or run_ref.get("kind") != "run":
                    raise StoreError("convoy binding requires the original run reference")
                _reference(run_ref)
                run_row = rows.get(run_ref["bead_id"])
                run = _metadata_record(run_row, contracts()["run"]["metadata_key"]) if run_row else None
                if run is None or record_reference("run", run_ref["bead_id"], run) != run_ref:
                    raise StoreError("convoy binding requires the original run as a guarded transaction row")
                validate_record("run", run)
                if run["workflow_root_id"] != root_id or run["worktree_lifecycle"] != "new":
                    raise StoreError("convoy binding conflicts with the recorded workflow run")
                if not any(g.bead_id == root_id and g.key == "gc.input_convoy_id" for g in guards):
                    raise StoreError("convoy binding requires an explicit original input-convoy read guard")
                previous_convoy = rows[root_id]["metadata"].get("gc.build.implementation_convoy_id", MISSING)
                if previous_convoy is not MISSING and previous_convoy != projection.convoy_id:
                    _id(previous_convoy, "preceding implementation convoy")
                    predecessor = rows.get(previous_convoy)
                    metadata = predecessor["metadata"] if predecessor else {}
                    if (predecessor is None or predecessor["type"] != "convoy"
                            or metadata.get("gc.root_bead_id") != root_id or metadata.get("gc.root_store_ref") != self.store_ref
                            or metadata.get("gc.source_root_id") != root_id
                            or metadata.get("gc.source_generation") != str(scope["generation"] - 1)):
                        raise StoreError("convoy replacement requires its guarded exact preceding source generation")
                for key, value in (("gc.source_plan_owner_id", plan["source_plan_owner_id"]),
                                   ("gc.source_plan_sha256", record_sha256(plan))):
                    old = native.get(key, MISSING)
                    if old is not MISSING and old != value:
                        raise StoreError("convoy already carries a conflicting source-plan binding")
                    put(projection.convoy_id, key, value)
                put(root_id, "gc.input_convoy_id", projection.convoy_id)
                put(root_id, "gc.build.implementation_convoy_id", projection.convoy_id)
                continue
            if isinstance(projection, SourceMembershipProjection):
                plans = [payload for (kind, _), payload in published.items() if kind == "source-plan"]
                if scope["record_kind"] != "source-plan" or len(plans) != 1:
                    raise StoreError("source membership must join its source-plan publication")
                plan = plans[0]
                members = {plan["source_plan_owner_id"], *[i for n in plan["nodes"] for i in (n["owner_id"], *n["member_ids"]) ]}
                if (projection.bead_id not in members or projection.root_id != root_id
                        or type(projection.generation) is not int or projection.generation != scope["generation"]):
                    raise StoreError("source membership is outside the declared plan/root/generation")
                native = rows[projection.bead_id]["metadata"]
                native_root = next((native[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if native.get(k)), None)
                if native_root != root_id or native.get("gc.root_store_ref") != self.store_ref:
                    raise StoreError("source membership requires the existing exact native root/store")
                for key, value in (("gc.source_root_id", root_id), ("gc.source_generation", str(projection.generation))):
                    old = native.get(key, MISSING)
                    if old is not MISSING and old != value:
                        raise StoreError("source membership cannot overwrite a conflicting declaration")
                    put(projection.bead_id, key, value)
                continue
            if scope["record_kind"] != "workspace":
                raise StoreError("native workspace projections require the workspace writer responsibility")
            owner_id = projection.workspace_bead_id
            workspace = published.get(("workspace", owner_id))
            if workspace is None:
                workspace = _metadata_record(rows[owner_id], contracts()["workspace"]["metadata_key"])
            if workspace is None:
                raise StoreError("native projection requires a validated workspace record in the same transaction")
            validate_record("workspace", workspace)
            self._dedicated(rows[owner_id], workspace)
            if (workspace["workflow_root_id"] != root_id or workspace["generation"] != scope["generation"]
                    or workspace["workspace_owner_id"] != scope["writer_scope_id"] or workspace["workspace_bead_id"] != owner_id):
                raise StoreError("native projection workspace conflicts with the writer scope")
            if isinstance(projection, NativeOwnerProjection):
                self._owner_projection(workspace, projection.metadata, rows)
                for key, value in projection.metadata.items():
                    previous = rows[owner_id]["metadata"].get(key, MISSING)
                    if previous is not MISSING and previous != value:
                        raise StoreError("native owner projection conflicts with retained provisioning identity")
                    put(owner_id, key, value)
            else:
                owners = [p for p in projections if isinstance(p, NativeOwnerProjection) and p.workspace_bead_id == owner_id]
                if len(owners) > 1:
                    raise StoreError("duplicate native owner projections")
                metadata = owners[0].metadata if owners else {k: rows[owner_id]["metadata"].get(k) for k in OWNER_PROJECTION_KEYS}
                self._owner_projection(workspace, metadata, rows)
                self._worktree_reference(workspace, projection, rows[projection.bead_id])
                value = canonical_bytes(projection.reference).decode()
                previous = rows[projection.bead_id]["metadata"].get("gc.worktree_ref", MISSING)
                if previous is not MISSING and previous != value:
                    raise StoreError("native worktree reference cannot silently rebind an existing consumer")
                put(projection.bead_id, "gc.worktree_ref", value)
        for guard in guards:
            if not isinstance(guard, GuardRead) or not isinstance(guard.key, str) or not guard.key:
                raise StoreError("read guard requires an exact row and metadata key")
            observed = rows[guard.bead_id]["metadata"].get(guard.key, MISSING)
            if observed is MISSING or guard.expected_value is MISSING:
                equal = observed is guard.expected_value
            else:
                equal = canonical_bytes(observed) == canonical_bytes(guard.expected_value)
            if not equal:
                raise StoreError("read guard conflicts with the original snapshot")
        after = copy.deepcopy(rows)
        for bead_id, patch in patches.items():
            after[bead_id]["metadata"].update(patch["set"])
        request = {"admission": attempt.admission, "rows": list(patches.values())}
        return PreparedWrite(canonical_bytes(request), canonical_bytes(rows), canonical_bytes(after),
                             canonical_bytes(scope), self._binding(), replay)

    @staticmethod
    def _dedicated(row, workspace=None):
        if row["status"] != "closed" or row["assignee"]:
            raise StoreError("dedicated lifecycle rows must remain closed and unassigned")
        runtime = {"gc.session_id", "gc.root_bead_id", "gc.root_store_ref", "gc.step_ref",
                   "workflow_id", "molecule_id", "current_claim_bead_id", "gc.kind",
                   "gc.drain_member_id", "gc.drain_owner_id"}
        if workspace is not None:
            if (row["id"] != workspace["workspace_bead_id"]
                    or row["metadata"].get("gc.root_bead_id", workspace["workflow_root_id"]) != workspace["workflow_root_id"]):
                raise StoreError("native owner projection has conflicting workspace root identity")
            present = OWNER_PROJECTION_KEYS.intersection(row["metadata"])
            if present and present != OWNER_PROJECTION_KEYS:
                raise StoreError("workspace carries an incomplete native owner projection")
            runtime -= {"gc.root_bead_id", "gc.root_store_ref"}
        elif OWNER_PROJECTION_KEYS.intersection(row["metadata"]):
            raise StoreError("only the matching workspace record may carry native owner projection")
        if runtime.intersection(row["metadata"]):
            raise StoreError("dedicated record carries native runtime routing identity")

    def _owner_projection(self, workspace, metadata, rows):
        if (not isinstance(metadata, dict) or set(metadata) != OWNER_PROJECTION_KEYS
                or any(not isinstance(v, str) for v in metadata.values())):
            raise StoreError("native owner projection requires the exact supported string metadata keys")
        native = workspace["native_provenance"]
        if not isinstance(native, dict) or type(native.get("schema_version")) is not int or native["schema_version"] != 2:
            raise StoreError("native owner projection requires explicit mode/placement provenance schema 2")
        exact = {"gc.root_bead_id": workspace["workflow_root_id"], "gc.root_store_ref": self.store_ref,
                 "gc.work_dir": workspace["work_dir"], "gc.work_branch": workspace["work_branch"] or "",
                 "gc.worktree_owner": workspace["workspace_owner_id"], "gc.worktree_generation": str(workspace["generation"])}
        for name in ("base_ref", "base_sha", "creator", "lifecycle", "mode", "placement"):
            exact["gc.worktree_" + name] = native.get(name)
        if (any(metadata[k] != v for k, v in exact.items()) or native.get("bead_id") != workspace["workspace_bead_id"]
                or native.get("store_ref") != self.store_ref or native.get("owner") != workspace["workspace_owner_id"]
                or native.get("generation") != str(workspace["generation"])
                or native.get("path") != workspace["work_dir"] or (native.get("branch") or None) != workspace["work_branch"]
                or native.get("attempt_id") != workspace["native_attempt_id"]
                or native.get("repo_identity") != str(self.common_git_dir)):
            raise StoreError("native owner projection does not match the complete retained provisioning identity")
        if native.get("mode") not in ("attached", "detached") or native.get("placement") not in ("outside-worktrees", "within-repo-root"):
            raise StoreError("unknown native worktree mode or placement")
        if (native["mode"] == "detached") != (workspace["work_branch"] is None):
            raise StoreError("native mode conflicts with workspace branch representation")
        for key in ("gc.worktree_repo", "gc.worktree_root", "gc.work_dir"):
            path = Path(metadata[key])
            if not path.is_absolute() or path != path.resolve(strict=True):
                raise StoreError("native projection requires canonical existing paths")
        run_ref = _metadata_record(rows[workspace["workflow_root_id"]], "gc.implementation_run_ref")
        if run_ref is None:
            raise StoreError("native owner projection requires the recorded exact run reference")
        _reference(run_ref)
        run = _metadata_record(rows.get(run_ref["bead_id"], {"id": run_ref["bead_id"], "metadata": {}}), contracts()["run"]["metadata_key"])
        if run is None:
            raise StoreError("native owner projection requires the recorded run as a guarded transaction row")
        validate_record("run", run)
        if (run_ref != record_reference("run", run_ref["bead_id"], run)
                or run["workflow_root_id"] != workspace["workflow_root_id"]
                or run["rig_root"] != metadata["gc.worktree_repo"] or run["common_git_dir"] != str(self.common_git_dir)):
            raise StoreError("native projected repository conflicts with the recorded rig/common Git identity")
        if not Path(workspace["work_dir"]).is_relative_to(metadata["gc.worktree_root"]):
            raise StoreError("native worktree path is outside its declared worktree root")

    def _worktree_reference(self, workspace, projection, consumer):
        reference = projection.reference
        expected = {"version": 1, "binding_step_id": projection.bead_id,
                    "workflow_root_id": workspace["workflow_root_id"], "generation": workspace["generation"],
                    "workspace_owner_id": workspace["workspace_owner_id"], "workspace_bead_id": workspace["workspace_bead_id"],
                    "store_ref": self.store_ref, "native_attempt_id": workspace["native_attempt_id"]}
        if not isinstance(reference, dict) or canonical_bytes(reference) != canonical_bytes(expected) or workspace["native_provenance"] is None:
            raise StoreError("native worktree reference conflicts with its exact workspace/step/store/attempt binding")
        native = consumer["metadata"]
        root = next((native[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if native.get(k)), None)
        if root != workspace["workflow_root_id"] or native.get("gc.root_store_ref") != self.store_ref:
            raise StoreError("native worktree consumer is outside the recorded workflow/store")

    @staticmethod
    def _grant(grant, scope, authority_id):
        if (not isinstance(grant, dict) or set(grant) != {"version", "scope", "authority_id", "attempt", "operation_nonce", "writer_map_sha256", "writer_occurrence"}
                or type(grant["version"]) is not int or grant["version"] != 1
                or grant["scope"] != scope or grant["authority_id"] != authority_id
                or not isinstance(grant["attempt"], dict) or set(grant["attempt"]) != {"session_id", "instance_token", "claimed_bead_id"}
                or not isinstance(grant["operation_nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", grant["operation_nonce"])
                or not isinstance(grant["writer_map_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", grant["writer_map_sha256"])):
            raise StoreError("unknown or conflicting write grant")
        Attempt(**grant["attempt"])
        occurrence = grant["writer_occurrence"]
        if (not isinstance(occurrence, dict) or set(occurrence) != {"source_member_id", "expansion_root_id",
                "formula_name", "formula_hash", "formula_source", "step_id", "step_ref"}
                or not _native_step_id(occurrence["step_id"]) or not isinstance(occurrence["step_ref"], str)
                or not occurrence["step_ref"].strip()):
            raise StoreError("unknown retained physical writer occurrence")
        _id(occurrence["source_member_id"], "retained source member")
        _id(occurrence["expansion_root_id"], "retained expansion root")
        _formula_identity({"metadata": {"gc.formula_" + key: occurrence["formula_" + key]
                                       for key in ("name", "hash", "source")}})

    @staticmethod
    def _successor(grant, attempt, scope, relation, rows, declaration, map_sha256):
        old = Attempt(**grant["attempt"])
        if old.admission == attempt.admission:
            raise StoreError("replacement needs a proven new native incarnation or declared successor")
        if old.claimed_bead_id == attempt.claimed_bead_id:
            if grant["writer_map_sha256"] != map_sha256:
                raise StoreError("same-step replacement cannot change its cooked writer designation")
            return
        if rows[old.claimed_bead_id]["status"] != "closed":
            raise StoreError("different-step replacement requires a closed native predecessor")
        previous = grant["writer_occurrence"]
        old_native = rows[old.claimed_bead_id]["metadata"]
        old_member = old_native.get("gc.source_anchor_id", old_native.get("gc.drain_member_id", scope["workflow_root_id"]))
        if (old_member != previous["source_member_id"] or old_native.get("gc.drain_member_id", old_member) != old_member
                or old_native.get("gc.step_id") != previous["step_id"] or old_native.get("gc.step_ref") != previous["step_ref"]
                or (old_native.get("gc.attach_root_id") or scope["workflow_root_id"]) != previous["expansion_root_id"]
                or _formula_identity(rows[previous["expansion_root_id"]]) != tuple(previous["formula_" + key] for key in ("name", "hash", "source"))
                or scope["record_kind"] not in _kinds(old_native, previous["step_ref"])):
            raise StoreError("predecessor differs from its retained native cooked writer occurrence")
        entries = {item["bead_id"]: item for item in declaration["steps"]}
        if old.claimed_bead_id in entries:
            before, after = entries[old.claimed_bead_id], entries[attempt.claimed_bead_id]
            if grant["writer_map_sha256"] != map_sha256 or scope["record_kind"] not in before["record_kinds"]:
                raise StoreError("same-member predecessor lacks its original cooked writer designation")
            # Intervening native stages may separate writers of the same record.
            # Every traversed prerequisite must have a closed exact occurrence.
            semantic = {}
            for item in declaration["steps"]:
                semantic.setdefault(item["step_id"], []).append(item)
            pending, seen = list(after["dependencies"]), set()
            while pending:
                step_id = pending.pop()
                if step_id in seen:
                    continue
                seen.add(step_id)
                occurrences = semantic[step_id]
                if any(rows[item["bead_id"]]["status"] != "closed" for item in occurrences):
                    continue
                if step_id == before["step_id"]:
                    return
                pending.extend(occurrences[0]["dependencies"])
            raise StoreError("same-member replacement lacks a closed declared native predecessor path")
        if not isinstance(relation, SuccessorRelation):
            raise StoreError("different-step replacement requires a recorded source-plan successor relation")
        plan = _metadata_record(rows[relation.source_plan_bead_id], contracts()["source-plan"]["metadata_key"])
        if plan is None:
            raise StoreError("missing recorded source-plan successor relation")
        validate_record("source-plan", plan)
        if plan["workflow_root_id"] != scope["workflow_root_id"] or plan["generation"] != scope["generation"]:
            raise StoreError("successor plan is outside the writer scope")
        reference = _metadata_record(rows[relation.reference_bead_id], "gc.source_plan_ref")
        if (relation.reference_bead_id not in (plan["source_plan_owner_id"], plan["workflow_root_id"])
                or reference != record_reference("source-plan", relation.source_plan_bead_id, plan)):
            raise StoreError("successor plan lacks its exact declared physical reference")
        def member(claimed_id):
            metadata = rows[claimed_id]["metadata"]
            root = next((metadata[k] for k in ("workflow_id", "molecule_id", "gc.root_bead_id") if metadata.get(k)), None)
            if root != scope["workflow_root_id"] or metadata.get("gc.root_store_ref") != rows[attempt.claimed_bead_id]["metadata"].get("gc.root_store_ref"):
                raise StoreError("successor claimed step is outside the recorded native workflow")
            source = metadata.get("gc.source_anchor_id", metadata.get("gc.drain_member_id", scope["workflow_root_id"]))
            if metadata.get("gc.source_anchor_id", source) != metadata.get("gc.drain_member_id", source):
                raise StoreError("successor claimed step has conflicting source member bindings")
            return _id(source, "successor member")
        before_member, after_member = member(old.claimed_bead_id), member(attempt.claimed_bead_id)
        matches = [n for n in plan["nodes"] if n["owner_id"] == scope["writer_scope_id"]
                   and n["strategy"] == "shared-chain" and n["single_lane"]]
        if len(matches) != 1 or not any(a == before_member and b == after_member
                                        for a, b in zip(matches[0]["member_ids"], matches[0]["member_ids"][1:])):
            raise StoreError("replacement is not the declared immediate shared-chain successor")

    def execute(self, prepared: PreparedWrite) -> dict:
        self._prepared(prepared)
        request = prepared.request
        attempt = Attempt(**request["admission"])
        scope = parse_record(prepared.scope_bytes.decode())
        with transition_locks(self.common_git_dir, scope, self.timeout):
            submission = (prepared.binding_bytes, prepared.sha256)
            if submission in _SUBMITTED_REQUESTS:
                raise StoreError("request was already submitted; resolve the original intent without another write")
            _SUBMITTED_REQUESTS.add(submission)
            with tempfile.TemporaryDirectory(prefix="gc-workspace-request-") as directory:
                path = Path(directory) / "request.json"
                path.write_bytes(prepared.request_bytes)
                try:
                    response = self._result(self._command(["--request=" + str(path)], attempt))
                    expected = request["rows"]
                    if len(response) != len(expected):
                        raise StoreError("native batch result is incomplete")
                    for actual, patch in zip(response, expected):
                        if (not isinstance(actual, dict) or set(actual) != {"id", "revision", "changed"}
                                or actual["id"] != patch["id"] or not isinstance(actual["revision"], str)
                                or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", actual["revision"])
                                or not -(2**63) <= int(actual["revision"]) < 2**63
                                or type(actual["changed"]) is not bool
                                or (patch["require_change"] and not actual["changed"])):
                            raise StoreError("native batch result mismatches the frozen request")
                except StoreError as exc:
                    return {"outcome": "unknown", "request_sha256": prepared.sha256,
                            "error": str(exc), "retry_allowed": False}
        return {"outcome": "replayed" if prepared.replay else "committed",
                "request_sha256": prepared.sha256, "rows": response, "retry_allowed": False}

    def resolve(self, prepared: PreparedWrite) -> dict:
        """Classify the original intent by exact same-store readback; never write."""
        self._prepared(prepared)
        before = parse_record(prepared.before_bytes.decode())
        after = parse_record(prepared.after_bytes.decode())
        try:
            actual = self.snapshot(list(after))
        except StoreError as exc:
            return {"outcome": "unknown", "request_sha256": prepared.sha256, "error": str(exc), "retry_allowed": False}
        def state(rows):
            return {i: {k: r[k] for k in ("status", "assignee", "type", "labels", "metadata")} for i, r in rows.items()}
        if canonical_bytes(state(actual)) == canonical_bytes(state(after)):
            outcome = "replayed" if prepared.replay else "committed"
        elif canonical_bytes(actual) == canonical_bytes(before):
            outcome = "not_committed"
        else:
            outcome = "unknown"
        return {"outcome": outcome, "request_sha256": prepared.sha256, "rows": actual, "retry_allowed": False}
