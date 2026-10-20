"""Methodology source contracts, rendered through the repository's formula layers.

These checks exercise graph ownership and prompts. Native workflow acceptance
still requires the composed core, helpers and project fixture.
"""
from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from test_formula_assets import load_formula_from_dirs, resolve_formula_from_dirs
from test_workspace_records import fixture_records, records_module


REPO = Path(__file__).resolve().parents[2]
PACKS = ("compound-engineering", "superpowers", "bmad", "gstack")
BASE = Path(os.environ.get("WORKSPACE_BASE_PACK", REPO / "gascity"))
DIRS = [BASE / "formulas", *[REPO / name / "formulas" for name in PACKS]]
ITEMS = {
    "compound-engineering": ("compound-work", "compound-work-item", "implement", "implement-item"),
    "superpowers": ("superpowers-development", "superpowers-development-item", "record-item-result", "record-item-result"),
    "bmad": ("bmad-story-development", "bmad-story-development-item", "apply-story-findings", "apply-story-findings"),
    "gstack": ("gstack-work", "gstack-work-item", "implement", "implement-item"),
}


def nodes(formula):
    for node in formula.get("steps", []) + formula.get("template", []):
        yield node
        yield from node.get("children", [])


def body(formula_name, node, **values):
    # Resolve imported assets using the same ordered layers as formula tests.
    relative = node["description_file"].removeprefix("../assets/")
    path = next((directory.parent / "assets" / relative for directory in reversed(DIRS)
                 if (directory.parent / "assets" / relative).is_file()), None)
    if path is None:
        raise AssertionError(f"missing imported asset for {formula_name}/{node['id']}")
    variables = {key: value.get("default", "") for key, value in
                 resolve_formula_from_dirs(DIRS, formula_name).get("vars", {}).items()}
    variables.update(values)
    text = re.sub(r"\{\{([a-z_]+)\}\}", lambda match: str(variables.get(match[1], match[0])), path.read_text())
    return text.replace("{target}", "review")


