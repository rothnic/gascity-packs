from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_formula_assets import resolve_formula_from_dirs
from test_workspace_records import fixture_records, records_module


PACK = Path(__file__).resolve().parents[1]
REPO = PACK.parent
CHECK = PACK / "assets/scripts/checks/workspace-lifecycle-valid.py"


def run_record(mode="legacy"):
    return dict(fixture_records()["run"], worktree_lifecycle=mode)


class WorkspaceLifecycleTests(unittest.TestCase):
    def test_run_requires_one_explicit_mode(self):
        records = records_module()
        for mode in ("legacy", "new"):
            with self.subTest(mode=mode):
                record = run_record(mode)
                self.assertEqual(records.validate_record("run", record)["worktree_lifecycle"], mode)
        missing = run_record()
        del missing["worktree_lifecycle"]
        with self.assertRaises(records.RecordError):
            records.validate_record("run", missing)
        for mode in (None, "", "automatic", True, ["legacy", "new"]):
            with self.subTest(invalid=mode):
                with self.assertRaises(records.RecordError):
                    records.validate_record("run", run_record(mode))

    def test_later_step_or_continuation_matches_recorded_mode_and_root(self):
        records = records_module()
        cases = json.loads((PACK / "tests/fixtures/workspace-lifecycle/modes.json").read_text())
        for case in cases:
            run = run_record(case["stored"])
            original = copy.deepcopy(run)
            with self.subTest(case=case["name"]):
                if case["ok"]:
                    self.assertEqual(records.verify_run_mode(run, case["selected"], run["workflow_root_id"]), case["selected"])
                else:
                    with self.assertRaisesRegex(records.RecordError, "lifecycle"):
                        records.verify_run_mode(run, case["selected"], run["workflow_root_id"])
                self.assertEqual(run, original)
        with self.assertRaisesRegex(records.RecordError, "root"):
            records.verify_run_mode(run_record(), "legacy", "different-root")

    def test_same_run_replay_cannot_replace_its_mode(self):
        records = records_module()
        stored = run_record("legacy")
        candidate = dict(stored, worktree_lifecycle="new")
        self.assertEqual(records.record_identity("run", stored), records.record_identity("run", candidate))
        with self.assertRaisesRegex(records.RecordError, "conflicting replay"):
            records.verify_replay("run", stored, candidate)

    def test_mixed_unclassified_or_missing_source_modes_fail(self):
        records = records_module()
        for mode in ("legacy", "new"):
            self.assertEqual(records.verify_source_modes(mode, {"owner": mode, "plan": "reference"}), mode)
            for surfaces in ({}, {"owner": ""}, {"owner": "unclassified"},
                             {"one": "legacy", "two": "new"}, {"plan": "reference"}):
                with self.subTest(mode=mode, surfaces=surfaces):
                    with self.assertRaisesRegex(records.RecordError, "lifecycle"):
                        records.verify_source_modes(mode, surfaces)

    def test_actual_entries_render_legacy_default_and_check_before_delegation(self):
        directories = [REPO / name / "formulas" for name in ("gascity", "compound-engineering", "superpowers", "bmad", "gstack")]
        entries = [(name, "prepare") for name in ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build")]
        entries += [(f"build-from-{stage}", f"prepare-{stage}") for stage in ("requirements", "plan", "decompose", "convoy", "review")]
        entries += [("implement", "prepare"), ("github-issue-fix", "snapshot")]
        for name, first in entries:
            with self.subTest(entry=name):
                formula = resolve_formula_from_dirs(directories, name)
                self.assertEqual(formula["vars"]["worktree_lifecycle"]["default"], "legacy")
                self.assertEqual(formula["vars"]["worktree_lifecycle"]["enum"], ["legacy", "new"])
                step = next(step for step in formula["steps"] if step["id"] == first)
                self.assertEqual(step["metadata"]["gc.lifecycle"], "{{worktree_lifecycle}}")
                self.assertEqual(step["metadata"]["gc.lifecycle.source_modes"], '{"workflow":"legacy"}')
                self.assertEqual(step["check"]["max_attempts"], 1)
                self.assertEqual(Path(step["check"]["check"]["path"]).name, CHECK.name)

    def test_manual_delegation_and_restart_preserve_selected_mode(self):
        for path in ("github-issue-fix-base/build.md", "build-from-review-base/review.md",
                     "build-from-review-base/repair-review.md"):
            with self.subTest(path=path):
                text = (PACK / "assets/workflows" / path).read_text()
                self.assertIn('--var worktree_lifecycle="{{worktree_lifecycle}}"', text)
                self.assertIn("unsupported", text)
        repair = (PACK / "assets/workflows/build-from-review-base/repair-review.md").read_text()
        self.assertIn("gc.restart.worktree_lifecycle={{worktree_lifecycle}}", repair)

    def test_admission_check_accepts_legacy_and_refuses_current_new_request(self):
        with tempfile.TemporaryDirectory(prefix="workspace-lifecycle-") as scratch:
            scratch = Path(scratch)
            snapshot = scratch / "step.json"
            calls = scratch / "calls.json"
            stub = scratch / "gc"
            stub.write_text("#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\n"
                            "Path(os.environ['GC_TEST_CALLS']).write_text(json.dumps(sys.argv[1:]))\n"
                            "print(Path(os.environ['GC_TEST_STEP']).read_text())\n")
            stub.chmod(0o755)
            env = dict(os.environ, PATH=f"{scratch}:{os.environ['PATH']}", GC_BEAD_ID="fixture-check",
                       GC_TEST_STEP=str(snapshot), GC_TEST_CALLS=str(calls))
            for selected, sources, ok in (("legacy", {"workflow": "legacy"}, True),
                                          ("new", {"workflow": "legacy"}, False),
                                          ("new", {"qualified-component": "new"}, True),
                                          ("legacy", {"one": "legacy", "two": "new"}, False),
                                          ("legacy", {}, False), ("", {"workflow": "legacy"}, False)):
                with self.subTest(selected=selected, sources=sources):
                    snapshot.write_text(json.dumps([{"id": "fixture-check", "metadata": {
                        "gc.lifecycle": selected, "gc.lifecycle.source_modes": json.dumps(sources)}}]))
                    result = subprocess.run([sys.executable, "-S", str(CHECK)], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
                    self.assertEqual(json.loads(calls.read_text()), ["bd", "show", "fixture-check", "--json"])
                    if ok:
                        self.assertEqual(json.loads(result.stdout)["worktree_lifecycle"], selected)
                    else:
                        self.assertIn("lifecycle", result.stderr)

    def test_admission_check_refuses_ambiguous_or_failed_native_read(self):
        with tempfile.TemporaryDirectory(prefix="workspace-lifecycle-invalid-") as scratch:
            scratch = Path(scratch)
            snapshot = scratch / "step.json"
            stub = scratch / "gc"
            stub.write_text("#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\n"
                            "print(Path(os.environ['GC_TEST_STEP']).read_text())\n"
                            "sys.exit(int(os.environ.get('GC_TEST_EXIT', '0')))\n")
            stub.chmod(0o755)
            env = dict(os.environ, PATH=f"{scratch}:{os.environ['PATH']}", GC_BEAD_ID="fixture-check",
                       GC_TEST_STEP=str(snapshot))
            valid = {"id": "fixture-check", "metadata": {
                "gc.lifecycle": "legacy", "gc.lifecycle.source_modes": '{"workflow":"legacy"}'}}
            for payload in ("not JSON", "[]", json.dumps([valid, valid]),
                            json.dumps(dict(valid, id="other-check")),
                            json.dumps(dict(valid, metadata=None)),
                            json.dumps(dict(valid, metadata={"gc.lifecycle": "legacy"})),
                            json.dumps(dict(valid, metadata={"gc.lifecycle": "legacy",
                                "gc.lifecycle.source_modes": '{"workflow":"legacy","workflow":"new"}'}))):
                with self.subTest(payload=payload):
                    snapshot.write_text(payload)
                    result = subprocess.run([sys.executable, "-S", str(CHECK)], env=env, text=True, capture_output=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")
            snapshot.write_text(json.dumps(valid))
            for overrides in ({"GC_TEST_EXIT": "1"}, {"GC_BEAD_ID": ""}):
                with self.subTest(overrides=overrides):
                    result = subprocess.run([sys.executable, "-S", str(CHECK)], env=dict(env, **overrides), text=True, capture_output=True)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
