#!/usr/bin/env python3
"""Native identities, frozen check policy and guarded workspace acceptance."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

from workspace_records import (RecordError, canonical_bytes, contracts, parse_record,
                               record_sha256, validate_record, verify_replay)
from workspace_run import (CHECKS_CONFIG_KEY, CHECKS_POLICY_KEY, capture_check_policy,
                           native_json, read_check_policy)
from workspace_store import (Attempt, CONTINUATION_KEY, ROOT_KEYS, GuardRead, NativeRunContinuation,
                             PreparedWrite, WorkspaceStore, merge_cooked_context, validate_native_continuation)
from workspace_entry import healthy, native_root, read_entry, read_native_continuation, reference
from workspace_cooked import read_cooked_writer_map
from workspace_checkout import WorkspaceCheckout, load_workspace_context
import workspace_outputs as outputs


def require(condition, message):
    if not condition:
        raise RecordError("native workspace acceptance: " + message)


def validate_check_policy(policy, run, run_record_id, native_config):
    """Validate the initial-run sidecar against independently read native config."""
    validate_record("run", run)
    expected = capture_check_policy(run, run_record_id, native_config)
    require(isinstance(policy, dict) and type(policy.get("version")) is int
            and policy == expected, "required-check policy, run, base or command scope changed")
    return copy.deepcopy(expected)


class _ReadFence:
    """Keep the first full work-store row, including its original revision."""
    def __init__(self, store):
        self.store, self.rows, self.cooked_rows = store, {}, {}

    def __getattr__(self, name):
        return getattr(self.store, name)

    def retain(self, rows):
        require(isinstance(rows, dict) and all(isinstance(row, dict) and row.get("id") == key
                                             for key, row in rows.items()), "incomplete original native rows")
        merge_cooked_context(self.original_rows, rows)
        require(len(set(self.rows) | set(rows)) <= 100, "complete native evidence exceeds the guarded row bound")
        self.rows.update(copy.deepcopy(rows))
        return copy.deepcopy(rows)

    @property
    def original_rows(self):
        return merge_cooked_context(self.cooked_rows, self.rows)

    def snapshot(self, ids):
        rows = self.store.snapshot(ids)
        require(set(rows) == set(ids), "native snapshot did not return the exact requested rows")
        return self.retain(rows)

    def cooked_snapshot(self, ids):
        """Read graph context without treating every sibling as an operation guard."""
        rows = self.store.snapshot(ids)
        require(set(rows) == set(ids), "native snapshot did not return the exact requested rows")
        self.cooked_rows = merge_cooked_context(self.original_rows, rows)
        return rows

    def read_record(self, kind, bead_id, identity=None, *, continuation=None):
        if kind == "workspace" and continuation is None:
            row = self.snapshot([bead_id])[bead_id]
            raw = row["metadata"].get(contracts()[kind]["metadata_key"])
            if raw is not None:
                workspace = validate_record(kind, parse_record(raw))
                writer = self.snapshot([workspace["writer_step_id"]])[workspace["writer_step_id"]]
                if native_root(writer) != workspace["workflow_root_id"]:
                    continuation, rows = read_native_continuation(self, claimed_step_id=writer["id"],
                        requested_root_id=workspace["workflow_root_id"])
                    self.retain(rows)
        if continuation is not None:
            require(isinstance(continuation, NativeRunContinuation), "record read requires typed native inheritance")
            self.snapshot(list(dict.fromkeys([bead_id, *continuation.row_ids])))
            validate_native_continuation(continuation, self.rows, store_ref=self.store_ref,
                workflow_root_id=continuation.binding["workflow_root_id"], require_reference=True)
            payload = self.store.read_record(kind, bead_id, identity, continuation=continuation)
            self.snapshot(list(dict.fromkeys([bead_id, *continuation.row_ids])))
        else:
            payload = self.store.read_record(kind, bead_id, identity)
        row = self.snapshot([bead_id])[bead_id]
        raw = row["metadata"].get(contracts()[kind]["metadata_key"])
        require((raw is None) == (payload is None), "record changed during native readback")
        if payload is not None:
            require(isinstance(raw, str) and canonical_bytes(payload).decode() == raw,
                    "record differs from its original native row")
        return payload


class NativeSourceRuntime:
    """Read actual native workflow authority; never accept manifest role flags.

    One instance spans qualification through one guarded publication. Construct
    a new instance after a completed workflow transition, never refresh its rows.
    Session authority is read separately and is not a cross-store transaction.
    """
    def __init__(self, store, *, gc, city_root, rig_name, run, plan, artifact_root,
                 evidence_dir, claimed_step_id, native_rows=None):
        self.store, self.gc = store, str(gc)
        self.city_root, self.rig_name = str(Path(city_root).resolve(strict=True)), rig_name
        require(self.city_root == store.cwd and self.gc == str(store.gc), "native command/store binding differs")
        self.run, self.plan = copy.deepcopy(run), copy.deepcopy(plan)
        validate_record("run", self.run)
        validate_record("source-plan", self.plan)
        self.claimed_step_id = claimed_step_id
        self.artifact_root = Path(artifact_root).resolve(strict=True)
        require(Path(artifact_root) == self.artifact_root and self.artifact_root.is_dir(),
                "artifact root must be an existing canonical directory")
        self.evidence_dir = str(Path(evidence_dir))
        self._fence, self._sessions, self._qualified = _ReadFence(store), {}, {}
        self._written_requests = {}
        self._formula_sources = {}
        self._continuations = {}
        self.continuation = None
        self._entry_initialized = False
        if native_rows is not None:
            self._fence.retain(native_rows)
        self._bound_workspace = None
        registration = native_json(self.gc, self.city_root, ["rig", "list", "--json"])
        require(isinstance(registration.get("city_name"), str) and registration["city_name"],
                "native registration has no exact city identity")
        city_ref = "city:" + registration["city_name"]
        self._session_store = WorkspaceStore(city_ref, gc=self.gc, cwd=self.city_root,
                                            timeout=store.timeout)
        self._entry()
        self._admitted()

    @property
    def guard_rows(self):
        return copy.deepcopy(self._fence.rows)

    @property
    def original_rows(self):
        """Original graph context plus selected guards, without promoting siblings."""
        return self._fence.original_rows

    @property
    def attempt(self):
        return self._admitted()[1]

    @property
    def writer_map(self):
        return self._writer_map(self.claimed_step_id, read_only=True, require_reference=False)[0]

    def _writer_map(self, claimed_step_id, *, read_only=False, require_reference=True):
        continuation = self._occurrence_continuation(claimed_step_id, require_reference=require_reference)
        writer_map, rows = read_cooked_writer_map(self._fence, workflow_root_id=self.run["workflow_root_id"],
            claimed_step_id=claimed_step_id, read_only=read_only, continuation=continuation,
            continuation_rows=self.guard_rows if continuation is not None else None)
        self._fence.cooked_rows = merge_cooked_context(self.original_rows, rows)
        declaration = writer_map.declaration
        selected = {claimed_step_id, declaration["source_member_id"], declaration["expansion_root_id"]}
        selected.update(key for key in rows if key in self._fence.rows)
        self._fence.retain({key: rows[key] for key in selected})
        self._formula_sources[declaration["formula_source"]] = declaration["formula_hash"]
        return writer_map, rows

    @property
    def guards(self):
        return tuple(GuardRead(key, name, value) for key, row in self._fence.rows.items()
                     for name, value in row["metadata"].items())

    @property
    def check_policy(self):
        return copy.deepcopy(self._policy)

    @property
    def required_checks(self):
        return copy.deepcopy(self._policy["required_checks"])

    @property
    def policy_binding(self):
        return {key: self._policy[key] for key in ("run_record_id", "base_oid", "policy_sha256")} | {
            "run_sha256": record_sha256(self.run), "source_plan_sha256": record_sha256(self.plan)}

    def _entry(self):
        entry = read_entry(self._fence, gc=self.gc, city_root=self.city_root, rig_name=self.rig_name,
            workflow_root_id=self.run["workflow_root_id"], claimed_step_id=self.claimed_step_id,
            worktree_lifecycle="new", generation=self.plan["generation"], require_plan=True,
            expected_run_sha256=record_sha256(self.run), expected_plan_sha256=record_sha256(self.plan))
        verify_replay("run", self.run, entry["run"])
        verify_replay("source-plan", self.plan, entry["source_plan"])
        self._fence.retain(entry.get("_native_rows", {}))
        context = entry.get("native_continuation")
        continuation = NativeRunContinuation(canonical_bytes(context)) if context is not None else None
        require(not self._entry_initialized or self.continuation == continuation,
                "invoking native continuation changed after entry")
        if continuation is not None:
            validate_native_continuation(continuation, self._fence.rows, store_ref=self.store.store_ref,
                workflow_root_id=self.run["workflow_root_id"], claimed_step_id=self.claimed_step_id)
            self._continuations[continuation.sha256] = continuation
        self.continuation = continuation
        self.native_workflow_root_id = entry.get("native_workflow_root_id", self.run["workflow_root_id"])
        self.native_input_convoy_id = entry.get("native_input_convoy_id", entry["input_convoy_id"])
        require(self._fence.rows[self.native_workflow_root_id]["status"] != "closed",
                "invoking native workflow root is no longer active")
        self._entry_initialized = True
        require(str(self.store.common_git_dir) == self.run["common_git_dir"], "store lock repository changed")
        if self.plan["generation"] == 1:
            require(self.plan["base_oid"] == self.run["base_oid"], "source plan changed the initial run base")
        else:
            require(self.plan["base_oid"] == self.plan["parent_canonical_oid"], "fix generation lost its parent base")
        self.run_record_id = entry["run_reference"]["bead_id"]
        self.plan_record_id = entry["source_plan_reference"]["bead_id"]
        self.input_convoy_id = entry["input_convoy_id"]
        policy = read_check_policy(self._fence, self.run_record_id, self.run)
        root = self._fence.rows[self.run["workflow_root_id"]]
        require(root["status"] != "closed" or continuation is not None and continuation.binding["version"] == 2,
                "workflow root is no longer active")
        self._policy = validate_check_policy(policy, self.run, self.run_record_id,
                                             root["metadata"].get(CHECKS_CONFIG_KEY))
        require(entry.get("check_policy") == self._policy, "entry and frozen policy readback differ")
        return entry

    def _occurrence_continuation(self, claimed_step_id, *, require_reference=True):
        step = self._fence.snapshot([claimed_step_id])[claimed_step_id]
        require(step["metadata"].get("gc.root_store_ref") == self.store.store_ref
                and all(step["metadata"][key] == native_root(step) for key in ROOT_KEYS if key in step["metadata"]),
                "retained native occurrence has conflicting root/store authority")
        if native_root(step) == self.run["workflow_root_id"]:
            return None
        continuation, rows = read_native_continuation(self._fence, claimed_step_id=claimed_step_id,
            requested_root_id=self.run["workflow_root_id"])
        self._fence.retain(rows)
        binding = validate_native_continuation(continuation, self._fence.rows, store_ref=self.store.store_ref,
            workflow_root_id=self.run["workflow_root_id"], claimed_step_id=claimed_step_id,
            require_reference=require_reference)
        require(binding["generation"] == self.plan["generation"]
                and binding["run_sha256"] == record_sha256(self.run)
                and binding["source_plan_sha256"] == record_sha256(self.plan)
                and binding["run_ref"]["bead_id"] == self.run_record_id
                and binding["source_plan_ref"]["bead_id"] == self.plan_record_id
                and binding["check_policy_sha256"] == hashlib.sha256(canonical_bytes(self._policy)).hexdigest(),
                "retained native occurrence differs from the original run/plan/policy")
        self._continuations[continuation.sha256] = continuation
        return continuation

    def retained_workspace_continuation(self, workspace):
        """Resolve the workspace writer's child, independently of the current caller."""
        validate_record("workspace", workspace)
        require(all(workspace[key] == self.plan[key] for key in
                    ("workflow_root_id", "generation", "source_plan_owner_id")),
                "retained workspace belongs to another selected generation")
        continuation = self._occurrence_continuation(workspace["writer_step_id"])
        if continuation is not None:
            require(continuation.binding["member_id"] == workspace["active_member_id"],
                    "workspace retained child belongs to another active member")
        return continuation

    def _session(self, step, *, live=False):
        metadata = step["metadata"]
        session_id = metadata.get("gc.session_id")
        require(isinstance(session_id, str) and session_id, "step has no retained native session")
        row = self._session_store.snapshot([session_id])[session_id]
        meta = row["metadata"]
        keys = ("instance_token", "template", "session_name", "alias", "configured_named_identity", "pool_managed", "pool_slot", "session_origin")
        require(all(isinstance(meta[key], str) for key in (*keys, "state", "current_claim_bead_id") if key in meta),
                "native session identity metadata is malformed")
        require(row["type"] == "session" and isinstance(meta.get("instance_token"), str)
                and meta["instance_token"].strip(), "native session instance is absent")
        target = metadata.get("gc.run_target")
        require(isinstance(target, str) and target and meta.get("template") in (target, self.rig_name + "/" + target),
                "native session template differs from the cooked role")
        require(meta.get("session_name") and metadata.get("gc.session_name") == meta["session_name"],
                "retained native session name changed")
        healthy(step)
        if live:
            require(row["status"] != "closed" and meta.get("state", "") in ("", "active", "awake", "creating", "start-pending")
                    and meta.get("current_claim_bead_id") == step["id"], "retained session no longer claims this physical step")
            assignee = meta.get("alias", "").strip() or meta.get("configured_named_identity", "").strip()
            if not assignee:
                pool = meta.get("pool_managed") == "true" or meta.get("pool_slot") or meta.get("session_origin") == "ephemeral"
                assignee = session_id if pool else meta.get("session_name") or session_id
            require(step["status"] == "in_progress" and step["assignee"] == assignee,
                    "native claimed step status or assignee changed")
        else:
            require(step["status"] == "closed" and metadata.get("gc.outcome") == "pass",
                    "historical native role did not complete successfully")
        attempt = Attempt(session_id, meta["instance_token"], step["id"])
        retained = metadata.get("gc.session_attempt_id")
        require(retained is None or isinstance(retained, str) and re.fullmatch(r"writer-[0-9a-f]{64}", retained),
                "native retained attempt stamp is malformed")
        if live:
            require(retained is None or retained == attempt.writer_attempt_id, "live native attempt stamp is stale")
        identity = {"step_id": step["id"], "session_id": session_id,
                    "attempt_id": retained if not live and retained is not None else attempt.writer_attempt_id}
        previous = self._sessions.get(session_id)
        require(previous is None or all(previous["metadata"].get(key) == meta.get(key) for key in keys),
                "session instance or native identity changed after qualification")
        self._sessions.setdefault(session_id, copy.deepcopy(row))
        return identity, attempt

    def _admitted(self):
        step = self._fence.snapshot([self.claimed_step_id])[self.claimed_step_id]
        require(native_root(step) == self.native_workflow_root_id
                and all(step["metadata"][key] == self.native_workflow_root_id for key in ROOT_KEYS if key in step["metadata"])
                and step["metadata"].get("gc.root_store_ref") == self.store.store_ref,
                "invoking step belongs to another root/store")
        identity, attempt = self._session(step, live=True)
        require(Attempt.from_env(self.claimed_step_id) == attempt, "invoking native session/instance differs from the retained claim")
        return identity, attempt

    def _roles(self, recorder_step_id=None):
        writer_map, rows = self._writer_map(recorder_step_id or self.claimed_step_id)
        declaration = writer_map.declaration
        self._formula_sources[declaration["formula_source"]] = declaration["formula_hash"]
        entries = declaration["steps"]
        predicates = {
            "reviewer": lambda item: "review" in item["record_kinds"] and
                item["step_id"].rsplit(".", 1)[-1] == "independent-acceptance",
            "recorder": lambda item: "member-result" in item["record_kinds"],
        }
        roles = {}
        for role, predicate in predicates.items():
            matches = [item for item in entries if predicate(item)]
            require(len(matches) == 1, "missing or ambiguous physical " + role + " occurrence")
            roles[role] = matches[0]
        producers = [item for item in entries if "workspace" in item["record_kinds"]
                     and item["step_id"] in roles["reviewer"]["dependencies"]
                     and rows[item["bead_id"]]["metadata"].get("gc.build.artifact_schema") == "gc.build.implementation-summary.v1"]
        require(len(producers) == 1, "missing or ambiguous actual review-predecessor producer occurrence")
        roles["producer"] = producers[0]
        require(len({item["bead_id"] for item in roles.values()}) == 3,
                "producer, independent reviewer and recorder must be distinct physical occurrences")
        require(roles["producer"]["step_id"] in roles["reviewer"]["dependencies"]
                and roles["reviewer"]["step_id"] in roles["recorder"]["dependencies"],
                "actual cooked roles lack the producer-review-recorder ordering")
        if recorder_step_id:
            require(roles["recorder"]["bead_id"] == recorder_step_id, "result writer is not its actual native recorder")
        selected = {item["step_id"] for item in roles.values()}
        self._fence.retain({item["bead_id"]: rows[item["bead_id"]] for item in entries
                            if item["step_id"] in selected})
        return roles, writer_map

    def role_identities(self, recorder_step_id=None):
        roles, _ = self._roles(recorder_step_id)
        return self._identities(roles)

    def _identities(self, roles):
        identities = {role: self._session(self._fence.rows[item["bead_id"]],
                         live=item["bead_id"] == self.claimed_step_id)[0] for role, item in roles.items()}
        require(identities["producer"]["session_id"] != identities["reviewer"]["session_id"],
                "producer and reviewer use the same native session")
        return identities

    def _workspace(self, owner_id):
        owner = self._fence.snapshot([owner_id])[owner_id]
        ref = reference(owner["metadata"].get("gc.workspace_ref"), "workspace")
        row = self._fence.snapshot([ref["bead_id"]])[ref["bead_id"]]
        raw = row["metadata"].get(contracts()["workspace"]["metadata_key"])
        require(isinstance(raw, str), "workspace reference points to an empty native record")
        retained = parse_record(raw)
        continuation = self.retained_workspace_continuation(retained)
        observed = self._fence.read_record("workspace", ref["bead_id"], ref["identity"], continuation=continuation)
        verify_replay("workspace", retained, observed)
        run, plan, workspace, rows = load_workspace_context(self._fence, gc=self.gc, city_root=self.city_root,
            rig_name=self.rig_name, workflow_root_id=self.run["workflow_root_id"],
            input_convoy_id=self.input_convoy_id, run_record_id=self.run_record_id,
            plan_record_id=self.plan_record_id, workspace_record_id=ref["bead_id"],
            claimed_step_id=self.claimed_step_id, record_kind=None, source_rows=self.guard_rows)
        verify_replay("run", run, self.run)
        verify_replay("source-plan", plan, self.plan)
        self._fence.retain(rows)
        require(workspace["workspace_owner_id"] == owner_id, "workspace reference names another physical owner")
        return workspace

    def _record(self, kind, owner_id):
        row = self._fence.snapshot([owner_id])[owner_id]
        ref = reference(row["metadata"].get(contracts()[kind]["metadata_key"] + "_ref"), kind)
        record = self._fence.read_record(kind, ref["bead_id"], ref["identity"])
        require(record is not None, "retained " + kind + " reference is empty")
        return record

    def _result_context(self, result):
        self._entry()
        self._admitted()
        workspace = self._workspace(result["workspace_owner_id"])
        historical = workspace["active_member_id"] != result["member_id"]
        subject = workspace
        if historical:
            node = next(node for node in self.plan["nodes"] if node["owner_id"] == workspace["workspace_owner_id"])
            require(node["strategy"] == workspace["strategy"] == "shared-chain"
                    and result["member_id"] in node["member_ids"], "result has no retained shared checkpoint")
            position = node["member_ids"].index(result["member_id"])
            require(position < workspace["next_member_position"], "checkpoint is not an earlier completed member")
            predecessors = node["source_predecessor_owner_ids"]
            input_oid = self.plan["base_oid"]
            if predecessors:
                require(len(predecessors) == 1, "shared checkpoint has ambiguous initial source")
                output = self._record("owner-output", predecessors[0])
                require(all(output[key] == self.plan[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id")),
                        "shared checkpoint initial source belongs to another generation")
                input_oid = output["output_oid"]
            for member_id in node["member_ids"][:workspace["next_member_position"]]:
                checkpoint = self._record("member-result", member_id)
                require(all(checkpoint[key] == result[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id", "workspace_owner_id"))
                        and checkpoint["member_id"] == member_id and checkpoint["input_oid"] == input_oid
                        and checkpoint["acceptance"]["status"] == "accepted", "retained shared checkpoint chain changed")
                input_oid = checkpoint["output_oid"]
                if member_id == result["member_id"]:
                    verify_replay("member-result", checkpoint, result)
            require(workspace["input_oid"] == input_oid, "current shared input differs from its retained accepted chain")
            head = outputs.git_value(workspace["work_dir"], "rev-parse", "--verify", "HEAD^{commit}")
            require(head == workspace["current_oid"], "current shared workspace HEAD differs from its native record")
            self._checkout(workspace, head)
            require(outputs.git(workspace["work_dir"], "merge-base", "--is-ancestor", result["output_oid"], head).returncode == 0,
                    "retained checkpoint is absent from the current shared source")
            subject = dict(workspace, phase="result", input_oid=result["input_oid"], current_oid=result["output_oid"],
                           output_oid=result["output_oid"], active_member_id=result["member_id"], next_member_position=position)
        else:
            head = result["output_oid"]
            self._checkout(workspace, head)
        binding = outputs.result_binding(self.run, self.plan, subject, store_ref=self.store.store_ref,
                                         member_id=result["member_id"], output_oid=result["output_oid"])
        return {"binding": binding, "required_checks": self.required_checks, "work_dir": workspace["work_dir"]}, historical, head

    def _checkout(self, workspace, output_oid, *, advancing=False):
        require(workspace["phase"] in ("entry", "active", "result"), "workspace is blocked or inactive")
        if workspace["phase"] == "result":
            require(workspace["current_oid"] == workspace["output_oid"] == output_oid,
                    "recorded workspace result HEAD changed")
        elif not advancing:
            require(workspace["current_oid"] in (workspace["input_oid"], output_oid), "workspace current source changed")
        # The temporary expected HEAD is checked by native verify and real Git.
        # No record is changed while an implementation/integration awaits publication.
        expected = copy.deepcopy(workspace)
        expected.update(phase="active", current_oid=output_oid)
        continuation = self.retained_workspace_continuation(workspace)
        inherited = {"continuation": continuation, "native_rows": self.guard_rows} if continuation is not None else {}
        checkout = WorkspaceCheckout(self.run, expected, store_ref=self.store.store_ref,
            evidence_dir=self.evidence_dir, gc=self.gc, city_root=self.city_root,
            parent=str(Path(workspace["work_dir"]).parent),
            allow_external_parent=workspace.get("layout", {}).get("allow_external_parent", True), **inherited)
        observed = checkout.verify()
        row = self._fence.snapshot([workspace["workspace_bead_id"]])[workspace["workspace_bead_id"]]
        require(all(row["metadata"].get(key) == value for key, value in observed["owner_metadata"].items()),
                "physical native workspace ownership projection changed")
        return observed

    def workspace_context(self, owner_id, member_id, output_oid):
        self._entry()
        self._admitted()
        workspace = self._workspace(owner_id)
        binding = outputs.result_binding(self.run, self.plan, workspace, store_ref=self.store.store_ref,
                                         member_id=member_id, output_oid=output_oid)
        self._checkout(workspace, output_oid)
        return {"binding": binding, "required_checks": self.required_checks, "work_dir": workspace["work_dir"]}

    def _fresh(self):
        self._fence.snapshot(list(self._fence.rows))
        self._entry()
        self._admitted()
        for continuation in self._continuations.values():
            validate_native_continuation(continuation, self._fence.rows, store_ref=self.store.store_ref,
                workflow_root_id=self.run["workflow_root_id"])
        if self._sessions:
            rows = self._session_store.snapshot(list(self._sessions))
            for key, row in rows.items():
                require(row["metadata"].get("instance_token") == self._sessions[key]["metadata"]["instance_token"],
                        "retained historical native session instance changed")
                require(all(row["metadata"].get(name) == self._sessions[key]["metadata"].get(name) for name in
                            ("template", "session_name", "alias", "configured_named_identity", "pool_managed", "pool_slot", "session_origin")),
                        "retained historical native session identity changed")
        for source, digest in self._formula_sources.items():
            path = Path(source)
            require(path.resolve(strict=True) == path and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                    "native formula source changed after occurrence qualification")

    def qualify_native(self, result):
        validate_record("member-result", result)
        require(all(result[key] == self.plan[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id")),
                "result is outside the currently selected native source generation")
        context, historical, current_head = self._result_context(result)
        binding = context["binding"]
        roles, _ = self._roles(result["writer_step_id"])
        identities = self._identities(roles)
        producer = self._fence.rows[roles["producer"]["bead_id"]]
        require(producer["metadata"].get("gc.source_anchor_id", producer["metadata"].get("gc.drain_member_id")) == result["member_id"],
                "native producer occurrence belongs to another source member")
        raw = producer["metadata"].get("gc.worktree_ref")
        expected_ref = {"version": 1, "binding_step_id": producer["id"],
            "workflow_root_id": native_root(producer), "generation": result["generation"],
            "workspace_owner_id": result["workspace_owner_id"], "workspace_bead_id": binding["workspace_bead_id"],
            "store_ref": self.store.store_ref, "native_attempt_id": binding["native_attempt_id"]}
        require(isinstance(raw, str) and parse_record(raw) == expected_ref,
                "producer lacks its exact retained native workspace reference")
        member = self._fence.snapshot([result["member_id"]])[result["member_id"]]
        if "gc.workspace_result_ref" in member["metadata"]:
            ref = reference(member["metadata"]["gc.workspace_result_ref"], "member-result")
            recorded = self._fence.read_record("member-result", ref["bead_id"], ref["identity"])
            require(recorded is not None, "member result reference is empty")
            verify_replay("member-result", recorded, result)
        else:
            require(self.claimed_step_id == result["writer_step_id"], "unrecorded output may only be qualified by its native recorder")
        native = {"verified": True, "current_generation": self.plan["generation"],
            **{key: result[key] for key in ("workflow_root_id", "generation", "workspace_owner_id", "member_id")},
            "store_ref": self.store.store_ref, "head_oid": result["output_oid"], "clean": True,
            "work_dir": binding["work_dir"], "common_git_dir": binding["common_git_dir"],
            "native_attempt_id": binding["native_attempt_id"], "result_binding": binding,
            "historical_checkpoint": historical, "current_head_oid": current_head,
            "native_workflow_root_id": self.native_workflow_root_id,
            "native_input_convoy_id": self.native_input_convoy_id,
            "producer_native_workflow_root_id": native_root(producer),
            "policy_binding": self.policy_binding, "session_atomicity": "separate_native_readback"}
        for role, identity in identities.items():
            native.update({role + "_" + key: value for key, value in identity.items()})
        outputs.validate_accepted_result(result, plan=self.plan, store_ref=self.store.store_ref,
            repo_dir=self.run["rig_root"], required_checks=self.required_checks,
            artifact_root=self.artifact_root, native_evidence=native,
            work_dir=None if historical else context["work_dir"])
        for check in result["acceptance"]["project_checks"]:
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifact_root)
            require(proof.get("policy_binding") == self.policy_binding, "project check lost its native run/base/policy binding")
        review = result["acceptance"]["independent_review"]
        proof = outputs.read_artifact({"path": review["report_path"], "sha256": review["report_sha256"]}, self.artifact_root)
        require(proof.get("policy_binding") == self.policy_binding, "independent review lost its native run/base/policy binding")
        self._fresh()
        native["guard_rows"] = self.guard_rows
        self._qualified[record_sha256(result)] = copy.deepcopy(native)
        return native

    def acceptance_context(self, result, native):
        require(self._qualified.get(record_sha256(result)) == native,
                "context requires this runtime's actual native qualification")
        self._fresh()
        return {"binding": copy.deepcopy(native["result_binding"]), "required_checks": self.required_checks,
                "work_dir": native["work_dir"]}

    def advance_written_rows(self, resolved_rows, *, prepared):
        """Acknowledge only our frozen request's exact native committed readback."""
        require(isinstance(prepared, PreparedWrite), "row advancement requires the actual frozen write request")
        binding = {"city_root": self.city_root, "store_ref": self.store.store_ref,
                   "common_git_dir": self.run["common_git_dir"]}
        require(prepared.binding_bytes == canonical_bytes(binding), "write receipt belongs to another store/repository")
        resolved = self.store.resolve(prepared)
        require(resolved.get("outcome") in ("committed", "replayed")
                and resolved.get("request_sha256") == prepared.sha256 and resolved.get("rows") == resolved_rows,
                "row advancement lacks exact native request/row readback")
        before = parse_record(prepared.before_bytes.decode())
        after = parse_record(prepared.after_bytes.decode())
        original = self.original_rows
        require(set(self._fence.rows).issubset(before)
                and all(canonical_bytes(before[key]) == canonical_bytes(original[key])
                        for key in set(before) & set(original)),
                "write did not guard the originally qualified rows")
        protected = {self.run_record_id: (contracts()["run"]["metadata_key"], CHECKS_POLICY_KEY),
                     self.plan_record_id: (contracts()["source-plan"]["metadata_key"],),
                     self.run["workflow_root_id"]: ("gc.implementation_run_ref", CHECKS_CONFIG_KEY, "gc.input_convoy_id")}
        for key, names in protected.items():
            if key in before:
                require(all(before[key]["metadata"].get(name) == after[key]["metadata"].get(name) for name in names),
                        "acknowledged write changed immutable source/policy authority")
        relationship_keys = ("workflow_id", "molecule_id", "gc.root_bead_id", "gc.root_store_ref",
            "gc.kind", "gc.input_convoy_id", "gc.build.implementation_convoy_id", "gc.parent_convoy_id",
            "gc.drain_control_id", "gc.drain_member_id", "gc.source_root_id", "gc.source_generation",
            "gc.source_plan_owner_id", "gc.source_plan_sha256")
        for continuation in self._continuations.values():
            for key in continuation.row_ids:
                require(all(before[key]["metadata"].get(name) == after[key]["metadata"].get(name)
                            for name in relationship_keys), "acknowledged write changed native inheritance authority")
            child = continuation.binding["child_root_id"]
            expected = {"gc.implementation_run_ref": canonical_bytes(continuation.binding["run_ref"]).decode(),
                        CONTINUATION_KEY: continuation.reference_bytes.decode()}
            require(all(after[child]["metadata"].get(name) == value for name, value in expected.items()),
                    "acknowledged write lost its exact inherited run reference")
        self._written_requests[prepared.sha256] = prepared
        self._fence.cooked_rows.update({key: copy.deepcopy(row) for key, row in resolved_rows.items()
                                       if key in self._fence.cooked_rows})
        self._fence.rows.update(copy.deepcopy(resolved_rows))
        self._qualified.clear()
        return {"outcome": resolved["outcome"], "request_sha256": prepared.sha256}

    def admit_continuation(self, workspace, original_rows, attempt):
        """Prove the current and retained prior writer without transferring a grant."""
        validate_record("workspace", workspace)
        self._fence.retain(original_rows)
        self._entry()
        identity, actual_attempt = self._admitted()
        require(isinstance(attempt, Attempt) and attempt == actual_attempt, "continuation names another retained writer attempt")
        require(all(workspace[key] == self.plan[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id")),
                "continuation workspace belongs to another selected generation")
        actual = self._workspace(workspace["workspace_owner_id"])
        verify_replay("workspace", actual, workspace)
        previous_step = self._fence.snapshot([workspace["writer_step_id"]])[workspace["writer_step_id"]]
        previous, _ = self._session(previous_step, live=previous_step["id"] == self.claimed_step_id)
        require(previous["attempt_id"] == workspace["writer_attempt_id"], "continuation workspace retained another writer instance")
        self._fresh()
        return {"identity": identity, "previous_identity": previous, "guard_rows": self.guard_rows,
                "policy_binding": self.policy_binding, "session_atomicity": "separate_native_readback"}

    def recheck_continuation(self):
        self._fresh()

    def bind_workspace(self, workspace, native_rows):
        validate_record("workspace", workspace)
        self._fence.retain(native_rows)
        actual = self._workspace(workspace["workspace_owner_id"])
        verify_replay("workspace", actual, workspace)
        self._bound_workspace = copy.deepcopy(workspace)

    def verify_integration(self, work_dir, bundle, head_oid):
        self._fresh()
        workspace = self._bound_workspace
        require(workspace is not None, "integration requires the bound provisioned workspace")
        _, attempt = self._admitted()
        metadata = self._fence.rows[self.claimed_step_id]["metadata"]
        require(workspace["writer_step_id"] == self.claimed_step_id and workspace["writer_attempt_id"] == attempt.writer_attempt_id
                and metadata.get("gc.source_anchor_id", metadata.get("gc.drain_member_id")) == workspace["active_member_id"],
                "integration owner differs from the actual retained member writer attempt")
        require(bundle.get("strategy") == workspace["strategy"] == "integration"
                and all(bundle.get(key) == workspace[key] for key in ("workflow_root_id", "generation", "workspace_owner_id"))
                and bundle.get("store_ref") == self.store.store_ref and bundle.get("base_oid") == self.plan["base_oid"]
                and bundle.get("member_id") == workspace["active_member_id"]
                and str(Path(work_dir).resolve(strict=True)) == workspace["work_dir"], "integration native source binding changed")
        nodes = [node for node in self.plan["nodes"] if node["owner_id"] == workspace["workspace_owner_id"]]
        require(len(nodes) == 1 and [item["owner_id"] for item in bundle.get("predecessors", [])]
                == nodes[0]["source_predecessor_owner_ids"], "integration predecessor order differs from the frozen plan")
        for predecessor in bundle["predecessors"]:
            output = self._record("owner-output", predecessor["owner_id"])
            require(all(output[key] == self.plan[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id"))
                    and output["workspace_owner_id"] == predecessor["owner_id"]
                    and output["output_oid"] == predecessor["output_oid"]
                    and record_sha256(output) == predecessor["workspace_output_sha256"],
                    "integration bundle changed an authoritative predecessor output")
            result = self._record("member-result", output["final_member_id"])
            require(record_sha256(result) == output["final_member_result_sha256"]
                    and result["workspace_owner_id"] == predecessor["owner_id"]
                    and result["member_id"] == output["final_member_id"] and result["output_oid"] == output["output_oid"],
                    "integration predecessor result changed")
            self.qualify_native(result)
        self._checkout(workspace, head_oid, advancing=True)
        require(outputs.git(self.run["rig_root"], "merge-base", "--is-ancestor", bundle["base_oid"], head_oid).returncode == 0,
                "integration HEAD no longer descends from the selected plan base")
        return {"verified": True, "clean": True, **{key: bundle[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "member_id", "base_oid", "store_ref")},
            "head_oid": head_oid, "native_attempt_id": workspace["native_attempt_id"],
            "guard_rows": self.guard_rows, "policy_binding": self.policy_binding}

    def execute_checks(self, owner_id, member_id, output_oid, *, timeout=60):
        context = self.workspace_context(owner_id, member_id, output_oid)
        roles, _ = self._roles()
        require(roles["producer"]["bead_id"] == self.claimed_step_id, "checks require the actual cooked producer")
        producer, _ = self._admitted()
        proofs = outputs.execute_checks(context["binding"], context["work_dir"], self.required_checks, producer,
            self.artifact_root / ("checks-" + producer["attempt_id"] + "-" + output_oid), timeout=timeout)
        bound = []
        for position, check in enumerate(proofs):
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifact_root)
            retained = outputs.immutable_json(Path(check["evidence_path"]).with_name(f"native-check-{position}.json"),
                                              dict(proof, policy_binding=self.policy_binding))
            bound.append(dict(check, evidence_path=retained["path"], evidence_sha256=retained["sha256"]))
        self._fresh()
        return bound

    def make_member_result(self, owner_id, member_id, output_oid, checks, review, artifacts):
        context = self.workspace_context(owner_id, member_id, output_oid)
        roles, _ = self._roles()
        require(roles["recorder"]["bead_id"] == self.claimed_step_id, "result construction requires the actual cooked recorder")
        commits = outputs.git_value(context["work_dir"], "rev-list", "--reverse", "--topo-order",
                                    context["binding"]["input_oid"] + ".." + output_oid).splitlines()
        result = outputs.make_member_result(context["binding"], writer_step_id=self.claimed_step_id,
            commit_oids=commits, checks=checks, review=review, artifacts=artifacts,
            required_checks=self.required_checks, artifact_root=self.artifact_root, work_dir=context["work_dir"])
        self.qualify_native(result)
        return result

    def begin_review(self, owner_id, member_id, output_oid, checks, artifacts):
        context = self.workspace_context(owner_id, member_id, output_oid)
        roles, _ = self._roles()
        require(roles["reviewer"]["bead_id"] == self.claimed_step_id, "review requires the actual independent cooked occurrence")
        producer = self._session(self._fence.rows[roles["producer"]["bead_id"]])[0]
        reviewer, _ = self._admitted()
        for check in checks:
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifact_root)
            require(proof.get("policy_binding") == self.policy_binding, "review lacks native run-bound project checks")
        review = outputs.begin_review(context["binding"], context["work_dir"], checks, self.required_checks,
                                      producer, reviewer, artifacts, self.artifact_root)
        return dict(review, policy_binding=self.policy_binding)

    def complete_review(self, context, report, status, evidence_path):
        require(context.get("policy_binding") == self.policy_binding, "review changed the frozen run policy")
        binding = context["binding"]
        current = self.workspace_context(binding["workspace_owner_id"], binding["member_id"], binding["output_oid"])
        require(current["binding"] == binding and context["required_checks"] == self.required_checks,
                "review workspace or required commands changed")
        roles, _ = self._roles()
        reviewer, _ = self._admitted()
        producer = self._session(self._fence.rows[roles["producer"]["bead_id"]])[0]
        require(roles["reviewer"]["bead_id"] == self.claimed_step_id
                and context["reviewer"] == reviewer and context["producer"] == producer,
                "review context names another native role or attempt")
        return outputs.complete_review(context, current["work_dir"], report, status, evidence_path, self.artifact_root)

    def prepare_member_result(self, result, *, record_id, authority_id, initial_write=False, operation_nonce=None):
        _, attempt = self._admitted()
        roles, writer_map = self._roles(result["writer_step_id"])
        require(roles["recorder"]["bead_id"] == self.claimed_step_id, "result publication requires its actual cooked recorder")
        return outputs.prepare_member_result(self._fence, attempt, result, run_owner_id=self.run["workflow_root_id"],
            plan_owner_id=self.plan["source_plan_owner_id"], workspace_owner_id=result["workspace_owner_id"],
            record_id=record_id, authority_id=authority_id, required_checks=self.required_checks,
            artifact_root=self.artifact_root, qualify_native=self.qualify_native, writer_map=writer_map,
            initial_write=initial_write, operation_nonce=operation_nonce)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("context", "checks", "begin-review", "complete-review", "make-result", "qualify", "record-result"))
    for name in ("city-root", "store-ref", "rig-name", "workflow-root-id", "claimed-step-id", "artifact-root", "evidence-dir"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--gc", default="gc")
    parser.add_argument("--generation", type=int, required=True)
    for name in ("owner-id", "member-id", "output-oid", "result", "checks", "artifacts", "context", "report", "review", "review-evidence", "record-id", "authority-id", "operation-nonce"):
        parser.add_argument("--" + name)
    parser.add_argument("--status", choices=sorted(outputs.STATUSES), default="passed")
    parser.add_argument("--initial-write", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    def read(path):
        require(bool(path), "missing required artifact argument")
        return json.loads(Path(path).read_text())
    try:
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city_root)
        entry = read_entry(store, gc=args.gc, city_root=args.city_root, rig_name=args.rig_name,
            workflow_root_id=args.workflow_root_id, claimed_step_id=args.claimed_step_id,
            worktree_lifecycle="new", generation=args.generation, require_plan=True)
        store.common_git_dir = entry["run"]["common_git_dir"]
        runtime = NativeSourceRuntime(store, gc=args.gc, city_root=args.city_root, rig_name=args.rig_name,
            run=entry["run"], plan=entry["source_plan"], artifact_root=args.artifact_root,
            evidence_dir=args.evidence_dir, claimed_step_id=args.claimed_step_id)
        if args.action in ("context", "checks", "begin-review", "make-result"):
            require(args.owner_id and args.member_id and args.output_oid, "action requires owner, member and exact output OID")
            if args.action == "context":
                result = runtime.workspace_context(args.owner_id, args.member_id, args.output_oid)
                result["policy_binding"] = runtime.policy_binding
                result["identity"] = runtime._admitted()[0]
            elif args.action == "checks":
                result = runtime.execute_checks(args.owner_id, args.member_id, args.output_oid, timeout=args.timeout)
            elif args.action == "begin-review":
                result = runtime.begin_review(args.owner_id, args.member_id, args.output_oid, read(args.checks), read(args.artifacts))
            else:
                result = runtime.make_member_result(args.owner_id, args.member_id, args.output_oid,
                                                     read(args.checks), read(args.review), read(args.artifacts))
        elif args.action == "complete-review":
            require(args.report and args.review_evidence, "completed review requires report and evidence paths")
            result = runtime.complete_review(read(args.context), args.report, args.status, args.review_evidence)
        elif args.action == "qualify":
            result = runtime.qualify_native(read(args.result))
            rows = result.pop("guard_rows")
            result["guard_revisions"] = {key: row["revision"] for key, row in rows.items()}
        else:
            require(args.record_id and args.authority_id, "publication requires exact allocated record and authority IDs")
            from workspace_requests import require_resolved_scope, retain_request, resolve_request
            from workspace_store import SCOPE_OWNER
            member_result = read(args.result)
            validate_record("member-result", member_result)
            require_resolved_scope(store, {
                "workflow_root_id": member_result["workflow_root_id"], "generation": member_result["generation"],
                "writer_scope_id": member_result[SCOPE_OWNER["member-result"]], "record_kind": "member-result",
            })
            prepared = runtime.prepare_member_result(member_result, record_id=args.record_id,
                authority_id=args.authority_id, initial_write=args.initial_write, operation_nonce=args.operation_nonce)
            runtime._fresh()
            request_path, _ = retain_request(store, prepared)
            recovery = "resolve the original retained request: " + str(request_path)
            try:
                store.execute(prepared)
                result = resolve_request(store, request_path)
            except (RecordError, OSError) as exc:
                raise RecordError(str(exc) + "; " + recovery) from exc
            require(result.get("outcome") in ("committed", "replayed"),
                    "result publication outcome unknown; " + recovery)
            result["request_path"] = str(request_path)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RecordError, OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
