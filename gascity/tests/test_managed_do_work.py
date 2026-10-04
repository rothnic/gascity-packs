from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest

PACK = Path(__file__).resolve().parents[1]
HELPER = PACK / "assets/scripts/managed_do_work.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("managed_do_work", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NativeCLI:
    """Only the native process boundary is replaced; policy runs in the helper."""

    def __init__(self):
        self.beads = {}
        self.deps = {}
        self.reports = {}
        self.convoys = {}
        self.calls = []
        self.current = ""
        self.reject_ancestor = False
        self.module = None

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:4] == ["gc", "hook", "current", "--id-only"]:
            return self.current + "\n"
        if args[:3] == ["gc", "convoy", "status"]:
            return json.dumps(self.convoys[args[3]])
        if args[:3] == ["gc", "bd", "show"]:
            return json.dumps([self.beads[args[3]]])
        if args[:4] == ["gc", "bd", "dep", "list"]:
            return json.dumps(self.deps.get(args[4], []))
        if args[:3] == ["gc", "bd", "update"]:
            bead = self.beads[args[3]]
            for index, value in enumerate(args):
                if value == "--set-metadata":
                    key, content = args[index + 1].split("=", 1)
                    bead["metadata"][key] = content
                elif value == "--status":
                    bead["status"] = args[index + 1]
            return ""
        if args[:2] == ["gc", "worktree"]:
            flags = dict(zip(args[3::2], args[4::2]))
            # --json is the final valueless flag.
            path = flags["--path"]
            if args[2] == "ensure" and path not in self.reports:
                Path(path).mkdir(parents=True)
                provenance = {
                    "schema_version": 1, "bead_id": flags["--bead"],
                    "store_ref": flags["--store-ref"],
                    "repo_identity": str(Path(flags["--repo"]) / ".git"),
                    "path": path, "branch": flags["--branch"],
                    "base_ref": flags["--base"], "base_sha": flags["--base-sha"],
                    "creator": flags["--creator"], "owner": flags["--owner"],
                    "generation": flags["--generation"], "lifecycle": "active",
                    "attempt_id": "attempt-" + flags["--bead"],
                }
                self.reports[path] = {
                    "schema_version": "1", "ok": True,
                    "path": path, "branch": flags["--branch"],
                    "head": flags["--base-sha"], "created": True,
                    "branch_created": True, "provenance": provenance,
                }
            return json.dumps(self.reports[path])
        if args[0] == "git":
            if "merge-base" in args and self.reject_ancestor:
                raise self.module.Error("parent commit is not contained in frozen base")
            if "rev-parse" in args:
                return args[-1].removesuffix("^{commit}") + "\n"
            return ""
        raise AssertionError("Unsupported native boundary: " + repr(args))


