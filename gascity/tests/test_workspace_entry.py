from __future__ import annotations

import copy
import contextlib
import hashlib
import io
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
import workspace_runtime as runtime
from workspace_records import canonical_bytes, contracts, record_identity, record_sha256
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
            worktree_lifecycle="new", base_ref="@default")
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
            from workspace_store import WorkspaceStore
            _binding = WorkspaceStore._binding
            def snapshot(self, ids):
                return {bead_id: copy.deepcopy(rows[bead_id]) for bead_id in ids}
            def read_record(self, kind, bead_id, identity=None):
                data = json.loads(rows[bead_id]["metadata"][contracts()[kind]["metadata_key"]])
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

    def drain_child(self):
        self.rows["root-1"]["metadata"]["gc.build.implementation_convoy_id"] = "implementation-1"
        self.plan = {"version": 1, "workflow_root_id": "root-1", "generation": 1,
            "writer_step_id": "declare-1", "source_plan_owner_id": "plan-owner",
            "base_oid": self.record["base_oid"], "parent_canonical_generation": None,
            "parent_canonical_oid": None, "nodes": [{"owner_id": "member-1", "strategy": "isolated",
                "member_ids": ["member-1"], "source_predecessor_owner_ids": [], "single_lane": False}],
            "terminal_owner_id": "member-1"}
        plan_ref = {"kind": "source-plan", "identity": list(record_identity("source-plan", self.plan)),
                    "bead_id": "plan-record"}
        membership = {"gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:example",
                      "gc.source_root_id": "root-1", "gc.source_generation": "1"}
        self.rows["implementation-1"]["metadata"].update({"gc.source_plan_owner_id": "plan-owner",
                                                          "gc.source_plan_sha256": record_sha256(self.plan)})
        self.rows.update({
            "plan-owner": self.row("plan-owner", metadata={**membership, entry.PLAN_REF: canonical_bytes(plan_ref).decode()}),
            "plan-record": self.row("plan-record", status="closed", metadata={
                contracts()["source-plan"]["metadata_key"]: canonical_bytes(self.plan).decode()}),
            "member-1": self.row("member-1", metadata=membership),
            "control-1": self.row("control-1", metadata={"gc.kind": "drain", "gc.root_bead_id": "root-1",
                "gc.root_store_ref": "rig:example"}),
            "unit-1": self.row("unit-1", kind="convoy", metadata={"gc.synthetic": "true",
                "gc.synthetic_kind": "drain-unit-convoy", "gc.parent_convoy_id": "implementation-1",
                "gc.drain_control_id": "control-1", "gc.drain_member_id": "member-1"}),
            "child-1": self.row("child-1", metadata={"gc.kind": "workflow", "gc.root_store_ref": "rig:example",
                "gc.input_convoy_id": "unit-1", "gc.drain_control_id": "control-1", "gc.drain_member_id": "member-1",
                "gc.var.worktree_lifecycle": "new"}),
        })
        self.rows["step-1"]["metadata"].update({"gc.root_bead_id": "child-1", "gc.step_ref": "do-work.prepare-worktree"})

    def native_snapshot_store(self):
        """Cross the actual subprocess boundary with a synthetic native command port."""
        from workspace_store import WorkspaceStore
        source = self.root / "native-rows.json"
        source.write_bytes(canonical_bytes(self.rows))
        native = self.root / "native-gc"
        native.write_text("#!" + sys.executable + "\n"
            "import json,os,sys\nfrom pathlib import Path\n"
            "root=Path(__file__).parent\nargs=sys.argv[1:]\n"
            "assert args[:4]==['--city='+str(root),'beads','guarded-metadata-batch','--store-ref=rig:example']\n"
            "assert len(args)==6 and args[4].startswith('--snapshot=') and args[5]=='--json'\n"
            "ids=args[4].partition('=')[2].split(',')\n"
            "assert 1<=len(ids)<=100 and len(set(ids))==len(ids)\n"
            "rows=json.loads((root/'native-rows.json').read_text())\n"
            "response=dict(schema_version='1',ok=True,store_ref='rig:example',rows=[rows[key] for key in ids])\n"
            "with (root/'native-reads.jsonl').open('a') as log:\n"
            " log.write(json.dumps(dict(pid=os.getpid(),argv=sys.argv,ids=ids,response=response))+'\\n')\n"
            "print(json.dumps(response))\n")
        native.chmod(0o700)
        store = WorkspaceStore("rig:example", gc=str(native), cwd=self.root,
            common_git_dir=self.repo / ".git")
        return store, source, self.root / "native-reads.jsonl"

    def test_native_continuation_batches_boundary_reads_without_changing_binding(self):
        self.drain_child()
        before = copy.deepcopy(self.rows)
        store, source, log = self.native_snapshot_store()
        continuation, observed = entry.read_native_continuation(store, claimed_step_id="step-1",
            requested_root_id="child-1")
        plan_ref = json.loads(self.rows["plan-owner"]["metadata"][entry.PLAN_REF])
        policy = json.loads(self.rows["record-1"]["metadata"][run.CHECKS_POLICY_KEY])
        self.assertEqual(continuation.binding, dict(version=1, workflow_root_id="root-1",
            store_ref="rig:example", generation=1, child_root_id="child-1", unit_convoy_id="unit-1",
            implementation_convoy_id="implementation-1", drain_control_id="control-1", member_id="member-1",
            run_ref=self.reference, source_plan_ref=plan_ref, run_sha256=record_sha256(self.record),
            source_plan_sha256=record_sha256(self.plan), check_policy_sha256=record_sha256(policy)))
        expected = {key: before[key] for key in ("step-1", "child-1", "unit-1", "control-1", "root-1",
            "implementation-1", "member-1", "plan-owner", "record-1", "plan-record")}
        self.assertEqual(observed, expected)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual({row["id"]: row for call in calls for row in call["response"]["rows"]}, expected)
        self.assertEqual(self.rows, before)
        self.assertEqual(json.loads(source.read_text()), before)
        # Count actual process-boundary launches, without prescribing a batch partition.
        self.assertLess(len(calls), len(expected))
        self.assertEqual(sum(len(call["ids"]) for call in calls), len(expected))

    def test_native_continuation_later_admission_rereads_and_rejects_changed_authority(self):
        self.drain_child()
        store, source, log = self.native_snapshot_store()
        fence = runtime._ReadFence(store)
        _, original = entry.read_native_continuation(fence, claimed_step_id="step-1", requested_root_id="child-1")
        for bead_id, field, value in (("step-1", "revision", "2"), ("step-1", "status", "closed"),
                ("step-1", "assignee", "replacement-worker"), ("member-1", "revision", "2"),
                ("record-1", "revision", "2")):
            with self.subTest(bead_id=bead_id, field=field):
                changed = copy.deepcopy(self.rows)
                changed[bead_id][field] = value
                source.write_bytes(canonical_bytes(changed))
                previous = len(log.read_text().splitlines())
                with self.assertRaisesRegex(entry.RecordError, "cooked context changed after its original snapshot"):
                    entry.read_native_continuation(fence, claimed_step_id="step-1", requested_root_id="child-1")
                calls = [json.loads(line) for line in log.read_text().splitlines()[previous:]]
                self.assertIn(bead_id, {key for call in calls for key in call["ids"]})
                self.assertEqual(fence.original_rows, original)
        source.write_bytes(canonical_bytes(self.rows))

    def test_native_continuation_boundary_refuses_changed_relationship_health_and_policy(self):
        self.drain_child()
        store, source, _ = self.native_snapshot_store()
        for bead_id, key, value in (("unit-1", "gc.drain_member_id", "wrong-member"),
                ("control-1", "gc.root_store_ref", "rig:other"),
                ("member-1", "gc.source_generation", "2"),
                ("plan-owner", "gc.outcome", "fail"),
                ("plan-owner", entry.PLAN_REF, "{}"),
                ("record-1", run.CHECKS_POLICY_KEY, "{}")):
            with self.subTest(bead_id=bead_id, key=key):
                changed = copy.deepcopy(self.rows)
                changed[bead_id]["metadata"][key] = value
                source.write_bytes(canonical_bytes(changed))
                with self.assertRaises(entry.RecordError):
                    entry.read_native_continuation(store, claimed_step_id="step-1", requested_root_id="child-1")
        source.write_bytes(canonical_bytes(self.rows))

    def test_native_drain_child_inherits_original_run_plan_policy_and_preserves_physical_root(self):
        self.drain_child()
        (self.repo / "file").write_text("moving default after original capture\n")
        self.git("commit", "-am", "advance default")
        for requested in ("root-1", "child-1"):
            with self.subTest(requested=requested):
                result = self.read(workflow_root_id=requested, input_convoy_id="unit-1", require_plan=True)
                self.assertEqual(result["run"], self.record)
                self.assertEqual(result["source_plan"], self.plan)
                self.assertEqual(result["workflow_root_id"], "root-1")
                self.assertEqual(result["native_workflow_root_id"], "child-1")
                self.assertEqual(result["input_convoy_id"], "implementation-1")
                self.assertEqual(result["native_input_convoy_id"], "unit-1")
                self.assertEqual(result["native_continuation"]["member_id"], "member-1")
                self.assertEqual(result["source_plan"]["source_plan_owner_id"], "plan-owner")
                self.assertIn("control-1", result["_native_rows"])
                self.assertEqual(self.rows["step-1"]["metadata"]["gc.root_bead_id"], "child-1")
                self.assertNotIn(entry.RUN_REF, self.rows["child-1"]["metadata"])
                self.assertNotIn(entry.PLAN_REF, self.rows["child-1"]["metadata"])
                self.assertNotIn(entry.PLAN_REF, self.rows["root-1"]["metadata"])
        with self.assertRaisesRegex(entry.EntryError, "rendered input differs from the current native convoy"):
            self.read(workflow_root_id="child-1", input_convoy_id="implementation-1", require_plan=True)

    def test_child_continuation_rejects_wrong_native_chain_store_generation_and_ref(self):
        self.drain_child()
        original = copy.deepcopy(self.rows)
        for bead, key, value in (("unit-1", "gc.drain_control_id", "wrong-control"),
                ("unit-1", "gc.drain_member_id", "wrong-member"),
                ("unit-1", "gc.parent_convoy_id", "initial-1"),
                ("control-1", "gc.root_bead_id", "child-1"),
                ("control-1", "gc.root_store_ref", "rig:other"),
                ("member-1", "gc.source_generation", "2"),
                ("member-1", "gc.root_bead_id", "child-1"),
                ("child-1", entry.RUN_REF, canonical_bytes(self.reference).decode())):
            with self.subTest(bead=bead, key=key):
                self.rows.clear()
                self.rows.update(copy.deepcopy(original))
                self.rows[bead]["metadata"][key] = value
                with self.assertRaises(entry.EntryError):
                    self.read(workflow_root_id="child-1", require_plan=True)

    def test_continuation_drift_retains_exact_private_operands_and_still_refuses(self):
        self.drain_child()
        (self.root / ".gc").mkdir()
        self.rows["step-1"]["revision"] = "-9007199254740993"
        initial = copy.deepcopy({key: self.rows[key] for key in ("child-1", "step-1")})
        native_read = entry.read_native_continuation

        def changed(*args, **kwargs):
            self.rows["step-1"]["revision"] = "9007199254740995"
            self.rows["step-1"]["assignee"] = "replacement-worker"
            self.rows["step-1"]["metadata"].update({"gc.session_name": "replacement-session",
                                                   "gc.attempt_id": "replacement-attempt"})
            self.rows["child-1"]["metadata"]["note/~"] = "native stamp"
            return native_read(*args, **kwargs)

        with patch.object(entry, "read_native_continuation", side_effect=changed), \
             patch.object(entry, "allocate_placeholder") as allocate, \
             self.assertRaisesRegex(entry.EntryError, "native continuation changed after its original entry snapshot") as failure:
            self.read(workflow_root_id="child-1", require_plan=True)
        allocate.assert_not_called()
        directory = self.root / ".gc" / "workspace-entry-diagnostics"
        files = list(directory.iterdir())
        self.assertEqual(len(files), 1)
        proof = files[0]
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(proof.stat().st_mode & 0o777, 0o600)
        diagnostic = json.loads(proof.read_text())
        self.assertEqual(diagnostic["city_root"], str(self.root))
        self.assertEqual(diagnostic["store_ref"], self.store.store_ref)
        self.assertEqual(set(diagnostic["overlapping_rows"]), set(initial))
        for bead_id, pair in diagnostic["overlapping_rows"].items():
            self.assertEqual(pair["initial"], initial[bead_id])
            self.assertEqual(pair["continuation"], self.rows[bead_id])
            for key in ("initial", "continuation"):
                self.assertEqual(pair[key + "_sha256"], record_sha256(pair[key]))
                self.assertEqual(pair[key + "_revision"], pair[key]["revision"])
        self.assertEqual(diagnostic["overlapping_rows"]["step-1"]["changed_paths"],
                         ["/assignee", "/metadata/gc.attempt_id", "/metadata/gc.session_name", "/revision"])
        self.assertEqual(diagnostic["overlapping_rows"]["child-1"]["changed_paths"], ["/metadata/note~1~0"])
        self.assertIn(str(proof), str(failure.exception))
        self.assertIn(hashlib.sha256(proof.read_bytes()).hexdigest(), str(failure.exception))
        self.assertNotIn("replacement-session", str(failure.exception))
        self.assertNotIn(entry.RUN_REF, self.rows["child-1"]["metadata"])

    def test_unchanged_continuation_creates_no_diagnostic(self):
        self.drain_child()
        before = copy.deepcopy(self.rows)
        self.read(workflow_root_id="child-1", require_plan=True)
        self.assertEqual(self.rows, before)
        self.assertFalse((self.root / ".gc").exists())

    def test_read_fence_identical_rereads_pass_without_diagnostic_or_write(self):
        self.drain_child()
        before = copy.deepcopy(self.rows)
        with patch.object(self, "store", runtime._ReadFence(self.store)), \
             patch.object(entry, "allocate_placeholder") as allocate:
            result = self.read(workflow_root_id="child-1", require_plan=True)
        self.assertEqual(result["run"], self.record)
        self.assertEqual(self.rows, before)
        self.assertFalse((self.root / ".gc").exists())
        allocate.assert_not_called()

    def test_read_fence_refusal_retains_the_conflicting_row_before_entry_comparison(self):
        self.drain_child()
        (self.root / ".gc").mkdir()
        initial = copy.deepcopy(self.rows["step-1"])
        initial["metadata"]["typed"] = True
        snapshot = self.store.snapshot
        for key, value, paths in (
            ("revision", "-9007199254740993", ["/revision"]),
            ("metadata", {**initial["metadata"], "note/~": "native stamp"}, ["/metadata/note~1~0"]),
            ("metadata", {**initial["metadata"], "typed": 1}, ["/metadata/typed"]),
            ("status", "closed", ["/status"]),
            ("assignee", "replacement-worker", ["/assignee"]),
        ):
            with self.subTest(changed=key):
                self.rows["step-1"] = copy.deepcopy(initial)
                calls = []

                def changed(ids):
                    calls.append(list(ids))
                    if len(calls) == 2:
                        self.rows["step-1"][key] = value
                    return snapshot(ids)

                fence = runtime._ReadFence(self.store)
                with patch.object(self.store, "snapshot", side_effect=changed), \
                     patch.object(self, "store", fence), \
                     patch.object(entry, "allocate_placeholder") as allocate, \
                     patch.object(entry, "native_json") as native, \
                     self.assertRaisesRegex(entry.EntryError, "cooked context changed after its original snapshot") as failure:
                    self.read(workflow_root_id="child-1", require_plan=True)
                self.assertEqual(len(calls), 2)  # Diagnostic adds no store read.
                self.assertEqual(fence.original_rows["step-1"], initial)
                allocate.assert_not_called()
                native.assert_not_called()
                proof, = (self.root / ".gc" / "workspace-entry-diagnostics").iterdir()
                packet = json.loads(proof.read_text())
                self.assertEqual(packet["phase"], "read-fence.retain")
                self.assertEqual(set(packet["overlapping_rows"]), {"step-1"})
                pair = packet["overlapping_rows"]["step-1"]
                self.assertEqual(pair["initial"], initial)
                self.assertEqual(pair["continuation"], self.rows["step-1"])
                self.assertEqual(pair["changed_paths"], paths)
                for name in ("initial", "continuation"):
                    self.assertEqual(pair[name + "_revision"], pair[name]["revision"])
                    self.assertEqual(pair[name + "_sha256"], record_sha256(pair[name]))
                self.assertIn(str(proof), str(failure.exception))
                self.assertNotIn("native stamp", str(failure.exception))
                self.assertEqual(proof.stat().st_mode & 0o777, 0o600)
                proof.unlink()

    def test_read_fence_diagnostic_failure_or_oversize_still_refuses_without_write(self):
        self.drain_child()
        (self.root / ".gc").mkdir()
        initial = copy.deepcopy(self.rows["step-1"])
        snapshot = self.store.snapshot
        for failure in ("write-error", "oversize"):
            with self.subTest(failure=failure):
                self.rows["step-1"] = copy.deepcopy(initial)
                calls = []

                def changed(ids):
                    calls.append(list(ids))
                    if len(calls) == 2:
                        self.rows["step-1"]["assignee"] = "replacement-worker"
                        if failure == "oversize":
                            self.rows["step-1"]["metadata"]["large"] = "x" * (1024 * 1024)
                    return snapshot(ids)

                fence = runtime._ReadFence(self.store)
                with patch.object(self.store, "snapshot", side_effect=changed), \
                     patch.object(self, "store", fence), \
                     patch("workspace_checkout.save_diagnostic", side_effect=OSError("private write failed")) as save, \
                     patch.object(entry, "allocate_placeholder") as allocate, \
                     patch.object(entry, "native_json") as native, \
                     self.assertRaisesRegex(entry.EntryError, "cooked context changed.*private diagnostic unavailable"):
                    self.read(workflow_root_id="child-1", require_plan=True)
                self.assertEqual(len(calls), 2)
                self.assertEqual(fence.original_rows["step-1"], initial)
                if failure == "oversize":
                    save.assert_not_called()
                else:
                    save.assert_called_once()
                allocate.assert_not_called()
                native.assert_not_called()
                self.assertFalse(list((self.root / ".gc").rglob("*.json")))

    def test_continuation_diagnostic_failure_never_allows_changed_authority(self):
        self.drain_child()
        native_read = entry.read_native_continuation

        def changed(*args, **kwargs):
            self.rows["step-1"]["assignee"] = "replacement-worker"
            return native_read(*args, **kwargs)

        for unsafe in ("missing-parent", "symlink-parent", "public-directory", "oversize", "write-error"):
            with self.subTest(unsafe=unsafe):
                self.rows["step-1"]["assignee"] = "worker"
                parent = self.root / ".gc"
                if unsafe == "symlink-parent":
                    parent.symlink_to(self.repo, target_is_directory=True)
                elif unsafe != "missing-parent":
                    parent.mkdir()
                if unsafe == "public-directory":
                    (parent / "workspace-entry-diagnostics").mkdir(mode=0o755)
                if unsafe == "oversize":
                    self.rows["step-1"]["metadata"]["large"] = "x" * (1024 * 1024)
                with patch.object(entry, "read_native_continuation", side_effect=changed), \
                     patch("workspace_checkout.save_diagnostic", side_effect=OSError("private write failed")), \
                     self.assertRaisesRegex(entry.EntryError, "native continuation changed.*private diagnostic unavailable"):
                    self.read(workflow_root_id="child-1", require_plan=True)
                self.assertFalse((self.repo / "workspace-entry-diagnostics").exists())
                if parent.is_symlink():
                    parent.unlink()
                elif parent.exists():
                    for directory in parent.iterdir():
                        self.assertFalse(list(directory.iterdir()))
                        directory.rmdir()
                    parent.rmdir()
                self.rows["step-1"]["metadata"].pop("large", None)

    def test_child_gate_uses_retained_mode_before_legacy_and_never_allocates_a_run(self):
        from workspace_store import Attempt
        self.drain_child()
        attempt = Attempt("session-1", "instance-1", "step-1")
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="child-1",
                    entrypoint="convoy", require_plan=True)
        with patch.object(entry, "registered_rig", return_value=str(self.repo)), \
             patch.object(entry, "allocate_placeholder") as allocate:
            result = entry.gate_entry(self.store, attempt, **args)
            self.assertEqual(result["run"], self.record)
            allocate.assert_not_called()
            self.rows["child-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
            with self.assertRaises(entry.EntryError):
                entry.gate_entry(self.store, attempt, **args)

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
        with self.assertRaisesRegex(entry.EntryError, "lifecycle"):
            entry.gate_entry(self.store, attempt, **args)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        with self.assertRaisesRegex(entry.EntryError, "explicit migration"):
            entry.gate_entry(self.store, attempt, **args)
        self.rows["root-1"]["metadata"][entry.RUN_REF] = saved_reference
        with self.assertRaises(entry.EntryError):
            entry.gate_entry(self.store, attempt, **args)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "new"
        with patch.object(entry, "registered_rig", return_value=str(self.repo)):
            self.assertEqual(entry.gate_entry(self.store, attempt, **args)["run"], self.record)
        with self.assertRaises(entry.EntryError):
            entry.gate_entry(self.store, attempt, worktree_lifecycle="legacy", **args)

    def test_fresh_gate_requires_native_selector_and_never_uses_current_checkout(self):
        from workspace_store import Attempt
        self.rows["root-1"]["metadata"].pop(entry.RUN_REF)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "new"
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1", entrypoint="build")
        attempt = Attempt("session-1", "instance-1", "step-1")
        with patch.object(entry, "prepare_entry", return_value={"state": "capture"}) as prepare:
            with self.assertRaisesRegex(entry.EntryError, "native worktree_base_ref"):
                entry.gate_entry(self.store, attempt, **args)
            prepare.assert_not_called()
            self.rows["root-1"]["metadata"]["gc.var.worktree_base_ref"] = "@default"
            self.assertEqual(entry.gate_entry(self.store, attempt, **args), {"state": "capture"})
            self.assertEqual(prepare.call_args.kwargs["base_ref"], "@default")

    def test_recorded_mode_is_inherited_and_rejects_native_mode_change(self):
        from workspace_store import Attempt
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
                    entrypoint="convoy")
        attempt = Attempt("session-1", "instance-1", "step-1")
        with patch.object(entry, "registered_rig", return_value=str(self.repo)):
            self.assertEqual(entry.gate_entry(self.store, attempt, **args)["run"], self.record)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        with self.assertRaises(entry.EntryError):
            entry.gate_entry(self.store, attempt, **args)

    def test_placeholder_is_closed_unassigned_empty_and_uses_native_id(self):
        self.rows["allocated-1"] = self.row("allocated-1", status="closed")
        with patch.object(entry, "native_json", return_value={"id": "allocated-1"}) as native:
            bead_id = entry.allocate_placeholder(self.store, title="Immutable run")
        self.assertEqual(bead_id, "allocated-1")
        self.assertIn("closed", native.call_args.args[2])
        self.assertIn("{}", native.call_args.args[2])
        self.assertNotIn("--id", native.call_args.args[2])

    def test_pending_run_blocks_initial_allocation_and_visible_reference_continuation(self):
        import hashlib
        from workspace_requests import journal_directory
        from workspace_store import Attempt
        original = journal_directory(self.store) / "original-request.json"
        pending = original.parent / (hashlib.sha256(canonical_bytes(run.run_scope("root-1"))).hexdigest() + ".pending")
        pending.write_text(str(original))
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
                    entrypoint="build", worktree_lifecycle="new")
        with patch.object(entry, "registered_rig", return_value=str(self.repo)), \
             patch.object(entry, "source_context", return_value=("implementation-1", copy.deepcopy(self.rows))), \
             patch.object(entry, "allocate_placeholder") as allocate:
            with self.assertRaisesRegex(run.RecordError, "original retained request"):
                entry.prepare_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **args)
            self.rows["root-1"]["metadata"].pop(entry.RUN_REF)
            self.rows["step-1"]["metadata"]["gc.session_id"] = "session-1"
            with self.assertRaisesRegex(run.RecordError, "original retained request"):
                entry.prepare_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **args)
            allocate.assert_not_called()

    def test_legacy_recorded_run_pending_scope_cannot_bypass_entry_gate(self):
        import hashlib
        from workspace_requests import journal_directory
        from workspace_store import Attempt
        self.record["worktree_lifecycle"] = "legacy"
        self.rows["record-1"]["metadata"][contracts()["run"]["metadata_key"]] = canonical_bytes(self.record).decode()
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        self.reference["identity"] = list(record_identity("run", self.record))
        self.rows["root-1"]["metadata"][entry.RUN_REF] = canonical_bytes(self.reference).decode()
        directory = journal_directory(self.store)
        pending = directory / (hashlib.sha256(canonical_bytes(run.run_scope("root-1"))).hexdigest() + ".pending")
        pending.write_text(str(directory / "original-legacy-request.json"))
        with patch.object(entry, "registered_rig", return_value=str(self.repo)), \
             self.assertRaisesRegex(run.RecordError, "explicit migration"):
            entry.gate_entry(self.store, Attempt("session-1", "instance-1", "step-1"), gc="gc",
                city_root=str(self.root), rig_name="example", workflow_root_id="root-1", entrypoint="convoy")

    def test_unrecorded_native_legacy_child_refuses_without_allocation(self):
        from workspace_store import Attempt
        self.drain_child()
        self.rows["root-1"]["metadata"].pop(entry.RUN_REF)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        self.rows["child-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        args = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="child-1", entrypoint="convoy")
        with patch.object(entry, "allocate_placeholder") as create:
            with self.assertRaisesRegex(entry.EntryError, "explicit migration"):
                entry.gate_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **args)
            create.assert_not_called()
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "new"
        with self.assertRaisesRegex(entry.EntryError, "explicit migration"):
            entry.gate_entry(self.store, Attempt("session-1", "instance-1", "step-1"), **args)

    def test_task_creation_defaults_to_new_and_requires_native_inputs_before_creation(self):
        with patch.object(tasks, "create_from_tasks") as create, contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(tasks.main([str(self.root / "tasks.md"), "--dry-run"]), 1)
        self.assertIn("new source expansion requires", stderr.getvalue())
        create.assert_not_called()

    def test_entry_cli_read_and_prepare_inherit_the_recorded_mode(self):
        from workspace_store import Attempt
        args = ["--city-root", str(self.root), "--store-ref", "rig:example", "--rig", "example",
                "--claimed-step", "step-1"]
        for child in (False, True):
            if child:
                self.drain_child()
            for mode in ("new", "legacy"):
                self.record["worktree_lifecycle"] = mode
                self.rows["record-1"]["metadata"][contracts()["run"]["metadata_key"]] = canonical_bytes(self.record).decode()
                if child:
                    self.rows["child-1"]["metadata"]["gc.var.worktree_lifecycle"] = mode
                for workflow_root in (("root-1", "child-1") if child else ("root-1",)):
                    for action in ("read", "prepare"):
                        with self.subTest(mode=mode, child=child, root=workflow_root, action=action), \
                             patch("workspace_store.WorkspaceStore", return_value=self.store), \
                             patch("workspace_store.Attempt.from_env", return_value=Attempt("session-1", "instance-1", "step-1")), \
                             patch.object(entry, "registered_rig", return_value=str(self.repo)), \
                             contextlib.redirect_stdout(io.StringIO()) as stdout, \
                             contextlib.redirect_stderr(io.StringIO()) as stderr:
                            before = copy.deepcopy(self.rows)
                            self.assertEqual(entry.main([action, *args, "--workflow-root", workflow_root]), 0 if mode == "new" else 1, stderr.getvalue())
                            if mode == "new":
                                self.assertEqual(json.loads(stdout.getvalue())["run"]["worktree_lifecycle"], mode)
                            else:
                                self.assertIn("explicit migration", stderr.getvalue())
                            self.assertEqual(self.rows, before)

    def test_task_creation_explicit_legacy_cannot_allocate_in_recorded_new_run(self):
        args = [str(self.root / "tasks.md"), "--city", str(self.root), "--store-ref", "rig:example",
                "--claimed-step", "step-1", "--worktree-lifecycle", "legacy"]
        for child in (False, True):
            if child:
                self.drain_child()
            for workflow_root in (("root-1", "child-1") if child else ("root-1",)):
                before = copy.deepcopy(self.rows)
                with self.subTest(child=child, root=workflow_root), \
                     patch("workspace_store.WorkspaceStore", return_value=self.store), \
                     patch.object(tasks, "create_from_tasks", return_value=0) as create, \
                     contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(tasks.main([*args, "--workflow-root", workflow_root]), 1)
                    self.assertIn("lifecycle", stderr.getvalue())
                    create.assert_not_called()
                self.assertEqual(self.rows, before)

    def test_task_creation_inherits_new_and_refuses_historical_legacy_without_effects(self):
        from workspace_store import Attempt
        path = self.root / "tasks.md"
        path.write_text("## Bead Creation Payload\n```yaml\n" + tasks.yaml.safe_dump(source_payload()) + "```\n")
        args = [str(path), "--city", str(self.root), "--store-ref", "rig:example",
                "--workflow-root", "root-1", "--claimed-step", "step-1", "--dry-run"]
        for mode in ("new", "legacy"):
            with self.subTest(mode=mode):
                self.record["worktree_lifecycle"] = mode
                self.rows["record-1"]["metadata"][contracts()["run"]["metadata_key"]] = canonical_bytes(self.record).decode()
                before = copy.deepcopy(self.rows)
                with patch("workspace_store.WorkspaceStore", return_value=self.store), \
                     patch("workspace_store.Attempt.from_env", return_value=Attempt("session-1", "instance-1", "step-1")), \
                     patch.object(entry, "registered_rig", return_value=str(self.repo)), \
                     patch.object(tasks, "create_from_tasks", return_value=0) as create, \
                     contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(tasks.main(args), 0 if mode == "new" else 1, stderr.getvalue())
                    if mode == "new":
                        self.assertEqual(create.call_args.kwargs["workspace"]["state"]["run"], self.record)
                    else:
                        create.assert_not_called()
                        self.assertIn("explicit migration", stderr.getvalue())
                    create.reset_mock()
                    self.assertEqual(tasks.main(args + ["--worktree-lifecycle", "legacy"]), 1)
                    create.assert_not_called()
                self.assertEqual(self.rows, before)

    def test_task_creation_explicit_standalone_legacy_refuses_before_native_reads(self):
        args = [str(self.root / "tasks.md"), "--worktree-lifecycle", "legacy", "--dry-run"]
        with patch.object(tasks, "create_from_tasks") as create, \
             patch("workspace_store.WorkspaceStore") as native, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(tasks.main(args), 1)
            self.assertIn("explicit migration", stderr.getvalue())
            create.assert_not_called()
            native.assert_not_called()

    def test_task_creation_refuses_cooked_legacy_unclassified_and_uncaptured_new(self):
        from workspace_store import Attempt
        path = self.root / "tasks.md"
        path.write_text("## Bead Creation Payload\n```yaml\n" + tasks.yaml.safe_dump(source_payload()) + "```\n")
        args = [str(path), "--city", str(self.root), "--store-ref", "rig:example",
                "--workflow-root", "root-1", "--claimed-step", "step-1", "--dry-run"]
        self.rows["root-1"]["metadata"].pop(entry.RUN_REF)
        with patch("workspace_store.WorkspaceStore", return_value=self.store), \
             patch("workspace_store.Attempt.from_env", return_value=Attempt("session-1", "instance-1", "step-1")), \
             patch.object(tasks, "create_from_tasks", return_value=0) as create, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            before = copy.deepcopy(self.rows)
            self.assertEqual(tasks.main(args), 1)
            self.assertIn("explicit migration", stderr.getvalue())
            create.assert_not_called()
            self.assertEqual(self.rows, before)
            for mode in ("legacy", "new"):
                self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = mode
                before = copy.deepcopy(self.rows)
                with self.subTest(mode=mode):
                    self.assertEqual(tasks.main(args), 1)
                    create.assert_not_called()
                    self.assertEqual(self.rows, before)
                    create.reset_mock()

    def test_claimed_new_lifecycle_cannot_bypass_required_capture_through_legacy_root_mode(self):
        from workspace_store import Attempt
        self.rows["root-1"]["metadata"].pop(entry.RUN_REF, None)
        self.rows["root-1"]["metadata"]["gc.var.worktree_lifecycle"] = "legacy"
        self.rows["step-1"]["metadata"]["gc.lifecycle"] = "new"
        before = copy.deepcopy(self.rows)
        with patch.object(entry, "prepare_entry", side_effect=AssertionError("recapture")), \
             self.assertRaisesRegex(entry.EntryError, "explicit migration"):
            entry.gate_entry(self.store, Attempt("session-1", "instance-1", "step-1"), gc="gc",
                city_root=str(self.root), rig_name="example", workflow_root_id="root-1", entrypoint="build")
        self.assertEqual(self.rows, before)

    def test_inherited_legacy_without_selectors_refuses_with_history_preserved(self):
        self.drain_child()
        for bead in ("root-1", "child-1"):
            self.rows[bead]["metadata"].pop("gc.var.worktree_lifecycle", None)
        mode, retained = entry.read_entry_mode(self.store, workflow_root_id="child-1", claimed_step_id="step-1")
        self.assertEqual((mode, retained), ("new", self.record))
        historical = dict(self.record, worktree_lifecycle="legacy")
        key = contracts()["run"]["metadata_key"]
        self.rows["record-1"]["metadata"][key] = canonical_bytes(historical).decode()
        before = copy.deepcopy(self.rows)
        with patch.object(entry, "native_json") as native, patch.object(entry, "allocate_placeholder") as allocate:
            with self.assertRaisesRegex(entry.EntryError, "explicit migration.*migrate-existing-work"):
                entry.read_entry_mode(self.store, workflow_root_id="child-1", claimed_step_id="step-1")
            native.assert_not_called()
            allocate.assert_not_called()
        self.assertEqual(self.rows, before)
        self.assertEqual(entry.parse_record(self.rows["record-1"]["metadata"][key]), historical)

    def test_explicit_legacy_cli_refuses_before_native_or_git_reads(self):
        with patch("workspace_store.WorkspaceStore") as store, patch.object(entry, "native_json") as native, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = entry.main(["gate", "--city-root", str(self.root), "--store-ref", "rig:example",
                "--rig", "example", "--workflow-root", "root-1", "--claimed-step", "step-1",
                "--worktree-lifecycle", "legacy"])
        self.assertEqual(code, 1)
        self.assertIn("explicit migration", stderr.getvalue())
        store.assert_not_called()
        native.assert_not_called()

    def test_standalone_allocation_cli_cannot_create_an_unjournaled_native_record(self):
        import contextlib
        import io
        with patch.object(entry, "native_json") as native, contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = entry.main(["allocate", "--city-root", str(self.root), "--store-ref", "rig:example", "--rig", "example"])
        self.assertEqual(code, 1)
        self.assertIn("admitted workflow entry", stderr.getvalue())
        native.assert_not_called()

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
