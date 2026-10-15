"""Exercise the executable subject guard shipped to the native repair author."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import test_plan_review_acceptance as acceptance


PACK = Path(__file__).resolve().parents[1]
SCRIPTS = PACK / "assets" / "scripts"
PROMPT = PACK / "assets" / "workflows" / "planning-base" / "repair-plan-review.md"


class PlanReviewRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="plan-repair-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.requirements = self.root / "requirements.md"
        self.requirements.write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
        self.plan = self.root / "plan.md"
        self.plan.write_text(acceptance.plan_text(self.root))
        self.report = self.root / "review.md"
        self.subject = acceptance.review.current_subject(
            self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_report()

    def write_report(self, *, subject=None, verdict="fail"):
        data = {"schema": "gc.verdict-report.v1", "kind": "review", "verdict": verdict,
                "severity": "blocker" if verdict == "fail" else "none",
                "subject": self.subject if subject is None else subject,
                "findings": [{"id": "PLAN-1", "severity": "blocker",
                              "title": "Missing exact procedure",
                              "evidence": "The plan omits a required command argument.",
                              "required_fix": "Name the actual command and its stage."}]
                            if verdict == "fail" else []}
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n# Plan review\nActual current plan findings.\n")

    def guard(self, *, root="workflow-1"):
        text = PROMPT.read_text()
        self.assertEqual(text.count("<<'PY'\n"), 1)
        script = text.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
        before = {path: path.read_bytes() for path in (self.requirements, self.plan, self.report)}
        result = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPTS),
                                 str(self.plan), str(self.report), root, str(self.root),
                                 str(self.requirements)], capture_output=True, text=True, check=False)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        return result

    def test_current_blocked_subject_is_eligible_but_does_not_approve(self):
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        observed = json.loads(result.stdout)
        self.assertEqual(observed, {"subject": self.subject,
            "report_sha256": hashlib.sha256(self.report.read_bytes()).hexdigest()})
        with self.assertRaisesRegex(acceptance.review.ReviewError, "unresolved findings"):
            acceptance.review.validate_review(self.plan, self.report,
                workflow_root_id="workflow-1", artifact_root=self.root)

    def test_stale_foreign_or_approved_report_cannot_authorize_repair(self):
        initial_plan = self.plan.read_bytes()
        initial_requirements = self.requirements.read_bytes()
        for fault in ("changed-plan", "changed-upstream", "foreign-report", "foreign-root", "approved"):
            with self.subTest(fault=fault):
                self.plan.write_bytes(initial_plan)
                self.requirements.write_bytes(initial_requirements)
                self.write_report()
                root = "workflow-1"
                if fault == "changed-plan":
                    self.plan.write_text(self.plan.read_text() + "\nNew procedure.\n")
                elif fault == "changed-upstream":
                    self.requirements.write_text("Changed requirements.\n")
                elif fault == "foreign-report":
                    subject = copy.deepcopy(self.subject)
                    subject["workflow_root_id"] = "other-workflow"
                    self.write_report(subject=subject)
                elif fault == "foreign-root":
                    root = "other-workflow"
                else:
                    self.write_report(verdict="pass")
                result = self.guard(root=root)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_report_and_repaired_plan_need_a_fresh_independent_verdict(self):
        self.assertEqual(self.guard().returncode, 0)
        self.plan.write_text(self.plan.read_text() + "\nExact commands and stages are now specified.\n")
        self.assertNotEqual(self.guard().returncode, 0)
        subject = acceptance.review.current_subject(self.plan, workflow_root_id="workflow-1",
                                                    artifact_root=self.root)
        self.write_report(subject=subject, verdict="pass")
        self.assertEqual(acceptance.review.validate_review(self.plan, self.report,
            workflow_root_id="workflow-1", artifact_root=self.root), subject)
        self.assertNotEqual(self.guard().returncode, 0)


if __name__ == "__main__":
    unittest.main()