class MethodologyWorkspaceTests(unittest.TestCase):
    def test_effective_build_prepare_allows_recorded_planning_without_waiving_admission(self):
        for name in ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build"):
            with self.subTest(formula=name):
                formula = resolve_formula_from_dirs(DIRS, name)
                prepare = next(step for step in formula["steps"] if step["id"] == "prepare")
                text = " ".join(body(name, prepare, context_path="/contexts/request.json").split())
                self.assertIn("successful `recorded` result allows requirements, planning and decomposition", text)
                self.assertIn("`committed` or `replayed` receipt", text)
                self.assertIn("source plan is not required at this stage", text)
                self.assertIn("`awaiting-source` result permits planning only", text)
                self.assertIn("Implementation still requires the original recorded run, source plan and admitted workspace", text)
                self.assertIn("nonzero exit, unknown receipt or refused read blocks handoff", text)
                self.assertIn("preserve the original request", text)
                self.assertIn("Resolve relative `items[].path` values from the directory containing `context_path`", text)
                self.assertIn("not from the worker's current directory", text)
                self.assertIn("validate_context_bundle.py", text)
                self.assertIn('PACK_SCRIPTS=$(gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace scripts-path)', text)
                self.assertIn('python3 "$PACK_SCRIPTS/validate_context_bundle.py" "/contexts/request.json"', text)
                self.assertIn("A failed lookup from the worker directory does not show that a declared input is missing", text)

    def test_effective_canonical_summary_retains_member_path_hash_and_provenance(self):
        for name in ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build"):
            with self.subTest(formula=name):
                formula = resolve_formula_from_dirs(DIRS, name)
                steps = {step["id"]: step for step in formula["steps"]}
                prepare = " ".join(body(name, steps["prepare"]).split())
                self.assertIn("Leave `gc.build.implementation_summary_path` unresolved", prepare)
                self.assertNotIn("`implementation-summary.md` for `gc.build.implementation_summary_path`", prepare)
                text = " ".join(body(name, steps["summarize-implementation"]).split())
                for contract in ("committed or replayed canonical binding", "earlier unqualified placeholder",
                                 "conflicting current qualified canonical binding", "changed bytes/hash blocks",
                                 "accepted member's original workflow, methodology, producer and trace",
                                 "Do not restamp", "<accepted-producer-stage>", "separate optional report"):
                    self.assertIn(contract, text)
                self.assertNotIn("stage: summarize-implementation", text)
        formula = resolve_formula_from_dirs(DIRS, "implement")
        summary = next(step for step in formula["steps"] if step["id"] == "summarize")
        text = " ".join(body("implement", summary, summary_path="/owned/reports/nondefault-member.md").split())
        self.assertIn("/owned/reports/nondefault-member.md", text)
        self.assertIn("accepted member's original workflow, methodology, producer and trace", text)
        self.assertNotIn("stage: summarize,", text)
        self.assertIn("Preserve those bytes and their hash", text)

    def test_effective_separate_item_summary_option_reaches_producer_and_close(self):
        items = [("do-work", "implement"),
                 *[(separate, writer) for separate, _, writer, _ in ITEMS.values()]]
        for name, writer in items:
            with self.subTest(formula=name):
                formula = resolve_formula_from_dirs(DIRS, name)
                self.assertIn("summary_path", formula["vars"])
                steps = {step["id"]: step for step in nodes(formula)}
                text = " ".join(body(name, steps[writer], summary_path="/owned/reports/nondefault-member.md").split())
                # The BMAD and Superpowers leaf assets are also shared-member
                # assets, so they read the declared native input without an
                # undefined template variable in the shared formula.
                self.assertTrue("/owned/reports/nondefault-member.md" in text or
                                "native root's `gc.var.summary_path`" in text)
                self.assertIn("When it is empty", text)
                self.assertIn("before project checks, independent acceptance and result publication", text)
                self.assertIn("same path and its exact bytes", text)
                self.assertIn("Do not move or rewrite an accepted summary", text)
                close = " ".join(body(name, steps["close-source-anchor"],
                                      summary_path="/owned/reports/nondefault-member.md").split())
                self.assertTrue("/owned/reports/nondefault-member.md" in close or
                                "native root's `gc.var.summary_path`" in close)
                self.assertIn("absolute path and its original hash", close)
                self.assertIn("mismatch blocks closure", close)
        for separate, shared, _, writer in ITEMS.values():
            with self.subTest(shared=shared):
                formula = resolve_formula_from_dirs(DIRS, shared)
                self.assertNotIn("summary_path", formula.get("vars", {}))
                step = next(step for step in nodes(formula) if step["id"] == writer)
                self.assertNotIn("{{summary_path}}", body(shared, step))

    def test_effective_review_fix_drafts_cannot_replace_accepted_artifacts(self):
        for name, suffix in (("compound-code-review", "apply-review-findings"),
                             ("bmad-code-review-flow", "apply-bmad-review-findings"),
                             ("gstack-code-review", "apply-review-findings")):
            with self.subTest(formula=name):
                formula = load_formula_from_dirs(DIRS, name)
                fix = next(node for node in nodes(formula) if node["id"].endswith("." + suffix))
                text = " ".join(body(name, fix).split())
                self.assertIn("workspace_review.fix_plan", text)
                self.assertIn("replacement generation", text)
                self.assertIn("distinct generation-specific paths before checks, independent review, result publication and canonical qualification", text)
                self.assertIn("Repair only this attempt's unaccepted draft in place", text)
                self.assertIn("accepted artifact remains immutable", text)
                self.assertIn("Schema validation alone cannot approve a replacement", text)
                self.assertNotIn("Edit it in place", text)
                self.assertNotIn("repair the artifact in place", text)

    def test_direct_items_require_new_without_legacy_compatibility(self):
        records = records_module()
        for separate, shared, _, _ in ITEMS.values():
            for name in (separate, shared):
                formula = resolve_formula_from_dirs(DIRS, name)
                steps = {step["id"]: step for step in formula["steps"]}
                gate = steps["validate-workspace-mode"]
                self.assertEqual(gate["check"]["max_attempts"], 1)
                self.assertEqual(Path(gate["check"]["check"]["path"]).name, "workspace-lifecycle-valid.py")
                self.assertEqual(formula["vars"]["worktree_lifecycle"]["default"], "new")
                declared = json.loads(gate["metadata"]["gc.lifecycle.source_modes"])
                self.assertEqual(records.verify_source_modes("new", declared), "new")
                self.assertNotIn("gc.lifecycle.compatibility", gate["metadata"])
                with self.assertRaises(records.RecordError):
                    records.verify_source_modes("legacy", declared)
                first = "prepare-worktree" if name == separate else "implement-item"
                self.assertEqual(steps[first]["needs"], ["validate-workspace-mode"] if name == separate else ["validate-workspace-mode", "prepare-worktree"])
                if name == separate:
                    self.assertEqual(steps[first]["metadata"]["gc.lifecycle.source_modes"], gate["metadata"]["gc.lifecycle.source_modes"])
                    self.assertEqual(steps[first]["check"], gate["check"])

    def test_imported_admission_check_accepts_only_new_and_refuses_malformed_state(self):
        check = BASE / "assets/scripts/checks/workspace-lifecycle-valid.py"
        with tempfile.TemporaryDirectory(prefix="methodology-mode-") as directory:
            scratch = Path(directory)
            stub = scratch / "gc"
            stub.write_text("#!/usr/bin/env python3\nimport os, sys\nfrom pathlib import Path\n"
                            "if sys.argv[1:] != ['bd', 'show', 'methodology-check', '--json']: sys.exit(2)\n"
                            "print(Path(os.environ['MODE_SNAPSHOT']).read_text())\n")
            stub.chmod(0o755)
            snapshot = scratch / "step.json"
            env = dict(os.environ, PATH=str(scratch) + os.pathsep + os.environ["PATH"],
                       GC_BEAD_ID="methodology-check", MODE_SNAPSHOT=str(snapshot))
            for pack, (separate, shared, _, _) in ITEMS.items():
                for name in (separate, shared):
                    formula = resolve_formula_from_dirs(DIRS, name)
                    gate = next(step for step in formula["steps"] if step["id"] == "validate-workspace-mode")
                    for mode in ("legacy", "new", "unknown"):
                        with self.subTest(pack=pack, formula=name, mode=mode):
                            metadata = dict(gate["metadata"], **{"gc.lifecycle": mode})
                            snapshot.write_text(json.dumps([{"id": "methodology-check", "metadata": metadata}]))
                            result = subprocess.run([sys.executable, "-S", str(check)], env=env,
                                                    capture_output=True, text=True, timeout=5)
                            self.assertEqual(result.returncode, 0 if mode == "new" else 1, result.stderr)
                            if mode == "legacy":
                                self.assertIn("explicit migration", result.stderr)
                            elif mode == "new":
                                self.assertEqual(result.stderr, "")
                            if mode != "new":
                                self.assertEqual(result.stdout, "")
                    snapshot.write_text(json.dumps([{"id": "foreign-check", "metadata": gate["metadata"]}]))
                    result = subprocess.run([sys.executable, "-S", str(check)], env=env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stdout, "")

    def test_closed_inventory_has_mode_guards_for_every_concrete_methodology_owner(self):
        manifest = json.loads((REPO / "gascity/schemas/workspace/affected-surfaces.v1.json").read_text())
        assets = {row["asset"] for row in manifest["owning_steps"] if row["formula"].split("/")[0] in PACKS}
        for asset in sorted(assets):
            with self.subTest(asset=asset):
                text = (REPO / asset).read_text()
                self.assertIn("worktree_lifecycle", text)
                self.assertIn("explicit migration", " ".join(text.lower().split()))
                self.assertIn("new", text)

    def test_actual_writer_steps_keep_native_routes_and_render_exact_result_contract(self):
        for pack, (separate, shared, separate_writer, shared_writer) in ITEMS.items():
            for formula_name, writer in ((separate, separate_writer), (shared, shared_writer)):
                with self.subTest(pack=pack, formula=formula_name):
                    formula = resolve_formula_from_dirs(DIRS, formula_name)
                    node = next(node for node in nodes(formula) if node["id"] == writer)
                    self.assertIn("gc.run_target", node["metadata"])
                    text = body(formula_name, node, worktree_lifecycle="new", artifact_root="proofs/methodology")
                    for contract in ("workspace_outputs.result_binding", "workspace_outputs.execute_checks",
                                     "input_oid", "output_oid", "no_change", "record-result"):
                        self.assertIn(contract, text)
                    self.assertIn("explicit migration", " ".join(text.lower().split()))
                    self.assertIn("proofs/methodology", text)

    def test_composed_items_have_complete_result_and_closure_dependencies(self):
        if not (BASE / "assets/workflows/do-work/record-result.md").is_file():
            self.skipTest("composed common result stages are absent; graph integration remains unrun")
        for pack, (separate, shared, _, _) in ITEMS.items():
            for name in (separate, shared):
                with self.subTest(pack=pack, formula=name):
                    formula = resolve_formula_from_dirs(DIRS, name)
                    steps = {step["id"]: step for step in formula["steps"]}
                    for step in steps.values():
                        for predecessor in step.get("needs", []):
                            self.assertIn(predecessor, steps, f"{name}/{step['id']} has an unresolved predecessor")
                    self.assertEqual(steps["record-result"]["needs"], ["independent-acceptance"])
                    producer = "record-item-result" if pack == "superpowers" else "implement" if name == separate else "implement-item"
                    self.assertIn("record-result", steps["close-source-anchor"]["needs"])
                    if "condition" not in steps["close-source-anchor"]:
                        self.assertIn(producer, steps["close-source-anchor"]["needs"],
                                      "closure must wait for the actual producer")
                    self.assertEqual(steps["independent-acceptance"]["needs"], [producer])
                    self.assertEqual(steps["independent-acceptance"]["metadata"]["gc.run_target"], "gc.implementation-reviewer")
                    self.assertIn("gc gc workspace flow close-source", body(name, steps["close-source-anchor"], worktree_lifecycle="new"))

    def test_expansion_callers_propagate_retained_mode_without_changing_routes(self):
        targets = {"compound-code-review", "compound-resolution", "superpowers-code-review",
                   "superpowers-task-review", "bmad-code-review-flow", "gstack-code-review",
                   "gstack-qa-review", "gstack-release-readiness"}
        for pack in PACKS:
            for path in (REPO / pack / "formulas").glob("*.formula.toml"):
                formula = load_formula_from_dirs(DIRS, path.name.removesuffix(".formula.toml"))
                for node in nodes(formula):
                    if node.get("expand") in targets:
                        self.assertEqual(node["expand_vars"]["worktree_lifecycle"], "{{worktree_lifecycle}}")
                        self.assertIn("gc.run_target", node["metadata"])

    def test_separate_and_shared_drains_keep_member_access_and_single_lane(self):
        builds = ("compound-build", "superpowers-build", "bmad-build", "gstack-build")
        entries = ("compound-implementation", "superpowers-implementation", "bmad-implementation", "gstack-implementation")
        for pack, build, entry in zip(PACKS, builds, entries):
            separate, shared, _, _ = ITEMS[pack]
            for name in (build, entry):
                with self.subTest(formula=name):
                    formula = resolve_formula_from_dirs(DIRS, name)
                    drains = [step for step in formula["steps"] if "drain" in step]
                    self.assertEqual({step["drain"]["formula"] for step in drains}, {separate, shared})
                    for step in drains:
                        self.assertEqual(step["drain"]["member_access"], "exclusive")
                        rendered = body(name, step, worktree_lifecycle="new", drain_policy="same-session")
                        self.assertIn("workspace_entry.read_entry", rendered)
                        self.assertIn("source-plan", rendered)
                        if step["drain"]["context"] == "shared":
                            self.assertTrue(step["drain"]["item"]["single_lane"])
                            self.assertEqual(step["drain"]["on_item_failure"], "skip_remaining")
                            self.assertIn("owner-output", rendered)

    def test_superpowers_inspection_cannot_checkpoint_or_close_before_tdd_review(self):
        for name, first in (("superpowers-development", "implement"), ("superpowers-development-item", "implement-item")):
            formula = resolve_formula_from_dirs(DIRS, name)
            steps = {step["id"]: step for step in formula["steps"]}
            order = (first, "write-failing-test", "verify-test-fails", "implement-change",
                     "verify-test-passes", "task-review", "record-item-result")
            for previous, current in zip(order, order[1:]):
                self.assertEqual(steps[current]["needs"], [previous])
            inspection = body(name, steps[first], worktree_lifecycle="new")
            self.assertIn("inspect-only", inspection)
            self.assertNotIn("workspace_outputs.make_member_result", inspection)
            self.assertEqual(steps["independent-acceptance"]["needs"], ["record-item-result"])
            self.assertEqual(steps["close-source-anchor"]["needs"], ["record-item-result", "record-result"])
            self.assertIn("gc gc workspace flow close-source", body(name, steps["close-source-anchor"], worktree_lifecycle="new"))

    def test_bmad_final_leaf_preserves_iterate_after_source_changes_and_drain_identity(self):
        for name in ITEMS["bmad"][:2]:
            formula = resolve_formula_from_dirs(DIRS, name)
            apply = next(node for node in nodes(formula) if node["id"] == "apply-story-findings")
            self.assertEqual(apply["needs"], ["acceptance-audit"])
            text = body(name, apply, worktree_lifecycle="new")
            for contract in ("gc.drain_member_id", "iterate", "no_change", "independent", "record-result"):
                self.assertIn(contract, text)

    def test_concrete_review_and_fix_owners_bind_canonical_commit(self):
        expansions = {"compound-engineering": "compound-code-review", "superpowers": "superpowers-code-review",
                      "bmad": "bmad-code-review-flow", "gstack": "gstack-code-review"}
        fixes = {"compound-engineering": "apply-review-findings", "superpowers": "process-code-review",
                 "bmad": "apply-bmad-review-findings", "gstack": "apply-review-findings"}
        for pack, name in expansions.items():
            formula = load_formula_from_dirs(DIRS, name)
            setup = next(node for node in nodes(formula) if node["id"].endswith(("setup-compound-code-review", "setup-superpowers-code-review", "gather-bmad-review-context", "setup-gstack-code-review")))
            fix = next(node for node in nodes(formula) if node["id"].endswith("." + fixes[pack]))
            end = next(node for node in formula["template"] if node["id"] == "{target}")
            for node in (setup, fix, end):
                self.assertIn("canonical", body(name, node, worktree_lifecycle="new"))
            self.assertIn("workspace_review.begin_canonical_review", body(name, setup))
            self.assertIn("workspace_review.fix_plan", body(name, fix))
            self.assertIn("workspace_review.finish_canonical_review", body(name, end))
            self.assertIn("report", fix.get("condition", ""))

    def test_gstack_publication_requires_exact_intent_and_all_readiness_evidence(self):
        formula = resolve_formula_from_dirs(DIRS, "gstack-build")
        steps = {step["id"]: step for step in formula["steps"]}
        self.assertEqual(steps["release-readiness"]["needs"], ["qa"])
        self.assertEqual(steps["finalize"]["needs"], ["release-readiness", "review-result"])
        self.assertEqual(steps["publish"]["needs"], ["finalize"])
        text = body("gstack-build", steps["publish"], worktree_lifecycle="new", push="false", open_pr="false")
        for contract in ("workspace_publish.publication_intent", "workspace_publish.prepare_publication_record",
                         "workspace_publish.push_publication", "workspace_publish.reserve_pr_attempt",
                         "workspace_publish.reconcile_publication", "output_oid", "QA", "release", "no-op"):
            self.assertIn(contract, text)

    def test_continuation_and_inherited_fix_formulas_refuse_legacy_admission(self):
        records = records_module()
        for pack, (_, shared, _, _) in ITEMS.items():
            for stage in ("plan", "decompose", "convoy", "review"):
                formula = resolve_formula_from_dirs(DIRS, "build-from-" + stage)
                prepare = next(step for step in formula["steps"] if step["id"] == "prepare-" + stage)
                self.assertEqual(formula["vars"]["worktree_lifecycle"]["default"], "new")
                declared = json.loads(prepare["metadata"]["gc.lifecycle.source_modes"])
                self.assertEqual(records.verify_source_modes("new", declared), "new")
                self.assertNotIn("gc.lifecycle.compatibility", prepare["metadata"])
            prefix = "compound" if pack == "compound-engineering" else pack
            fix = resolve_formula_from_dirs(DIRS, prefix + "-fix-loop")
            self.assertEqual(fix["vars"]["implementation_formula"]["default"], prefix + "-implementation")
            self.assertIn("single_lane", load_formula_from_dirs(DIRS, shared))

    def test_changed_no_change_and_refusal_records_preserve_same_run_state(self):
        records = records_module()
        fixture = fixture_records()
        original = copy.deepcopy(fixture["member-result"])
        unchanged = dict(original, status="no_change", output_oid=original["input_oid"], commit_oids=[])
        unchanged["acceptance"] = copy.deepcopy(original["acceptance"])
        unchanged["acceptance"]["subject_oid"] = unchanged["output_oid"]
        for check in unchanged["acceptance"]["project_checks"]:
            check["subject_oid"] = unchanged["output_oid"]
        for pack in PACKS:
            with self.subTest(pack=pack):
                records.validate_record("member-result", original)
                records.validate_record("member-result", unchanged)
                with self.assertRaises(records.RecordError):
                    records.verify_replay("member-result", original, unchanged)
                for invalid in (dict(original, member_id="foreign-member"), dict(original, generation=2)):
                    with self.assertRaises(records.RecordError):
                        records.verify_replay("member-result", original, invalid)
                self.assertEqual(fixture["member-result"], original)


