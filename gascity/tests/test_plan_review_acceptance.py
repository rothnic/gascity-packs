from __future__ import annotations

import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "scripts"))
import validate_plan_review as review


PACK = Path(__file__).resolve().parents[1]


def plan_text(root: Path, *, workflow: str = "workflow-1", status: str = "approved",
              upstream_hash: str | None = None) -> str:
    upstream = root / "requirements.md"
    data = {
        "schema": "gc.build.plan.v1", "workflow": {"id": workflow, "formula": "build-basic"},
        "methodology": {"pack": "gascity", "name": "build-basic"},
        "producer": {"formula": "build-basic", "stage": "plan", "attempt": 1}, "status": status,
        "trace": {"upstream": [{"path": str(upstream),
                    "hash": upstream_hash or "sha256:" + hashlib.sha256(upstream.read_bytes()).hexdigest(),
                    "ids": ["REQ-1"]}], "coverage": [{"id": "REQ-1", "status": "covered"}]}}
    return "---\n" + review.build.yaml.safe_dump(data, sort_keys=False) + "---\n" + "\n".join([
        "# Implementation plan", "## Summary", "Implement the requested behavior.",
        "## Current System", "Current behavior is covered by a regression.",
        "## Proposed Implementation", "Use the existing procedure with its exact inputs.",
        "## Non-Goals", "Unrelated behavior remains outside this change.",
        "## Verification", "Run the documented project check.",
        "| ID | Status |", "| --- | --- |", "| REQ-1 | covered |", ""])


def relative_native_fixture(artifact_dir: Path, artifact_root: object) -> dict:
    artifact_dir.mkdir(parents=True)
    requirements = artifact_dir / "requirements.md"
    requirements.write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
    plan = artifact_dir / "plan.md"
    plan.write_text(plan_text(artifact_dir).replace(str(requirements), "requirements.md"))
    subject = review.current_subject(Path("plan.md"), workflow_root_id="workflow-1",
                                     artifact_root=artifact_dir)
    report_data = {"schema": "gc.verdict-report.v1", "kind": "review", "verdict": "pass",
                   "severity": "none", "subject": subject, "findings": []}
    (artifact_dir / "review.md").write_text("---\n" + review.build.yaml.safe_dump(report_data, sort_keys=False)
                                             + "---\n# Plan review\nExact current subject.\n")
    return {"id": "workflow-1", "metadata": {
        "gc.build.plan_path": "plan.md", "gc.build.requirements_path": "requirements.md",
        "gc.build.plan_review_report_path": "review.md", "gc.var.artifact_root": artifact_root}}


class PlanReviewAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="plan-review-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "requirements.md").write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
        self.plan = self.root / "plan.md"
        self.plan.write_text(plan_text(self.root))
        self.report = self.root / "review.md"
        self.subject = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_review()
        self.native_root = {"id": "workflow-1", "metadata": {
            "gc.build.plan_path": str(self.plan), "gc.build.requirements_path": str(self.root / "requirements.md"),
            "gc.build.plan_review_report_path": str(self.report)}}

    def write_review(self, *, subject=None, blocked=False):
        data = {"schema": "gc.verdict-report.v1", "kind": "review", "verdict": "fail" if blocked else "pass",
                "severity": "blocker" if blocked else "none", "subject": subject or self.subject,
                "findings": [{"id": "PLAN-1", "severity": "blocker", "title": "Plan is not implementation-ready",
                              "evidence": "Task boundaries and exact procedure arguments are missing.",
                              "required_fix": "Repair and review the current plan before decomposition."}] if blocked else []}
        self.report.write_text("---\n" + review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n# Plan review\nThe findings describe the reviewed plan.\n")

    def validate(self):
        return review.validate_recorded_review(self.native_root, artifact_root=self.root)

    def test_current_explicit_approval_is_accepted(self):
        self.assertEqual(self.validate(), self.subject)

    def test_default_native_stage_uses_existing_bounded_exec_gate(self):
        for name in ("build-base", "build-basic", "build-from-plan-base", "planning-base"):
            with self.subTest(formula=name):
                formula = tomllib.loads((PACK / "formulas" / (name + ".formula.toml")).read_text())
                step = next(step for step in formula["steps"] if step["id"] == "plan-review")
                self.assertEqual(step["metadata"][review.REQUIRED_KEY], "true")
                self.assertEqual(step["check"], {"max_attempts": 3, "check": {
                    "mode": "exec", "path": "../assets/scripts/checks/plan-review-approved.py", "timeout": "5m"}})
                self.assertTrue((PACK / "formulas" / step["check"]["check"]["path"]).resolve().is_file())

    def test_recording_blockers_does_not_authorize_an_approved_plan(self):
        self.write_review(blocked=True)
        # A well-formed failing report is valid evidence, not approval.
        self.assertEqual(review.verdict.validate_report_text(self.report.read_text()).verdict, "fail")
        with self.assertRaisesRegex(review.ReviewError, "unresolved findings"):
            self.validate()

    def test_changed_plan_requires_a_new_review_even_with_approved_status(self):
        self.plan.write_text(self.plan.read_text() + "\nChanged implementation procedure.\n")
        with self.assertRaisesRegex(review.ReviewError, "exact current plan"):
            self.validate()

    def test_changed_current_upstream_refuses_stale_plan_and_report(self):
        (self.root / "requirements.md").write_text("Changed acceptance requirement.\n")
        with self.assertRaisesRegex(review.ReviewError, "upstream hash is stale"):
            self.validate()

    def test_updating_plan_trace_does_not_refresh_old_approval(self):
        (self.root / "requirements.md").write_text("Changed acceptance requirement.\n")
        self.plan.write_text(plan_text(self.root))
        with self.assertRaisesRegex(review.ReviewError, "exact current plan"):
            self.validate()

    def test_missing_unknown_or_foreign_review_never_passes(self):
        for fault in ("missing", "foreign-workflow", "missing-subject", "wrong-kind"):
            with self.subTest(fault=fault):
                self.write_review()
                if fault == "missing":
                    self.report.unlink()
                elif fault == "foreign-workflow":
                    subject = copy.deepcopy(self.subject); subject["workflow_root_id"] = "other-workflow"
                    self.write_review(subject=subject)
                elif fault == "missing-subject":
                    self.report.write_text(self.report.read_text().replace("subject:", "unknown_subject:"))
                else:
                    self.report.write_text(self.report.read_text().replace("kind: review", "kind: gap-analysis"))
                with self.assertRaises(review.ERRORS):
                    self.validate()

    def test_blocked_plan_and_foreign_plan_cannot_be_reviewed_as_current(self):
        for args in ({"status": "blocked"}, {"workflow": "other-workflow"}):
            with self.subTest(args=args):
                self.plan.write_text(plan_text(self.root, **args))
                with self.assertRaises(review.ReviewError):
                    self.validate()

    def test_repaired_plan_requires_a_genuine_new_passing_review(self):
        self.write_review(blocked=True)
        self.plan.write_text(self.plan.read_text() + "\nExact task procedures and verification are now present.\n")
        with self.assertRaises(review.ReviewError):
            self.validate()
        current = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_review(subject=current)
        self.assertEqual(self.validate(), current)

    def test_native_current_requirements_cannot_be_omitted_from_trace(self):
        another = self.root / "new-requirements.md"; another.write_text("Current native requirement.\n")
        self.native_root["metadata"]["gc.build.requirements_path"] = str(another)
        with self.assertRaisesRegex(review.ReviewError, "omits a current native-recorded upstream"):
            self.validate()

    def test_no_ambient_cwd_fallback_for_relative_paths(self):
        self.native_root["metadata"]["gc.build.plan_path"] = "plan.md"
        self.native_root["metadata"]["gc.build.plan_review_report_path"] = "review.md"
        self.assertEqual(self.validate(), self.subject)
        with self.assertRaises(review.ERRORS):
            review.validate_recorded_review(self.native_root, artifact_root=self.root / "other")

    def test_native_gate_reads_exact_root_and_refuses_blocked_report(self):
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(self.root)}), \
             patch.object(review, "show", side_effect=[step, self.native_root]), redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 0)
        self.write_review(blocked=True)
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(self.root)}), \
             patch.object(review, "show", side_effect=[step, self.native_root]), redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 1)

    def test_native_gate_uses_recorded_artifact_root_instead_of_rig_root(self):
        rig_root = self.root / "rig"
        rig_root.mkdir()
        root = relative_native_fixture(self.root / "artifacts", str(self.root / "artifacts"))
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(rig_root)}), \
             patch.object(review, "show", side_effect=[step, root]), redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 0)

    def test_explicit_artifact_root_does_not_require_an_environment_rig_root(self):
        root = relative_native_fixture(self.root / "artifacts", str(self.root / "artifacts"))
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1"}, clear=True), \
             patch.object(review, "durable_root", side_effect=AssertionError("unexpected fallback")), \
             patch.object(review, "show", side_effect=[step, root]), redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 0)

    def test_declared_missing_artifact_root_does_not_fall_back_to_rig_root(self):
        rig_root = self.root / "rig"
        root = relative_native_fixture(rig_root, str(self.root / "missing"))
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(rig_root)}), \
             patch.object(review, "show", side_effect=[step, root]), redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 1)

    def test_malformed_declared_artifact_root_is_rejected(self):
        rig_root = self.root / "rig"
        root = relative_native_fixture(rig_root, False)
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(rig_root)}), \
             patch.object(review, "show", side_effect=[step, root]), redirect_stderr(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 1)

    def test_recorded_relative_artifact_root_matches_existing_setup_resolution(self):
        rig_root = self.root / "rig"
        rig_root.mkdir()
        configured = self.root / "configured-artifacts"
        configured.mkdir()
        previous_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            resolved = review.recorded_artifact_root(
                {"gc.var.artifact_root": "configured-artifacts"}, rig_root=rig_root)
            self.assertEqual(resolved, configured.resolve())
        finally:
            os.chdir(previous_cwd)

    def test_empty_recorded_artifact_root_uses_the_existing_rig_default(self):
        rig_root = self.root / "rig"
        root = relative_native_fixture(rig_root / "plans", "")
        step = {"id": "review-1", "metadata": {"gc.root_bead_id": "workflow-1"}}
        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(rig_root)}), \
             patch.object(review, "show", side_effect=[step, root]), redirect_stdout(io.StringIO()):
            self.assertEqual(review.main(["native-check"]), 0)

    def test_creator_review_uses_recorded_artifact_root_in_both_call_paths(self):
        # An explicit artifact root must not depend on an old rig path still existing.
        rig_root = self.root / "missing-rig"
        root = relative_native_fixture(self.root / "artifacts", str(self.root / "artifacts"))
        step = {"id": "review-1", "issue_type": "task", "metadata": {
            "gc.root_bead_id": "workflow-1", review.REQUIRED_KEY: "true"}}

        def bd_output(args):
            if args[1:4] == ["show", "review-1", "--json"]:
                return [step]
            if args[1:3] == ["list", "--metadata-field"]:
                return [step]
            if args[1:3] == ["show", "workflow-1"]:
                return [root]
            raise AssertionError(args)

        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, json.dumps(bd_output(args)), "")

        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1", "GC_RIG_ROOT": str(rig_root)}), \
             patch.object(review.subprocess, "run", side_effect=run):
            review.check_creator_review(None, bd_command=["bd"])

        workspace = {
            "writer_map": SimpleNamespace(declaration={"steps": [{"bead_id": "review-1"}]}),
            "writer_rows": {"review-1": step, "workflow-1": root},
            "attempt": type("Attempt", (), {"claimed_bead_id": "review-1"})(),
            "state": {"run": {"rig_root": str(rig_root)}},
        }
        review.check_creator_review(workspace, bd_command=["bd"])

    def test_creator_review_refuses_workflow_root_without_metadata_before_allocation(self):
        step = {"id": "review-1", "issue_type": "task", "metadata": {
            "gc.root_bead_id": "workflow-1", review.REQUIRED_KEY: "true"}}
        root = {"id": "workflow-1", "metadata": None}

        def bd_output(args):
            if args[1:4] == ["show", "review-1", "--json"]:
                return [step]
            if args[1:3] == ["list", "--metadata-field"]:
                return [step]
            if args[1:3] == ["show", "workflow-1"]:
                return [root]
            raise AssertionError(args)

        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, json.dumps(bd_output(args)), "")

        with patch.dict(os.environ, {"GC_BEAD_ID": "review-1"}), \
             patch.object(review.subprocess, "run", side_effect=run) as run_bd:
            with self.assertRaisesRegex(review.ReviewError, "native workflow metadata is missing"):
                review.check_creator_review(None, bd_command=["bd"])
        self.assertEqual(run_bd.call_count, 3)

    def test_git_upstream_requires_immutable_revision_and_exact_current_file(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                  text=True, check=True).stdout.strip()
        git("init", "-b", "main"); git("add", "requirements.md")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Requirements")
        commit = git("rev-parse", "HEAD")
        self.plan.write_text(plan_text(self.root, upstream_hash="git:" + commit))
        subject = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_review(subject=subject)
        self.assertEqual(self.validate(), subject)
        (self.root / "requirements.md").write_text("Uncommitted changed requirement.\n")
        with self.assertRaisesRegex(review.ReviewError, "differs from its Git revision"):
            self.validate()
        self.plan.write_text(plan_text(self.root, upstream_hash="git:HEAD"))
        with self.assertRaisesRegex(review.ReviewError, "full immutable commit"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
