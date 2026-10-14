"""Public configuration, actual helper calls and real Git; no native worker credit."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest
from unittest.mock import patch

import test_workspace_dependency as dependency_tests

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "gascity/assets/scripts"
PACKS = ("gascity", "compound-engineering", "superpowers", "bmad", "gstack")
LAYOUT_VARS = {"worktree_parent": "", "worktree_name_prefix": "",
               "worktree_allow_external_parent": "false"}


class PublicLayoutTests(unittest.TestCase):
    def test_all_public_workspace_formulas_declare_layout(self):
        counts = {}
        for pack in PACKS:
            count = 0
            for path in sorted((ROOT / pack / "formulas").glob("*.formula.toml")):
                formula = tomllib.loads(path.read_text())
                if "worktree_lifecycle" not in formula.get("vars", {}):
                    continue
                count += 1
                for key, default in LAYOUT_VARS.items():
                    with self.subTest(path=str(path.relative_to(ROOT)), key=key):
                        self.assertIn(key, formula["vars"])
                        self.assertEqual(default, formula["vars"][key]["default"])
            counts[pack] = count
        self.assertEqual(dict(gascity=23, **{"compound-engineering": 9},
                              superpowers=10, bmad=7, gstack=10), counts)

    def test_recorded_layout_is_complete_and_immutable_in_actual_writer(self):
        from workspace_records import RecordError, validate_record
        from workspace_store import validate_transition
        records = json.loads((ROOT / "gascity/tests/fixtures/workspace-records/valid.json").read_text())
        original = records["workspace"]
        owner = original["workspace_owner_id"]
        workspace = dict(original, work_dir="/project/worktrees/" + owner + "-g1",
                         layout=dict(parent="/project/worktrees", name_prefix="", allow_external_parent=False))
        validate_record("workspace", workspace)
        for layout in (dict(workspace["layout"], name_prefix="changed-"),
                       dict(workspace["layout"], parent="/other"),
                       dict(workspace["layout"], allow_external_parent=True), None):
            changed = copy.deepcopy(workspace)
            if layout is None:
                changed.pop("layout")
            else:
                changed["layout"] = layout
                changed["work_dir"] = layout["parent"] + "/" + layout["name_prefix"] + owner + "-g1"
            with self.subTest(layout=layout), self.assertRaises(RecordError):
                validate_transition("workspace", workspace, changed)
        historical = dict(workspace)
        historical.pop("layout")
        with self.assertRaises(RecordError):
            validate_transition("workspace", historical, workspace)
        for layout in ({"parent": "/project/worktrees"},
                       dict(workspace["layout"], allow_external_parent="true")):
            with self.subTest(layout=layout), self.assertRaises(RecordError):
                validate_record("workspace", dict(workspace, layout=layout))

    def test_historical_workspace_does_not_infer_prefix_or_external_permission(self):
        from workspace_checkout import WorkspaceCheckout
        from workspace_records import RecordError
        import test_workspace_checkout as checkout_tests
        case = checkout_tests.CheckoutTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.assertNotIn("layout", case.workspace)
        with self.assertRaisesRegex(RecordError, "recorded name prefix"):
            WorkspaceCheckout(case.run, case.workspace, store_ref="rig:fixture",
                evidence_dir=str(case.evidence), parent=str(case.parent),
                name_prefix="new-", allow_external_parent=True, gc=str(case.native))
        with self.assertRaisesRegex(RecordError, "explicit permission"):
            WorkspaceCheckout(case.run, case.workspace, store_ref="rig:fixture",
                evidence_dir=str(case.evidence), parent=str(case.parent), gc=str(case.native))


class LayoutNativeCompositionTests(unittest.TestCase):
    def setUp(self):
        self.case = dependency_tests.DependencyNativeCompositionTests(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.prepare_fixture()
        self.fixture = self.case.fixture

    def configure(self, **values):
        state = self.case.state()
        metadata = state["stores"]["rig:fixture"]["root"]["metadata"]
        for key, value in (LAYOUT_VARS | values).items():
            # Native graph creation omits empty formula values.
            if value == "":
                metadata.pop("gc.var." + key, None)
            else:
                metadata["gc.var." + key] = value
        (self.fixture.root / "port.json").write_text(json.dumps(state))
        return state

    def invoke(self, *extra, root="root", convoy="convoy"):
        f = self.fixture
        return subprocess.run([sys.executable, "-B", str(SCRIPTS / "workspace_dependency.py"),
            "--gc", str(f.port), "--store-ref", "rig:fixture", "--city-root", str(f.city),
            "--rig-name", "fixture", "--workflow-root-id", root, "--input-convoy-id", convoy,
            "--worktree-lifecycle", "new", "--generation", "1", "--workspace-owner-id", "C",
            "--member-id", "C", "--claimed-step-id", "prepare-C", "--artifact-root", str(f.artifacts),
            "--evidence-dir", str(f.diagnostics), *extra], cwd=f.city, capture_output=True,
            text=True, timeout=90)

    def passed(self, response):
        self.assertEqual(0, response.returncode, response.stderr)
        return json.loads(response.stdout)

    def assert_refused_without_effect(self, response, before):
        self.assertEqual(1, response.returncode, response.stdout)
        self.assertEqual(before, self.case.state())
        self.assertNotIn("native-allocation-", response.stdout)

    def test_public_root_variables_select_parent_prefix_and_native_flags(self):
        f = self.fixture
        parent = f.repo / "custom workspaces"
        parent.mkdir()
        self.configure(worktree_parent=str(parent), worktree_name_prefix="feature-")
        result = self.passed(self.invoke())
        expected = parent / "feature-C-g1"
        self.assertEqual(str(expected), result["path"])
        self.assertEqual(f.oid, f.git(expected, "rev-parse", "HEAD"))
        self.assertEqual(dict(parent=str(parent), name_prefix="feature-", allow_external_parent=False),
                         result["workspace"]["layout"])
        commands = [json.loads(line) for line in (f.root / "port.commands").read_text().splitlines()]
        ensure = next(args for args in commands if "ensure" in args and "--json" in args)
        self.assertIn("--root=" + str(parent), ensure)
        self.assertIn("--path=" + str(expected), ensure)

    def test_external_opt_in_is_recorded_and_omitted_resume_flags_reuse_it(self):
        f = self.fixture
        self.configure(worktree_parent=str(f.work.parent), worktree_name_prefix="private-",
                       worktree_allow_external_parent="true")
        first = self.passed(self.invoke())
        before = self.case.state()
        resumed = self.passed(self.invoke())
        self.assertEqual(first["path"], resumed["path"])
        self.assertEqual(first["workspace"]["layout"], resumed["workspace"]["layout"])
        self.assertEqual(before, self.case.state())

    def test_default_layout_preserves_owner_generation_name(self):
        f = self.fixture
        self.configure()
        result = self.passed(self.invoke())
        self.assertEqual(str(f.repo / "worktrees/C-g1"), result["path"])
        self.assertEqual(dict(parent=str(f.repo / "worktrees"), name_prefix="", allow_external_parent=False),
                         result["workspace"]["layout"])

    def assert_default_override_refuses(self, *flags):
        f = self.fixture
        before = self.configure()
        metadata = before["stores"]["rig:fixture"]["root"]["metadata"]
        self.assertNotIn("gc.var.worktree_parent", metadata)
        self.assertNotIn("gc.var.worktree_name_prefix", metadata)
        registrations = f.git(f.repo, "worktree", "list", "--porcelain")
        self.assert_refused_without_effect(self.invoke(*flags), before)
        self.assertEqual(registrations, f.git(f.repo, "worktree", "list", "--porcelain"))
        self.assertFalse((f.repo / "worktrees/C-g1").exists())

    def test_absent_native_parent_default_refuses_conflicting_cli_before_allocation(self):
        parent = self.fixture.repo / "custom workspaces"
        parent.mkdir()
        self.assert_default_override_refuses("--parent", str(parent))
        self.assertFalse((parent / "C-g1").exists())

    def test_absent_native_prefix_default_refuses_conflicting_cli_before_allocation(self):
        self.assert_default_override_refuses("--name-prefix", "feature-")
        self.assertFalse((self.fixture.repo / "worktrees/feature-C-g1").exists())

    def test_external_without_opt_in_refuses_before_native_allocation(self):
        f = self.fixture
        before = self.configure(worktree_parent=str(f.work.parent))
        self.assert_refused_without_effect(self.invoke(), before)
        self.assertFalse((f.work.parent / "C-g1").exists())

    def test_invalid_native_layout_refuses_before_native_allocation(self):
        f = self.fixture
        symlink = f.root / "layout-alias"
        symlink.symlink_to(f.work.parent)
        collision = f.root / "layout-file"
        collision.write_text("preserve this file\n")
        foreign = f.root / "foreign"
        foreign.mkdir()
        f.git(foreign, "init", "-q")
        for values in ({"worktree_parent": "relative"},
                       {"worktree_parent": str(f.root / "absent")},
                       {"worktree_parent": str(symlink), "worktree_allow_external_parent": "true"},
                       {"worktree_parent": str(collision), "worktree_allow_external_parent": "true"},
                       {"worktree_parent": str(foreign), "worktree_allow_external_parent": "true"},
                       {"worktree_name_prefix": "../escape-"},
                       {"worktree_name_prefix": "bad\n"},
                       {"worktree_allow_external_parent": "TRUE"}):
            with self.subTest(values=values):
                before = self.configure(**values)
                self.assert_refused_without_effect(self.invoke(), before)
        self.assertEqual("preserve this file\n", collision.read_text())
        self.assertFalse((f.repo / "worktrees/C-g1").exists())

    def test_changed_recorded_layout_refuses_without_write_or_git_change(self):
        f = self.fixture
        self.configure(worktree_parent=str(f.work.parent), worktree_name_prefix="private-",
                       worktree_allow_external_parent="true")
        first = self.passed(self.invoke())
        original = self.case.state()
        work = Path(first["path"])
        (work / "notes.txt").write_text("preserved unfinished work\n")
        for key, value in (("worktree_parent", str(f.repo)), ("worktree_name_prefix", "changed-"),
                           ("worktree_allow_external_parent", "false")):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed["stores"]["rig:fixture"]["root"]["metadata"]["gc.var." + key] = value
                (f.root / "port.json").write_text(json.dumps(changed))
                self.assert_refused_without_effect(self.invoke(), changed)
                self.assertEqual(f.oid, f.git(work, "rev-parse", "HEAD"))
                self.assertEqual("preserved unfinished work\n", (work / "notes.txt").read_text())

    def test_removed_original_root_settings_refuse_recorded_reuse(self):
        f = self.fixture
        self.configure(worktree_parent=str(f.work.parent), worktree_name_prefix="private-",
                       worktree_allow_external_parent="true")
        first = self.passed(self.invoke())
        original = self.case.state()
        work = Path(first["path"])
        (work / "notes.txt").write_text("preserved unfinished work\n")
        for variable in LAYOUT_VARS:
            with self.subTest(variable=variable):
                changed = copy.deepcopy(original)
                changed["stores"]["rig:fixture"]["root"]["metadata"].pop("gc.var." + variable)
                (f.root / "port.json").write_text(json.dumps(changed))
                self.assert_refused_without_effect(self.invoke(), changed)
                self.assertEqual(f.oid, f.git(work, "rev-parse", "HEAD"))
                self.assertEqual("preserved unfinished work\n", (work / "notes.txt").read_text())

    def test_conflicting_explicit_override_refuses_before_native_allocation(self):
        f = self.fixture
        before = self.configure(worktree_parent=str(f.work.parent), worktree_name_prefix="private-",
                                worktree_allow_external_parent="true")
        for flags in (("--parent", str(f.repo)), ("--name-prefix", "changed-"),
                      ("--no-allow-external-parent",)):
            with self.subTest(flags=flags):
                self.assert_refused_without_effect(self.invoke(*flags), before)

    def test_explicit_external_permission_requires_an_actual_boolean(self):
        from workspace_checkout import select_workspace_layout
        from workspace_records import RecordError
        f = self.fixture
        before = self.configure(worktree_parent=str(f.work.parent), worktree_allow_external_parent="true")
        with self.assertRaisesRegex(RecordError, "boolean"):
            select_workspace_layout(f.run, "C", 1, before["stores"]["rig:fixture"]["root"]["metadata"],
                                    allow_external_parent=1, evidence_dir=f.diagnostics)
        self.assertEqual(before, self.case.state())
        self.assertFalse((f.work.parent / "C-g1").exists())

    def test_native_child_uses_original_logical_root_layout(self):
        f = self.fixture
        state = self.configure(worktree_parent=str(f.work.parent), worktree_name_prefix="original-",
                               worktree_allow_external_parent="true")
        f.rows = state["stores"]["rig:fixture"]
        f.sessions = state["stores"]["city:fixture"]
        f.provenances = state["provenances"]
        f.native_child("child-C", "C", roles=("prepare-C", "producer-C", "reviewer-C", "recorder-C"),
                       expansion="expansion-C", published=False)
        state = self.case.state()
        state["stores"]["rig:fixture"]["child-C"]["metadata"].update(
            {"gc.var." + key: value for key, value in LAYOUT_VARS.items() if value})
        (f.root / "port.json").write_text(json.dumps(state))
        result = self.passed(self.invoke(root="child-C", convoy="child-C-unit"))
        self.assertEqual(str(f.work.parent / "original-C-g1"), result["path"])
        self.assertEqual("root", result["workspace"]["workflow_root_id"])

    def test_shared_successor_keeps_recorded_owner_layout(self):
        # A new source plan needs new acceptance artifacts, not a rewrite of
        # the already-qualified dependent fixture's immutable evidence.
        self.case = dependency_tests.DependencyNativeCompositionTests(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture = self.case.fixture
        original_prepare = self.case.prepare_fixture

        def configured_fixture(**kwargs):
            original_prepare(**kwargs)
            state = self.configure(worktree_parent=str(self.fixture.work.parent),
                                   worktree_name_prefix="chain-", worktree_allow_external_parent="true")
            self.fixture.rows = state["stores"]["rig:fixture"]
            self.fixture.sessions = state["stores"]["city:fixture"]

        with patch.object(self.case, "prepare_fixture", configured_fixture):
            first, head = self.case.shared_successor_fixture()
        second = self.case.prepare(workflow_root_id="child-D", input_convoy_id="child-D-unit", member_id="D")
        self.assertEqual(str(self.fixture.work.parent / "chain-C-g1"), second["path"])
        self.assertEqual(first["workspace"]["layout"], second["workspace"]["layout"])
        self.assertEqual(head, second["input_oid"])
        self.assertEqual("D", second["workspace"]["active_member_id"])


if __name__ == "__main__":
    unittest.main()