class Bundle:
    def __init__(self, module, native, directory, prefix):
        self.module, self.native = module, native
        self.source, self.root = prefix + "-source", prefix + "-root"
        self.directory = directory
        self.input_path = directory / (prefix + "-input.json")
        self.data = {
            "schema_version": 1, "source_anchor_id": self.source,
            "source_store_ref": "city:test", "repo_dir": str(directory / "repo"),
            "worktree_root": str(directory / "worktrees"),
            "base_sha": "a" * 40, "branch": "work/" + self.source,
            "generation": prefix + "-generation", "verification_command": "python3 fixture-tests.py", "parents": [],
        }
        native.beads[self.source] = {
            "id": self.source, "status": "open", "type": "task",
            "metadata": {"workflow_id": self.root},
        }
        native.beads[self.root] = {
            "id": self.root, "status": "open", "type": "epic",
            "metadata": {
                "gc.kind": "workflow", "gc.source_bead_id": self.source,
                "gc.source_store_ref": "city:test",
                "gc.input_convoy_id": self.source,
            },
        }
        native.deps[self.source] = [
            {"id": self.root, "dependency_type": "blocks"}
        ]
        self.write_input()

    def write_input(self):
        self.input_path.write_text(json.dumps(self.data), encoding="utf-8")

    def stage(self, stage, session="session-author"):
        self.step = self.root + "-" + stage
        self.native.beads[self.step] = {
            "id": self.step, "status": "in_progress", "type": "task",
            "assignee": session,
            "metadata": {
                "gc.root_bead_id": self.root, "gc.step_id": stage,
                "gc.attempt": "1", "gc.session_id": session,
            },
        }
        self.native.current = self.step
        return self.module.Workflow(
            self.step, run=self.native,
            env={"GC_SESSION_ID": session},
        )

    def close_step(self):
        self.native.beads[self.step]["status"] = "closed"
        self.native.beads[self.step]["metadata"]["gc.outcome"] = "pass"

    def prepare(self):
        self.stage("prepare-worktree").prepare(str(self.input_path))
        self.close_step()

    def artifact(self, path, stage, schema, upstream, **changes):
        meta = {
            "schema": schema, "workflow": {"id": self.root, "formula": "do-work"},
            "methodology": {"pack": "gascity", "name": "do-work"},
            "producer": {"formula": "do-work", "stage": stage, "attempt": 1},
            "status": "approved", "trace": {
                "upstream": [{"path": str(upstream),
                              "hash": "sha256:" + self.module.file_record(str(upstream))["sha256"]}],
                "coverage": [{"id": "REQ-1", "status": "covered"}],
            },
        }
        meta.update(changes)
        headings = (["Summary", "Intended Behavior", "Changed Files", "Verification", "Remaining Risks"]
                    if schema.endswith("implementation-summary.v1")
                    else ["Verdict", "Findings", "Verification"])
        body = "\n\n".join("## " + heading + "\n\nFixture pass." for heading in headings)
        body += "\n\n| ID | Status |\n| --- | --- |\n| REQ-1 | covered |\n"
        path.write_text("---\n" + json.dumps(meta) + "\n---\n\n" + body)
        return path

    def output(self):
        workflow = self.stage("implement")
        path = str(Path(self.data["worktree_root"]) / self.source)
        self.native.reports[path]["head"] = "b" * 40
        summary = self.directory / (self.source + "-summary.md")
        verification = self.directory / (self.source + "-verification.json")
        self.artifact(summary, "implement", "gc.build.implementation-summary.v1", self.input_path)
        verification.write_text(json.dumps({
            "tested_commit": "b" * 40, "result": "pass",
            "command": "python3 fixture-tests.py",
        }), encoding="utf-8")
        workflow.publish_output(str(summary), str(verification))
        self.close_step()

    def accept(self, session="session-reviewer"):
        workflow = self.stage("independent-acceptance", session)
        report = self.directory / (self.source + "-review.md")
        output = self.native.beads[self.root]["metadata"]["gc.implementation.output_path"]
        self.artifact(report, "independent-acceptance", "gc.build.review.v1", output)
        workflow.record_acceptance(str(report))
        self.close_step()

    def complete(self):
        self.prepare()
        self.output()
        self.accept()
        self.stage("close-source-anchor", "session-operator").close_source()
        self.close_step()


class FormulaContractTests(unittest.TestCase):
    def test_formula_requires_frozen_input_and_independent_acceptance(self):
        formula = tomllib.loads((PACK / "formulas/do-work.formula.toml").read_text())
        self.assertEqual(formula["vars"]["input_path"]["default"], "")
        self.assertIn("frozen", formula["vars"]["input_path"]["description"])
        steps = {step["id"]: step for step in formula["steps"]}
        self.assertEqual(
            steps["independent-acceptance"]["needs"], ["implement"]
        )
        self.assertEqual(
            steps["close-source-anchor"]["needs"], ["independent-acceptance"]
        )
        for stage in ("prepare-worktree", "implement", "independent-acceptance",
                      "close-source-anchor"):
            self.assertIn("managed-", steps[stage]["check"]["check"]["path"])


