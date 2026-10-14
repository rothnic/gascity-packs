from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "scripts"))

import create_beads_from_tasks as tasks
import workspace_entry as entry
from workspace_records import canonical_bytes, record_identity, record_sha256
import workspace_run as run


def source_payload():
    return {"target_rig": "example", "beads": [
        {"key": key, "title": key, "type": "task", "priority": 2,
         "description": "Implement " + key, "acceptance_criteria": ["Checks and review pass."]}
        for key in ("a", "b", "d")], "sources": {
        "nodes": [
            {"owner": "a", "members": ["a"], "strategy": "isolated", "predecessors": []},
            {"owner": "b", "members": ["b"], "strategy": "isolated", "predecessors": []},
            {"owner": "d", "members": ["d"], "strategy": "dependent", "predecessors": ["b", "a"]}],
        "terminal": "d"}}


class SourceExpansionTests(unittest.TestCase):
    def test_fan_in_allocates_real_integration_before_dependent(self):
        plan = tasks.parse_plan(source_payload())
        self.assertIn("d-inputs", [item.key for item in plan.runnables])
        self.assertEqual([node["owner"] for node in plan.sources["nodes"]], ["a", "b", "d-inputs", "d"])
        integration = next(item for item in plan.runnables if item.key == "d-inputs")
        self.assertEqual(integration.dependencies, ["b", "a"])
        self.assertEqual(plan.sources["nodes"][2]["predecessors"], ["b", "a"])
        self.assertEqual(plan.sources["nodes"][3]["predecessors"], ["d-inputs"])
        self.assertIn(("d", "d-inputs"), tasks.expanded_dependency_edges(plan))

    def test_source_order_never_comes_from_scheduler_edges(self):
        payload = source_payload()
        payload["beads"][1]["dependencies"] = ["a"]
        plan = tasks.parse_plan(payload)
        self.assertEqual(plan.sources["nodes"][1]["predecessors"], [])
        self.assertEqual(plan.sources["nodes"][2]["predecessors"], ["b", "a"])

    def test_expansion_refuses_cycle_unknown_member_and_ambiguous_terminal(self):
        for mutation in ("cycle", "missing", "terminal", "duplicate", "generated-collision"):
            with self.subTest(mutation=mutation):
                payload = source_payload()
                if mutation == "cycle":
                    payload["sources"]["nodes"][0].update(strategy="dependent", predecessors=["d"])
                elif mutation == "missing":
                    payload["sources"]["nodes"][0]["members"] = ["unknown"]
                elif mutation == "terminal":
                    payload["sources"]["terminal"] = "a"
                elif mutation == "duplicate":
                    payload["sources"]["nodes"][2]["predecessors"] = ["a", "a"]
                else:
                    payload["beads"].append(dict(payload["beads"][0], key="d-inputs"))
                with self.assertRaises(tasks.PlanError):
                    tasks.parse_plan(payload)

    def test_physical_plan_has_one_terminal_and_preserves_accepted_run(self):
        plan = tasks.parse_plan(source_payload())
        ids = {item.key: "native-" + item.key for item in plan.runnables}
        captured = {"workflow_root_id": "root-1", "base_oid": "a" * 40}
        physical = tasks.physical_source_plan(plan, ids, captured, writer_step_id="step-1", generation=1)
        self.assertEqual(physical["base_oid"], captured["base_oid"])
        self.assertEqual(physical["terminal_owner_id"], "native-d")
        self.assertEqual(physical["nodes"][2]["source_predecessor_owner_ids"], ["native-b", "native-a"])
        self.assertEqual(physical["nodes"][2]["member_ids"], ["native-d-inputs"])
        self.assertIsNone(physical["parent_canonical_oid"])


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workspace-entry-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "registered rig"
        self.git("init", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "file").write_text("base\n")
        self.git("add", "file")
        self.git("commit", "-m", "base")
        self.record = run.capture_payload(workflow_root_id="root-1", input_convoy_id="initial-1",
            source_anchor_id="initial-1", rig_root=str(self.repo), writer_step_id="prepare-1",
            worktree_lifecycle="new")
        self.reference = {"kind": "run", "identity": list(record_identity("run", self.record)), "bead_id": "record-1"}
        self.rows = {
            "root-1": self.row("root-1", metadata={"gc.kind": "workflow", "gc.root_store_ref": "rig:example",
                "gc.input_convoy_id": "implementation-1", "gc.implementation_run_ref": canonical_bytes(self.reference).decode()}),
            "step-1": self.row("step-1", status="in_progress", assignee="worker", metadata={
                "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:example", "gc.step_ref": "prepare-convoy"}),
            "initial-1": self.row("initial-1", kind="convoy", metadata={"gc.root_store_ref": "rig:example"}),
            "implementation-1": self.row("implementation-1", kind="convoy", metadata={
                "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:example",
                "gc.source_root_id": "root-1", "gc.source_generation": "1"}),
            "record-1": self.row("record-1", status="closed", metadata={
                "gc.implementation_run": canonical_bytes(self.record).decode(),
                run.CHECKS_POLICY_KEY: canonical_bytes(run.capture_check_policy(self.record, "record-1",
                    canonical_bytes({"required_checks": [{"id": "project-tests", "argv": ["python3", "-m", "unittest"]}]}).decode())).decode()}),
        }
        rows = self.rows
        class Store:
            store_ref = "rig:example"
            cwd = str(self.root)
            gc = "gc"
            common_git_dir = str(self.repo / ".git")
            def snapshot(self, ids):
                return {bead_id: copy.deepcopy(rows[bead_id]) for bead_id in ids}
            def read_record(self, kind, bead_id, identity=None):
                data = json.loads(rows[bead_id]["metadata"]["gc.implementation_run"])
                if identity is not None and list(record_identity(kind, data)) != identity:
                    raise entry.EntryError("record identity mismatch")
                return data
        self.store = Store()

    @staticmethod
    def row(bead_id, *, status="open", assignee="", kind="task", metadata=None):
        return {"id": bead_id, "revision": "1", "status": status, "assignee": assignee,
                "type": kind, "labels": [], "metadata": metadata or {}}

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], text=True,
            capture_output=True, check=True).stdout.strip()

    def read(self, **changes):
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
            claimed_step_id="step-1", worktree_lifecycle="new", generation=1)
        args.update(changes)
        with patch.object(entry, "registered_rig", return_value=str(self.repo)):
            return entry.read_entry(self.store, **args)

    def test_changed_implementation_convoy_and_default_do_not_recapture(self):
        before = copy.deepcopy(self.record)
        (self.repo / "file").write_text("later\n")
        self.git("commit", "-am", "later")
        result = self.read()
        self.assertEqual(result["run"], before)
        self.assertEqual(result["input_convoy_id"], "implementation-1")
        self.assertEqual(result["run_sha256"], record_sha256(before))

    def test_wrong_native_root_store_generation_missing_record_and_mode_refuse(self):
        for changed in ("root", "store", "generation", "record", "mode"):
            with self.subTest(changed=changed):
                original = copy.deepcopy(self.rows)
                if changed == "root":
                    self.rows["implementation-1"]["metadata"]["gc.root_bead_id"] = "other-root"
                elif changed == "store":
                    self.rows["implementation-1"]["metadata"]["gc.root_store_ref"] = "rig:other"
                elif changed == "generation":
                    self.rows["implementation-1"]["metadata"]["gc.source_generation"] = "02"
                elif changed == "record":
                    self.rows["root-1"]["metadata"].pop("gc.implementation_run_ref")
                with self.assertRaises(entry.EntryError):
                    self.read(**({"worktree_lifecycle": "legacy"} if changed == "mode" else {}))
                self.rows.clear()
                self.rows.update(original)

    def test_record_hash_pin_is_checked(self):
        with self.assertRaises(entry.EntryError):
            self.read(expected_run_sha256="0" * 64)

    def test_missing_run_never_adopts_artifact_context(self):
        self.rows["root-1"]["metadata"].pop("gc.implementation_run_ref")
        with self.assertRaisesRegex(entry.EntryError, "recorded run|migration"):
            self.read()

    def test_premature_implementation_without_declared_plan_refuses(self):
        with self.assertRaisesRegex(entry.EntryError, "source-plan owner"):
            self.read(require_plan=True)

    def test_pending_source_is_explicit_and_checks_native_claim(self):
        from workspace_store import Attempt
        self.rows["root-1"]["metadata"].pop("gc.implementation_run_ref")
        self.rows["root-1"]["metadata"].pop("gc.input_convoy_id")
        self.rows["step-1"]["metadata"]["gc.session_id"] = "session-1"
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
                    entrypoint="build", worktree_lifecycle="new", allow_pending_source=True)
        result = entry.prepare_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **args)
        self.assertEqual(result["state"], "awaiting-source")
        self.assertFalse(result["implementation_allowed"])
        for change in (dict(entrypoint="plan"), dict(generation=2), dict(worktree_lifecycle="unknown")):
            with self.subTest(change=change), self.assertRaises(entry.EntryError):
                entry.prepare_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **dict(args, **change))
        with self.assertRaises(entry.EntryError):
            entry.prepare_entry(self.store, Attempt("other-session", "instance-1", "step-1"), **args)

    def test_gate_reads_native_mode_and_does_not_adopt_changed_mode(self):
        from workspace_store import Attempt
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1", entrypoint="convoy")
        attempt = Attempt("session-1", "instance-1", "step-1")
        saved_reference = self.rows["root-1"]["metadata"].pop(entry.RUN_REF)
        self.assertEqual(entry.gate_entry(self.store, attempt, **args)["state"], "legacy")
        self.rows["root-1"]["metadata"][entry.RUN_REF] = saved_reference
        with self.assertRaises(entry.EntryError):
            entry.gate_entry(self.store, attempt, **args)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "new"
        with patch.object(entry, "registered_rig", return_value=str(self.repo)):
            self.assertEqual(entry.gate_entry(self.store, attempt, **args)["run"], self.record)
        with self.assertRaises(entry.EntryError):
            entry.gate_entry(self.store, attempt, worktree_lifecycle="legacy", **args)

    def test_recorded_mode_cannot_be_bypassed_by_legacy_default_or_native_mode_change(self):
        from workspace_store import Attempt
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
                    entrypoint="convoy")
        attempt = Attempt("session-1", "instance-1", "step-1")
        for mode in (None, "legacy"):
            with self.subTest(mode=mode), self.assertRaises(entry.EntryError):
                if mode is None:
                    self.rows["root-1"]["metadata"].pop("gc.var.worktree_lifecycle", None)
                else:
                    self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = mode
                entry.gate_entry(self.store, attempt, **args)

    def test_placeholder_is_closed_unassigned_empty_and_uses_native_id(self):
        self.rows["allocated-1"] = self.row("allocated-1", status="closed")
        with patch.object(entry, "native_json", return_value={"id": "allocated-1"}) as native:
            bead_id = entry.allocate_placeholder(self.store, title="Immutable run")
        self.assertEqual(bead_id, "allocated-1")
        self.assertIn("closed", native.call_args.args[2])
        self.assertIn("{}", native.call_args.args[2])
        self.assertNotIn("--id", native.call_args.args[2])

    def test_allocation_unknown_or_nonempty_blocks_without_duplicate_retry(self):
        with patch.object(entry, "native_json", side_effect=run.RunError("timeout")) as native:
            with self.assertRaisesRegex(entry.EntryError, "unknown|uncertain"):
                entry.allocate_placeholder(self.store, title="Immutable run")
            self.assertEqual(native.call_count, 1)
        self.rows["allocated-1"] = self.row("allocated-1", status="closed", metadata={"foreign": "state"})
        with patch.object(entry, "native_json", return_value={"id": "allocated-1"}):
            with self.assertRaises(entry.EntryError):
                entry.allocate_placeholder(self.store, title="Immutable run")


if __name__ == "__main__":
    unittest.main()
