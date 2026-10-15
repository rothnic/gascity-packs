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

    def test_native_child_map_keeps_physical_occurrences_and_original_proof_rows(self):
        from test_workspace_entry import EntryTests
        import workspace_entry as entry
        fixture = EntryTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.drain_child()
        fixture.rows["child-1"]["metadata"].update({"gc.formula_name": "do-work",
            "gc.formula_hash": hashlib.sha256(self.path.read_bytes()).hexdigest(), "gc.formula_source": str(self.path)})
        native_ids = []
        for old_id in ("prepare-worktree", "implement", "independent-acceptance", "record-result", "close-source-anchor"):
            bead_id = "step-1" if old_id == "prepare-worktree" else old_id
            native = copy.deepcopy(self.rows[old_id])
            native["id"] = bead_id
            native["metadata"]["gc.root_bead_id"] = "child-1"
            for key in ("gc.attach_root_id", "gc.source_anchor_id", "gc.drain_member_id"):
                native["metadata"].pop(key)
            if bead_id == "step-1":
                native.update(status="in_progress", assignee="worker")
            fixture.rows[bead_id] = native
            native_ids.append(bead_id)
        continuation, original_rows = entry.read_native_continuation(fixture.store, claimed_step_id="step-1",
                                                                    requested_root_id="child-1")
        with patch.object(cooked, "_native_list", return_value=native_ids) as listing, \
             patch.object(cooked, "native_json", return_value=self.formula):
            writer_map, rows = cooked.read_cooked_writer_map(fixture.store, workflow_root_id="root-1",
                claimed_step_id="step-1", continuation=continuation, continuation_rows=original_rows)
        self.assertEqual(listing.call_args.args[1:], ("gc.root_bead_id", "child-1"))
        self.assertEqual(writer_map.declaration["expansion_root_id"], "child-1")
        self.assertEqual(writer_map.declaration["workflow_root_id"], "root-1")
        self.assertEqual(writer_map.declaration["source_member_id"], "member-1")
        self.assertEqual(writer_map.continuation.binding, continuation.binding)
        self.assertEqual(rows["step-1"]["metadata"]["gc.root_bead_id"], "child-1")
        for bead_id, row in original_rows.items():
            self.assertEqual(rows[bead_id], row)
        self.assertIn("control-1", rows)

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

    def test_large_cooked_context_keeps_complete_graph_with_bounded_snapshot_reads(self):
        for number in range(105):
            self.readonly_stage("branch-" + str(number))
        original = self.store.snapshot
        reads = []
        def snapshot(ids):
            self.assertLessEqual(len(ids), 100)
            reads.append(list(ids))
            return original(ids)
        self.store.snapshot = snapshot
        writer_map, rows = self.read()
        self.assertEqual(110, len(writer_map.declaration["steps"]))
        self.assertEqual(112, len(rows))
        self.assertEqual(set(rows), set().union(*(set(ids) for ids in reads)))

    def test_native_preview_raw_metadata_uses_exact_persisted_vars_before_defaults(self):
        self.rows["attach-1"]["metadata"].update({"gc.var.worktree_lifecycle": "new",
            "gc.var.implementation_target": "gc.implementation-worker"})
        self.formula["vars"] = [{"name": "worktree_lifecycle", "default": "legacy"},
            {"name": "implementation_target", "default": "gc.other-worker"}]
        self.formula["steps"][1]["metadata"].update({"gc.lifecycle": "{{worktree_lifecycle}}",
            "gc.run_target": "{{implementation_target}}"})
        self.rows["implement"]["metadata"]["gc.lifecycle"] = "new"
        with patch.object(cooked, "native_json", return_value=self.formula) as native, \
             patch.object(cooked, "_native_list", return_value=list(self.rows)[3:]):
            writer_map, _ = cooked.read_cooked_writer_map(self.store, workflow_root_id="root-1",
                claimed_step_id="prepare-worktree")
        self.assertEqual(5, len(writer_map.declaration["steps"]))
        arguments = native.call_args.args[2]
        self.assertIn("worktree_lifecycle=new", arguments)
        self.assertIn("implementation_target=gc.implementation-worker", arguments)
        self.assertEqual("{{implementation_target}}", self.formula["steps"][1]["metadata"]["gc.run_target"])

    def test_native_preview_defaults_are_used_only_when_no_persisted_var_exists(self):
        self.formula["vars"] = [{"name": "target", "default": "gc.implementation-worker"}]
        self.formula["steps"][1]["metadata"]["gc.run_target"] = "{{target}}"
        self.read()
        self.rows["attach-1"]["metadata"]["gc.var.target"] = ""
        with self.assertRaisesRegex(RecordError, "writer designation"):
            self.read()

    def test_native_preview_unknown_or_changed_metadata_cannot_admit_a_writer(self):
        self.formula["steps"][1]["metadata"]["gc.run_target"] = "{{target}}"
        with self.assertRaisesRegex(RecordError, "unresolved variables"):
            self.read()
        self.rows["attach-1"]["metadata"]["gc.var.target"] = "gc.publisher"
        with self.assertRaisesRegex(RecordError, "writer designation"):
            self.read()
        self.rows["attach-1"]["metadata"]["gc.var.target"] = "{{other}}"
        with self.assertRaisesRegex(RecordError, "unresolved variables"):
            self.read()

    def test_native_preview_variable_defaults_require_unique_native_string_definitions(self):
        for definitions in ({}, [{"name": "target", "default": True}],
                            [{"name": "target"}, {"name": "target"}], [{"default": "x"}]):
            with self.subTest(definitions=definitions), self.assertRaises(RecordError):
                self.formula["vars"] = definitions
                self.read()

    def use_explicit_native_refs(self):
        for step in self.formula["steps"]:
            stage = step["id"].removeprefix("do-work.")
            ref = stage + ".iteration.1"
            step["metadata"].update({"gc.step_id": step["id"], "gc.step_ref": ref})
            self.rows[stage]["metadata"]["gc.step_ref"] = ref

    def test_explicit_native_refs_match_physical_steps_and_keep_compiled_dependencies(self):
        self.use_explicit_native_refs()
        writer_map, _ = self.read()
        items = {step["bead_id"]: step for step in writer_map.declaration["steps"]}
        self.assertEqual(items["prepare-worktree"]["step_ref"], "prepare-worktree.iteration.1")
        self.assertEqual(items["implement"]["dependencies"], ["do-work.prepare-worktree"])
        self.assertEqual(items["record-result"]["record_kinds"], ["member-result", "owner-output", "workspace"])

    def test_explicit_native_ref_refuses_unknown_physical_ref(self):
        self.use_explicit_native_refs()
        self.rows["prepare-worktree"]["metadata"]["gc.step_ref"] = "do-work.prepare-worktree"
        with self.assertRaisesRegex(RecordError, "physical occurrence"):
            self.read()

    def test_explicit_native_ref_must_be_nonblank_unique_and_a_string(self):
        self.use_explicit_native_refs()
        original = copy.deepcopy(self.formula)
        for value in ("", " ", None, 1, "implement.iteration.1"):
            with self.subTest(value=value):
                self.formula = copy.deepcopy(original)
                self.formula["steps"][0]["metadata"]["gc.step_ref"] = value
                with self.assertRaises(RecordError):
                    self.read()

    def test_explicit_native_refs_preserve_designation_and_dependency_refusals(self):
        self.use_explicit_native_refs()
        original = copy.deepcopy(self.rows)
        for fact, value in (("gc.step_id", "foreign"), ("gc.run_target", "gc.publisher"),
                            (cooked.TOPOLOGY, '["unknown"]'), ("gc.control_for", "forged")):
            with self.subTest(fact=fact):
                self.rows = copy.deepcopy(original)
                self.store.snapshot = lambda ids: {bead_id: copy.deepcopy(self.rows[bead_id]) for bead_id in ids}
                self.rows["prepare-worktree"]["metadata"][fact] = value
                with self.assertRaises(RecordError):
                    self.read()

    def test_authored_plan_review_requirement_cannot_be_removed_or_invented(self):
        key = "gc.build.plan_review_required"
        self.formula["steps"][0]["metadata"][key] = "true"
        with self.assertRaises(RecordError):
            self.read()
        self.rows["prepare-worktree"]["metadata"][key] = "true"
        self.read()
        self.formula["steps"][0]["metadata"].pop(key)
        with self.assertRaises(RecordError):
            self.read()

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

    def test_native_ralph_control_keeps_one_exact_iteration_without_write_rights(self):
        control = self.rows["implement"]
        control["metadata"].update({"gc.kind": "ralph", "gc.step_id": "implement"})
        self.formula["steps"][1]["metadata"].update({"gc.kind": "ralph", "gc.step_id": "implement"})
        attempt = copy.deepcopy(control)
        attempt["id"] = "implement-iteration-1"
        attempt["metadata"].pop("gc.kind")
        attempt["metadata"].update({"gc.step_ref": "implement.iteration.1", "gc.control_for": "implement"})
        self.rows[attempt["id"]] = attempt
        self.formula["steps"].append({"id": "do-work.implement.iteration.1", "metadata": {
            key: value for key, value in attempt["metadata"].items()
            if key in ("gc.run_target", "gc.build.artifact_schema", "gc.step_id", "gc.step_ref", "gc.control_for")}})
        self.formula["deps"].append({"step_id": "do-work.implement.iteration.1", "depends_on_id": "do-work.prepare-worktree", "type": "blocks"})
        self.rows["independent-acceptance"]["metadata"][cooked.TOPOLOGY] = '["implement"]'
        writer_map, _ = self.read(claimed=attempt["id"])
        items = {item["bead_id"]: item for item in writer_map.declaration["steps"]}
        self.assertEqual(items["implement"]["record_kinds"], [])
        self.assertEqual(items[attempt["id"]]["record_kinds"], ["workspace"])
        with self.assertRaises(RecordError):
            self.read(claimed="implement")
        attempt["metadata"]["gc.control_for"] = "foreign"
        with self.assertRaises(RecordError):
            self.read(claimed=attempt["id"])

    def scope_check_pair(self):
        body = self.rows["implement"]
        body["metadata"].update({"gc.step_ref": "review.loop.iteration.1.implement",
            "gc.scope_ref": "review.loop.iteration.1", "gc.scope_role": "member",
            "gc.ralph_step_id": "review.loop", "gc.attempt": "1", "gc.on_fail": "abort_scope"})
        self.formula["steps"][1]["metadata"].update({key: body["metadata"][key] for key in
            ("gc.step_ref", "gc.scope_ref", "gc.scope_role", "gc.ralph_step_id", "gc.attempt", "gc.on_fail")})
        control = copy.deepcopy(body)
        control["id"] = "scope-check-1"
        for key in ("gc.run_target", "gc.build.artifact_schema"):
            control["metadata"].pop(key)
        control["metadata"].update({"gc.kind": "scope-check", "gc.scope_role": "control",
            "gc.control_for": body["metadata"]["gc.step_ref"],
            "gc.step_ref": "do-work." + body["metadata"]["gc.step_ref"] + "-scope-check"})
        self.rows[control["id"]] = control
        self.formula["steps"].append({"id": control["metadata"]["gc.step_ref"], "metadata": {
            key: value for key, value in control["metadata"].items() if key in
            ("gc.kind", "gc.step_id", "gc.scope_role", "gc.scope_ref", "gc.control_for",
             "gc.ralph_step_id", "gc.attempt", "gc.on_fail")}})
        self.formula["deps"].append({"step_id": control["metadata"]["gc.step_ref"],
            "depends_on_id": "do-work.implement", "type": "blocks"})

    def test_exact_native_scope_check_body_pair_keeps_control_readonly(self):
        self.scope_check_pair()
        writer_map, _ = self.read("implement")
        items = {item["bead_id"]: item for item in writer_map.declaration["steps"]}
        self.assertEqual(items["implement"]["record_kinds"], ["workspace"])
        self.assertEqual(items["scope-check-1"]["record_kinds"], [])
        self.read("scope-check-1", read_only=True)
        with self.assertRaises(RecordError):
            self.read("scope-check-1")

    def test_scope_check_pair_refuses_changed_lineage_and_second_writer(self):
        self.scope_check_pair()
        original_rows, original_formula = copy.deepcopy(self.rows), copy.deepcopy(self.formula)
        for key, value in (("gc.control_for", "foreign"), ("gc.scope_ref", "foreign"),
                           ("gc.scope_role", "member"), ("gc.ralph_step_id", "foreign"),
                           ("gc.attempt", "2"), (cooked.TOPOLOGY, '[]'), ("gc.kind", "task")):
            with self.subTest(key=key):
                self.rows.clear(); self.rows.update(copy.deepcopy(original_rows))
                self.formula = copy.deepcopy(original_formula)
                self.rows["scope-check-1"]["metadata"][key] = value
                if key != cooked.TOPOLOGY:
                    self.formula["steps"][-1]["metadata"][key] = value
                if key == "gc.kind":
                    designation = {"gc.run_target": "gc.implementation-worker",
                                   "gc.build.artifact_schema": "gc.build.implementation-summary.v1"}
                    self.rows["scope-check-1"]["metadata"].update(designation)
                    self.formula["steps"][-1]["metadata"].update(designation)
                with self.assertRaises(RecordError):
                    self.read("implement")

    def test_scope_check_lineage_must_match_compiled_source_not_just_its_pair(self):
        self.scope_check_pair()
        original_rows, original_formula = copy.deepcopy(self.rows), copy.deepcopy(self.formula)
        for key, value in (("gc.scope_ref", "foreign"), ("gc.ralph_step_id", "foreign"),
                           ("gc.attempt", "2"), ("gc.on_fail", "continue"),
                           ("gc.scope_role", "foreign")):
            with self.subTest(key=key):
                self.rows.clear(); self.rows.update(copy.deepcopy(original_rows))
                for bead_id in ("implement", "scope-check-1"):
                    self.rows[bead_id]["metadata"][key] = value
                with self.assertRaisesRegex(RecordError, "writer designation differs from the cooked source"):
                    self.read("implement")
                self.assertEqual(self.formula, original_formula)

    def test_bounded_native_listing_uses_selected_city_store_and_no_ambient_route(self):
        class Result:
            returncode = 0
            stdout = '[{"id":"prepare-worktree"}]'
        with patch.dict(os.environ, {"GC_CITY": "wrong", "GC_RIG": "wrong"}), \
             patch.object(cooked.subprocess, "run", return_value=Result()) as native:
            self.assertEqual(cooked._native_list(self.store, "gc.attach_root_id", "attach-1"), ["prepare-worktree"])
        args, kwargs = native.call_args
        self.assertEqual(args[0][:5], ["gc", "--city", self.store.cwd, "--rig", "example"])
        self.assertIn("4097", args[0])
        self.assertNotIn("GC_CITY", kwargs["env"])
        self.assertNotIn("GC_RIG", kwargs["env"])

    def test_native_listing_refuses_sentinel_duplicate_and_malformed_context(self):
        class Result:
            returncode = 0
        for rows in ([{"id": "row-" + str(i)} for i in range(4097)],
                     [{"id": "same"}, {"id": "same"}], [{"id": None}], {"rows": []}):
            Result.stdout = json.dumps(rows)
            with self.subTest(kind=type(rows)), patch.object(cooked.subprocess, "run", return_value=Result()), \
                 self.assertRaises(RecordError):
                cooked._native_list(self.store, "gc.attach_root_id", "attach-1")


if __name__ == "__main__":
    unittest.main()
