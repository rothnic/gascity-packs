from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gascity" / "tests"))
import test_formula_assets as formulas
from test_plan_review_acceptance import plan_text
import validate_plan_review as review


METHODS = (
    ("compound-engineering", "compound", "compound-engineering.ce-plan-review-synthesizer"),
    ("superpowers", "superpowers", "superpowers.plan-reviewer"),
    ("bmad", "bmad", "bmad.architect"),
    ("gstack", "gstack", "gstack.review-synthesizer"),
)
CHECK = {"max_attempts": 3, "check": {
    "mode": "exec", "path": "../assets/scripts/checks/plan-review-approved.py", "timeout": "5m"}}


def gate_for(pack: str, prefix: str, entry: str = "build") -> dict:
    directories = [ROOT / "gascity" / "formulas", ROOT / pack / "formulas"]
    resolved = formulas.resolve_formula_from_dirs(directories, f"{prefix}-{entry}")
    step = next(step for step in resolved["steps"] if step["id"] == "plan-review")
    if "expand" not in step:
        return step
    expansion = formulas.load_formula_from_dirs(directories, step["expand"])
    return next(node for node in expansion["template"] if node["id"] == "{target}")


class SpecializedPlanReviewAcceptanceTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="specialized plan review ", dir=os.environ.get("TMPDIR"))
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        (self.root / "requirements.md").write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
        self.plan = self.root / "plan.md"
        self.report = self.root / "review.md"
        self.rows_path = self.root / "native-rows.json"
        self.calls_path = self.root / "native-reads.jsonl"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        gc = self.bin / "gc"
        gc.write_text(f"#!{sys.executable}\n" + "\n".join([
            "import json, os, pathlib, sys",
            "args = sys.argv[1:]",
            "rows = json.loads(pathlib.Path(os.environ['REVIEW_TEST_ROWS']).read_text())",
            "if len(args) != 4 or args[0] != 'bd' or args[1] != 'show' or args[3] != '--json' or args[2] not in rows:",
            "    raise SystemExit('unexpected native command: ' + repr(args))",
            "with open(os.environ['REVIEW_TEST_CALLS'], 'a') as output:",
            "    output.write(json.dumps(args) + '\\n')",
            "print(json.dumps([rows[args[2]]]))",
            "",
        ]))
        gc.chmod(0o755)

    def test_compound_synthesizer_uses_and_validates_verdict_severity_contract(self):
        contract = (ROOT / "gascity" / "docs" / "plan-review-acceptance.md").read_text()
        contract_text = " ".join(contract.split())
        prompt = (ROOT / "compound-engineering" / "assets" / "workflows" /
                  "compound-plan-review" / "{target}.synthesize-plan-review.md").read_text()
        self.assertIn("`minor`, `major`, or `blocker`", contract_text)
        self.assertIn("`none`, `minor`, `major`, or `blocker`", contract_text)
        self.assertIn("highest finding severity", contract_text)
        self.assertIn("finding severities `minor`, `major`, or `blocker`", prompt)
        self.assertIn("report severities\n`none`, `minor`, `major`, or `blocker`", prompt)
        self.assertIn("highest finding severity", prompt)
        self.assertIn("validate_verdict_report.py <report-path> --kind review", prompt)

        validator = ROOT / "gascity" / "assets" / "scripts" / "validate_verdict_report.py"
        report = self.root / "synthesized-review.md"
        invalid_reports = (
            ("medium", "major", "severity must be one of"),
            ("major", "blocker", "maximum finding severity"),
        )
        for report_severity, finding_severity, error in invalid_reports:
            with self.subTest(report_severity=report_severity, finding_severity=finding_severity):
                report.write_text(
                    "---\n"
                    "schema: gc.verdict-report.v1\n"
                    "kind: review\n"
                    "verdict: fail\n"
                    f"severity: {report_severity}\n"
                    "findings:\n"
                    "  - id: PLAN-1\n"
                    f"    severity: {finding_severity}\n"
                    "    title: Required plan change\n"
                    "    evidence: The plan omits a required procedure.\n"
                    "    required_fix: Add and review the procedure.\n"
                    "---\n",
                    encoding="utf-8",
                )
                result = subprocess.run(
                    [sys.executable, str(validator), str(report), "--kind", "review"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(error, result.stderr)

    def test_compound_apply_keeps_author_and_review_statuses_coherent(self):
        prompt = (ROOT / "compound-engineering" / "assets" / "workflows" /
                  "compound-plan-review" / "{target}.apply-plan-findings.md").read_text()
        prompt_text = " ".join(prompt.split())
        self.assertIn("workflow root from the current native claim's `gc.root_bead_id`", prompt_text)
        self.assertIn("write both `gc.build.*` status fields to that root bead, not to this claimed apply child", prompt_text)
        self.assertIn("front-matter `status: approved` and `gc.build.plan_status=approved`", prompt_text)
        self.assertIn("`gc.build.plan_review_status=draft`", prompt_text)
        self.assertIn("leave the already-approved `gc.build.plan_status` aligned with the plan's approved front matter", prompt_text)
        self.assertNotIn("Only then set `gc.build.plan_status=approved`", prompt_text)
        self.assertIn("`design_review.verdict=iterate`", prompt_text)
        self.assertIn("front-matter status and `gc.build.plan_status` at `draft`", prompt_text)
        self.assertIn("report-only mode or missing repair authority prevents an edit", prompt_text)
        self.assertIn("Do not reset an approved, unchanged plan to `draft`", prompt_text)
        self.assertIn("`validate_plan_review.py native-check` succeeds", prompt_text)

        self.prepare("compound-engineering", "compound")
        self.plan.write_text(self.plan_text("compound-engineering", "compound", status="draft"))
        refused_draft = self.run_gate("compound-engineering", "compound")
        self.assertEqual(refused_draft.returncode, 1, refused_draft.stdout + refused_draft.stderr)

        # Completing the author repair makes the plan ready, but the previous
        # report still cannot approve the changed subject.
        self.plan.write_text(self.plan_text("compound-engineering", "compound")
                             + "\nThe required procedure is now complete.\n")
        refused_stale_subject = self.run_gate("compound-engineering", "compound")
        self.assertEqual(refused_stale_subject.returncode, 1,
                         refused_stale_subject.stdout + refused_stale_subject.stderr)

        current = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_report(subject=current)
        accepted_current_subject = self.run_gate("compound-engineering", "compound")
        self.assertEqual(accepted_current_subject.returncode, 0,
                         accepted_current_subject.stdout + accepted_current_subject.stderr)
        self.assertEqual(json.loads(accepted_current_subject.stdout), current)

    def test_compound_review_subject_excludes_supplemental_citations(self):
        workflow_dir = (ROOT / "compound-engineering" / "assets" / "workflows" /
                        "compound-plan-review")
        canonical_rule = ("The canonical review subject is the workflow root plus the current plan and "
                          "exact `plan.trace.upstream` paths and hashes.")
        supplementary_rule = ("those citations are not part of the canonical subject and need not "
                              "match across personas")
        for lane in ("coherence-review", "feasibility-review", "scope-review", "architecture-review"):
            prompt = (workflow_dir / f"{{target}}.{lane}.md").read_text()
            prompt_text = " ".join(prompt.split())
            self.assertIn(canonical_rule, prompt_text)
            self.assertIn(supplementary_rule, prompt_text)
        synthesizer = (workflow_dir / "{target}.synthesize-plan-review.md").read_text()
        synth_text = " ".join(synthesizer.split())
        self.assertIn("canonical subject returned by the imported `validate_plan_review.py subject` command", synth_text)
        self.assertIn("exactly the current `plan.trace.upstream` paths and hashes", synth_text)
        self.assertIn("those citations may differ across lanes", synth_text)

        self.prepare("compound-engineering", "compound")
        citations = []
        for lane in ("coherence", "feasibility", "scope", "architecture"):
            cited = self.root / f"{lane}-support.md"
            contents = f"Current supplementary evidence for the {lane} lane.\n"
            cited.write_text(contents, encoding="utf-8")
            digest = hashlib.sha256(contents.encode()).hexdigest()
            citations.append(f"{lane}: {cited.resolve()} sha256={digest}")
        self.report.write_text(
            self.report.read_text(encoding="utf-8")
            + "\nSupplementary references cited by the four lanes:\n"
            + "\n".join(citations) + "\n",
            encoding="utf-8",
        )
        for citation, lane in zip(citations, ("coherence", "feasibility", "scope", "architecture")):
            cited = self.root / f"{lane}-support.md"
            self.assertTrue(cited.is_file())
            self.assertIn(hashlib.sha256(cited.read_bytes()).hexdigest(), citation)
        accepted = self.run_gate("compound-engineering", "compound")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        self.assertEqual(json.loads(accepted.stdout), self.subject)

        # A different canonical upstream path remains a refusal even when it is
        # one of the valid, current files cited as supplementary evidence.
        different_subject = copy.deepcopy(self.subject)
        different_subject["upstream"][0]["path"] = str(self.root / "coherence-support.md")
        self.write_report(subject=different_subject)
        refused_changed_subject = self.run_gate("compound-engineering", "compound")
        self.assertEqual(refused_changed_subject.returncode, 1,
                         refused_changed_subject.stdout + refused_changed_subject.stderr)

    def plan_text(self, pack: str, prefix: str, **kwargs) -> str:
        # Reuse the production-schema fixture used by the shared helper tests.
        return (plan_text(self.root, **kwargs).replace("build-basic", f"{prefix}-build")
                .replace("pack: gascity", f"pack: {pack}"))

    def prepare(self, pack: str, prefix: str):
        (self.root / "requirements.md").write_text("# Requirements\nREQ-1: implement the requested behavior.\n")
        self.plan.write_text(self.plan_text(pack, prefix))
        self.subject = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
        self.write_report()
        self.rows_path.write_text(json.dumps({
            "plan-review-1": {"id": "plan-review-1", "metadata": {"gc.root_bead_id": "workflow-1"}},
            "workflow-1": {"id": "workflow-1", "metadata": {
                "gc.build.plan_path": "plan.md", "gc.build.requirements_path": "requirements.md",
                "gc.build.plan_review_report_path": "review.md"}},
        }))
        self.calls_path.unlink(missing_ok=True)

    def write_report(self, *, blocked: bool = False, subject: dict | None = None):
        data = {"schema": "gc.verdict-report.v1", "kind": "review",
                "verdict": "fail" if blocked else "pass", "severity": "blocker" if blocked else "none",
                "findings": [{"id": "PLAN-1", "severity": "blocker", "title": "Required plan repair",
                              "evidence": "The current plan omits a required verification procedure.",
                              "required_fix": "Repair the procedure and review its new subject."}] if blocked else [],
                "subject": self.subject if subject is None else subject}
        self.report.write_text("---\n" + review.build.yaml.safe_dump(data, sort_keys=False)
                               + "---\n# Methodology plan review\nReview of the recorded current artifacts.\n")

    def run_gate(self, pack: str, prefix: str) -> subprocess.CompletedProcess:
        # Native ../assets resolution searches the imported Gas City layer.
        # Execute that actual shipped wrapper; only its native row transport is a fixture.
        gate = gate_for(pack, prefix)
        script = (ROOT / "gascity" / "formulas" / gate["check"]["check"]["path"]).resolve()
        environment = {**os.environ, "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                       "GC_BEAD_ID": "plan-review-1", "GC_RIG_ROOT": str(self.root),
                       "REVIEW_TEST_ROWS": str(self.rows_path), "REVIEW_TEST_CALLS": str(self.calls_path)}
        return subprocess.run([sys.executable, str(script)], cwd=self.bin, env=environment,
                              text=True, capture_output=True, timeout=15)

    def test_build_and_planning_overrides_retain_required_subject_gate(self):
        for pack, prefix, target in METHODS:
            for entry in ("build", "planning"):
                with self.subTest(pack=pack, entry=entry):
                    directories = [ROOT / "gascity" / "formulas", ROOT / pack / "formulas"]
                    resolved = formulas.resolve_formula_from_dirs(directories, f"{prefix}-{entry}")
                    steps = {step["id"]: step for step in resolved["steps"]}
                    self.assertEqual(steps["plan-review"]["metadata"][review.REQUIRED_KEY], "true")
                    self.assertEqual(steps["plan-review"]["metadata"]["gc.run_target"], target)
                    self.assertEqual(steps["plan-review"]["needs"], ["plan"])
                    if entry == "build":
                        self.assertIn("plan-review", steps["decompose"]["needs"])
                    gate = gate_for(pack, prefix, entry)
                    self.assertEqual(gate["metadata"][review.REQUIRED_KEY], "true")
                    self.assertEqual(gate["check"], CHECK)
                    script = (ROOT / "gascity" / "formulas" / CHECK["check"]["path"]).resolve()
                    self.assertTrue(os.access(script, os.X_OK))
                    self.assertIn("validate_plan_review", script.read_text())

    def test_expansions_keep_existing_reviewers_and_repair_owners(self):
        expected = {
            "compound-engineering": ({"compound-engineering.ce-coherence-reviewer",
                "compound-engineering.ce-feasibility-reviewer", "compound-engineering.ce-scope-guardian-reviewer",
                "compound-engineering.ce-architecture-strategist", "compound-engineering.ce-plan-review-synthesizer"},
                "compound-engineering.ce-plan"),
            "superpowers": ({"superpowers.plan-reviewer"}, "superpowers.writing-plans"),
            "gstack": ({"gstack.founder-reviewer", "gstack.design-reviewer", "gstack.eng-reviewer",
                "gstack.devex-reviewer", "gstack.review-synthesizer"}, "gstack.founder-reviewer"),
        }
        for pack, prefix, _ in METHODS:
            if pack == "bmad":
                continue
            with self.subTest(pack=pack):
                expansion = formulas.load_formula(ROOT / pack, f"{prefix}-plan-review")
                loop = next(node for node in expansion["template"] if node.get("children"))
                check_path = ("../assets/scripts/checks/design-review-approved.sh" if pack == "superpowers"
                              else ".gc/scripts/checks/design-review-approved.sh")
                self.assertEqual(loop["check"], {"max_attempts": 6, "check": {
                    "mode": "exec", "path": check_path, "timeout": "10m"}})
                children = loop["children"]
                apply = next(node for node in children if ".apply-plan-" in node["id"])
                self.assertEqual(apply["metadata"]["gc.run_target"], expected[pack][1])
                self.assertEqual({node["metadata"]["gc.run_target"] for node in children if node is not apply},
                                 expected[pack][0])
                self.assertEqual(gate_for(pack, prefix)["needs"], [loop["id"]])

    def test_bmad_handoff_gate_precedes_stories_and_separate_readiness(self):
        resolved = formulas.resolve_formula_from_dirs(
            [ROOT / "gascity" / "formulas", ROOT / "bmad" / "formulas"], "bmad-build")
        steps = {step["id"]: step for step in resolved["steps"]}
        self.assertEqual(steps["plan-review"]["check"], CHECK)
        self.assertEqual(steps["decompose"]["needs"], ["plan-review"])
        self.assertEqual(steps["implementation-readiness"]["needs"], ["decompose"])
        self.assertEqual(steps["implementation-readiness"]["metadata"]["gc.run_target"], "bmad.readiness-reviewer")
        for item in ("implement", "implement-same-session"):
            self.assertEqual(steps[item]["needs"], ["implementation-readiness"])

    def test_each_method_executes_current_subject_gate_from_native_paths(self):
        for pack, prefix, _ in METHODS:
            with self.subTest(pack=pack):
                self.prepare(pack, prefix)
                result = self.run_gate(pack, prefix)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout), self.subject)
                calls = [json.loads(line) for line in self.calls_path.read_text().splitlines()]
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0], ["bd", "show", "plan-review-1", "--json"])
                self.assertEqual(calls[1], ["bd", "show", "workflow-1", "--json"])

    def test_required_findings_block_every_method_despite_approved_plan(self):
        for pack, prefix, _ in METHODS:
            with self.subTest(pack=pack):
                self.prepare(pack, prefix)
                self.write_report(blocked=True)
                result = self.run_gate(pack, prefix)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("unresolved findings", result.stderr)

    def test_changed_plan_or_upstream_cannot_reuse_method_approval(self):
        for pack, prefix, _ in METHODS:
            for fault in ("plan", "upstream", "updated-trace"):
                with self.subTest(pack=pack, fault=fault):
                    self.prepare(pack, prefix)
                    if fault == "plan":
                        self.plan.write_text(self.plan.read_text() + "\nA changed implementation procedure.\n")
                    else:
                        (self.root / "requirements.md").write_text("REQ-1: changed required behavior.\n")
                        if fault == "updated-trace":
                            self.plan.write_text(self.plan_text(pack, prefix))
                    result = self.run_gate(pack, prefix)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("upstream hash is stale" if fault == "upstream" else "exact current plan", result.stderr)

    def test_foreign_missing_or_unapproved_subject_never_passes(self):
        for pack, prefix, _ in METHODS:
            for fault in ("foreign-workflow", "foreign-plan", "missing-report", "draft-plan",
                          "wrong-schema", "wrong-kind", "missing-subject"):
                with self.subTest(pack=pack, fault=fault):
                    self.prepare(pack, prefix)
                    if fault == "missing-report":
                        self.report.unlink()
                    elif fault == "draft-plan":
                        self.plan.write_text(self.plan_text(pack, prefix, status="draft"))
                    elif fault == "wrong-schema":
                        self.report.write_text(self.report.read_text().replace(
                            "schema: gc.verdict-report.v1", "schema: unknown-review.v1"))
                    elif fault == "wrong-kind":
                        self.report.write_text(self.report.read_text().replace("kind: review", "kind: gap-analysis"))
                    elif fault == "missing-subject":
                        self.report.write_text(self.report.read_text().replace("subject:", "unbound_subject:"))
                    else:
                        subject = copy.deepcopy(self.subject)
                        if fault == "foreign-workflow":
                            subject["workflow_root_id"] = "another-workflow"
                        else:
                            subject["plan"]["path"] = str(self.root / "another-plan.md")
                        self.write_report(subject=subject)
                    result = self.run_gate(pack, prefix)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_repaired_method_plan_requires_new_review_before_acceptance(self):
        for pack, prefix, _ in METHODS:
            with self.subTest(pack=pack):
                self.prepare(pack, prefix)
                self.write_report(blocked=True)
                self.plan.write_text(self.plan.read_text() + "\nThe required verification procedure is now explicit.\n")
                result = self.run_gate(pack, prefix)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                current = review.current_subject(self.plan, workflow_root_id="workflow-1", artifact_root=self.root)
                self.write_report(subject=current)
                result = self.run_gate(pack, prefix)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout), current)


if __name__ == "__main__":
    unittest.main()
