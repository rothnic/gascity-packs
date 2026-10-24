"""Exercise the executable subject guard shipped to the native repair author."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_plan_review_acceptance as acceptance


PACK = Path(__file__).resolve().parents[1]
REPAIR_PROMPT = PACK / "assets" / "workflows" / "planning-base" / "repair-plan-review.md"
REVIEW_PROMPTS = (
    PACK / "assets" / "workflows" / "build-basic" / "plan-review.md",
    PACK / "assets" / "workflows" / "planning-base" / "plan-review.md",
    PACK / "assets" / "workflows" / "build-base" / "plan-review.md",
    PACK / "assets" / "workflows" / "build-from-plan-base" / "plan-review.md",
)


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
                "repair_subject": self.repair_subject(),
                "findings": [{"id": "PLAN-1", "severity": "blocker",
                              "title": "Missing exact procedure",
                              "evidence": "The plan omits a required command argument.",
                              "required_fix": "Name the actual command and its stage."}]
                            if verdict == "fail" else []}
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n# Plan review\nActual current plan findings.\n")

    def repair_subject(self):
        return {"workflow_root_id": "workflow-1",
                "plan": {"path": str(self.plan),
                         "sha256": hashlib.sha256(self.plan.read_bytes()).hexdigest()},
                "required_upstream": [{"path": str(self.requirements),
                    "sha256": hashlib.sha256(self.requirements.read_bytes()).hexdigest()}],
                "reviewer": {"bead_id": "review-1", "attempt": 1}}

    def current_repair_subject(self, *, reviewer="review-2", attempt=2):
        subject = self.repair_subject()
        subject["reviewer"] = {"bead_id": reviewer, "attempt": attempt}
        return subject

    def native_rows(self, *, root="workflow-1"):
        def child(bead_id, step, attempt, status):
            metadata = {
                "gc.root_bead_id": root, "gc.ralph_step_id": "plan-review", "gc.kind": "task",
                "gc.step_id": step, "gc.attempt": attempt}
            if status == "closed":
                metadata["gc.outcome"] = "fail"
            return {"id": bead_id, "status": status, "issue_type": "task", "metadata": metadata}
        rows = {root: {"id": root, "metadata": {"gc.build.plan_path": self.plan.name,
                    "gc.build.requirements_path": self.requirements.name,
                    "gc.build.plan_review_report_path": self.report.name}},
                "author-2": child("author-2", "author-repair", "2", "in_progress"),
                "review-1": child("review-1", "plan-review-verdict", "1", "closed"),
                "review-2": child("review-2", "plan-review-verdict", "2", "in_progress")}
        # First cooked reviewers are plain task rows; later attempts stamp gc.kind.
        del rows["review-1"]["metadata"]["gc.kind"]
        return rows

    def native(self, mode, *, rows=None, claim="author-2", report_sha256=None, rig_root=None):
        rows = self.native_rows() if rows is None else rows
        output, error = io.StringIO(), io.StringIO()
        argv = [mode]
        if mode == "native-repair-check":
            argv += ["--report-sha256", report_sha256 or hashlib.sha256(self.report.read_bytes()).hexdigest()]
        elif mode == "native-review-report-check":
            argv += ["--report", str(self.report), "--report-sha256",
                     report_sha256 or hashlib.sha256(self.report.read_bytes()).hexdigest()]
        with patch.object(acceptance.review, "show", side_effect=lambda key: rows[key]), \
             patch.dict(os.environ, GC_BEAD_ID=claim, GC_RIG_ROOT=str(rig_root or self.root)), \
             redirect_stdout(output), redirect_stderr(error):
            rc = acceptance.review.main(argv)
        return subprocess.CompletedProcess(argv, rc, output.getvalue(), error.getvalue())

    def test_plan_review_prompts_require_current_repair_identity_for_every_block(self):
        for prompt in REVIEW_PROMPTS:
            with self.subTest(prompt=prompt.name):
                text = prompt.read_text()
                self.assertIn("native-review-report-check", text)
                self.assertIn("native-repair-subject", text)
                self.assertIn("every blocked review", text.lower())
                self.assertIn("gc.failure_reason", text)

    def test_native_repair_uses_recorded_artifact_root_instead_of_rig_root(self):
        rig_root = self.root / "rig"
        rig_root.mkdir()
        rows = self.native_rows()
        rows["workflow-1"]["metadata"]["gc.var.artifact_root"] = str(self.root)
        result = self.native("native-repair-check", rows=rows, rig_root=rig_root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def guard(self, *, root="workflow-1", rows=None, report_sha256=None):
        self.assertIn('native-repair-check --report-sha256 "$REPORT_SHA256"', REPAIR_PROMPT.read_text())
        before = {path: path.read_bytes() for path in (self.requirements, self.plan, self.report)}
        result = self.native("native-repair-check", rows=rows or self.native_rows(root=root),
                             report_sha256=report_sha256)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        return result

    def test_current_blocked_subject_is_eligible_but_does_not_approve(self):
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed, {"repair_subject": self.repair_subject(),
            "report": {"path": str(self.report),
                       "sha256": hashlib.sha256(self.report.read_bytes()).hexdigest()},
            "author_bead_id": "author-2", "author_attempt": 2})
        with self.assertRaisesRegex(acceptance.review.ReviewError, "unresolved findings"):
            acceptance.review.validate_review(self.plan, self.report,
                workflow_root_id="workflow-1", artifact_root=self.root)

    def test_native_review_report_check_rejects_blocked_report_missing_repair_identity(self):
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        del data["repair_subject"]
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        result = self.native("native-review-report-check", claim="review-2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("repair subject", result.stderr.lower())

    def test_native_review_report_check_accepts_complete_fail_without_approval(self):
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        data["repair_subject"] = self.current_repair_subject()
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        result = self.native("native-review-report-check", claim="review-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["review_verdict"], "fail")
        self.assertFalse(observed["approval"])
        self.assertEqual(observed["repair_subject"], self.current_repair_subject())

    def test_native_review_report_check_allows_blocked_malformed_trace_without_fake_subject(self):
        self.plan.write_text(self.plan.read_text().replace(
            str(self.requirements), "missing-requirements.md"))
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        data.pop("subject")
        data["repair_subject"] = self.current_repair_subject()
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        result = self.native("native-review-report-check", claim="review-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["review_verdict"], "fail")
        self.assertFalse(observed["approval"])

    def test_native_repair_subject_refuses_malformed_plan_without_editing_inputs(self):
        self.write_report()
        self.plan.write_text("---\nschema: gc.build.other.v1\nworkflow: {}\n---\nNot a plan.\n")
        before = {path: path.read_bytes() for path in (self.plan, self.requirements, self.report)}
        checked = self.native("native-review-report-check", claim="review-2")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("repair plan", checked.stderr.lower())
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        result = self.native("native-repair-subject", claim="review-2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("repair plan", result.stderr.lower())
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_native_review_report_check_uses_the_hashed_report_text_if_path_changes(self):
        self.write_report(verdict="pass")
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        data.pop("repair_subject")
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        original = self.report.read_bytes()
        original_hash = hashlib.sha256(original).hexdigest()
        validate = acceptance.review.verdict.validate_report_text
        mutated = False

        def mutate_after_parse(text, *, expected_kind):
            nonlocal mutated
            report = validate(text, expected_kind=expected_kind)
            if not mutated:
                mutated = True
                self.report.write_text(text.replace("verdict: pass", "verdict: fail")
                                       .replace("severity: none", "severity: blocker"))
            return report

        with patch.object(acceptance.review.verdict, "validate_report_text",
                          side_effect=mutate_after_parse):
            result = self.native("native-review-report-check", claim="review-2",
                                 report_sha256=original_hash)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["review_verdict"], "pass")
        self.assertEqual(observed["report"]["sha256"], original_hash)
        self.assertNotEqual(self.report.read_bytes(), original)

    def test_native_review_report_check_refuses_stale_replayed_or_changed_identity(self):
        for fault in ("old-reviewer", "foreign-root", "changed-plan", "changed-requirements",
                      "changed-report", "boolean-attempt", "float-attempt"):
            with self.subTest(fault=fault):
                rows = None
                self.requirements.write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
                self.plan.write_text(acceptance.plan_text(self.root))
                self.subject = acceptance.review.current_subject(
                    self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
                self.write_report()
                _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
                data["repair_subject"] = self.current_repair_subject()
                if fault == "old-reviewer":
                    data["repair_subject"]["reviewer"] = {"bead_id": "review-1", "attempt": 1}
                elif fault == "foreign-root":
                    data["repair_subject"]["workflow_root_id"] = "other-workflow"
                elif fault in ("boolean-attempt", "float-attempt"):
                    rows = self.native_rows()
                    rows["review-2"]["metadata"]["gc.attempt"] = "1"
                    data["repair_subject"]["reviewer"]["attempt"] = (
                        True if fault == "boolean-attempt" else 1.0)
                self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                                       + "---\n" + body)
                read_hash = hashlib.sha256(self.report.read_bytes()).hexdigest()
                if fault == "changed-report":
                    self.report.write_text(self.report.read_text() + "\nChanged after read.\n")
                if fault == "changed-plan":
                    self.plan.write_text(self.plan.read_text() + "\nChanged after review.\n")
                if fault == "changed-requirements":
                    self.requirements.write_text(self.requirements.read_text() + "\nChanged after review.\n")
                result = self.native("native-review-report-check", rows=rows, claim="review-2",
                                     report_sha256=read_hash)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_native_review_report_check_keeps_pass_subject_validation(self):
        self.write_report(verdict="pass")
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        data.pop("repair_subject")
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        result = self.native("native-review-report-check", claim="review-2")
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["review_verdict"], "pass")
        self.assertEqual(observed["subject"], self.subject)
        self.assertEqual(observed["reviewer"], {"bead_id": "review-2", "attempt": 2})
        self.assertTrue(observed["complete"])
        self.assertFalse(observed["approval"])

    def test_malformed_upstream_can_be_repaired_without_approving(self):
        valid_plan = self.plan.read_text()
        self.plan.write_text(valid_plan.replace(str(self.requirements),
                                               "requirements.md at captured source base"))
        repair_subject = self.repair_subject()
        _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
        data.pop("subject")
        data["repair_subject"] = repair_subject
        self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n" + body)
        blocked_report = self.report.read_bytes()

        rows = self.native_rows()
        self.assertEqual(rows["review-1"]["issue_type"], "task")
        self.assertNotIn("gc.kind", rows["review-1"]["metadata"])
        rows["review-1"]["status"] = "in_progress"
        captured = self.native("native-repair-subject", rows=rows, claim="review-1")
        self.assertEqual(captured.returncode, 0, captured.stderr)
        self.assertEqual(json.loads(captured.stdout), repair_subject)

        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(acceptance.review.ReviewError, "unresolved findings"):
            acceptance.review.validate_review(self.plan, self.report,
                workflow_root_id="workflow-1", artifact_root=self.root)
        self.plan.write_text(valid_plan)
        self.assertNotEqual(self.guard().returncode, 0)
        self.assertEqual(self.report.read_bytes(), blocked_report)
        subject = acceptance.review.current_subject(self.plan, workflow_root_id="workflow-1",
                                                    artifact_root=self.root)
        self.write_report(subject=subject, verdict="pass")
        self.assertEqual(acceptance.review.validate_review(self.plan, self.report,
            workflow_root_id="workflow-1", artifact_root=self.root), subject)

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
                    text = self.report.read_text().replace("workflow-1", "other-workflow")
                    self.report.write_text(text)
                elif fault == "foreign-root":
                    root = "other-workflow"
                else:
                    self.write_report(verdict="pass")
                result = self.guard(root=root)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_report_replay_and_native_claim_mismatches_refuse_without_edits(self):
        for fault in ("old-attempt", "future-review", "review-open", "review-passed",
                      "wrong-child", "scope-check", "invalid-kind", "null-kind", "empty-kind",
                      "non-task", "missing-type", "foreign-review", "closed-author", "first-attempt"):
            with self.subTest(fault=fault):
                rows = self.native_rows()
                reviewer, author = rows["review-1"], rows["author-2"]
                if fault == "old-attempt":
                    author["metadata"]["gc.attempt"] = "3"
                elif fault == "future-review":
                    reviewer["metadata"]["gc.attempt"] = "2"
                elif fault == "review-open":
                    reviewer["status"] = "in_progress"
                elif fault == "review-passed":
                    reviewer["metadata"]["gc.outcome"] = "pass"
                elif fault == "wrong-child":
                    reviewer["metadata"]["gc.step_id"] = "author-repair"
                elif fault == "scope-check":
                    reviewer["metadata"]["gc.kind"] = "scope-check"
                elif fault == "invalid-kind":
                    reviewer["metadata"]["gc.kind"] = "unknown"
                elif fault == "null-kind":
                    reviewer["metadata"]["gc.kind"] = None
                elif fault == "empty-kind":
                    reviewer["metadata"]["gc.kind"] = ""
                elif fault == "non-task":
                    reviewer["issue_type"] = "feature"
                elif fault == "missing-type":
                    del reviewer["issue_type"]
                elif fault == "foreign-review":
                    reviewer["metadata"]["gc.root_bead_id"] = "other-workflow"
                elif fault == "closed-author":
                    author["status"] = "closed"
                else:
                    author["metadata"]["gc.attempt"] = "1"
                result = self.guard(rows=rows)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_native_report_path_and_read_hash_are_required(self):
        read_hash = hashlib.sha256(self.report.read_bytes()).hexdigest()
        self.report.write_text(self.report.read_text() + "\nChanged findings after the author read.\n")
        self.assertNotEqual(self.guard(report_sha256=read_hash).returncode, 0)
        rows = self.native_rows()
        rows["workflow-1"]["metadata"]["gc.build.plan_review_report_path"] = str(self.root / "missing.md")
        self.assertNotEqual(self.guard(rows=rows).returncode, 0)

    def test_wrong_repair_plan_requirements_or_report_identity_refuses(self):
        for fault in ("plan-path", "plan-hash", "requirements-hash", "missing-repair-subject",
                      "reviewer-id", "boolean-attempt"):
            with self.subTest(fault=fault):
                self.write_report()
                _, data, body = acceptance.review.build.parse_front_matter(self.report.read_text())
                subject = data["repair_subject"]
                if fault == "plan-path":
                    subject["plan"]["path"] = str(self.root / "another-plan.md")
                elif fault == "plan-hash":
                    subject["plan"]["sha256"] = "0" * 64
                elif fault == "requirements-hash":
                    subject["required_upstream"][0]["sha256"] = "0" * 64
                elif fault == "missing-repair-subject":
                    del data["repair_subject"]
                elif fault == "reviewer-id":
                    subject["reviewer"]["bead_id"] = "author-2"
                else:
                    subject["reviewer"]["attempt"] = True
                self.report.write_text("---\n" + acceptance.review.build.yaml.safe_dump(data, sort_keys=False)
                                      + "---\n" + body)
                self.assertNotEqual(self.guard().returncode, 0)

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
