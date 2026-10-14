"""Native readback doubles exercise discovery; they are not backend proof."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "scripts"))
import workspace_cooked as cooked
from workspace_records import RecordError


class CookedReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "do-work.formula.toml"
        self.path.write_text('formula = "do-work"\n')
        self.rows = {"root-1": self.row("root-1"), "member-1": self.row("member-1"),
            "attach-1": self.row("attach-1", {"gc.formula_name": "do-work",
                "gc.formula_hash": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                "gc.formula_source": str(self.path)})}
        self.formula = {"ok": True, "name": "do-work", "steps": [], "deps": []}
        prior = None
        for stage, designation in (
            ("prepare-worktree", {"gc.run_target": "gc.run-operator"}),
            ("implement", {"gc.run_target": "gc.implementation-worker", "gc.build.artifact_schema": "gc.build.implementation-summary.v1"}),
            ("independent-acceptance", {"gc.run_target": "gc.implementation-reviewer"}),
            ("record-result", {"gc.run_target": "gc.run-operator"}),
            ("close-source-anchor", {"gc.run_target": "gc.run-operator"})):
            ref = "do-work." + stage
            metadata = {**designation, "gc.step_id": ref, "gc.step_ref": ref,
                "gc.attach_root_id": "attach-1", "gc.source_anchor_id": "member-1",
                "gc.drain_member_id": "member-1", cooked.TOPOLOGY: json.dumps([prior] if prior else [], separators=(",", ":"))}
            self.rows[stage] = self.row(stage, metadata)
            self.formula["steps"].append({"id": ref, "metadata": designation})
            if prior:
                self.formula["deps"].append({"step_id": ref, "depends_on_id": prior, "type": "blocks"})
            prior = ref
        rows = self.rows
        class Store:
            cwd = self.tmp.name
            store_ref = "rig:example"
            gc = "gc"
            def snapshot(self, ids):
                return {bead_id: copy.deepcopy(rows[bead_id]) for bead_id in ids}
        self.store = Store()

    @staticmethod
    def row(bead_id, metadata=None):
        return {"id": bead_id, "revision": "1", "status": "closed", "assignee": "", "type": "task", "labels": [],
                "metadata": {"gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:example", **(metadata or {})}}

    def read(self, claimed="prepare-worktree", **options):
        ids = [key for key in self.rows if key not in ("root-1", "member-1", "attach-1")]
        with patch.object(cooked, "_native_list", return_value=ids), \
             patch.object(cooked, "native_json", return_value=self.formula):
            return cooked.read_cooked_writer_map(self.store, workflow_root_id="root-1", claimed_step_id=claimed,
                                                 **options)

    def readonly_stage(self, stage):
        ref = "do-work." + stage
        designation = {"gc.run_target": "gc.implementation-worker"}
        self.rows[stage] = self.row(stage, {**designation, "gc.step_id": ref, "gc.step_ref": ref,
            "gc.attach_root_id": "attach-1", "gc.source_anchor_id": "member-1",
            "gc.drain_member_id": "member-1", cooked.TOPOLOGY: '[]'})
        self.formula["steps"].append({"id": ref, "metadata": designation})

    def test_readonly_tdd_and_story_steps_keep_exact_native_occurrences_without_write_rights(self):
        for stage in ("write-failing-test", "implement-story"):
            self.readonly_stage(stage)
            with self.subTest(stage=stage):
                with self.assertRaises(RecordError):
                    self.read(stage)
                writer_map, rows = self.read(stage, read_only=True)
                item = next(step for step in writer_map.declaration["steps"] if step["bead_id"] == stage)
                self.assertEqual(item["record_kinds"], [])
                self.assertEqual(item["step_ref"], "do-work." + stage)
                self.assertEqual(rows[stage], self.rows[stage])
                for kind in ("workspace", "run"):
                    with self.subTest(kind=kind), self.assertRaises(RecordError):
                        cooked.validate_cooked_writer_map(writer_map, rows, store_ref=self.store.store_ref,
                            workflow_root_id="root-1", record_kind=kind, claimed_step_id=stage)

    def test_readonly_admission_still_refuses_foreign_tampered_and_missing_native_occurrences(self):
        stage = "write-failing-test"
        self.readonly_stage(stage)
        original = copy.deepcopy(self.rows)
        for change in ("root", "store", "role", "dependencies", "ref", "missing"):
            with self.subTest(change=change):
                self.rows.clear()
                self.rows.update(copy.deepcopy(original))
                metadata = self.rows[stage]["metadata"]
                if change == "root":
                    metadata["workflow_id"] = "foreign-root"
                elif change == "store":
                    metadata["gc.root_store_ref"] = "rig:other"
                elif change == "role":
                    metadata["gc.run_target"] = "gc.publisher"
                elif change == "dependencies":
                    metadata[cooked.TOPOLOGY] = '["unknown"]'
                elif change == "ref":
                    metadata["gc.step_ref"] = "do-work.foreign"
                else:
                    for key in ("gc.step_ref", "gc.step_id", cooked.TOPOLOGY):
                        metadata.pop(key)
                with self.assertRaises(RecordError):
                    self.read(stage, read_only=True)

    def test_readonly_opt_in_requires_an_explicit_boolean(self):
        for value in (None, 1, "true"):
            with self.subTest(value=value), self.assertRaises(RecordError):
                self.read(read_only=value)

    def test_actual_stage_graph_resolves_exact_physical_writer_responsibilities(self):
        writer_map, rows = self.read()
        kinds = {item["bead_id"]: item["record_kinds"] for item in writer_map.declaration["steps"]}
        self.assertIn("workspace", kinds["prepare-worktree"])
        self.assertEqual(kinds["independent-acceptance"], ["review"])
        self.assertEqual(kinds["record-result"], ["member-result", "owner-output", "workspace"])
        self.assertEqual(writer_map.declaration["source_member_id"], "member-1")
        self.assertEqual(set(rows), {"attach-1", "member-1", *kinds})

    def test_source_work_rows_never_become_cooked_steps(self):
        self.rows["ordinary-source-work"] = self.row("ordinary-source-work")
        writer_map, _ = self.read()
        self.assertNotIn("ordinary-source-work", [step["bead_id"] for step in writer_map.declaration["steps"]])

    def test_unknown_duplicate_foreign_and_changed_native_facts_refuse(self):
        originals = copy.deepcopy(self.rows)
        for change in ("missing", "duplicate", "foreign", "dependencies", "role", "member"):
            with self.subTest(change=change):
                self.rows.clear()
                self.rows.update(copy.deepcopy(originals))
                metadata = self.rows["prepare-worktree"]["metadata"]
                if change == "missing":
                    metadata.pop(cooked.TOPOLOGY)
                elif change == "duplicate":
                    self.rows["other-occurrence"] = copy.deepcopy(self.rows["prepare-worktree"])
                    self.rows["other-occurrence"]["id"] = "other-occurrence"
                elif change == "foreign":
                    metadata["gc.root_store_ref"] = "rig:other"
                elif change == "dependencies":
                    metadata[cooked.TOPOLOGY] = '["unknown"]'
                elif change == "role":
                    metadata["gc.run_target"] = "gc.publisher"
                else:
                    metadata["gc.drain_member_id"] = "another-member"
                with self.assertRaises(RecordError):
                    self.read()

    def test_changed_formula_source_blocks_reconstruction(self):
        self.path.write_text('formula = "different"\n')
        with self.assertRaisesRegex(RecordError, "changed since cooking"):
            self.read()

    def test_native_retry_control_and_single_attempt_are_unambiguous(self):
        control = self.rows["implement"]
        control["metadata"].update({"gc.kind": "retry", "gc.step_id": "implement"})
        self.formula["steps"][1]["metadata"].update({"gc.kind": "retry", "gc.step_id": "implement"})
        attempt = copy.deepcopy(control)
        attempt["id"] = "implement-attempt-1"
        attempt["metadata"].pop("gc.kind")
        attempt["metadata"].update({"gc.step_ref": "do-work.implement.attempt.1", "gc.control_for": "implement"})
        self.rows[attempt["id"]] = attempt
        self.formula["steps"].append({"id": attempt["metadata"]["gc.step_ref"], "metadata": {
            key: value for key, value in attempt["metadata"].items() if key in ("gc.run_target", "gc.build.artifact_schema", "gc.step_id", "gc.control_for")}})
        self.formula["deps"].append({"step_id": "do-work.implement.attempt.1", "depends_on_id": "do-work.prepare-worktree", "type": "blocks"})
        self.rows["independent-acceptance"]["metadata"][cooked.TOPOLOGY] = '["implement"]'
        writer_map, _ = self.read()
        items = {item["bead_id"]: item for item in writer_map.declaration["steps"]}
        self.assertEqual(items["implement"]["record_kinds"], [])
        self.assertEqual(items["implement-attempt-1"]["record_kinds"], ["workspace"])
        self.rows["implement-attempt-2"] = copy.deepcopy(attempt)
        self.rows["implement-attempt-2"]["id"] = "implement-attempt-2"
        self.rows["implement-attempt-2"]["metadata"]["gc.step_ref"] = "do-work.implement.attempt.2"
        self.formula["steps"].append({"id": "do-work.implement.attempt.2", "metadata": self.formula["steps"][-1]["metadata"]})
        self.formula["deps"].append({"step_id": "do-work.implement.attempt.2", "depends_on_id": "do-work.prepare-worktree", "type": "blocks"})
        with self.assertRaisesRegex(RecordError, "multiple semantic"):
            self.read()

    def test_bounded_native_listing_uses_selected_city_store_and_no_ambient_route(self):
        class Result:
            returncode = 0
            stdout = '[{"id":"prepare-worktree"}]'
        with patch.dict(os.environ, {"GC_CITY": "wrong", "GC_RIG": "wrong"}), \
             patch.object(cooked.subprocess, "run", return_value=Result()) as native:
            self.assertEqual(cooked._native_list(self.store, "gc.attach_root_id", "attach-1"), ["prepare-worktree"])
        args, kwargs = native.call_args
        self.assertEqual(args[0][:5], ["gc", "--city", self.store.cwd, "--rig", "example"])
        self.assertIn("101", args[0])
        self.assertNotIn("GC_CITY", kwargs["env"])
        self.assertNotIn("GC_RIG", kwargs["env"])


if __name__ == "__main__":
    unittest.main()
