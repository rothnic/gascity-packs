"""Candidate source composition and native-command-port delivery regressions.

These tests use real Git and native protocol doubles. Worker acceptance is unrun.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest
from unittest.mock import patch

from test_formula_assets import resolve_formula_from_dirs

REPO = Path(__file__).resolve().parents[2]
PACKS = ("gascity", "compound-engineering", "superpowers", "bmad", "gstack")
DIRECTORIES = [REPO / name / "formulas" for name in PACKS]
POLICY_VARS = ("worktree_lifecycle", "worktree_base_ref", "worktree_checks")


class ComposedFormulaTests(unittest.TestCase):
    def resolve(self, name):
        return resolve_formula_from_dirs(DIRECTORIES, name)

    def test_actual_entries_preserve_policy_and_legacy_defaults(self):
        names = ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build",
                 "implement", "build-from-convoy", "build-from-review", "github-issue-fix")
        for name in names:
            with self.subTest(formula=name):
                variables = self.resolve(name)["vars"]
                self.assertEqual(variables["worktree_lifecycle"]["default"], "legacy")
                self.assertEqual(variables["worktree_base_ref"]["default"], "@default")
                self.assertEqual(variables["worktree_checks"]["default"], "")

    def test_reached_expansions_forward_exact_native_policy_strings(self):
        for directory in DIRECTORIES:
            for path in directory.glob("*.formula.toml"):
                data = tomllib.loads(path.read_text())
                for step in data.get("steps", []) + data.get("template", []):
                    if step.get("expand_vars", {}).get("worktree_lifecycle"):
                        with self.subTest(path=path.name, step=step["id"]):
                            for variable in POLICY_VARS:
                                self.assertEqual(step["expand_vars"][variable], "{{" + variable + "}}")

    def test_both_drain_contexts_prepare_before_implementation_and_accept_before_close(self):
        for name, producer in (("do-work", "implement"), ("do-work-item", "implement-item"),
                               ("compound-work-item", "implement-item"), ("gstack-work-item", "implement-item")):
            steps = {step["id"]: step for step in self.resolve(name)["steps"]}
            with self.subTest(formula=name):
                self.assertIn("prepare-worktree", steps[producer]["needs"])
                self.assertIn(producer, steps["independent-acceptance"]["needs"])
                self.assertIn("independent-acceptance", steps["record-result"]["needs"])
                self.assertIn("record-result", steps["close-source-anchor"]["needs"])
                self.assertIn(producer, steps["close-source-anchor"]["needs"])

    def test_canonical_review_is_a_native_occurrence_before_finalization(self):
        for name in ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build"):
            steps = {step["id"]: step for step in self.resolve(name)["steps"]}
            with self.subTest(formula=name):
                approval = steps["review-result"]
                self.assertEqual(approval["metadata"]["gc.run_target"], "gc.implementation-reviewer")
                self.assertEqual(approval["condition"], "{{worktree_lifecycle}} == new")
                self.assertIn("review-result", steps["finalize"]["needs"])
                self.assertTrue(set(steps["finalize"]["needs"]) - {"review-result"})

    def test_installed_command_registry_uses_only_candidate_helpers(self):
        command = REPO / "gascity/commands/workspace/run.sh"
        for helper in ("entry", "dependency", "checkout", "runtime", "flow"):
            with self.subTest(helper=helper):
                result = subprocess.run([str(command), helper, "--help"], text=True, capture_output=True,
                    env=dict(os.environ, GC_PACK_DIR=str(REPO / "gascity")), timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
        bad = subprocess.run([str(command), "../foreign"], text=True, capture_output=True,
                             env=dict(os.environ, GC_PACK_DIR=str(REPO / "gascity")), timeout=10)
        self.assertEqual(bad.returncode, 2)


class ComposedFlowTests(unittest.TestCase):
    def setUp(self):
        import test_workspace_runtime as fixtures
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.fixture = fixtures.NativeRuntimeTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Add native create to the existing command port, preserving its actual
        # guarded-batch/session/worktree protocol and real Git checks.
        port = self.fixture.port
        text = port.read_text()
        insert = '''if 'bd' in args and 'create' in args:
    data['allocation_counter'] = data.get('allocation_counter', 0) + 1
    key = 'allocated-' + str(data['allocation_counter'])
    data['stores']['rig:fixture'][key] = dict(id=key, revision='1', status='closed',
        assignee='', type='task', labels=[], metadata={})
    state_path.write_text(json.dumps(data))
    emit(dict(id=key))
'''
        text = text.replace("if 'list' in args and 'bd' in args:", insert + "if 'list' in args and 'bd' in args:")
        port.write_text(text)

    def test_actual_native_checks_review_allocation_result_and_owner_output(self):
        from workspace_flow import WorkspaceFlow
        from workspace_outputs import artifact
        from workspace_records import record_sha256
        f = self.fixture
        f.select_role("producer")
        checks = f.adapter("producer").execute_checks("member", "member", f.oid)
        f.select_role("reviewer")
        reviewer = f.adapter("reviewer")
        artifacts = [artifact(f.summary, f.artifacts)]
        context = reviewer.begin_review("member", "member", f.oid, checks, artifacts)
        independent = reviewer.complete_review(context, f.artifacts / "report.md", "passed", f.artifacts / "flow-review.json")
        f.select_role("recorder")
        flow = WorkspaceFlow(f.adapter())
        recorded = flow.record_result("member", "member", f.oid, checks, independent, artifacts)
        self.assertEqual(recorded["receipt"]["outcome"], "committed")
        self.assertEqual(recorded["checkpoint"]["output_oid"], f.oid)
        output = flow.owner_output("member")
        self.assertEqual(output["receipt"]["outcome"], "committed")
        self.assertEqual(output["output"]["final_member_result_sha256"], record_sha256(recorded["result"]))
        state = json.loads((f.root / "port.json").read_text())
        self.assertEqual(state["allocation_counter"], 4)
        member = state["stores"]["rig:fixture"]["member"]["metadata"]
        self.assertIn("gc.workspace_result_ref", member)
        self.assertIn("gc.workspace_output_ref", member)
        commands = [json.loads(line) for line in (f.root / "port.commands").read_text().splitlines()]
        self.assertFalse(any("sling" in command or "start" in command for command in commands))

    def test_uncertain_native_allocation_cannot_create_another_record(self):
        from workspace_flow import WorkspaceFlow
        from workspace_records import RecordError
        flow = WorkspaceFlow(self.fixture.adapter())
        with patch("workspace_flow.allocate_placeholder", side_effect=RecordError("native create reply lost")) as create:
            with self.assertRaisesRegex(RecordError, "reply lost"):
                flow._allocation("member-result", "member", "member")
            with self.assertRaisesRegex(RecordError, "uncertain"):
                flow._allocation("member-result", "member", "member")
            self.assertEqual(create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
