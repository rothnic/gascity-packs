from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "gascity/assets/scripts/workspace_discovery.py"
MANIFEST = Path("gascity/schemas/workspace/affected-surfaces.v1.json")


class WorkspaceDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="workspace-discovery-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.manifest = json.loads((REPO_ROOT / MANIFEST).read_text())
        for path in list(self.manifest["inventory"]) + list(self.manifest["source_helpers"]):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / path, target)
        self.save_manifest()

    def save_manifest(self):
        target = self.root / MANIFEST
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.manifest))

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def check(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report["ok"], ok)
        return report

    def reject(self, path, *args):
        report = self.check(*args, ok=False)
        matches = [issue for issue in report["issues"] if issue["path"] == path]
        self.assertTrue(matches, report)
        self.assertTrue(all(issue["migration"] for issue in matches))
        return matches

    def refresh_hash(self, path):
        self.manifest["inventory"][path]["sha256"] = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
        self.save_manifest()

    def test_canonical_toml_override_fails_with_migration_guidance(self):
        path = "gascity/formulas/do-work.toml"
        self.write(path, 'formula = "do-work"\n[[steps]]\nid = "implement"\ndescription = "Write source"\n')
        # Native resolution prefers this file to the inventoried .formula.toml.
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertIn('"unclassified"', result.stdout, result.stderr + result.stdout)
        self.assertIn("migration", result.stdout)
        self.assertEqual(result.returncode, 1)

    def test_current_legacy_inventory_passes_only_stage_a(self):
        report = self.check()
        self.assertEqual(sum(report["classifications"].values()), len(self.manifest["inventory"]) + len(self.manifest["source_helpers"]))
        self.assertGreater(report["classifications"]["legacy"], 0)
        self.assertGreater(report["classifications"]["new"], 0)
        self.assertEqual(report["source_owner_count"], 10)
        self.assertEqual(set(report["inspected_roots"]), set(self.manifest["packs"]))
        self.assertEqual(report["unresolved_inputs"], [])
        later = self.check("--stage", "b", ok=False)
        self.assertTrue(any(issue["classification"] == "legacy" for issue in later["issues"]))

    def test_legacy_json_formula_and_new_workflow_asset_are_unclassified(self):
        for path, text in (
            ("gascity/formulas/do-work.formula.json", '{"formula":"do-work","steps":[]}'),
            ("bmad/assets/workflows/integration/resolve.txt", "Apply source conflict fixes"),
        ):
            with self.subTest(path=path):
                self.write(path, text)
                self.assertEqual(self.reject(path)[0]["classification"], "unclassified")

    def test_independent_description_and_check_overrides_require_explicit_entries(self):
        for path in (
            "local/assets/workflows/do-work/implement.md",
            "local/assets/scripts/checks/build-artifact-valid.sh",
        ):
            with self.subTest(path=path):
                self.write(path, "Changed layer override\n")
                self.assertEqual(self.reject(path, "--layer", "local")[0]["classification"], "unclassified")
        path = "bmad/assets/scripts/checks/build-artifact-valid.sh"
        self.write(path, "Changed supported-pack check override\n")
        self.assertEqual(self.reject(path)[0]["classification"], "unclassified")

    def test_default_helper_scope_and_explicit_pack_asset_scope_are_distinct(self):
        path = "bmad/assets/scripts/local-source-check.sh"
        self.write(path, "An ordinary script outside the default helper inventory\n")
        self.check()
        self.assertEqual(self.reject(path, "--layer", "bmad")[0]["classification"], "unclassified")

    def test_layer_scope_is_explicit_and_missing_or_escaping_inputs_fail(self):
        path = "local/assets/workflows/publish/preflight.md"
        self.write(path, "Override publication\n")
        self.check()  # An omitted live layer is outside this source check's scope.
        self.reject(path, "--layer", "local")
        missing = self.check("--layer", "missing", ok=False)
        self.assertIn("missing", missing["unresolved_inputs"])
        escaping = self.check("--layer", str(self.root.parent), ok=False)
        self.assertTrue(escaping["unresolved_inputs"])

    def test_symlinked_override_directory_cannot_hide_uninspected_assets(self):
        outside = tempfile.TemporaryDirectory(prefix="workspace-override-")
        self.addCleanup(outside.cleanup)
        Path(outside.name, "implement.md").write_text("Uninspected source override\n")
        path = self.root / "local/assets/workflows/do-work"
        path.parent.mkdir(parents=True)
        path.symlink_to(outside.name, target_is_directory=True)
        report = self.check("--layer", "local", ok=False)
        self.assertIn("local/assets/workflows/do-work", report["unresolved_inputs"])

    def test_formula_directory_symlinks_are_unresolved_even_without_formula_suffixes(self):
        outside = tempfile.TemporaryDirectory(prefix="workspace-formula-override-")
        self.addCleanup(outside.cleanup)
        Path(outside.name, "do-work.toml").write_text('formula = "do-work"\nsteps = []\n')
        for name in ("local/formulas/nested", "local/formulas"):
            with self.subTest(path=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to(outside.name, target_is_directory=True)
                try:
                    self.assertTrue((path / "do-work.toml").is_file())  # Native Source.Stat can reach the formula.
                    report = self.check("--layer", "local", ok=False)
                    self.assertIn(name, report["unresolved_inputs"])
                finally:
                    path.unlink()
                    if name.endswith("/nested"):
                        path.parent.rmdir()

    def test_changed_and_missing_assets_fail_without_reclassifying_current_workflows(self):
        path = "gascity/assets/workflows/do-work/implement.md"
        self.write(path, "A different commit contract\n")
        self.assertIn("changed", self.reject(path)[0]["reason"])
        (self.root / path).unlink()
        self.assertIn("missing", self.reject(path)[0]["reason"])

    def test_changed_delegation_still_fails_after_only_refreshing_the_formula_hash(self):
        path = "superpowers/formulas/superpowers-build.formula.toml"
        text = (self.root / path).read_text().replace('formula = "superpowers-development"', 'formula = "do-work"')
        self.write(path, text)
        self.refresh_hash(path)
        self.assertTrue(any("delegation" in issue["reason"] for issue in self.reject(path)))

    def test_wrong_final_commit_binding_fails_even_when_the_asset_is_inventoried(self):
        owner = next(row for row in self.manifest["source_owners"] if row["formula"].endswith("superpowers-development-item.formula.toml"))
        owner["final_source_step"] = next(row for row in self.manifest["owning_steps"]
                                         if row["formula"] == owner["formula"] and row["step_id"] == "implement-change")
        self.save_manifest()
        self.assertTrue(any("final source" in issue["reason"] for issue in self.reject(owner["formula"])))

    def test_native_drain_aliases_cannot_hide_unclassified_shared_or_separate_delegators(self):
        path = "gascity/formulas/unclassified-delegator.formula.json"
        for source, step_id in (
            ("gascity/formulas/same-session-implement.formula.toml", "shared-drain"),
            ("gascity/formulas/build-from-convoy-base.formula.toml", "implement"),
        ):
            data = tomllib.loads((self.root / source).read_text())
            step = next(step for step in data["steps"] if step["id"] == step_id)
            target = step["drain"]["formula"]
            for suffix in ("", ".toml", ".formula.toml", ".formula.json"):
                with self.subTest(context=step["drain"]["context"], suffix=suffix):
                    step["drain"]["formula"] = target + suffix
                    text = json.dumps({"formula": "unclassified-delegator", "steps": [step]})
                    self.write(path, text)
                    self.manifest["inventory"][path] = {"classification": "reference", "responsibility": "reference", "sha256": hashlib.sha256(text.encode()).hexdigest()}
                    self.save_manifest()
                    self.assertTrue(any("unclassified delegation" in issue["reason"] and repr(target + suffix) in issue["reason"] for issue in self.reject(path)))

    def test_native_drain_aliases_preserve_declared_shared_and_separate_routes(self):
        path = "gascity/formulas/build-from-convoy-base.formula.toml"
        source = (self.root / path).read_text()
        for suffix in ("", ".toml", ".formula.toml", ".formula.json"):
            with self.subTest(suffix=suffix):
                text = source.replace('formula = "do-work"', f'formula = "do-work{suffix}"')
                text = text.replace('formula = "do-work-item"', f'formula = "do-work-item{suffix}"')
                self.write(path, text)
                self.refresh_hash(path)
                self.check()

    def test_native_inheritance_aliases_preserve_raw_ambiguous_layer_diagnostics(self):
        path = "gascity/formulas/build-from-convoy.formula.toml"
        source = (self.root / path).read_text()
        for suffix in ("", ".toml", ".formula.toml", ".formula.json"):
            with self.subTest(suffix=suffix):
                self.write(path, source.replace('"build-from-convoy-base"', f'"build-from-convoy-base{suffix}"'))
                self.refresh_hash(path)
                self.check()
        shadow = "local/formulas/build-from-convoy-base.toml"
        text = 'formula = "build-from-convoy-base"\nsteps = []\n'
        self.write(shadow, text)
        self.manifest["inventory"][shadow] = {"classification": "reference", "responsibility": "reference", "sha256": hashlib.sha256(text.encode()).hexdigest()}
        self.save_manifest()
        report = self.check("--layer", "local", ok=False)
        self.assertIn("build-from-convoy-base.formula.json", report["unresolved_inputs"])
        self.assertTrue(any("ambiguous inherited formula" in issue["reason"] for issue in report["issues"]))

    def test_empty_and_noncanonical_helper_keys_have_structured_cli_errors(self):
        entry = self.manifest["source_helpers"]["gascity/assets/scripts/checks/build-artifact-valid.sh"]
        for path in ("", ".", "/helper.sh", "gascity//assets/helper.sh", "gascity/../helper.sh", "./gascity/assets/helper.sh"):
            with self.subTest(path=path):
                self.manifest["source_helpers"] = {path: entry}
                self.save_manifest()
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--root", str(self.root), "--manifest", str(self.root / MANIFEST)],
                    capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertFalse(report["ok"])
                self.assertTrue(any(issue["path"] == path and "helper path" in issue["reason"] and issue["migration"] for issue in report["issues"]))

    def test_inherited_continuation_and_derived_shared_item_bindings_are_checked(self):
        path = "gascity/formulas/build-from-convoy.formula.toml"
        self.write(path, (self.root / path).read_text().replace('"build-from-convoy-base"', '"build-from-review-base"'))
        self.refresh_hash(path)
        self.assertTrue(any("inherited" in issue["reason"] for issue in self.reject(path)))
        item = "gstack/formulas/gstack-work-item.formula.toml"
        self.write(item, (self.root / item).read_text().replace("../assets/workflows/gstack-work-item/implement-item.md", "../../gascity/assets/workflows/do-work-item/implement-item.md"))
        self.refresh_hash(item)
        self.assertTrue(any("binding" in issue["reason"] for issue in self.reject(item)))

    def test_direct_publish_and_nested_review_fix_bindings_are_checked(self):
        for path, old, new in (
            ("gstack/formulas/gstack-build.formula.toml", "../assets/workflows/gstack-build/publish.md", "../assets/workflows/gstack-build/finalize.md"),
            ("bmad/formulas/bmad-story-development-item.formula.toml", "../assets/workflows/bmad-story-development/apply-story-findings.md", "../assets/workflows/bmad-story-development/story-self-check.md"),
        ):
            with self.subTest(path=path):
                self.write(path, (self.root / path).read_text().replace(old, new))
                self.refresh_hash(path)
                self.assertTrue(any("binding" in issue["reason"] for issue in self.reject(path)))

    def test_reference_rows_cannot_hide_owning_assets(self):
        path = "gascity/assets/workflows/publish/preflight.md"
        self.manifest["inventory"][path]["classification"] = "reference"
        self.save_manifest()
        self.assertTrue(any("owning" in issue["reason"] for issue in self.reject(path)))

    def test_declared_new_owner_passes_without_claiming_runtime_migration(self):
        formula = "gascity/formulas/source-integration.toml"
        asset = "gascity/assets/workflows/source-integration/merge.md"
        self.write(formula, 'formula = "source-integration"\n[[steps]]\nid = "integrate"\ndescription_file = "../assets/workflows/source-integration/merge.md"\n')
        self.write(asset, "Integrate source and record its exact result\n")
        for path in (formula, asset):
            self.manifest["inventory"][path] = {"classification": "new", "responsibility": "source-writer,integration", "sha256": hashlib.sha256((self.root / path).read_bytes()).hexdigest()}
        self.manifest["owning_steps"].append({"formula": formula, "step_id": "integrate", "asset": asset, "roles": ["source-writer", "integration"]})
        self.save_manifest()
        report = self.check()
        self.assertEqual(report["classifications"]["new"], 2 + sum(row["classification"] == "new" for rows in (self.manifest["inventory"], self.manifest["source_helpers"]) for name,row in rows.items() if name not in (formula, asset)))
        self.assertFalse(report["runtime_verified"])

    def test_unknown_classification_and_missing_supported_pack_fail_closed(self):
        path = "gascity/assets/workflows/publish/preflight.md"
        self.manifest["inventory"][path]["classification"] = "unclassified"
        self.save_manifest()
        self.assertEqual(self.reject(path)[0]["classification"], "unclassified")
        self.manifest["packs"].remove("gstack")
        self.save_manifest()
        self.assertTrue(self.check(ok=False)["unresolved_inputs"])


if __name__ == "__main__":
    unittest.main()