class ManagedDoWorkTests(unittest.TestCase):
    def setUp(self):
        self.module = load_helper()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "repo").mkdir()
        self.native = NativeCLI()
        self.native.module = self.module
        self.bundle = Bundle(self.module, self.native, self.directory, "item")

    def test_native_prepare_binds_source_not_generated_step(self):
        workflow = self.bundle.stage("prepare-worktree")
        report = workflow.prepare(str(self.bundle.input_path))
        ensure = next(call for call in self.native.calls if call[:3] ==
                      ["gc", "worktree", "ensure"])
        self.assertEqual(ensure[ensure.index("--bead") + 1], self.bundle.source)
        self.assertEqual(ensure[ensure.index("--owner") + 1], self.bundle.root)
        self.assertEqual(ensure[ensure.index("--base") + 1], "a" * 40)
        self.assertEqual(ensure[ensure.index("--base-sha") + 1], "a" * 40)
        source = self.native.beads[self.bundle.source]["metadata"]
        self.assertEqual(source["gc.work_dir"], report["path"])
        self.assertEqual(source["work_dir"], report["path"])
        self.assertEqual(source["gc.implementation.worktree_attempt_id"],
                         report["provenance"]["attempt_id"])
        step = self.native.beads[self.bundle.step]["metadata"]
        self.assertNotIn("gc.worktree_owner", step)
        self.assertFalse(any(call[:2] == ["git", "merge"] for call in self.native.calls))

    def test_native_own_workflow_dependency_is_not_a_parent_output(self):
        self.bundle.prepare()
        self.assertEqual(self.bundle.data["parents"], [])

    def test_other_blockers_are_never_dropped(self):
        self.native.deps[self.bundle.source].append(
            {"id": "unresolved-parent", "dependency_type": "waits-for"}
        )
        with self.assertRaisesRegex(self.module.Error, "parent.*dependencies"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_wrong_source_authority_cannot_be_repaired_by_stamping_input(self):
        self.native.beads[self.bundle.root]["metadata"]["gc.source_bead_id"] = "wrong"
        with self.assertRaisesRegex(self.module.Error, "source"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)
        self.assertNotIn("gc.source_anchor_id",
                         self.native.beads[self.bundle.root]["metadata"])

    def test_changed_source_workflow_owner_refuses_self_edge_exemption(self):
        self.native.beads[self.bundle.source]["metadata"]["workflow_id"] = "other-root"
        with self.assertRaisesRegex(self.module.Error, "workflow"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_input_bytes_and_location_remain_frozen_on_retry(self):
        self.bundle.prepare()
        before = copy.deepcopy(self.native.beads)
        self.bundle.data["generation"] = "replacement"
        self.bundle.write_input()
        with self.assertRaisesRegex(self.module.Error, "frozen"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertEqual(self.native.beads[self.bundle.source],
                         before[self.bundle.source])

    def test_repeat_prepare_retains_attempt_and_input(self):
        self.bundle.prepare()
        before = copy.deepcopy(self.native.beads[self.bundle.source])
        self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertEqual(self.native.beads[self.bundle.source], before)

    def test_absent_or_stale_native_claim_fails_before_provisioning(self):
        workflow = self.bundle.stage("prepare-worktree")
        for env, current in (({}, self.bundle.step),
                             ({"GC_SESSION_ID": "session-author"}, "other-step")):
            with self.subTest(env=env, current=current):
                workflow.env = env
                self.native.current = current
                with self.assertRaisesRegex(self.module.Error, "claim|session"):
                    workflow.prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_root_failure_or_cancellation_refuses_entry(self):
        self.bundle.prepare()
        for key, value in (("gc.outcome", "canceled"),
                           ("gc.outcome", "fail"),
                           ("gc.molecule_failed", "true")):
            with self.subTest(key=key, value=value):
                self.native.beads[self.bundle.root]["metadata"][key] = value
                with self.assertRaises(self.module.Error):
                    self.bundle.stage("implement").verify()
                self.native.beads[self.bundle.root]["metadata"].pop(key)

    def test_stale_worktree_attempt_is_not_adopted(self):
        self.bundle.prepare()
        path = str(Path(self.bundle.data["worktree_root"]) / self.bundle.source)
        self.native.reports[path]["provenance"]["attempt_id"] = "replacement-attempt"
        with self.assertRaisesRegex(self.module.Error, "attempt"):
            self.bundle.stage("implement").verify()

    def test_native_scalar_metadata_and_singleton_intake_are_supported(self):
        wrapper = "native-wrapper"
        self.native.beads[wrapper] = {
            "id": wrapper, "status": "open",
            "metadata": {"gc.synthetic": True, "gc.root_store_ref": "city:test"},
        }
        root = self.native.beads[self.bundle.root]["metadata"]
        root.pop("gc.source_bead_id")
        root.pop("gc.source_store_ref")
        root["gc.input_convoy_id"] = wrapper
        self.native.convoys[wrapper] = {"children": [{"id": self.bundle.source}]}
        self.native.beads[self.bundle.source]["metadata"].pop("workflow_id")
        workflow = self.bundle.stage("prepare-worktree")
        self.native.beads[self.bundle.step]["metadata"]["gc.attempt"] = 1
        self.assertEqual(workflow.worker()["attempt"], 1)
        workflow.prepare(str(self.bundle.input_path))
        self.assertEqual(self.native.beads[self.bundle.root]["metadata"]["gc.source_anchor_id"],
                         self.bundle.source)
        self.assertEqual(self.native.beads[self.bundle.source]["metadata"]["workflow_id"],
                         self.bundle.root)
        self.assertNotIn("gc.work_dir", self.native.beads[wrapper]["metadata"])

    def test_closed_failed_or_cancelled_root_cannot_provision(self):
        root = self.native.beads[self.bundle.root]
        root["status"] = "closed"
        for outcome in ("", "fail", "canceled", "cancelled", "skipped"):
            root["metadata"]["gc.outcome"] = outcome
            with self.subTest(outcome=outcome):
                with self.assertRaises(self.module.Error):
                    self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_native_metadata_rejects_structured_values(self):
        for value in ([], {}):
            with self.subTest(value=value):
                self.native.beads[self.bundle.root]["metadata"]["gc.synthetic"] = value
                with self.assertRaisesRegex(self.module.Error, "metadata"):
                    self.bundle.stage("prepare-worktree")
        self.assertFalse(self.native.reports)

    def test_frozen_schema_version_requires_an_integer_not_boolean(self):
        self.bundle.data["schema_version"] = True
        self.bundle.write_input()
        with self.assertRaisesRegex(self.module.Error, "contract"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_source_handoff_requires_exact_recorded_input_hash(self):
        source = self.native.beads[self.bundle.source]["metadata"]
        record = self.module.file_record(str(self.bundle.input_path))
        source.pop("workflow_id")
        source["gc.implementation.input_path"] = record["path"]
        workflow = self.bundle.stage("prepare-worktree")
        with self.assertRaisesRegex(self.module.Error, "hash|handoff"):
            workflow.prepare(None)
        source["gc.implementation.input_sha256"] = record["sha256"]
        workflow.prepare(None)
        self.assertEqual(self.native.beads[self.bundle.root]["metadata"]
                         ["gc.implementation.input_sha256"], record["sha256"])

    def test_missing_input_has_no_default_tip_fallback(self):
        with self.assertRaisesRegex(self.module.Error, "frozen.*required"):
            self.bundle.stage("prepare-worktree").prepare(None)
        self.assertFalse(self.native.reports)
        self.assertFalse(any(call[0] == "git" for call in self.native.calls))

    def test_cleared_source_workflow_link_refuses_every_replay_mode(self):
        self.bundle.complete()
        self.native.beads[self.bundle.source]["metadata"].pop("workflow_id")
        self.native.beads[self.bundle.source]["status"] = "open"
        for stage, mode in (("prepare-worktree", "prepare"), ("implement", "verify"),
                            ("independent-acceptance", "verify"), ("close-source-anchor", "close_source")):
            with self.subTest(stage=stage):
                workflow = self.bundle.stage(stage)
                with self.assertRaisesRegex(self.module.Error, "workflow"):
                    if mode == "prepare":
                        workflow.prepare(str(self.bundle.input_path))
                    else:
                        getattr(workflow, mode)()
        self.assertNotIn("workflow_id", self.native.beads[self.bundle.source]["metadata"])

    def test_closed_pass_root_cannot_start_worker_actions(self):
        root = self.native.beads[self.bundle.root]
        root["status"] = "closed"
        root["metadata"]["gc.outcome"] = "pass"
        with self.assertRaisesRegex(self.module.Error, "root|settled"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(self.native.reports)

    def test_source_stamp_mismatch_is_not_overwritten(self):
        root = self.native.beads[self.bundle.root]["metadata"]
        root["gc.source_anchor_id"] = "other-source"
        with self.assertRaisesRegex(self.module.Error, "anchor"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertEqual(root["gc.source_anchor_id"], "other-source")
        self.assertFalse(self.native.reports)

    def test_partial_managed_ownership_is_not_repaired(self):
        source = self.native.beads[self.bundle.source]["metadata"]
        source["work_dir"] = "/old/unmanaged-worktree"
        before = copy.deepcopy(source)
        with self.assertRaisesRegex(self.module.Error, "ownership"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertEqual(source, before)
        self.assertFalse(self.native.reports)

    def test_partial_input_pins_are_not_rebound_by_explicit_input(self):
        record = self.module.file_record(str(self.bundle.input_path))
        for bead_id in (self.bundle.root, self.bundle.source):
            meta = self.native.beads[bead_id]["metadata"]
            for key, value in (("input_path", record["path"]),
                               ("input_sha256", record["sha256"])):
                with self.subTest(bead_id=bead_id, key=key):
                    meta["gc.implementation." + key] = value
                    with self.assertRaisesRegex(self.module.Error, "input"):
                        self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
                    meta.pop("gc.implementation." + key)
        self.assertFalse(any(call[:3] == ["gc", "worktree", "ensure"]
                             for call in self.native.calls))
        self.assertFalse(self.native.reports)

    def test_root_attempt_pin_without_source_provenance_never_reprovisions(self):
        self.native.beads[self.bundle.root]["metadata"][
            "gc.implementation.worktree_attempt_id"] = "old-provisioning-attempt"
        before = copy.deepcopy(self.native.beads)
        with self.assertRaisesRegex(self.module.Error, "ownership"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertFalse(any(call[:3] == ["gc", "worktree", "ensure"]
                             for call in self.native.calls))
        self.assertFalse(self.native.reports)
        self.assertEqual(self.native.beads[self.bundle.source], before[self.bundle.source])

    def test_source_root_and_intake_store_pins_must_all_agree(self):
        for bead_id, key in ((self.bundle.root, "gc.root_store_ref"),
                             (self.bundle.source, "gc.root_store_ref")):
            meta = self.native.beads[bead_id]["metadata"]
            meta[key] = "rig:different"
            with self.subTest(bead_id=bead_id):
                with self.assertRaisesRegex(self.module.Error, "store"):
                    self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
            meta.pop(key)
        self.assertFalse(self.native.reports)

    def test_repeated_prepare_refuses_changed_managed_ownership(self):
        self.bundle.prepare()
        source = self.native.beads[self.bundle.source]["metadata"]
        source["gc.worktree_owner"] = "other-root"
        before = copy.deepcopy(source)
        with self.assertRaisesRegex(self.module.Error, "ownership"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertEqual(source, before)

    def test_frozen_input_location_cannot_change_on_retry(self):
        self.bundle.prepare()
        replacement = self.directory / "copied-input.json"
        replacement.write_bytes(self.bundle.input_path.read_bytes())
        with self.assertRaisesRegex(self.module.Error, "location"):
            self.bundle.stage("prepare-worktree").prepare(str(replacement))

    def test_verification_must_name_actual_output_head(self):
        self.bundle.prepare()
        workflow = self.bundle.stage("implement")
        summary = self.directory / "summary.md"
        summary.write_text("# Summary\n")
        verification = self.directory / "verification.json"
        verification.write_text(json.dumps({
            "tested_commit": "b" * 40, "result": "pass", "command": "test",
        }))
        with self.assertRaisesRegex(self.module.Error, "tested.*commit|HEAD"):
            workflow.publish_output(str(summary), str(verification))

    def test_review_must_be_approved_and_bind_exact_native_attempt_output(self):
        self.bundle.prepare()
        self.bundle.output()
        output = self.native.beads[self.bundle.root]["metadata"]["gc.implementation.output_path"]
        for changes in (
            {"status": "changes_required"}, {"status": "blocked"}, {"status": "draft"},
            {"workflow": {"id": "stale-root", "formula": "do-work"}},
            {"producer": {"formula": "do-work", "stage": "independent-acceptance", "attempt": 2}},
            {"producer": {"formula": "do-work", "stage": "implement", "attempt": 1}},
            {"trace": {"upstream": [{"path": output, "hash": "sha256:" + "0" * 64}],
                       "coverage": [{"id": "REQ-1", "status": "covered"}]}},
        ):
            with self.subTest(changes=changes):
                workflow = self.bundle.stage("independent-acceptance", "session-reviewer")
                report = self.directory / "review-candidate.md"
                self.bundle.artifact(report, "independent-acceptance", "gc.build.review.v1",
                                     output, **changes)
                with self.assertRaisesRegex(self.module.Error, "artifact|approved|upstream"):
                    workflow.record_acceptance(str(report))
        self.assertNotIn("gc.implementation.acceptance_path",
                         self.native.beads[self.bundle.root]["metadata"])

    def test_summary_must_be_approved_and_bind_exact_native_attempt_input(self):
        self.bundle.prepare()
        workflow = self.bundle.stage("implement")
        summary = self.directory / "summary-candidate.md"
        verification = self.directory / "verification.json"
        verification.write_text(json.dumps({
            "tested_commit": "a" * 40, "result": "pass", "command": "python3 fixture-tests.py"}))
        for changes in (
            {"status": "draft"}, {"status": "blocked"},
            {"workflow": {"id": "stale-root", "formula": "do-work"}},
            {"producer": {"formula": "do-work", "stage": "implement", "attempt": 2}},
            {"trace": {"upstream": [{"path": str(self.bundle.input_path), "hash": "sha256:" + "0" * 64}],
                       "coverage": [{"id": "REQ-1", "status": "covered"}]}},
        ):
            with self.subTest(changes=changes):
                self.bundle.artifact(summary, "implement", "gc.build.implementation-summary.v1",
                                     self.bundle.input_path, **changes)
                with self.assertRaisesRegex(self.module.Error, "artifact|approved|upstream"):
                    workflow.publish_output(str(summary), str(verification))
        self.assertNotIn("gc.implementation.output_path",
                         self.native.beads[self.bundle.root]["metadata"])

    def test_verification_command_is_frozen(self):
        self.bundle.prepare()
        workflow = self.bundle.stage("implement")
        summary = self.directory / "summary.md"
        self.bundle.artifact(summary, "implement", "gc.build.implementation-summary.v1",
                             self.bundle.input_path)
        verification = self.directory / "verification.json"
        verification.write_text(json.dumps({
            "tested_commit": "a" * 40, "result": "pass", "command": "unrelated passing command"}))
        with self.assertRaisesRegex(self.module.Error, "verification"):
            workflow.publish_output(str(summary), str(verification))

    def test_open_native_failure_and_cancel_intent_refuse_entry(self):
        for bead_id in (self.bundle.root, self.bundle.source):
            meta = self.native.beads[bead_id]["metadata"]
            for key, value in (("molecule_failed", True),
                               ("gc.cancel_requested", "operator requested cancellation"),
                               ("gc.cancel_requested", "false")):
                with self.subTest(bead_id=bead_id, key=key, value=value):
                    meta[key] = value
                    with self.assertRaises(self.module.Error):
                        self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
                    meta.pop(key)
        self.assertFalse(self.native.reports)

    def test_same_native_session_cannot_independently_accept(self):
        self.bundle.prepare()
        self.bundle.output()
        with self.assertRaisesRegex(self.module.Error, "distinct|independent"):
            self.bundle.accept("session-author")
        self.assertNotIn("gc.implementation.acceptance_path",
                         self.native.beads[self.bundle.root]["metadata"])

    def test_acceptance_is_for_exact_current_head(self):
        self.bundle.prepare()
        self.bundle.output()
        path = str(Path(self.bundle.data["worktree_root"]) / self.bundle.source)
        self.native.reports[path]["head"] = "c" * 40
        with self.assertRaisesRegex(self.module.Error, "HEAD|commit"):
            self.bundle.accept()

    def test_complete_publication_preserves_native_budget_and_owner(self):
        self.native.beads[self.bundle.root]["metadata"]["gc.max_attempts"] = "3"
        self.native.beads[self.bundle.root]["metadata"]["gc.attempt"] = "2"
        self.bundle.complete()
        source = self.native.beads[self.bundle.source]
        self.assertEqual(source["status"], "closed")
        self.assertEqual(source["metadata"]["gc.outcome"], "pass")
        self.assertEqual(source["metadata"]["gc.work_outcome"], "shipped")
        self.assertEqual(source["metadata"]["gc.work_commit"], "b" * 40)
        self.assertEqual(source["metadata"]["workflow_id"], self.bundle.root)
        self.assertEqual(self.native.beads[self.bundle.root]["metadata"]["gc.attempt"], "2")
        self.assertEqual(self.native.beads[self.bundle.root]["metadata"]["gc.max_attempts"], "3")
        self.assertTrue(self.native.reports)

    def test_native_gates_are_read_only_and_require_returned_pass(self):
        self.bundle.complete()
        stages = {"prepare": "prepare-worktree", "output": "implement",
                  "acceptance": "independent-acceptance", "close": "close-source-anchor"}
        for phase, stage in stages.items():
            before = len(self.native.calls)
            workflow = self.module.Workflow(self.bundle.root + "-" + stage,
                                            run=self.native, env={})
            workflow.check(phase)
            calls = self.native.calls[before:]
            self.assertFalse(any(call[:3] == ["gc", "bd", "update"] or
                                 call[:3] == ["gc", "worktree", "ensure"] for call in calls))
        step = self.native.beads[self.bundle.root + "-implement"]
        step["status"] = "in_progress"
        workflow = self.module.Workflow(step["id"], run=self.native, env={})
        with self.assertRaisesRegex(self.module.Error, "closed/pass"):
            workflow.check("output")

    def test_parent_receipt_and_current_head_are_required(self):
        parent = Bundle(self.module, self.native, self.directory, "parent")
        parent.complete()
        metadata = self.native.beads[parent.source]["metadata"]
        self.bundle.data["base_sha"] = "b" * 40
        self.bundle.data["parents"] = [{
            "source_anchor_id": parent.source, "source_store_ref": "city:test",
            "accepted_commit": "b" * 40,
            "acceptance_path": metadata["gc.implementation.acceptance_path"],
            "acceptance_sha256": metadata["gc.implementation.acceptance_sha256"],
        }]
        self.bundle.write_input()
        self.native.deps[self.bundle.source].append(
            {"id": parent.source, "dependency_type": "blocks"}
        )
        self.bundle.prepare()
        parent_path = str(Path(parent.data["worktree_root"]) / parent.source)
        self.native.reports[parent_path]["head"] = "c" * 40
        with self.assertRaisesRegex(self.module.Error, "parent|HEAD|commit"):
            self.bundle.stage("implement").verify()

    def accepted_parent(self):
        parent = Bundle(self.module, self.native, self.directory, "parent")
        parent.complete()
        meta = self.native.beads[parent.source]["metadata"]
        self.bundle.data["base_sha"] = "b" * 40
        self.bundle.data["parents"] = [{
            "source_anchor_id": parent.source, "source_store_ref": "city:test",
            "accepted_commit": "b" * 40,
            "acceptance_path": meta["gc.implementation.acceptance_path"],
            "acceptance_sha256": meta["gc.implementation.acceptance_sha256"],
        }]
        self.bundle.write_input()
        self.native.deps[self.bundle.source].append(
            {"id": parent.source, "dependency_type": "blocks"})
        return parent

    def test_parent_source_and_root_publication_pins_are_required(self):
        parent = self.accepted_parent()
        source_meta = self.native.beads[parent.source]["metadata"]
        root_meta = self.native.beads[parent.root]["metadata"]
        for meta, key in ((source_meta, "gc.work_verification"),
                          (root_meta, "gc.implementation.input_sha256"),
                          (root_meta, "gc.implementation.worktree_attempt_id"),
                          (root_meta, "gc.source_anchor_id")):
            original = meta[key]
            meta[key] = "changed"
            with self.subTest(key=key):
                with self.assertRaises(self.module.Error):
                    self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
            meta[key] = original
        self.assertNotIn(str(self.bundle.data["worktree_root"]) + "/" + self.bundle.source,
                         self.native.reports)

    def test_parent_native_reviewer_and_exact_receipt_evidence_are_required(self):
        parent = self.accepted_parent()
        reviewer = self.native.beads[parent.root + "-independent-acceptance"]
        reviewer["metadata"]["gc.session_id"] = "replacement-session"
        with self.assertRaisesRegex(self.module.Error, "identity"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        reviewer["metadata"]["gc.session_id"] = "session-reviewer"
        review = self.directory / (parent.source + "-review.md")
        review.write_text("changed review")
        with self.assertRaisesRegex(self.module.Error, "evidence"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))

    def test_parent_ancestry_is_required_after_acceptance(self):
        self.accepted_parent()
        self.native.reject_ancestor = True
        with self.assertRaisesRegex(self.module.Error, "contained"):
            self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
        self.assertNotIn(str(self.bundle.data["worktree_root"]) + "/" + self.bundle.source,
                         self.native.reports)

    def test_canceled_failed_or_unreviewed_parent_is_refused(self):
        parent = Bundle(self.module, self.native, self.directory, "parent")
        parent.complete()
        metadata = self.native.beads[parent.source]["metadata"]
        self.bundle.data["base_sha"] = "b" * 40
        self.bundle.data["parents"] = [{
            "source_anchor_id": parent.source, "source_store_ref": "city:test",
            "accepted_commit": "b" * 40,
            "acceptance_path": metadata["gc.implementation.acceptance_path"],
            "acceptance_sha256": metadata["gc.implementation.acceptance_sha256"],
        }]
        self.bundle.write_input()
        self.native.deps[self.bundle.source].append(
            {"id": parent.source, "dependency_type": "blocks"}
        )
        for key, value in (("gc.outcome", "canceled"), ("gc.outcome", "fail"),
                           ("gc.implementation.acceptance_sha256", "0" * 64)):
            original = metadata[key]
            metadata[key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(self.module.Error):
                    self.bundle.stage("prepare-worktree").prepare(str(self.bundle.input_path))
            metadata[key] = original
        self.assertFalse(any(call[:3] == ["gc", "worktree", "ensure"] and
                             self.bundle.source in call for call in self.native.calls))


if __name__ == "__main__":
    unittest.main()
