#!/usr/bin/env python3
"""Capture an immutable workspace run through the selected native record store."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from workspace_records import (RecordError, canonical_bytes, parse_record,
                               record_identity, validate_record)


RUN_REFERENCE_KEY = "gc.implementation_run_ref"
CHECKS_CONFIG_KEY = "gc.var.worktree_checks"
CHECKS_POLICY_KEY = "gc.workspace_required_checks.v1"


class RunError(RecordError):
    pass


def run_scope(workflow_root_id: str) -> dict[str, Any]:
    return {"workflow_root_id": workflow_root_id, "generation": 1,
            "writer_scope_id": workflow_root_id, "record_kind": "run"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RunError(message)


def capture_check_policy(run: dict[str, Any], run_record_id: str, raw: Any) -> dict[str, Any]:
    """Bind configured checks to this original run, outside its closed schema."""
    from workspace_outputs import check_scope
    require(isinstance(raw, str), "new lifecycle requires native gc.var.worktree_checks configuration")
    config = parse_record(raw)
    require(set(config) == {"required_checks"} and canonical_bytes(config).decode() == raw,
            "worktree_checks must be canonical JSON {required_checks:[{id,argv}]}")
    digest = check_scope(config["required_checks"])
    return {"version": 1, "workflow_root_id": run["workflow_root_id"], "run_record_id": run_record_id,
            "run_identity": list(record_identity("run", run)), "base_oid": run["base_oid"],
            "required_checks": config["required_checks"], "policy_sha256": digest}


def read_check_policy(store: Any, run_record_id: str, run: dict[str, Any]) -> dict[str, Any]:
    row = store.snapshot([run_record_id])[run_record_id]
    raw = row["metadata"].get(CHECKS_POLICY_KEY)
    require(isinstance(raw, str), "recorded run has no immutable required-check policy; migrate explicitly")
    policy = parse_record(raw)
    require("required_checks" in policy, "recorded check policy is malformed")
    config = canonical_bytes({"required_checks": policy["required_checks"]}).decode()
    expected = capture_check_policy(run, run_record_id, config)
    require(policy == expected and canonical_bytes(policy).decode() == raw,
            "recorded check policy identity, base or digest changed")
    return policy


def canonical_path(value: str) -> str:
    require(isinstance(value, str) and value.startswith("/") and
            not re.search(r"[\x00-\x1f\x7f]", value), "an absolute path without controls is required")
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise RunError(f"path is unavailable: {value}: {exc}") from exc
    require(path.is_dir(), f"path is not a directory: {value}")
    return str(path)


def git(root: str, *args: str) -> str:
    # Explicit -C must not inherit another worktree, object store or config.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        result = subprocess.run(["git", "-C", root, *args], env=env, text=True,
                                capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(f"Git source read failed: {exc}") from exc
    if "ambiguous" in result.stderr:
        raise RunError("ambiguous base ref: use a full refs/heads/ or refs/tags/ name")
    require(result.returncode == 0, "Git source read failed: " + result.stderr.strip()[-1000:])
    return result.stdout.strip()


def repository_identity(rig_root: str) -> tuple[str, str]:
    root = canonical_path(rig_root)
    common = canonical_path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    bare = git(root, "rev-parse", "--is-bare-repository")
    require(bare in ("true", "false"), "Git did not identify the repository topology")
    if bare == "true":
        require(common in (root, str(Path(root) / ".git")),
                "registered rig does not identify its bare repository")
    else:
        top = canonical_path(git(root, "rev-parse", "--show-toplevel"))
        require(top == root, "registered rig must be the selected checkout root")
    return root, common


def resolve_base(rig_root: str, selector: str) -> str:
    require(isinstance(selector, str) and selector and selector == selector.strip()
            and not selector.startswith("-") and not re.search(r"[\x00-\x1f\x7f]", selector),
            "base ref must be nonempty, or explicit @default")
    selected = "HEAD" if selector == "@default" else selector
    # Git itself resolves qualified refs, full OIDs and commit expressions. Its
    # ambiguity warning is a refusal, even when rev-parse exits successfully.
    oid = git(rig_root, "rev-parse", "--verify", "--end-of-options", selected + "^{commit}")
    require(bool(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid)), "Git did not return a full commit OID")
    require(git(rig_root, "cat-file", "-t", oid) == "commit", "selected base is not a commit")
    return oid


def capture_payload(*, workflow_root_id: str, input_convoy_id: str, source_anchor_id: str,
                    rig_root: str, writer_step_id: str, worktree_lifecycle: str,
                    base_ref: str = "@default", stored: dict[str, Any] | None = None) -> dict[str, Any]:
    root, common = repository_identity(rig_root)
    candidate = dict(version=1, workflow_root_id=workflow_root_id, generation=1,
                     writer_step_id=writer_step_id, input_convoy_id=input_convoy_id,
                     source_anchor_id=source_anchor_id, rig_root=root, common_git_dir=common,
                     base_oid="0" * 40, worktree_lifecycle=worktree_lifecycle)
    validate_record("run", candidate)
    require(isinstance(base_ref, str) and bool(base_ref) and base_ref == base_ref.strip()
            and not base_ref.startswith("-") and not re.search(r"[\x00-\x1f\x7f]", base_ref),
            "base ref must be nonempty, or explicit @default")
    if stored is not None:
        validate_record("run", stored)
        require(record_identity("run", candidate) == record_identity("run", stored),
                "captured run source or repository identity changed")
        require(stored["worktree_lifecycle"] == worktree_lifecycle, "captured run lifecycle mode changed")
        require(git(root, "cat-file", "-t", stored["base_oid"]) == "commit", "saved base commit is unavailable")
        # The initial writer is immutable provenance. Authorization of the
        # current caller remains the adapter's native claim/grant responsibility.
        return dict(stored)
    candidate["base_oid"] = resolve_base(root, base_ref)
    return validate_record("run", candidate)


def native_json(gc: str, city_root: str, args: list[str], rig: str | None = None,
                *, unwrap_singleton: bool = False) -> dict[str, Any]:
    command = [gc, "--city", city_root]
    if rig is not None:
        command += ["--rig", rig]
    env = dict(os.environ)
    for key in ("GC_CITY_URL", "GC_CITY_CONTEXT", "GC_CITY", "GC_CITY_PATH", "GC_CITY_ROOT", "GC_RIG"):
        env.pop(key, None)
    try:
        result = subprocess.run(command + args, cwd=city_root, env=env,
                                capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunError(f"native source read failed: {exc}") from exc
    require(result.returncode == 0, "native source read failed: " + result.stderr.strip()[-1000:])
    if unwrap_singleton:
        value = parse_record('{"value":' + result.stdout + '}')["value"]
        if isinstance(value, list):
            require(len(value) == 1, "native bead read must return exactly one physical row")
            value = value[0]
        require(isinstance(value, dict), "native bead read must return an object")
        return value
    return parse_record(result.stdout)


def registered_rig(gc: str, city_root: str, rig_name: str, store_ref: str) -> str:
    data = native_json(gc, city_root, ["rig", "list", "--json"])
    require(canonical_path(data.get("city_path")) == city_root, "native city identity changed")
    require(isinstance(data.get("rigs"), list), "native rig registration is missing")
    matches = [rig for rig in data["rigs"] if isinstance(rig, dict) and rig.get("name") == rig_name]
    require(len(matches) == 1, "registered rig is missing or ambiguous")
    if store_ref.startswith("rig:"):
        require(store_ref == "rig:" + rig_name, "selected store belongs to a different rig")
    elif store_ref.startswith("city:"):
        require(store_ref == "city:" + str(data.get("city_name", "")), "selected store belongs to a different city")
    else:
        raise RunError("select one explicit city:<name> or rig:<name> store")
    return canonical_path(matches[0].get("path"))


def source_context(store: Any, *, gc: str, city_root: str, workflow_root_id: str,
                   input_convoy_id: str, claimed_step_id: str | None = None,
                   expected_source_anchor_id: str | None = None,
                   require_live: bool = True) -> tuple[str, dict[str, Any]]:
    rows: dict[str, Any] = {}

    def read(bead_id: str) -> dict[str, Any]:
        if bead_id not in rows:
            try:
                snapshot = store.snapshot([bead_id])
            except (RecordError, OSError, KeyError) as exc:
                raise RunError("native source is unavailable in the selected store: " + str(bead_id)) from exc
            require(set(snapshot) == {bead_id} and snapshot[bead_id].get("id") == bead_id,
                    "native source read did not return the exact requested ID")
            rows.update(snapshot)
        row = rows[bead_id]
        require(isinstance(row.get("metadata"), dict), "native source metadata is malformed")
        meta = row["metadata"]
        outcome = meta.get("gc.outcome", "")
        require(isinstance(outcome, str) and outcome.strip() not in ("fail", "canceled", "cancelled", "skipped")
                and meta.get("molecule_failed") not in (True, "true")
                and meta.get("gc.molecule_failed") not in (True, "true")
                and not meta.get("gc.cancel_requested")
                and (row.get("status") != "closed" or outcome == "pass"),
                "native source is failed, canceled or closed without pass")
        labels = [] if row.get("labels") is None else row["labels"]
        require(isinstance(labels, list) and all(isinstance(label, str) for label in labels)
                and not any(label.startswith("hold:") for label in labels), "native source is held or has malformed labels")
        return row

    step = None
    if claimed_step_id is not None:
        step = read(claimed_step_id)
        require(step["metadata"].get("gc.root_bead_id") == workflow_root_id, "claimed step belongs to another root")
        require(step.get("status") == "in_progress", "claimed step is not in progress")
    root = read(workflow_root_id)
    meta = root["metadata"]
    require(meta.get("gc.kind") == "workflow" and (not require_live or root.get("status") != "closed"),
            "native root is not an eligible workflow")
    require(meta.get("gc.input_convoy_id") == input_convoy_id, "native input convoy identity changed")
    intake = read(input_convoy_id)
    require(intake.get("type") == "convoy", "native input is not a convoy")
    intake_meta = intake["metadata"]
    # Native source stamps share the issue-row revision used by publication.
    # Tracks edges live in a separate table and cannot establish this identity.
    source_rows = [root, intake] + ([step] if step is not None else [])
    candidates = set()
    for row in source_rows:
        for key in ("gc.source_bead_id", "gc.drain_member_id"):
            if key not in row["metadata"]:
                continue
            value = row["metadata"][key]
            require(isinstance(value, str) and value.strip() == value and bool(value)
                    and not re.search(r"[\x00-\x1f\x7f]", value), "native source pin is empty or malformed: " + key)
            if key == "gc.source_bead_id" and value == input_convoy_id:
                continue  # An explicit convoy launch identifies the convoy itself.
            candidates.add(value)
    require(len(candidates) <= 1, "native source pins disagree on the original source")
    if intake_meta.get("gc.synthetic_kind") == "drain-unit-convoy":
        member = intake_meta.get("gc.drain_member_id")
        require(isinstance(member, str) and bool(member) and member != input_convoy_id,
                "drain-unit convoy has no original source")
    require(intake_meta.get("gc.synthetic") != "true" or bool(candidates),
            "synthetic input has no immutable native source pin; use a newly created native wrapper or a real convoy")
    anchor = next(iter(candidates), input_convoy_id)
    require(expected_source_anchor_id is None or anchor == expected_source_anchor_id, "selected source anchor changed")
    source = read(anchor)
    require(source["metadata"].get("gc.synthetic") != "true", "source anchor is synthetic")
    for row in source_rows:
        for key, accepted in (("gc.source_anchor_id", {anchor}), ("gc.drain_member_id", {anchor}),
                              ("gc.source_bead_id", {anchor, input_convoy_id})):
            require(key not in row["metadata"] or row["metadata"][key] in accepted,
                    "native source pin changed: " + key)
    source_meta = source["metadata"]
    require("workflow_id" not in source_meta or source_meta["workflow_id"] == workflow_root_id,
            "source anchor belongs to another workflow")
    pins = [(row, key) for row in (*source_rows, source) for key in ("gc.root_store_ref", "gc.source_store_ref")
            if key in row["metadata"]]
    require(bool(pins) and all(row["metadata"][key] == store.store_ref for row, key in pins),
            "native source store pins are missing, empty or conflicting")
    return anchor, rows


def read_run(store: Any, *, gc: str, city_root: str, rig_name: str,
             workflow_root_id: str, input_convoy_id: str, record_bead_id: str,
             worktree_lifecycle: str, expected_source_anchor_id: str | None = None,
             claimed_step_id: str | None = None) -> dict[str, Any]:
    city_root = canonical_path(city_root)
    rig_root = registered_rig(gc, city_root, rig_name, store.store_ref)
    anchor, rows = source_context(store, gc=gc, city_root=city_root, workflow_root_id=workflow_root_id,
                                  input_convoy_id=input_convoy_id, claimed_step_id=claimed_step_id,
                                  expected_source_anchor_id=expected_source_anchor_id, require_live=False)
    raw = rows[workflow_root_id]["metadata"].get(RUN_REFERENCE_KEY)
    require(isinstance(raw, str), "native root has no explicit run reference")
    reference = parse_record(raw)
    require(set(reference) == {"kind", "identity", "bead_id"} and reference["kind"] == "run"
            and reference["bead_id"] == record_bead_id, "native run reference identity changed")
    stored = store.read_record("run", record_bead_id, reference["identity"])
    require(stored is not None, "run reference points to an empty record")
    payload = capture_payload(workflow_root_id=workflow_root_id, input_convoy_id=input_convoy_id,
                              source_anchor_id=anchor, rig_root=rig_root, writer_step_id=stored["writer_step_id"],
                              worktree_lifecycle=worktree_lifecycle, stored=stored)
    require(reference["identity"] == list(record_identity("run", payload)), "run reference tuple changed")
    return payload


def capture_run(store: Any, attempt: Any, *, gc: str, city_root: str, rig_name: str,
                workflow_root_id: str, input_convoy_id: str, record_bead_id: str,
                authority_id: str, worktree_lifecycle: str, writer_map: Any, base_ref: str = "@default",
                writer_rows: dict[str, Any] | None = None,
                allocation_rows: dict[str, Any] | None = None,
                captured_run: dict[str, Any] | None = None,
                captured_checks_config: str | None = None,
                expected_source_anchor_id: str | None = None, operation_nonce: str | None = None) -> dict[str, Any]:
    from workspace_store import GuardRead, MISSING, RecordWrite, ReferenceWrite, RunCheckPolicyProjection
    from workspace_requests import require_resolved_scope, retain_request, resolve_request

    city_root = canonical_path(city_root)
    rig_root = registered_rig(gc, city_root, rig_name, store.store_ref)
    require(canonical_path(str(store.common_git_dir)) == repository_identity(rig_root)[1],
            "record lock repository identity changed")
    require_resolved_scope(store, run_scope(workflow_root_id))
    anchor, rows = source_context(store, gc=gc, city_root=city_root, workflow_root_id=workflow_root_id,
                                  input_convoy_id=input_convoy_id, claimed_step_id=attempt.claimed_bead_id,
                                  expected_source_anchor_id=expected_source_anchor_id)
    root_meta = rows[workflow_root_id]["metadata"]
    raw_reference = root_meta.get(RUN_REFERENCE_KEY, MISSING)
    stored = None
    if raw_reference is not MISSING:
        require(isinstance(raw_reference, str), "run reference must be canonical JSON metadata")
        reference = parse_record(raw_reference)
        require(set(reference) == {"kind", "identity", "bead_id"} and reference["kind"] == "run"
                and reference["bead_id"] == record_bead_id, "run reference identity changed")
        stored = store.read_record("run", record_bead_id, reference["identity"])
        require(stored is not None, "run reference points to an empty record")
    else:
        require(store.read_record("run", record_bead_id) is None, "unreferenced run record cannot be adopted")
    payload = capture_payload(workflow_root_id=workflow_root_id, input_convoy_id=input_convoy_id,
                              source_anchor_id=anchor, rig_root=rig_root, writer_step_id=attempt.claimed_bead_id,
                              worktree_lifecycle=worktree_lifecycle, base_ref=base_ref, stored=stored or captured_run)
    require(captured_run is None or payload == captured_run, "retained allocation run changed before publication")
    reference = dict(kind="run", identity=list(record_identity("run", payload)), bead_id=record_bead_id)
    require(raw_reference is MISSING or canonical_bytes(parse_record(raw_reference)) == canonical_bytes(reference),
            "run reference payload changed")
    require(canonical_path(str(store.common_git_dir)) == payload["common_git_dir"],
            "record lock repository identity changed")
    # Every observed native row keeps its exact original revision/status/assignee.
    # The adapter checks these in the same batch as grant, record and reference.
    guards = tuple(GuardRead(bead_id, key, row["metadata"].get(key, MISSING))
                   for bead_id, row in rows.items()
                   for key in ("gc.root_bead_id", "gc.kind", "gc.input_convoy_id", "gc.source_anchor_id",
                               "gc.drain_member_id", "gc.source_bead_id", "gc.root_store_ref",
                               "gc.source_store_ref", "gc.synthetic", "gc.synthetic_kind", "workflow_id",
                               "gc.outcome", "molecule_failed", "gc.molecule_failed", "gc.cancel_requested"))
    missing_ids = [bead_id for bead_id in (record_bead_id, authority_id) if bead_id not in rows]
    if missing_ids:
        additional = store.snapshot(missing_ids)
        require(set(additional) == set(missing_ids), "native lifecycle placeholder read is incomplete")
        rows.update(additional)
    if allocation_rows is not None:
        require(set(allocation_rows) == {record_bead_id, authority_id}
                and all(rows[bead_id] == row for bead_id, row in allocation_rows.items()),
                "native run allocation changed after its original identity readback")
        rows.update(allocation_rows)
    declaration = writer_map.declaration
    map_ids = list(dict.fromkeys([declaration["expansion_root_id"], declaration["source_member_id"],
                                *(step["bead_id"] for step in declaration["steps"])]))
    if writer_rows is not None:
        require(all(bead_id in writer_rows for bead_id in map_ids), "original cooked writer readback is incomplete")
        require(all(bead_id not in rows or rows[bead_id] == writer_rows[bead_id] for bead_id in map_ids),
                "native source or writer changed after cooked admission")
        rows.update({bead_id: writer_rows[bead_id] for bead_id in map_ids})
    else:
        absent = [bead_id for bead_id in map_ids if bead_id not in rows]
        if absent:
            rows.update(store.snapshot(absent))
    projections = []
    if worktree_lifecycle == "new":
        raw_checks = root_meta.get(CHECKS_CONFIG_KEY)
        require(captured_run is None or raw_checks == captured_checks_config,
                "native required-check configuration changed after retained allocation")
        policy = capture_check_policy(payload, record_bead_id, raw_checks)
        projections = [RunCheckPolicyProjection(record_bead_id, policy)]
        guards += (GuardRead(workflow_root_id, CHECKS_CONFIG_KEY, raw_checks),)
    method = store.install_grant if stored is None else store.write_records
    prepared = method(attempt, run_scope(workflow_root_id), authority_id,
                      [RecordWrite("run", record_bead_id, payload)],
                      references=[ReferenceWrite(workflow_root_id, RUN_REFERENCE_KEY, reference)],
                      guards=guards, expected_rows=rows, operation_nonce=operation_nonce, writer_map=writer_map,
                      projections=projections)
    request_path, _ = retain_request(store, prepared)
    try:
        write_receipt = store.execute(prepared)
        readback = resolve_request(store, request_path)
    except (RecordError, OSError) as exc:
        raise RunError(f"run publication is uncertain; resolve original request {request_path}: {exc}") from exc
    # Raw authority metadata contains the retained instance token. The public
    # receipt only needs the classification and exact request binding.
    receipt = {key: value for key, value in readback.items() if key != "rows"}
    receipt["write_outcome"] = write_receipt.get("outcome")
    receipt["request_path"] = str(request_path)
    require(receipt.get("request_sha256") == prepared.sha256,
            f"run publication readback request changed; resolve original request {request_path}")
    return {"record": payload, "reference": reference, "receipt": receipt}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("capture", "read"))
    for flag in ("store-ref", "city-root", "rig-name", "workflow-root-id", "input-convoy-id", "record-bead-id"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--worktree-lifecycle", choices=("legacy", "new"), required=True)
    parser.add_argument("--claimed-step-id")
    parser.add_argument("--authority-id")
    parser.add_argument("--source-anchor-id")
    parser.add_argument("--base-ref", default="@default")
    parser.add_argument("--operation-nonce")
    parser.add_argument("--gc", default="gc")
    args = parser.parse_args(argv)
    try:
        from workspace_store import Attempt, WorkspaceStore
        city_root = canonical_path(args.city_root)
        rig_root = registered_rig(args.gc, city_root, args.rig_name, args.store_ref)
        _, common = repository_identity(rig_root)
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=city_root, common_git_dir=common)
        if args.action == "capture":
            require(bool(args.claimed_step_id) and bool(args.authority_id), "capture requires claimed step and authority IDs")
            from workspace_requests import require_resolved_scope
            require_resolved_scope(store, run_scope(args.workflow_root_id))
            from workspace_cooked import read_cooked_writer_map
            writer_map, writer_rows = read_cooked_writer_map(store, workflow_root_id=args.workflow_root_id,
                                                            claimed_step_id=args.claimed_step_id)
            result = capture_run(store, Attempt.from_env(args.claimed_step_id), gc=args.gc, city_root=city_root,
                                 rig_name=args.rig_name, workflow_root_id=args.workflow_root_id,
                                 input_convoy_id=args.input_convoy_id, record_bead_id=args.record_bead_id,
                                 authority_id=args.authority_id, worktree_lifecycle=args.worktree_lifecycle,
                                 base_ref=args.base_ref, expected_source_anchor_id=args.source_anchor_id,
                                 operation_nonce=args.operation_nonce, writer_map=writer_map, writer_rows=writer_rows)
        else:
            require(not args.authority_id and not args.operation_nonce, "read does not accept writer authority")
            result = read_run(store, gc=args.gc, city_root=city_root, rig_name=args.rig_name,
                              workflow_root_id=args.workflow_root_id, input_convoy_id=args.input_convoy_id,
                              record_bead_id=args.record_bead_id, worktree_lifecycle=args.worktree_lifecycle,
                              expected_source_anchor_id=args.source_anchor_id, claimed_step_id=args.claimed_step_id)
        print(json.dumps(result, sort_keys=True))
        if args.action == "capture" and result["receipt"].get("outcome") not in ("committed", "replayed"):
            return 1
        return 0
    except (RecordError, OSError, UnicodeError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
