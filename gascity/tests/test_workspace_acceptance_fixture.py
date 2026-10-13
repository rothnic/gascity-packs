"""Real Git and frozen behavioral oracles; no store, controller, or model worker."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PACK_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PACK_ROOT / "gascity/assets/scripts/workspace_acceptance_fixture.py"
FIXTURE = PACK_ROOT / "gascity/tests/fixtures/workspace-acceptance"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("workspace_acceptance_fixture", SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def case(report, name):
    return next(c for scenario in report["scenarios"] for c in scenario["cases"] if c["name"] == name)


class WorkspaceAcceptanceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="workspace-acceptance-")
        cls.root = Path(cls.temp.name)
        cls.report = harness.exercise(cls.root / "ordinary", "ordinary")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_independent_outputs_and_ordered_integration(self):
        topology = self.report["git"]
        base, outputs = topology["base_oid"], topology["outputs"]
        self.assertEqual(topology["inputs"]["A"], base)
        self.assertEqual(topology["inputs"]["B"], base)
        self.assertNotEqual(outputs["A"], outputs["B"])
        self.assertNotEqual(topology["workspaces"]["A"], topology["workspaces"]["B"])
        self.assertEqual(topology["integration_inputs"], [outputs["A"], outputs["B"]])
        for member in ("A", "B"):
            self.assertTrue(topology["integration_ancestry"][member])
        self.assertNotEqual(topology["default_oid_after_capture"], base)
        self.assertEqual(topology["inputs"]["C"], outputs["integration"])
        self.assertEqual(topology["inputs"]["D"], outputs["C"])
        repo = Path(topology["workspaces"]["integration"])
        for member in ("A", "B"):
            self.assertEqual(harness.git(repo, "rev-list", "-n", "1", "--parents", outputs[member]).split(),
                             [outputs[member], base])
        merge_b = harness.git(repo, "rev-list", "-n", "1", "--parents", outputs["integration"]).split()
        self.assertEqual(merge_b[2], outputs["B"])
        merge_a = harness.git(repo, "rev-list", "-n", "1", "--parents", merge_b[1]).split()
        self.assertEqual(merge_a[1:], [base, outputs["A"]])
        for member, parent in (("C", "integration"), ("D", "C")):
            self.assertEqual(harness.git(repo, "rev-list", "-n", "1", "--parents", outputs[member]).split(),
                             [outputs[member], outputs[parent]])

    def test_combined_c_and_d_preserve_all_requirements(self):
        for name in ("ordered-A-B-integration", "dependent-C", "shared-D"):
            probe = case(self.report, name)
            self.assertEqual(probe["status"], "pass", probe)
            self.assertEqual(probe["observed"]["status"], "pass")
        final = case(self.report, "shared-D")["observed"]
        self.assertEqual(len(final["checks"]), 9)
        self.assertEqual({c["status"] for c in final["checks"]}, {"pass"})

    def test_default_branch_bypass_fails_exact_input_and_behavior(self):
        probe = case(self.report, "default-branch-bypass")
        self.assertEqual(probe["status"], "pass", probe)
        self.assertEqual(probe["observed"]["status"], "fail")
        failed = {c["name"] for c in probe["observed"]["checks"] if c["status"] == "fail"}
        self.assertIn("exact-input-oid", failed)
        self.assertIn("A.quantity-subtotal", failed)
        self.assertIn("B.domestic-shipping", failed)

    def test_premature_readiness_fails_missing_shipping(self):
        probe = case(self.report, "premature-readiness")
        self.assertEqual(probe["status"], "pass", probe)
        observed = {c["name"]: c["status"] for c in probe["observed"]["checks"]}
        self.assertEqual(observed["A.quantity-subtotal"], "pass")
        self.assertEqual(observed["B.domestic-shipping"], "fail")
        self.assertEqual(observed["B.international-shipping"], "fail")

    def test_ancestry_valid_revert_fails_semantic_oracle(self):
        probe = case(self.report, "ancestry-valid-semantic-revert")
        self.assertEqual(probe["status"], "pass", probe)
        self.assertTrue(probe["prerequisite_is_ancestor"])
        observed = {c["name"]: c["status"] for c in probe["observed"]["checks"]}
        self.assertEqual(observed["A.quantity-subtotal"], "pass")
        self.assertEqual(observed["B.domestic-shipping"], "fail")
        self.assertEqual(observed["C.domestic-quote"], "fail")
        self.assertEqual(observed["D.domestic-receipt"], "fail")

    def test_stale_review_fails_even_when_behavior_passes(self):
        probe = case(self.report, "stale-review")
        self.assertEqual(probe["status"], "pass", probe)
        self.assertEqual(probe["observed"]["status"], "fail")
        observed = {c["name"]: c["status"] for c in probe["observed"]["checks"]}
        self.assertEqual(observed["exact-reviewed-oid"], "fail")
        behavior = [c for c in probe["observed"]["checks"] if c["name"] != "exact-reviewed-oid"]
        self.assertEqual(len(behavior), 9)
        self.assertEqual({c["status"] for c in behavior}, {"pass"})
        self.assertEqual(probe["observed"]["exit_code"], 0)
        self.assertEqual({name for name, status in observed.items() if status == "fail"}, {"exact-reviewed-oid"})
        self.assertNotEqual(probe["reviewed_oid"], probe["observed"]["subject_oid"])

    def test_broken_later_source_gets_no_stale_review_credit(self):
        real_check = harness.check_project

        def broken_fix(project, *args, **kwargs):
            if project.name == "fix":
                (project / "shipping.py").write_text("def shipping_cost(zone):\n    return 0\n")
                harness.git(project, "add", "shipping.py")
                harness.git(project, "commit", "-m", "Break shipping in the later fix")
            return real_check(project, *args, **kwargs)

        with patch.object(harness, "check_project", side_effect=broken_fix):
            report = harness.exercise(self.root / "broken-review")
        probe = case(report, "stale-review")
        self.assertEqual(probe["observed"]["exit_code"], 1)
        failed = {c["name"] for c in probe["observed"]["checks"] if c["status"] == "fail"}
        self.assertTrue({"exact-reviewed-oid", "B.domestic-shipping"} <= failed)
        self.assertEqual(probe["status"], "fail")

    def test_no_change_checkpoint_retains_oid(self):
        probe = case(self.report, "no-change-checkpoint")
        self.assertEqual(probe["status"], "pass", probe)
        self.assertEqual(probe["input_oid"], probe["output_oid"])
        self.assertEqual(probe["commit_oids"], [])

    def test_check_is_readonly_and_binds_real_head(self):
        project = Path(self.report["git"]["workspaces"]["integration"])
        before = harness.git(project, "status", "--porcelain=v1")
        index = Path(harness.git(project, "rev-parse", "--git-path", "index").strip())
        index = index if index.is_absolute() else project / index
        tracked = project / "quote.py"
        original_bytes = tracked.read_bytes()
        original_stat = tracked.stat()
        os.utime(tracked, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 2_000_000_000))
        before_index = index.read_bytes()
        result = harness.check_project(project, "D")
        self.assertEqual(result["status"], "pass", result)
        self.assertEqual(result["subject_oid"], self.report["git"]["outputs"]["D"])
        self.assertEqual(harness.git(project, "rev-parse", "HEAD").strip(), result["subject_oid"])
        self.assertEqual(index.read_bytes(), before_index)
        self.assertEqual(tracked.read_bytes(), original_bytes)
        self.assertEqual(len(result["checks"]), 9)
        self.assertEqual({c["status"] for c in result["checks"]}, {"pass"})
        self.assertEqual(harness.git(project, "status", "--porcelain=v1"), before)
        self.assertEqual(index.read_bytes(), before_index)
        self.assertFalse(list(project.rglob("__pycache__")))

    def test_frozen_assertion_tamper_is_refused(self):
        copied = self.root / "tampered-assertions"
        shutil.copytree(FIXTURE, copied)
        path = copied / "requirements.json"
        path.write_text(path.read_text().replace('"subtotal_cents": 2750', '"subtotal_cents": 1500'))
        with self.assertRaisesRegex(harness.FixtureError, "frozen requirement digest"):
            harness.verify_requirements(copied)

    def test_dirty_source_fails_even_when_behavior_passes(self):
        project = Path(self.report["git"]["workspaces"]["fix"])
        path = project / "uncommitted.txt"
        path.write_text("This source was not part of the recorded commit.\n")
        try:
            result = harness.check_project(project, "D")
            observed = {c["name"]: c["status"] for c in result["checks"]}
            self.assertEqual(result["status"], "fail")
            self.assertEqual(observed["D.domestic-receipt"], "pass")
            self.assertEqual(observed["clean-unchanged-source"], "fail")
            self.assertFalse(result["clean_before"])
        finally:
            path.unlink()

    def test_all_23_cases_retain_catalog_names_and_unrun_drivers(self):
        catalog = json.loads((PACK_ROOT / "gascity/schemas/workspace/scenario-coverage.v1.json").read_text())
        scenarios = self.report["scenarios"]
        self.assertEqual([(s["scenario"], s["name"]) for s in scenarios],
                         [(s["scenario"], s["name"]) for s in catalog["scenarios"]])
        self.assertEqual(len(scenarios), 23)
        for scenario in scenarios:
            required = [c for c in scenario["cases"] if c["required"]]
            self.assertTrue(required, scenario)
            self.assertEqual(scenario["status"], "unrun", scenario)
            self.assertTrue(all(c["status"] == "unrun" and c["needed_driver"] for c in required))
        self.assertFalse(self.report["acceptance_passed"])
        self.assertTrue(self.report["fixture_checks_passed"])

    def test_skipped_or_missing_required_case_never_passes(self):
        self.assertEqual(harness.scenario_status([]), "unrun")
        for status in ("skip", "unrun", "fail"):
            self.assertNotEqual(harness.scenario_status([
                {"required": True, "status": "pass"}, {"required": True, "status": status}
            ]), "pass")
        self.assertEqual(harness.scenario_status([{"required": True, "status": "pass"}]), "pass")

    def test_unknown_report_status_is_refused(self):
        with self.assertRaisesRegex(harness.FixtureError, "unknown case status"):
            harness.scenario_status([{"required": True, "status": "unknown"}])

    def test_evidence_layers_and_pins_are_explicit(self):
        layers = {c["layer"] for s in self.report["scenarios"] for c in s["cases"]}
        self.assertTrue({"component", "deterministic-git", "store-concurrency",
                         "native-controller", "native-worker"} <= layers)
        pins = self.report["pins"]
        self.assertEqual(len(pins["fixture_sha256"]), 64)
        self.assertEqual(len(pins["pack_oid"]), 40)
        self.assertIn("git version", pins["git_version"])
        self.assertTrue(pins["python_version"])
        self.assertIsNone(pins["core_oid"])
        self.assertEqual(pins["native_evidence"], "unrun")

    def test_existing_root_is_preserved(self):
        before = (self.root / "ordinary/seed/pricing.py").read_bytes()
        with self.assertRaisesRegex(harness.FixtureError, "already exists"):
            harness.seed(self.root / "ordinary", "ordinary")
        self.assertEqual((self.root / "ordinary/seed/pricing.py").read_bytes(), before)

    def test_real_bare_and_control_root_topologies(self):
        for topology in ("bare-root", "bare-control-root"):
            with self.subTest(topology=topology):
                report = harness.exercise(self.root / topology, topology)
                self.assertEqual(report["git"]["topology"], topology)
                self.assertTrue(report["fixture_checks_passed"])
                self.assertFalse(report["acceptance_passed"])
                self.assertTrue(Path(report["git"]["common_git_dir"]).is_absolute())

    def test_require_acceptance_exit_is_nonzero_for_unrun_native_cases(self):
        run = subprocess.run([sys.executable, "-B", str(SCRIPT), "exercise", "--root",
                              str(self.root / "cli"), "--require-acceptance"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        report = json.loads(run.stdout)
        self.assertTrue(report["fixture_checks_passed"])
        self.assertFalse(report["acceptance_passed"])


if __name__ == "__main__":
    unittest.main()