class WorkspaceHelperContractTests(unittest.TestCase):
    """Exercise the actual composed APIs without stores, processes or commits."""

    @classmethod
    def setUpClass(cls):
        directories = os.environ.get("WORKSPACE_HELPER_SCRIPTS")
        if directories:
            sys.path[:0] = directories.split(os.pathsep)
        elif not (BASE / "assets/scripts/workspace_outputs.py").is_file():
            raise unittest.SkipTest("composed workspace helper APIs are not present; native acceptance remains unrun")
        else:
            sys.path.insert(0, str(BASE / "assets/scripts"))
        cls.outputs = importlib.import_module("workspace_outputs")
        cls.review = importlib.import_module("workspace_review")
        cls.publish = importlib.import_module("workspace_publish")
        cls.records = importlib.import_module("workspace_records")

    def setUp(self):
        self.fixtures = fixture_records()
        self.run = dict(self.fixtures["run"], worktree_lifecycle="new")
        self.plan = copy.deepcopy(self.fixtures["source-plan"])
        self.workspace = copy.deepcopy(self.fixtures["workspace"])
        self.workspace["phase"] = "active"

    def binding(self, output_oid=None):
        return self.outputs.result_binding(self.run, self.plan, self.workspace,
            store_ref="rig:example", member_id=self.workspace["active_member_id"],
            output_oid=output_oid or self.workspace["input_oid"])

    def test_separate_and_shared_bindings_refuse_foreign_native_provenance(self):
        for pack in PACKS:
            for strategy in ("isolated", "shared-chain"):
                with self.subTest(pack=pack, strategy=strategy):
                    self.plan["nodes"] = [dict(owner_id="integration-example", strategy=strategy,
                        member_ids=["integration-example", "next-member"] if strategy == "shared-chain" else ["integration-example"],
                        source_predecessor_owner_ids=[], single_lane=strategy == "shared-chain")]
                    self.workspace.update(strategy=strategy, integration_inputs=None)
                    expected = self.binding()
                    retained = copy.deepcopy(self.workspace)
                    for key, value in (("store_ref", "rig:foreign"), ("owner", "foreign-owner"),
                                       ("attempt_id", "stale-attempt"), ("generation", "2")):
                        self.workspace["native_provenance"][key] = value
                        with self.assertRaises(self.records.RecordError):
                            self.binding()
                        self.assertEqual(self.workspace["native_provenance"][key], value)
                        self.workspace = copy.deepcopy(retained)
                    self.assertEqual(self.binding(), expected)

    def test_changed_and_no_change_cannot_bypass_checks_or_independent_review(self):
        for pack, (_, _, writer, _) in ITEMS.items():
            for oid in (self.workspace["input_oid"], "b" * 40):
                with self.subTest(pack=pack, output=oid):
                    binding = self.binding(oid)
                    with self.assertRaises(self.records.RecordError):
                        self.outputs.make_member_result(binding, writer_step_id=pack + "-" + writer,
                            commit_oids=[] if oid == binding["input_oid"] else [oid], checks=[],
                            review=copy.deepcopy(self.fixtures["member-result"]["acceptance"]["independent_review"]),
                            artifacts=[], required_checks=[{"id": "required-behavior", "argv": ["python3", "verify.py"]}],
                            artifact_root="/example/artifacts", work_dir=self.workspace["work_dir"])

    def test_fix_generation_binds_reviewed_parent_and_preserves_stale_evidence(self):
        canonical = self.fixtures["canonical"]
        findings = dict(self.fixtures["review"], verdict="changes_required",
                        canonical_record_sha256=self.records.record_sha256(canonical))
        retained = copy.deepcopy((canonical, findings, self.plan))
        for pack in PACKS:
            arguments = dict(writer_step_id=pack + "-fix", source_plan_owner_id="plan-owner-example",
                nodes=self.plan["nodes"], terminal_owner_id=self.plan["terminal_owner_id"], max_iterations=3)
            plan = self.review.fix_plan(canonical, findings, self.plan, **arguments)
            self.assertEqual(plan["generation"], canonical["generation"] + 1)
            self.assertEqual(plan["base_oid"], canonical["output_oid"])
            self.assertEqual(plan["parent_canonical_oid"], canonical["output_oid"])
            self.assertEqual(plan["parent_canonical_generation"], canonical["generation"])
            with self.assertRaises(self.records.RecordError):
                self.review.fix_plan(dict(canonical, generation=2), findings, self.plan, **arguments)
            with self.assertRaises(self.records.RecordError):
                self.review.fix_plan(canonical, dict(findings, reviewed_oid="d" * 40), self.plan, **arguments)
        self.assertEqual((canonical, findings, self.plan), retained)

    def test_publication_reconciliation_preserves_unknown_or_different_output(self):
        intent = copy.deepcopy(self.fixtures["publish"])
        intent.update(status="uncertain", observed_oid=None, pr_url=None)
        retained = copy.deepcopy(intent)
        for observed in (None, "e" * 40):
            self.assertEqual(self.publish.reconcile_publication(intent, remote_oid=observed), retained)
        # Matching Git alone cannot complete a PR-enabled intent.
        intent["authorization"]["open_pr"] = True
        observed = self.publish.reconcile_publication(intent, remote_oid=intent["output_oid"])
        self.assertEqual(observed["status"], "uncertain")
        self.assertIsNone(observed["pr_url"])
        self.assertEqual(intent["observed_oid"], None)


if __name__ == "__main__":
    unittest.main()
