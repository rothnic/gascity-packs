"""Pack adapter controls. The command port is synthetic, not native Beads proof."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from workspace_records import canonical_bytes, contracts, record_identity, record_sha256
from workspace_store import (MISSING, Attempt, CookedWriterMap, GuardRead, RecordWrite, ReferenceWrite,
                             NativeOwnerProjection, NativeWorktreeReference, SourceMembershipProjection,
                             SourcePlanConvoyBinding, RunCheckPolicyProjection, StoreError, SuccessorRelation, WorkspaceStore, record_reference,
                             transition_locks, validate_cooked_writer_map, validate_transition)

FIXTURES = Path(__file__).parent / "fixtures" / "workspace-records" / "valid.json"


class MemoryPort:
    """A deterministic command-contract double with whole-batch revision guards."""
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.requests = []
        self.lose_ack = False

    def __call__(self, arguments, attempt=None):
        if arguments[0].startswith("--snapshot="):
            ids = arguments[0].partition("=")[2].split(",")
            return {"schema_version": "1", "ok": True, "store_ref": "rig:example",
                    "rows": [copy.deepcopy(self.rows[i]) for i in ids]}
        request = json.loads(Path(arguments[0].partition("=")[2]).read_text())
        self.requests.append(copy.deepcopy(request))
        for p in request["rows"]:
            row = self.rows[p["id"]]
            if row["revision"] != p["expected_revision"]:
                raise StoreError("synthetic stale revision")
            for field in ("status", "assignee"):
                if p.get("expected_" + field, row[field]) != row[field]:
                    raise StoreError("synthetic native guard mismatch")
            changed = any(row["metadata"].get(k, MISSING) != v for k, v in p.get("set", {}).items())
            changed |= any(k in row["metadata"] for k in p.get("delete", []))
            if p["require_change"] and not changed:
                raise StoreError("synthetic no-op guard")
        results = []
        for p in request["rows"]:
            row = self.rows[p["id"]]
            old = copy.deepcopy(row["metadata"])
            row["metadata"].update(p.get("set", {}))
            for k in p.get("delete", []):
                row["metadata"].pop(k, None)
            changed = old != row["metadata"]
            if changed:
                row["revision"] = str(int(row["revision"]) + 1)
            results.append({"id": p["id"], "revision": row["revision"], "changed": changed})
        if self.lose_ack:
            raise StoreError("synthetic acknowledgement loss")
        return {"schema_version": "1", "ok": True, "store_ref": "rig:example", "rows": results}


def row(bead_id, *, status="closed", assignee="", metadata=None):
    return {"id": bead_id, "revision": "1", "status": status, "assignee": assignee,
            "type": "task", "labels": [], "metadata": copy.deepcopy(metadata or {})}


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.git = Path(self.tmp.name) / ".git"
        self.git.mkdir()
        self.attempt = Attempt("session-a", "incarnation-a", "writer-step-example")
        self.samples = json.loads(FIXTURES.read_text())
        self.scope = {"workflow_root_id": "run-example", "generation": 1,
                      "writer_scope_id": "run-example", "record_kind": "run"}
        self.rows = {"run-example": row("run-example", status="in_progress", metadata={
                         "gc.root_store_ref": "rig:example", "gc.formula_name": "build",
                         "gc.formula_hash": "a" * 64, "gc.formula_source": "/fixture/build.formula.toml"}),
                     "grant-row": row("grant-row"), "payload-row": row("payload-row"),
                     "writer-step-example": row("writer-step-example", status="in_progress",
                         assignee="worker", metadata={"gc.session_id": "session-a",
                           "workflow_id": "run-example", "gc.root_store_ref": "rig:example",
                           "gc.step_ref": "build.prepare", "gc.step_id": "prepare",
                           "gc.lifecycle": "new", "gc.native_step_dependencies.v1": "[]"})}
        self.rows["payload-row"]["metadata"]["typed-sibling"] = [True, 3, {"x": None}]
        self.checks = [{"id": "unit", "argv": ["true"]}]
        self.rows["run-example"]["metadata"]["gc.var.worktree_checks"] = canonical_bytes({"required_checks": self.checks}).decode()
        self.port = MemoryPort(self.rows)
        self.store = WorkspaceStore("rig:example", cwd=self.tmp.name, common_git_dir=self.git)
        self.command = patch.object(self.store, "_command", side_effect=self.port)
        self.command.start()
        self.addCleanup(self.command.stop)

    def writer_map(self, scope, attempt=None):
        """Declare explicit native role fixtures; production validation stays enabled."""
        attempt = attempt or self.attempt
        native = self.port.rows[attempt.claimed_bead_id]["metadata"]
        stage, facts = {
            "run": ("prepare", {"gc.lifecycle": "new"}),
            "source-plan": ("decompose", {"gc.build.artifact_schema": "gc.build.decomposition.v1"}),
            "workspace": ("prepare-worktree", {"gc.run_target": "gc.run-operator"}),
            "blocker": ("prepare-worktree", {"gc.run_target": "gc.run-operator"}),
            "member-result": ("record-result", {"gc.run_target": "gc.run-operator"}),
            "owner-output": ("record-result", {"gc.run_target": "gc.run-operator"}),
            "canonical": ("summarize-implementation", {"gc.run_target": "gc.run-operator"}),
            "review": ("review", {"gc.run_target": "gc.implementation-reviewer"}),
            "publish": ("publish", {"gc.run_target": "gc.publisher"}),
        }[scope["record_kind"]]
        native.update(facts, **{"gc.step_id": stage})
        native.setdefault("gc.native_step_dependencies.v1", "[]")
        root_id = scope["workflow_root_id"]
        member = native.get("gc.source_anchor_id", native.get("gc.drain_member_id", root_id))
        if member not in self.port.rows:
            self.port.rows[member] = row(member, metadata={"workflow_id": root_id, "gc.root_store_ref": "rig:example"})
        expansion = native.get("gc.attach_root_id") or root_id
        formula = self.port.rows[expansion]["metadata"]
        responsibilities = {
            "prepare": ["run"], "decompose": ["source-plan"],
            "prepare-worktree": ["blocker", "workspace"],
            "record-result": ["member-result", "owner-output", "workspace"],
            "summarize-implementation": ["canonical"], "review": ["review"], "publish": ["publish"],
        }[stage]
        return CookedWriterMap(canonical_bytes({"version": 1, "workflow_root_id": root_id,
            "store_ref": "rig:example", "source_member_id": member, "expansion_root_id": expansion,
            "formula_name": formula["gc.formula_name"], "formula_hash": formula["gc.formula_hash"],
            "formula_source": formula["gc.formula_source"], "steps": [{"bead_id": attempt.claimed_bead_id,
                "step_id": native["gc.step_id"], "step_ref": native["gc.step_ref"],
                "dependencies": json.loads(native["gc.native_step_dependencies.v1"]),
                "record_kinds": responsibilities}]}))

    def prepare(self, kind="run", install=True, **kwargs):
        payload = copy.deepcopy(self.samples[kind])
        if kind == "workspace":
            payload["workspace_bead_id"] = "payload-row"
            payload["writer_attempt_id"] = self.attempt.writer_attempt_id
            payload["claim_binding"]["writer_attempt_id"] = self.attempt.writer_attempt_id
        scope = dict(self.scope, record_kind=kind, writer_scope_id={
            "run": "run-example", "source-plan": "plan-owner-example",
            "workspace": "integration-example", "member-result": "task-a",
            "owner-output": "task-a", "canonical": "plan-owner-example",
            "review": "review-example", "publish": "publish-example",
            "blocker": "integration-example"}[kind])
        method = self.store.install_grant if install else self.store.write_records
        writer_map = kwargs.pop("writer_map", self.writer_map(scope))
        if kind == "run":
            kwargs.setdefault("projections", [self.run_policy("payload-row", payload)])
        return method(self.attempt, scope, "grant-row", [RecordWrite(kind, "payload-row", payload)],
                      [ReferenceWrite("run-example", contracts()[kind]["metadata_key"] + "_ref",
                                      record_reference(kind, "payload-row", payload))], writer_map=writer_map, **kwargs)

    def run_policy(self, bead_id, run):
        return RunCheckPolicyProjection(bead_id, {"version": 1, "workflow_root_id": run["workflow_root_id"],
            "run_record_id": bead_id, "run_identity": list(record_identity("run", run)), "base_oid": run["base_oid"],
            "required_checks": self.checks, "policy_sha256": record_sha256({"required_checks": self.checks})})

    def test_all_nine_kinds_publish_payload_grant_claim_and_reference_together(self):
        for kind in contracts():
            with self.subTest(kind=kind):
                self.port.rows = copy.deepcopy(self.rows)
                prepared = self.prepare(kind)
                result = self.store.execute(prepared)
                self.assertEqual("committed", result["outcome"])
                self.assertEqual(4, len(self.port.requests[-1]["rows"]))
                guards = [p for p in prepared.request["rows"] if p["require_change"]]
                self.assertEqual({"grant-row", "writer-step-example", "payload-row", "run-example"}, {p["id"] for p in guards})
                self.assertEqual([True, 3, {"x": None}], self.port.rows["payload-row"]["metadata"]["typed-sibling"])

    def test_stale_original_request_loses_to_changed_authority_for_every_kind(self):
        for kind in contracts():
            with self.subTest(kind=kind):
                self.port.rows = copy.deepcopy(self.rows)
                stale = self.prepare(kind)
                accepted = self.prepare(kind)
                self.assertEqual("committed", self.store.execute(accepted)["outcome"])
                state = copy.deepcopy(self.port.rows)
                self.assertEqual("unknown", self.store.execute(stale)["outcome"])
                self.assertEqual(state, self.port.rows)

    def test_late_reference_guard_refuses_complete_batch(self):
        prepared = self.prepare()
        self.port.rows["run-example"]["revision"] = "2"
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)

    def test_acknowledgement_loss_resolves_by_exact_readback_without_replay(self):
        prepared = self.prepare()
        self.port.lose_ack = True
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual("committed", self.store.resolve(prepared)["outcome"])
        self.assertEqual(1, len(self.port.requests))

    def test_submitted_request_cannot_be_retried_even_after_unknown(self):
        prepared = self.prepare()
        self.port.lose_ack = True
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        for store in (self.store, WorkspaceStore("rig:example", cwd=self.tmp.name, common_git_dir=self.git)):
            with self.assertRaisesRegex(StoreError, "already submitted"):
                store.execute(prepared)
        self.assertEqual(1, len(self.port.requests))
        self.assertEqual("committed", self.store.resolve(prepared)["outcome"])

    def test_frozen_request_cannot_be_rebound_to_another_store_city_or_git_directory(self):
        prepared = self.prepare()
        other_city = Path(self.tmp.name) / "other-city"
        other_git = Path(self.tmp.name) / "other.git"
        other_city.mkdir()
        other_git.mkdir()
        for store in (WorkspaceStore("rig:other", cwd=self.tmp.name, common_git_dir=self.git),
                      WorkspaceStore("rig:example", cwd=other_city, common_git_dir=self.git),
                      WorkspaceStore("rig:example", cwd=self.tmp.name, common_git_dir=other_git)):
            with self.subTest(store=store.store_ref, city=store.cwd, git=store.common_git_dir):
                with self.assertRaisesRegex(StoreError, "different city"):
                    store.execute(prepared)
                with self.assertRaisesRegex(StoreError, "different city"):
                    store.resolve(prepared)
        self.assertEqual([], self.port.requests)

    def test_record_kind_namespace_is_required_and_separates_same_logical_owner(self):
        scope = dict(self.scope)
        del scope["record_kind"]
        with self.assertRaisesRegex(StoreError, "record_kind"):
            self.store.install_grant(self.attempt, scope, "grant-row", [RecordWrite("run", "payload-row", self.samples["run"])], writer_map=self.writer_map(self.scope, self.attempt))
        self.store.execute(self.prepare("source-plan"))
        self.port.rows["canonical-grant"] = row("canonical-grant")
        self.port.rows["canonical-record"] = row("canonical-record")
        canonical = self.samples["canonical"]
        scope = dict(self.scope, record_kind="canonical", writer_scope_id="plan-owner-example")
        prepared = self.store.install_grant(self.attempt, scope, "canonical-grant",
            [RecordWrite("canonical", "canonical-record", canonical)],
            [ReferenceWrite("run-example", "gc.canonical_ref", record_reference("canonical", "canonical-record", canonical))], writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        index = json.loads(self.port.rows["run-example"]["metadata"]["gc.workspace_write_grant_refs"])
        self.assertEqual({"source-plan", "canonical"}, {r["scope"]["record_kind"] for r in index["scopes"].values()})
        with self.assertRaisesRegex(StoreError, "writer responsibility"):
            self.store.write_records(self.attempt, scope, "canonical-grant", [RecordWrite("source-plan", "payload-row", self.samples["source-plan"])], writer_map=self.writer_map(scope, self.attempt))

    def test_first_grant_cannot_adopt_a_previously_published_payload(self):
        self.port.rows["payload-row"]["metadata"]["gc.implementation_run"] = canonical_bytes(self.samples["run"]).decode()
        with self.assertRaisesRegex(StoreError, "previously published"):
            self.prepare()
        self.assertEqual([], self.port.requests)

    def test_runtime_rows_cannot_be_read_as_dedicated_lifecycle_records(self):
        self.port.rows["payload-row"]["metadata"]["gc.implementation_run"] = canonical_bytes(self.samples["run"]).decode()
        self.port.rows["payload-row"]["status"] = "in_progress"
        with self.assertRaisesRegex(StoreError, "closed and unassigned"):
            self.store.read_record("run", "payload-row")

    def test_reference_cannot_mutate_another_native_workflow(self):
        self.port.rows["foreign-root"] = row("foreign-root", metadata={"workflow_id": "foreign-root", "gc.root_store_ref": "rig:example"})
        with self.assertRaisesRegex(StoreError, "reference target"):
            self.store.install_grant(self.attempt, self.scope, "grant-row",
                [RecordWrite("run", "payload-row", self.samples["run"])],
                [ReferenceWrite("foreign-root", "gc.implementation_run_ref", record_reference("run", "payload-row", self.samples["run"]))], writer_map=self.writer_map(self.scope, self.attempt))
        self.assertEqual([], self.port.requests)

    def test_one_logical_record_cannot_have_two_physical_payloads(self):
        self.port.rows["second-record"] = row("second-record")
        with self.assertRaisesRegex(StoreError, "multiple physical"):
            self.store.install_grant(self.attempt, self.scope, "grant-row",
                [RecordWrite("run", "payload-row", self.samples["run"]), RecordWrite("run", "second-record", self.samples["run"])], writer_map=self.writer_map(self.scope, self.attempt))
        self.assertEqual([], self.port.requests)

    def workspace_block(self):
        self.store.execute(self.prepare("workspace"))
        workspace = self.store.read_record("workspace", "payload-row")
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        self.port.rows["blocker-record"] = row("blocker-record")
        self.port.rows[workspace["workspace_owner_id"]] = row(workspace["workspace_owner_id"], metadata={
            "workflow_id": "run-example", "gc.root_store_ref": "rig:example"})
        blocked = dict(workspace, phase="blocked")
        blocker = dict(self.samples["blocker"], blocked_from_phase=workspace["phase"], work_dir=workspace["work_dir"])
        reference = ReferenceWrite(workspace["workspace_owner_id"], "gc.workspace_blocker_ref",
                                   record_reference("blocker", "blocker-record", blocker))
        return grant["scope"], workspace, blocked, blocker, reference

    def test_block_requires_matching_open_observation_and_preserves_checkpoint(self):
        scope, workspace, blocked, blocker, reference = self.workspace_block()
        with self.assertRaisesRegex(StoreError, "one open blocker"):
            self.store.write_records(self.attempt, scope, "grant-row", [RecordWrite("workspace", "payload-row", blocked)], writer_map=self.writer_map(scope, self.attempt))
        wrong = dict(blocker, blocked_current_oid="b" * 40)
        with self.assertRaisesRegex(StoreError, "preceding workspace checkpoint"):
            self.store.write_records(self.attempt, scope, "grant-row", [RecordWrite("workspace", "payload-row", blocked), RecordWrite("blocker", "blocker-record", wrong)], writer_map=self.writer_map(scope, self.attempt))
        changed = dict(blocked, current_oid="b" * 40)
        with self.assertRaisesRegex(StoreError, "preserve the workspace source"):
            self.store.write_records(self.attempt, scope, "grant-row", [RecordWrite("workspace", "payload-row", changed), RecordWrite("blocker", "blocker-record", blocker)], writer_map=self.writer_map(scope, self.attempt))
        prepared = self.store.write_records(self.attempt, scope, "grant-row",
            [RecordWrite("workspace", "payload-row", blocked), RecordWrite("blocker", "blocker-record", blocker)], [reference], writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])

    def test_resume_requires_decision_bound_paused_phase_and_fences_late_resolution(self):
        scope, workspace, blocked, blocker, reference = self.workspace_block()
        prepared = self.store.write_records(self.attempt, scope, "grant-row",
            [RecordWrite("workspace", "payload-row", blocked), RecordWrite("blocker", "blocker-record", blocker)], [reference], writer_map=self.writer_map(scope, self.attempt))
        self.store.execute(prepared)
        with self.assertRaisesRegex(StoreError, "guarded workspace blocker reference"):
            self.store.write_records(self.attempt, scope, "grant-row", [RecordWrite("workspace", "payload-row", workspace)], writer_map=self.writer_map(scope, self.attempt))
        resolved = dict(blocker, status="resolved", resolution={"decision_path": "/example/decision.md",
            "decision_sha256": "0" * 64, "expected_head_oid": workspace["current_oid"]})
        wrong_phase = dict(workspace, phase="active")
        with self.assertRaisesRegex(StoreError, "paused phase"):
            self.store.write_records(self.attempt, scope, "grant-row",
                [RecordWrite("workspace", "payload-row", wrong_phase), RecordWrite("blocker", "blocker-record", resolved)], [reference], writer_map=self.writer_map(scope, self.attempt))
        prepared = self.store.write_records(self.attempt, scope, "grant-row",
            [RecordWrite("workspace", "payload-row", workspace), RecordWrite("blocker", "blocker-record", resolved)], [reference], writer_map=self.writer_map(scope, self.attempt))
        self.port.rows["blocker-record"]["revision"] = str(int(self.port.rows["blocker-record"]["revision"]) + 1)
        state = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(state, self.port.rows)
        fresh = self.store.write_records(self.attempt, scope, "grant-row",
            [RecordWrite("workspace", "payload-row", workspace), RecordWrite("blocker", "blocker-record", resolved)], [reference], writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual("committed", self.store.execute(fresh)["outcome"])
        self.assertEqual("entry", self.store.read_record("workspace", "payload-row")["phase"])

    def test_source_membership_projection_joins_plan_and_preserves_original_native_rows(self):
        plan = self.samples["source-plan"]
        owner = plan["source_plan_owner_id"]
        self.port.rows[owner] = row(owner, status="in_progress", metadata={
            "workflow_id": "run-example", "gc.root_store_ref": "rig:example", "native-parent": [1, None]})
        projection = SourceMembershipProjection(owner, "run-example", 1)
        prepared = self.prepare("source-plan", projections=[projection],
            guards=[GuardRead(owner, "gc.source_root_id", MISSING), GuardRead(owner, "gc.source_generation", MISSING)])
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        metadata = self.port.rows[owner]["metadata"]
        self.assertEqual("run-example", metadata["gc.source_root_id"])
        self.assertEqual("1", metadata["gc.source_generation"])
        self.assertEqual([1, None], metadata["native-parent"])
        replay = self.prepare("source-plan", install=False, projections=[projection])
        self.assertEqual("replayed", self.store.execute(replay)["outcome"])

    def test_source_membership_projection_refuses_conflicts_and_nonmember_rows(self):
        owner = self.samples["source-plan"]["source_plan_owner_id"]
        metadata = {"workflow_id": "run-example", "gc.root_store_ref": "rig:example"}
        self.port.rows[owner] = row(owner, metadata=metadata)
        for key, value in (("workflow_id", "another-root"), ("gc.root_store_ref", "rig:another"),
                           ("gc.source_root_id", None), ("gc.source_generation", "2")):
            with self.subTest(key=key):
                self.port.rows[owner] = row(owner, metadata=dict(metadata, **{key: value}))
                with self.assertRaises(StoreError):
                    self.prepare("source-plan", projections=[SourceMembershipProjection(owner, "run-example", 1)])
        self.port.rows[owner] = row(owner, metadata=metadata)
        for projection in (SourceMembershipProjection(owner, "run-example", True),
                           SourceMembershipProjection("run-example", "run-example", 1)):
            with self.assertRaises(StoreError):
                self.prepare("source-plan", projections=[projection])
        self.assertEqual([], self.port.requests)

    def test_immutable_replay_fences_current_authority_and_keeps_first_writer(self):
        first = self.prepare()
        self.assertEqual("committed", self.store.execute(first)["outcome"])
        replay = self.prepare(install=False)
        self.assertEqual("replayed", self.store.execute(replay)["outcome"])
        self.assertEqual(self.samples["run"], self.store.read_record("run", "payload-row"))
        changed = copy.deepcopy(self.samples["run"])
        changed["base_oid"] = "b" * 40
        with self.assertRaisesRegex(StoreError, "replay"):
            self.store.write_records(self.attempt, self.scope, "grant-row", [RecordWrite("run", "payload-row", changed)], writer_map=self.writer_map(self.scope, self.attempt))

    def test_missing_and_null_are_different_read_guards(self):
        self.port.rows["run-example"]["metadata"]["null-sibling"] = None
        with self.assertRaisesRegex(StoreError, "read guard"):
            self.prepare(guards=[GuardRead("run-example", "null-sibling", MISSING)])
        self.prepare(guards=[GuardRead("run-example", "null-sibling", None)])

    def test_capture_can_retain_original_row_revisions(self):
        original = self.store.snapshot(list(self.rows))
        self.port.rows["run-example"]["revision"] = "2"
        prepared = self.prepare(expected_rows=original)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])

    def test_wrong_claim_root_session_status_or_store_refuses_without_requests(self):
        for key, value in [("gc.session_id", "session-other"), ("workflow_id", "root-other"),
                           ("gc.root_store_ref", "rig:other"), ("gc.step_ref", "")]:
            with self.subTest(key=key):
                self.port.rows = copy.deepcopy(self.rows)
                self.port.rows["writer-step-example"]["metadata"][key] = value
                with self.assertRaises(StoreError):
                    self.prepare()
        self.assertEqual([], self.port.requests)

    def test_allocated_nonempty_or_dispatchable_authority_is_not_adopted(self):
        for field, value in [("status", "open"), ("assignee", "worker"),
                             ("metadata", {"gc.workspace_write_grant": "{}"})]:
            with self.subTest(field=field):
                self.port.rows = copy.deepcopy(self.rows)
                self.port.rows["grant-row"][field] = value
                with self.assertRaises(StoreError):
                    self.prepare()

    def test_runtime_metadata_is_never_a_publication_target(self):
        for key in ("gc.session_id", "gc.work_dir", "gc.root_store_ref", "current_claim_bead_id"):
            with self.subTest(key=key):
                with self.assertRaises(StoreError):
                    self.store.install_grant(self.attempt, self.scope, "grant-row",
                        [RecordWrite("run", "payload-row", self.samples["run"])],
                        [ReferenceWrite("run-example", key, record_reference("run", "payload-row", self.samples["run"]))], writer_map=self.writer_map(self.scope, self.attempt))

    def test_batch_limit_refuses_whole_request_without_chunking(self):
        guards = []
        for i in range(98):
            bead_id = "guard-" + str(i)
            self.port.rows[bead_id] = row(bead_id)
            guards.append(GuardRead(bead_id, "missing", MISSING))
        with self.assertRaisesRegex(StoreError, "100"):
            self.prepare(guards=guards)
        self.assertEqual([], self.port.requests)

    def test_scope_and_identity_cannot_be_reassigned(self):
        self.store.execute(self.prepare())
        altered_scope = dict(self.scope, writer_scope_id="someone-else")
        with self.assertRaises(StoreError):
            self.store.write_records(self.attempt, altered_scope, "grant-row", [], writer_map=self.writer_map(altered_scope, self.attempt))

    def test_attempt_retains_startup_tuple_without_trigger_fallback(self):
        with patch.dict(os.environ, {"GC_SESSION_ID": "s", "GC_INSTANCE_TOKEN": "t", "GC_BEAD_ID": "ambient"}):
            attempt = Attempt.from_env("exact-step")
        self.assertEqual("exact-step", attempt.claimed_bead_id)
        self.assertEqual(attempt.writer_attempt_id, Attempt("s", "t", "exact-step").writer_attempt_id)
        self.assertNotEqual(attempt.writer_attempt_id, Attempt("s", "new-t", "exact-step").writer_attempt_id)

    def test_terminal_publish_intent_and_native_provenance_do_not_change(self):
        old = self.samples["publish"]
        changed = copy.deepcopy(old)
        changed["output_oid"] = "d" * 40
        with self.assertRaises(StoreError):
            validate_transition("publish", old, changed)
        old = self.samples["workspace"]
        changed = copy.deepcopy(old)
        changed["native_provenance"]["owner"] = "someone-else"
        with self.assertRaises(StoreError):
            validate_transition("workspace", old, changed)

    def test_read_guard_rows_make_a_real_change_at_native_commit(self):
        self.port.rows["subject-row"] = row("subject-row", metadata={"canonical": "accepted-a"})
        prepared = self.prepare(guards=[GuardRead("subject-row", "canonical", "accepted-a")])
        guard = next(p for p in prepared.request["rows"] if p["id"] == "subject-row")
        self.assertTrue(guard["require_change"])
        self.assertNotEqual(self.port.rows["subject-row"]["metadata"], guard["set"])
        self.port.rows["subject-row"]["revision"] = "2"
        self.port.rows["subject-row"]["metadata"]["canonical"] = "accepted-b"
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)

    def test_explicit_new_incarnation_transfers_grant_and_fences_old_attempt(self):
        self.store.execute(self.prepare())
        stale = self.prepare(install=False)
        old_grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        successor = Attempt("session-a", "incarnation-b", "writer-step-example")
        handoff = self.store.accept_replacement(successor, self.scope, "grant-row", [], expected_grant=old_grant, writer_map=self.writer_map(self.scope, successor))
        self.assertEqual("committed", self.store.execute(handoff)["outcome"])
        state = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(stale)["outcome"])
        self.assertEqual(state, self.port.rows)
        with self.assertRaisesRegex(StoreError, "different native"):
            self.prepare(install=False)

    def test_same_tuple_and_undeclared_successor_never_take_over(self):
        self.store.execute(self.prepare())
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        with self.assertRaisesRegex(StoreError, "proven new"):
            self.store.accept_replacement(self.attempt, self.scope, "grant-row", [], expected_grant=grant, writer_map=self.writer_map(self.scope, self.attempt))
        self.port.rows["successor-step"] = row("successor-step", status="in_progress", assignee="worker",
            metadata={"gc.session_id": "session-b", "workflow_id": "run-example",
                      "gc.root_store_ref": "rig:example", "gc.step_ref": "build.next"})
        self.port.rows["writer-step-example"]["status"] = "closed"
        with self.assertRaisesRegex(StoreError, "successor relation"):
            self.store.accept_replacement(Attempt("session-b", "incarnation-b", "successor-step"),
                self.scope, "grant-row", [], expected_grant=grant, writer_map=self.writer_map(self.scope, Attempt("session-b", "incarnation-b", "successor-step")))

    def test_successor_requires_exact_referenced_plan_and_native_member_relation(self):
        self.port.rows["writer-step-example"]["metadata"]["gc.source_anchor_id"] = "source-a"
        self.store.execute(self.prepare("workspace"))
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        scope = grant["scope"]
        plan = copy.deepcopy(self.samples["source-plan"])
        plan["nodes"] = [{"owner_id": "integration-example", "strategy": "shared-chain",
                          "member_ids": ["source-a", "source-b"], "source_predecessor_owner_ids": [], "single_lane": True}]
        plan["terminal_owner_id"] = "integration-example"
        self.port.rows["plan-row"] = row("plan-row", metadata={"gc.source_plan": canonical_bytes(plan).decode()})
        self.port.rows["plan-owner-example"] = row("plan-owner-example", metadata={
            "gc.source_plan_ref": canonical_bytes(record_reference("source-plan", "plan-row", plan)).decode()})
        self.port.rows["writer-step-example"]["status"] = "closed"
        self.port.rows["successor-step"] = row("successor-step", status="in_progress", assignee="worker",
            metadata={"gc.session_id": "session-b", "workflow_id": "run-example", "gc.source_anchor_id": "source-b",
                      "gc.root_store_ref": "rig:example", "gc.step_ref": "build.next"})
        relation = SuccessorRelation("plan-row", "plan-owner-example")
        attempt = Attempt("session-b", "incarnation-b", "successor-step")
        prepared = self.store.accept_replacement(attempt, scope, "grant-row", [], expected_grant=grant,
                                                successor_relation=relation, writer_map=self.writer_map(scope, attempt))
        self.port.rows["plan-owner-example"]["revision"] = "2"
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)
        self.port.rows["plan-owner-example"]["metadata"].pop("gc.source_plan_ref")
        with self.assertRaisesRegex(StoreError, "physical reference"):
            self.store.accept_replacement(attempt, scope, "grant-row", [], expected_grant=grant,
                                         successor_relation=relation, writer_map=self.writer_map(scope, attempt))

    def test_bad_snapshot_and_result_responses_do_not_become_success(self):
        response = self.port(["--snapshot=run-example"])
        for altered in [dict(response, store_ref="rig:other"), dict(response, ok=1),
                        dict(response, rows=[]), dict(response, unexpected=True)]:
            with self.subTest(altered=altered):
                with patch.object(self.store, "_command", return_value=altered):
                    with self.assertRaises(StoreError):
                        self.store.snapshot(["run-example"])
        bad_results = [{"schema_version": "1", "ok": True, "store_ref": "rig:example", "rows": []},
                       {"schema_version": "1", "ok": True, "store_ref": "rig:other", "rows": []}]
        for response in bad_results:
            prepared = self.prepare()
            with patch.object(self.store, "_command", return_value=response):
                self.assertEqual("unknown", self.store.execute(prepared)["outcome"])

    def convoy_projection(self):
        run = dict(self.samples["run"], worktree_lifecycle="new")
        run_raw = canonical_bytes(run).decode()
        run_ref = canonical_bytes(record_reference("run", "run-record", run)).decode()
        self.port.rows["run-record"] = row("run-record", metadata={"gc.implementation_run": run_raw})
        self.port.rows["run-example"]["metadata"].update({"gc.implementation_run_ref": run_ref, "gc.input_convoy_id": "intake-convoy"})
        self.port.rows["implementation-convoy"] = row("implementation-convoy", metadata={
            "gc.root_bead_id": "run-example", "gc.root_store_ref": "rig:example",
            "gc.source_root_id": "run-example", "gc.source_generation": "1"})
        self.port.rows["implementation-convoy"]["type"] = "convoy"
        return [GuardRead("run-example", "gc.implementation_run_ref", run_ref),
                GuardRead("run-record", "gc.implementation_run", run_raw),
                GuardRead("run-example", "gc.input_convoy_id", "intake-convoy")]

    def test_implementation_convoy_binding_joins_plan_and_fences_original_input(self):
        guards = self.convoy_projection()
        prepared = self.prepare("source-plan", guards=guards, projections=[SourcePlanConvoyBinding("implementation-convoy")])
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        root = self.port.rows["run-example"]["metadata"]
        self.assertEqual("implementation-convoy", root["gc.input_convoy_id"])
        self.assertEqual("implementation-convoy", root["gc.build.implementation_convoy_id"])
        convoy = self.port.rows["implementation-convoy"]["metadata"]
        self.assertEqual("plan-owner-example", convoy["gc.source_plan_owner_id"])
        self.assertEqual(64, len(convoy["gc.source_plan_sha256"]))

    def test_convoy_binding_wrong_native_scope_or_late_input_change_has_no_partial_publication(self):
        guards = self.convoy_projection()
        with self.assertRaisesRegex(StoreError, "input-convoy read guard"):
            self.prepare("source-plan", guards=guards[:-1], projections=[SourcePlanConvoyBinding("implementation-convoy")])
        self.port.rows["implementation-convoy"]["metadata"]["gc.source_generation"] = "2"
        with self.assertRaisesRegex(StoreError, "source generation"):
            self.prepare("source-plan", guards=guards, projections=[SourcePlanConvoyBinding("implementation-convoy")])
        self.port.rows["implementation-convoy"]["metadata"]["gc.source_generation"] = "1"
        prepared = self.prepare("source-plan", guards=guards, projections=[SourcePlanConvoyBinding("implementation-convoy")])
        self.port.rows["run-example"]["revision"] = "2"
        self.port.rows["run-example"]["metadata"]["gc.input_convoy_id"] = "competing-convoy"
        state = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(state, self.port.rows)

    def test_same_plan_cannot_adopt_a_second_implementation_convoy(self):
        guards = self.convoy_projection()
        self.store.execute(self.prepare("source-plan", guards=guards, projections=[SourcePlanConvoyBinding("implementation-convoy")]))
        self.port.rows["duplicate-convoy"] = copy.deepcopy(self.port.rows["implementation-convoy"])
        self.port.rows["duplicate-convoy"]["id"] = "duplicate-convoy"
        current_guards = [*guards[:-1], GuardRead("run-example", "gc.input_convoy_id", "implementation-convoy"),
                          GuardRead("implementation-convoy", "gc.source_generation", "1")]
        with self.assertRaisesRegex(StoreError, "preceding source generation"):
            self.prepare("source-plan", install=False, guards=current_guards,
                         projections=[SourcePlanConvoyBinding("duplicate-convoy")])

    def test_malformed_root_authority_index_and_duplicate_records_refuse(self):
        self.port.rows["run-example"]["metadata"]["gc.workspace_write_grant_refs"] = "{}"
        with self.assertRaisesRegex(StoreError, "malformed root"):
            self.prepare()
        self.port.rows = copy.deepcopy(self.rows)
        write = RecordWrite("run", "payload-row", self.samples["run"])
        with self.assertRaisesRegex(StoreError, "multiple payload"):
            self.store.install_grant(self.attempt, self.scope, "grant-row", [write, write], writer_map=self.writer_map(self.scope, self.attempt))

    def test_transition_lock_is_bounded_and_preserves_existing_lock_inode(self):
        import fcntl
        with transition_locks(self.git, self.scope):
            files = list((self.git / "gc-workspace-locks").iterdir())
        root_file = next(p for p in files if p.name.startswith("root-"))
        inode = root_file.stat().st_ino
        with root_file.open("rb") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            start = time.monotonic()
            with self.assertRaisesRegex(StoreError, "timeout"):
                with transition_locks(self.git, self.scope, timeout=0.04):
                    self.fail("contended lock was admitted")
            self.assertLess(time.monotonic() - start, 0.5)
        with transition_locks(self.git, self.scope):
            self.assertEqual(inode, root_file.stat().st_ino)

    def test_nested_same_owner_is_safe_and_independent_owner_has_no_deadlock(self):
        ready, done = threading.Event(), threading.Event()
        errors = []
        def contender():
            ready.set()
            try:
                with transition_locks(self.git, dict(self.scope, writer_scope_id="other-owner"), timeout=0.04):
                    errors.append("unexpected grant")
            except StoreError as exc:
                errors.append(str(exc))
            finally:
                done.set()
        with transition_locks(self.git, self.scope):
            with transition_locks(self.git, self.scope, timeout=0.01):
                worker = threading.Thread(target=contender)
                worker.start()
                self.assertTrue(ready.wait(1))
                self.assertTrue(done.wait(1))
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(["workspace transition lock timeout"], errors)

    def test_unknown_filesystem_symlink_and_permissions_refuse(self):
        with patch("workspace_store._filesystem", side_effect=StoreError("unsupported filesystem")):
            with self.assertRaisesRegex(StoreError, "unsupported filesystem"):
                self.store.execute(self.prepare())
        directory = self.git / "gc-workspace-locks"
        directory.mkdir(mode=0o777)
        directory.chmod(0o777)
        with self.assertRaisesRegex(StoreError, "private"):
            self.store.execute(self.prepare())
        directory.rmdir()
        directory.symlink_to(Path(self.tmp.name))
        with self.assertRaisesRegex(StoreError, "ownership"):
            self.store.execute(self.prepare())

    def test_native_git_gc_and_prune_preserve_transition_locks(self):
        subprocess.run(["git", "init", "--bare", str(self.git)], check=True, capture_output=True)
        with transition_locks(self.git, self.scope):
            before = {p.name: p.stat().st_ino for p in (self.git / "gc-workspace-locks").iterdir()}
            subprocess.run(["git", "--git-dir=" + str(self.git), "gc", "--prune=now"], check=True, capture_output=True)
            self.assertEqual(before, {p.name: p.stat().st_ino for p in (self.git / "gc-workspace-locks").iterdir()})

    def test_actual_command_port_binds_city_store_and_clears_inherited_remote_context(self):
        native = Path(self.tmp.name) / "gc"
        fixture = Path(self.tmp.name) / "snapshot.json"
        fixture.write_text(json.dumps(self.port(["--snapshot=run-example"])))
        native.write_text("#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
            "assert sys.argv[1]=='--city='+os.getcwd()\n"
            "assert sys.argv[2:4]==['beads','guarded-metadata-batch']\n"
            "assert sys.argv[4:] == ['--store-ref=rig:example','--snapshot=run-example','--json']\n"
            "assert not any(k in os.environ for k in ('GC_CITY_URL','GC_CITY_CONTEXT','GC_RIG','GC_CITY'))\n"
            "print(Path(__file__).with_name('snapshot.json').read_text())\n")
        native.chmod(0o700)
        store = WorkspaceStore("rig:example", gc=str(native), cwd=self.tmp.name, common_git_dir=self.git)
        with patch.dict(os.environ, {"GC_CITY_URL": "https://invalid.example", "GC_CITY_CONTEXT": "other",
                                    "GC_CITY": "/wrong", "GC_RIG": "other-rig"}):
            self.assertEqual("run-example", store.snapshot(["run-example"])["run-example"]["id"])
        fixture.write_text('{"ok":true,"ok":true}')
        with self.assertRaisesRegex(StoreError, "duplicate JSON"):
            store.snapshot(["run-example"])

    def native_projection(self):
        run = copy.deepcopy(self.samples["run"])
        run["rig_root"], run["common_git_dir"] = self.tmp.name, str(self.git)
        self.port.rows["run-record"] = row("run-record", metadata={"gc.implementation_run": canonical_bytes(run).decode()})
        run_ref = canonical_bytes(record_reference("run", "run-record", run)).decode()
        self.port.rows["run-example"]["metadata"]["gc.implementation_run_ref"] = run_ref
        workspace = copy.deepcopy(self.samples["workspace"])
        workspace["workspace_bead_id"] = "payload-row"
        workspace["writer_attempt_id"] = workspace["claim_binding"]["writer_attempt_id"] = self.attempt.writer_attempt_id
        work_root = Path(self.tmp.name) / "workspaces"
        workspace["work_dir"] = str(work_root / "owner")
        Path(workspace["work_dir"]).mkdir(parents=True, exist_ok=True)
        native = workspace["native_provenance"]
        native.update(schema_version=2, bead_id="payload-row", repo_identity=str(self.git), path=workspace["work_dir"],
                      mode="attached", placement="outside-worktrees")
        owner = {"gc.root_bead_id": workspace["workflow_root_id"], "gc.root_store_ref": "rig:example",
                 "gc.work_dir": workspace["work_dir"], "gc.work_branch": workspace["work_branch"],
                 "gc.worktree_repo": self.tmp.name, "gc.worktree_root": str(work_root),
                 "gc.worktree_owner": workspace["workspace_owner_id"], "gc.worktree_generation": "1"}
        owner.update({"gc.worktree_" + name: native[name] for name in ("base_ref", "base_sha", "creator", "lifecycle", "mode", "placement")})
        reference = {"version": 1, "binding_step_id": self.attempt.claimed_bead_id, "workflow_root_id": "run-example", "generation": 1,
                     "workspace_owner_id": workspace["workspace_owner_id"], "workspace_bead_id": "payload-row",
                     "store_ref": "rig:example", "native_attempt_id": workspace["native_attempt_id"]}
        scope = dict(self.scope, record_kind="workspace", writer_scope_id="integration-example")
        writes = [RecordWrite("workspace", "payload-row", workspace)]
        refs = [ReferenceWrite("run-example", "gc.workspace_ref", record_reference("workspace", "payload-row", workspace))]
        guards = [GuardRead("run-record", "gc.implementation_run", canonical_bytes(run).decode()),
                  GuardRead("run-example", "gc.implementation_run_ref", run_ref)]
        projections = [NativeOwnerProjection("payload-row", owner), NativeWorktreeReference(self.attempt.claimed_bead_id, "payload-row", reference)]
        return scope, writes, refs, guards, projections

    def test_native_owner_projection_and_consumer_reference_join_the_same_batch(self):
        scope, writes, refs, guards, projections = self.native_projection()
        prepared = self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, guards=guards, projections=projections, writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        self.assertEqual(5, len(self.port.requests[-1]["rows"]))
        self.assertEqual("run-example", self.port.rows["payload-row"]["metadata"]["gc.root_bead_id"])
        self.assertEqual(projections[1].reference, json.loads(self.port.rows["writer-step-example"]["metadata"]["gc.worktree_ref"]))
        replay = self.store.write_records(self.attempt, scope, "grant-row", writes, refs, guards=guards, projections=projections, writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual("replayed", self.store.execute(replay)["outcome"])

    def test_native_projection_wrong_identity_or_missing_owner_never_publishes(self):
        scope, writes, refs, guards, projections = self.native_projection()
        for key, wrong in [("gc.root_bead_id", "foreign-root"), ("gc.root_store_ref", "rig:other"),
                           ("gc.worktree_base_sha", "f" * 40), ("gc.worktree_generation", "2"),
                           ("gc.worktree_owner", "foreign-owner"), ("gc.worktree_mode", "detached")]:
            with self.subTest(key=key):
                owner = dict(projections[0].metadata, **{key: wrong})
                with self.assertRaises(StoreError):
                    self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, guards=guards,
                        projections=[NativeOwnerProjection("payload-row", owner), projections[1]], writer_map=self.writer_map(scope, self.attempt))
        with self.assertRaisesRegex(StoreError, "supported string"):
            self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, guards=guards, projections=[projections[1]], writer_map=self.writer_map(scope, self.attempt))
        bad_reference = dict(projections[1].reference, generation=True)
        with self.assertRaises(StoreError):
            self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, guards=guards,
                projections=[projections[0], NativeWorktreeReference(self.attempt.claimed_bead_id, "payload-row", bad_reference)], writer_map=self.writer_map(scope, self.attempt))
        self.assertEqual([], self.port.requests)

    def test_native_projection_run_and_consumer_scope_are_guarded_not_inferred(self):
        scope, writes, refs, guards, projections = self.native_projection()
        with self.assertRaisesRegex(StoreError, "guarded transaction row"):
            self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, projections=projections, writer_map=self.writer_map(scope, self.attempt))
        prepared = self.store.install_grant(self.attempt, scope, "grant-row", writes, refs, guards=guards, projections=projections, writer_map=self.writer_map(scope, self.attempt))
        self.port.rows["run-record"]["revision"] = "2"
        state = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(state, self.port.rows)

    def native_writer_chain(self):
        scope = dict(self.scope, record_kind="workspace", writer_scope_id="integration-example")
        declaration = self.writer_map(scope).declaration
        stages = [("implement-step", "implement", {"gc.build.artifact_schema": "gc.build.implementation-summary.v1"},
                   ["prepare-worktree"], ["workspace"]),
                  ("review-step", "independent-acceptance", {"gc.run_target": "gc.implementation-reviewer"},
                   ["implement"], ["review"]),
                  ("result-step", "record-result", {"gc.run_target": "gc.run-operator"},
                   ["independent-acceptance"], ["member-result", "owner-output", "workspace"]),
                  ("close-step", "close-source-anchor", {"gc.run_target": "gc.run-operator"},
                   ["record-result"], ["workspace"])]
        for bead_id, step_id, facts, dependencies, kinds in stages:
            metadata = {"workflow_id": "run-example", "gc.root_store_ref": "rig:example",
                        "gc.step_id": step_id, "gc.step_ref": "do-work." + step_id,
                        "gc.session_id": "session-b", "gc.native_step_dependencies.v1":
                            json.dumps(dependencies, separators=(",", ":")), **facts}
            self.port.rows[bead_id] = row(bead_id, status="open", metadata=metadata)
            declaration["steps"].append({"bead_id": bead_id, "step_id": step_id,
                "step_ref": metadata["gc.step_ref"], "dependencies": dependencies, "record_kinds": kinds})
        return scope, CookedWriterMap(canonical_bytes(declaration))

    def test_initial_grant_requires_actual_cooked_kind_not_a_caller_role(self):
        writer_map = self.writer_map(self.scope)
        self.port.rows["writer-step-example"]["metadata"]["gc.kind"] = "retry"
        with self.assertRaisesRegex(StoreError, "responsibilities"):
            self.store.install_grant(self.attempt, self.scope, "grant-row",
                [RecordWrite("run", "payload-row", self.samples["run"])], writer_map=writer_map)
        with self.assertRaises(TypeError):
            self.store.install_grant(self.attempt, self.scope, "grant-row", [])
        self.assertEqual([], self.port.requests)

    def test_generator_operations_cannot_consume_the_first_payload_before_admission(self):
        writer_map = self.writer_map(self.scope)
        original = copy.deepcopy(self.port.rows)
        writes = (item for item in [RecordWrite("run", "payload-row", self.samples["run"])])
        with self.assertRaisesRegex(StoreError, "retained lists or tuples"):
            self.store.install_grant(self.attempt, self.scope, "grant-row", writes,
                writer_map=writer_map, projections=[self.run_policy("payload-row", self.samples["run"])])
        self.assertEqual([], self.port.requests)
        self.assertEqual(original, self.port.rows)

    def test_map_refuses_boolean_version_foreign_member_and_duplicate_occurrences(self):
        original = self.writer_map(self.scope).declaration
        alternatives = [dict(original, version=True), dict(original, source_member_id="foreign-member")]
        duplicate = copy.deepcopy(original)
        duplicate["steps"].append(copy.deepcopy(duplicate["steps"][0]))
        alternatives.append(duplicate)
        self.port.rows["foreign-member"] = row("foreign-member", metadata={"workflow_id": "foreign-root", "gc.root_store_ref": "rig:example"})
        for declaration in alternatives:
            with self.subTest(declaration=declaration):
                with self.assertRaises(StoreError):
                    validate_cooked_writer_map(CookedWriterMap(canonical_bytes(declaration)), self.port.rows,
                        store_ref="rig:example", workflow_root_id="run-example", record_kind="run",
                        claimed_step_id="writer-step-example")
        self.assertEqual([], self.port.requests)

    def test_native_retry_control_and_single_writer_pair_is_unambiguous(self):
        data = self.writer_map(self.scope).declaration
        native = self.port.rows["writer-step-example"]["metadata"]
        native["gc.control_for"] = "prepare"
        control = dict(native, **{"gc.kind": "retry", "gc.step_ref": "build.prepare.control"})
        control.pop("gc.control_for")
        self.port.rows["retry-control"] = row("retry-control", metadata=control)
        data["steps"].append({"bead_id": "retry-control", "step_id": "prepare", "step_ref": control["gc.step_ref"],
                             "dependencies": [], "record_kinds": []})
        writer_map = CookedWriterMap(canonical_bytes(data))
        prepared = self.prepare(writer_map=writer_map)
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        self.assertIn("retry-control", {r["id"] for r in prepared.request["rows"]})
        self.port.rows["second-attempt"] = row("second-attempt", metadata=dict(native, **{"gc.step_ref": "build.prepare.attempt.2"}))
        second = dict(data["steps"][0], bead_id="second-attempt", step_ref="build.prepare.attempt.2")
        data["steps"].append(second)
        with self.assertRaisesRegex(StoreError, "multiple semantic"):
            validate_cooked_writer_map(CookedWriterMap(canonical_bytes(data)), self.port.rows,
                store_ref="rig:example", workflow_root_id="run-example", record_kind="run", claimed_step_id="writer-step-example")

    def test_every_cooked_occurrence_is_fenced_against_late_graph_change(self):
        scope, writer_map = self.native_writer_chain()
        prepared = self.prepare("workspace", writer_map=writer_map)
        self.port.rows["review-step"]["revision"] = "2"
        self.port.rows["review-step"]["metadata"]["gc.run_target"] = "other-role"
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)
        self.assertTrue(all(r["require_change"] for r in prepared.request["rows"]))

    def test_same_member_handoff_requires_closed_declared_predecessor(self):
        scope, writer_map = self.native_writer_chain()
        self.store.execute(self.prepare("workspace", writer_map=writer_map))
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        next_attempt = Attempt("session-b", "incarnation-b", "implement-step")
        self.port.rows["implement-step"].update(status="in_progress", assignee="worker")
        with self.assertRaisesRegex(StoreError, "closed native predecessor"):
            self.store.accept_replacement(next_attempt, scope, "grant-row", [], expected_grant=grant, writer_map=writer_map)
        self.port.rows["writer-step-example"]["status"] = "closed"
        prepared = self.store.accept_replacement(next_attempt, scope, "grant-row", [], expected_grant=grant, writer_map=writer_map)
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        self.assertEqual("implement-step", json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])["attempt"]["claimed_bead_id"])

    def test_same_member_close_handoff_fences_intervening_review_and_result(self):
        scope, writer_map = self.native_writer_chain()
        self.store.execute(self.prepare("workspace", writer_map=writer_map))
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        for bead_id in ("writer-step-example", "implement-step", "result-step"):
            self.port.rows[bead_id]["status"] = "closed"
        self.port.rows["close-step"].update(status="in_progress", assignee="worker")
        next_attempt = Attempt("session-b", "incarnation-b", "close-step")
        with self.assertRaisesRegex(StoreError, "closed declared native predecessor path"):
            self.store.accept_replacement(next_attempt, scope, "grant-row", [], expected_grant=grant, writer_map=writer_map)
        self.port.rows["review-step"]["status"] = "closed"
        prepared = self.store.accept_replacement(next_attempt, scope, "grant-row", [], expected_grant=grant, writer_map=writer_map)
        self.port.rows["review-step"]["revision"] = "20"
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)

    def test_retained_occurrence_cannot_be_rebound_before_shared_successor(self):
        scope, writer_map = self.native_writer_chain()
        self.store.execute(self.prepare("workspace", writer_map=writer_map))
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        self.port.rows["writer-step-example"]["status"] = "closed"
        self.port.rows["writer-step-example"]["metadata"]["gc.source_anchor_id"] = "different-member"
        self.port.rows["implement-step"].update(status="in_progress", assignee="worker")
        with self.assertRaises(StoreError):
            self.store.accept_replacement(Attempt("session-b", "incarnation-b", "implement-step"), scope,
                "grant-row", [], expected_grant=grant, writer_map=writer_map)

    def test_new_run_policy_joins_run_and_original_configuration_in_one_batch(self):
        prepared = self.prepare()
        changes = {r["id"]: r["set"] for r in prepared.request["rows"]}
        policy = self.run_policy("payload-row", self.samples["run"]).payload
        self.assertEqual(canonical_bytes(policy).decode(), changes["payload-row"]["gc.workspace_required_checks.v1"])
        self.assertEqual("committed", self.store.execute(prepared)["outcome"])
        self.assertEqual("replayed", self.store.execute(self.prepare(install=False))["outcome"])

    def test_new_mode_policy_missing_empty_or_conflicting_configuration_refuses(self):
        with self.assertRaisesRegex(StoreError, "one captured"):
            self.prepare(projections=[])
        projection = self.run_policy("payload-row", self.samples["run"])
        for checks in ([], [{"id": "same", "argv": ["true"]}, {"id": "same", "argv": ["false"]}],
                       [{"id": "unit", "argv": []}]):
            policy = dict(projection.payload, required_checks=checks, policy_sha256=record_sha256({"required_checks": checks}))
            with self.subTest(checks=checks):
                with self.assertRaises(StoreError):
                    self.prepare(projections=[RunCheckPolicyProjection("payload-row", policy)])
        self.port.rows["run-example"]["metadata"].pop("gc.var.worktree_checks")
        with self.assertRaisesRegex(StoreError, "original native configuration"):
            self.prepare()
        self.assertEqual([], self.port.requests)

    def test_captured_policy_configuration_race_has_no_partial_run_publication(self):
        prepared = self.prepare()
        self.port.rows["run-example"]["revision"] = "20"
        self.port.rows["run-example"]["metadata"]["gc.var.worktree_checks"] = canonical_bytes({"required_checks": [{"id": "other", "argv": ["false"]}]}).decode()
        before = copy.deepcopy(self.port.rows)
        self.assertEqual("unknown", self.store.execute(prepared)["outcome"])
        self.assertEqual(before, self.port.rows)

    def test_required_policy_cannot_change_or_be_added_to_an_existing_run(self):
        self.store.execute(self.prepare())
        original = copy.deepcopy(self.port.rows)
        self.checks = [{"id": "different", "argv": ["false"]}]
        self.port.rows["run-example"]["metadata"]["gc.var.worktree_checks"] = canonical_bytes({"required_checks": self.checks}).decode()
        with self.assertRaisesRegex(StoreError, "immutable"):
            self.prepare(install=False)
        self.port.rows = original
        self.checks = [{"id": "unit", "argv": ["true"]}]
        self.port.rows["payload-row"]["metadata"].pop("gc.workspace_required_checks.v1")
        with self.assertRaisesRegex(StoreError, "cannot be added on replay"):
            self.prepare(install=False)


    def readonly_map(self):
        declaration = self.writer_map(self.scope).declaration
        item = next(item for item in declaration["steps"] if item["bead_id"] == self.attempt.claimed_bead_id)
        metadata = self.port.rows[self.attempt.claimed_bead_id]["metadata"]
        metadata.update({"gc.step_id": "write-failing-test", "gc.step_ref": "build.write-failing-test"})
        item.update(step_id=metadata["gc.step_id"], step_ref=metadata["gc.step_ref"], record_kinds=[])
        return CookedWriterMap(canonical_bytes(declaration))

    def test_readonly_nonwriter_map_never_authorizes_any_mutation(self):
        self.assertEqual(self.store.execute(self.prepare())["outcome"], "committed")
        grant = json.loads(self.port.rows["grant-row"]["metadata"]["gc.workspace_write_grant"])
        self.port.requests.clear()
        writer_map = self.readonly_map()
        declaration = validate_cooked_writer_map(writer_map, self.port.rows, store_ref="rig:example",
            workflow_root_id="run-example", record_kind=None, claimed_step_id=self.attempt.claimed_bead_id,
            read_only=True)
        self.assertEqual(declaration["steps"][0]["record_kinds"], [])
        before = copy.deepcopy(self.port.rows)
        for method, extra in ((self.store.install_grant, {}), (self.store.write_records, {}),
                              (self.store.accept_replacement, {"expected_grant": grant})):
            with self.subTest(method=method.__name__):
                with self.assertRaisesRegex(StoreError, "not designated"):
                    method(self.attempt, self.scope, "grant-row",
                        [RecordWrite("run", "payload-row", self.samples["run"])], writer_map=writer_map, **extra)
        self.assertEqual(self.port.requests, [])
        self.assertEqual(self.port.rows, before)

    def test_readonly_admission_is_explicit_and_preserves_physical_scope_validation(self):
        writer_map = self.readonly_map()
        arguments = dict(store_ref="rig:example", workflow_root_id="run-example", record_kind=None,
                         claimed_step_id=self.attempt.claimed_bead_id)
        for selected in (False, 1, "true", None):
            with self.subTest(read_only=selected), self.assertRaises(StoreError):
                validate_cooked_writer_map(writer_map, self.port.rows, read_only=selected, **arguments)
        for key, value in (("gc.root_store_ref", "rig:other"), ("workflow_id", "foreign-root"),
                           ("gc.step_ref", "foreign.physical")):
            original = self.port.rows[self.attempt.claimed_bead_id]["metadata"][key]
            self.port.rows[self.attempt.claimed_bead_id]["metadata"][key] = value
            with self.subTest(fact=key), self.assertRaises(StoreError):
                validate_cooked_writer_map(writer_map, self.port.rows, read_only=True, **arguments)
            self.port.rows[self.attempt.claimed_bead_id]["metadata"][key] = original
        with self.assertRaises(StoreError):
            validate_cooked_writer_map(writer_map, self.port.rows, read_only=True,
                **dict(arguments, claimed_step_id="foreign-step"))
        changed = writer_map.declaration
        changed["steps"].append(copy.deepcopy(changed["steps"][0]))
        with self.assertRaises(StoreError):
            validate_cooked_writer_map(CookedWriterMap(canonical_bytes(changed)), self.port.rows,
                                      read_only=True, **arguments)


if __name__ == "__main__":
    unittest.main()
