"""Real-Git regressions for qualified output, review generations and publication."""
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
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from workspace_records import RecordError, record_sha256


class ResultFixture(unittest.TestCase):
    def setUp(self):
        import workspace_outputs as outputs
        import workspace_review as review
        import workspace_publish as publish
        self.outputs, self.review, self.publish = outputs, review, publish
        self.temp = tempfile.TemporaryDirectory(prefix="workspace-results-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.artifacts = self.root / "evidence"
        self.artifacts.mkdir()
        self.git("init", "-q", "--initial-branch=task")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.source = self.repo / "feature.py"
        self.source.write_text("VALUE = 0\n")
        self.base = self.commit("baseline")
        self.source.write_text("VALUE = 42\n")
        self.oid = self.commit("required behavior")
        fixtures = json.loads((SCRIPTS.parents[1] / "tests/fixtures/workspace-records/valid.json").read_text())
        self.run = dict(fixtures["run"], workflow_root_id="run", rig_root=str(self.repo),
                        common_git_dir=str(self.repo / ".git"), base_oid=self.base, worktree_lifecycle="new")
        self.plan = dict(fixtures["source-plan"], workflow_root_id="run", source_plan_owner_id="plan",
                         base_oid=self.base, terminal_owner_id="task",
                         nodes=[dict(owner_id="task", strategy="isolated", member_ids=["task"],
                                     source_predecessor_owner_ids=[], single_lane=False)])
        self.workspace = dict(fixtures["workspace"], workflow_root_id="run", source_plan_owner_id="plan",
                              workspace_owner_id="task", strategy="isolated", work_dir=str(self.repo),
                              work_branch="task", phase="active", input_oid=self.base, current_oid=self.oid,
                              active_member_id="task", integration_inputs=None)
        self.workspace["claim_binding"] = {key: self.workspace[key] for key in
                                            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        self.workspace["native_provenance"].update(repo_identity=str(self.repo / ".git"), path=str(self.repo),
                                                   owner="task", base_ref=self.base, base_sha=self.base,
                                                   branch="task", store_ref="rig:fixture")
        self.binding = outputs.result_binding(self.run, self.plan, self.workspace, store_ref="rig:fixture",
                                               member_id="task", output_oid=self.oid)
        self.requirements = [dict(id="REQ-42", argv=[sys.executable, "-c", "import feature; assert feature.VALUE == 42"])]
        self.producer = dict(step_id="producer", session_id="producer-session", attempt_id="producer-attempt")
        self.reviewer = dict(step_id="reviewer", session_id="reviewer-session", attempt_id="reviewer-attempt")
        self.summary = self.artifacts / "summary.md"
        self.summary.write_text("Required behavior and requirement check REQ-42.\n")
        self.summary_ref = outputs.artifact(self.summary, self.artifacts)

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.repo), *args], text=True, capture_output=True,
                                env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message):
        self.git("add", "feature.py")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def qualified(self, *, label="first"):
        checks = self.outputs.execute_checks(self.binding, self.repo, self.requirements, self.producer,
                                               self.artifacts / label)
        context = self.outputs.begin_review(self.binding, self.repo, checks, self.requirements,
                                              self.producer, self.reviewer, [self.summary_ref], self.artifacts)
        report = self.artifacts / (label + "-report.md")
        report.write_text("Independent inspection of REQ-42 and the exact source.\n")
        review = self.outputs.complete_review(context, self.repo, report, "passed",
                                                self.artifacts / (label + "-review.json"), self.artifacts)
        result = self.outputs.make_member_result(self.binding, writer_step_id="producer",
                                                   commit_oids=[] if self.binding["input_oid"] == self.oid else [self.oid],
                                                   checks=checks, review=review, artifacts=[self.summary_ref],
                                                   required_checks=self.requirements, artifact_root=self.artifacts,
                                                   work_dir=self.repo)
        return result

    def canonical(self, result):
        output = self.outputs.make_owner_output(self.plan, [result], artifact_root=self.artifacts,
                    qualifications={"task": {"binding": self.binding, "required_checks": self.requirements}})
        canonical = self.outputs.canonical_payload(self.run, self.plan, output, result,
                                                     self.summary_ref, writer_step_id="canonical",
                                                     binding=self.binding, required_checks=self.requirements,
                                                     artifact_root=self.artifacts, work_dir=self.repo)
        return output, canonical

    def approved(self):
        result = self.qualified()
        output, canonical = self.canonical(result)
        context = self.review.begin_canonical_review(canonical, result, binding=self.binding,
                                                       required_checks=self.requirements, artifact_root=self.artifacts,
                                                       work_dir=self.repo, reviewer=self.reviewer, review_mode="report")
        review = self.review.finish_canonical_review(context, canonical, result, writer_step_id="reviewer",
                                                       review_id="approval", artifact_root=self.artifacts, work_dir=self.repo)
        return result, canonical, review


class OutputTests(ResultFixture):
    def test_consumer_compares_actual_native_identities_and_frozen_policy(self):
        result = self.qualified()
        native = dict(verified=True, workflow_root_id="run", generation=1, workspace_owner_id="task",
                      member_id="task", store_ref="rig:fixture", head_oid=self.oid, clean=True,
                      recorder_step_id="producer", producer_step_id="producer", producer_session_id="producer-session",
                      producer_attempt_id="producer-attempt", reviewer_step_id="reviewer", reviewer_session_id="reviewer-session",
                      reviewer_attempt_id="reviewer-attempt", native_attempt_id=self.binding["native_attempt_id"],
                      result_binding=self.binding)
        args = dict(plan=self.plan, store_ref="rig:fixture", repo_dir=self.repo, artifact_root=self.artifacts,
                    required_checks=self.requirements)
        self.outputs.validate_accepted_result(result, native_evidence=native, **args)
        for change in (dict(producer_session_id="invented"), dict(generation=2), dict(store_ref="rig:wrong"),
                       dict(recorder_step_id="another-recorder"), dict(verified=1), dict(result_binding={})):
            with self.assertRaises(RecordError):
                self.outputs.validate_accepted_result(result, native_evidence=dict(native, **change), **args)

    def test_review_statuses_are_preserved_without_acceptance(self):
        checks = self.outputs.execute_checks(self.binding, self.repo, self.requirements, self.producer, self.artifacts / "checks")
        for status in ("failed", "skipped", "unrun", "setup_failure"):
            context = self.outputs.begin_review(self.binding, self.repo, checks, self.requirements,
                                                  self.producer, self.reviewer, [self.summary_ref], self.artifacts)
            report = self.artifacts / (status + ".md")
            report.write_text(status + " observed\n")
            review = self.outputs.complete_review(context, self.repo, report, status, self.artifacts / (status + ".json"), self.artifacts)
            self.assertEqual(json.loads(Path(review["report_path"]).read_text())["status"], status)
            with self.assertRaises(RecordError):
                self.outputs.make_member_result(self.binding, writer_step_id="producer", commit_oids=[self.oid],
                    checks=checks, review=review, artifacts=[self.summary_ref], required_checks=self.requirements,
                    artifact_root=self.artifacts, work_dir=self.repo)

    def test_completed_checks_and_independent_review_are_required_before_acceptance(self):
        result = self.qualified()
        self.outputs.validate_accepted_result(result, binding=self.binding, required_checks=self.requirements,
                                                artifact_root=self.artifacts, work_dir=self.repo)
        for mutate in (lambda r: r["acceptance"].update(status="unverified"),
                       lambda r: r["acceptance"].update(project_checks=[]),
                       lambda r: r["acceptance"]["independent_review"].update(status="unrun"),
                       lambda r: r.update(generation=2), lambda r: r.update(input_oid=self.oid),
                       lambda r: r.update(member_id="wrong-target")):
            bad = copy.deepcopy(result)
            mutate(bad)
            with self.assertRaises(RecordError):
                self.outputs.validate_accepted_result(bad, binding=self.binding, required_checks=self.requirements,
                                                        artifact_root=self.artifacts, work_dir=self.repo)

    def test_changed_artifact_wrong_store_and_wrong_repository_refuse(self):
        result = self.qualified()
        for key, value in [("store_ref", "rig:wrong"), ("common_git_dir", str(self.root)), ("workspace_owner_id", "wrong")]:
            bad = dict(self.binding, **{key: value})
            with self.assertRaises(RecordError):
                self.outputs.validate_accepted_result(result, binding=bad, required_checks=self.requirements,
                                                        artifact_root=self.artifacts, work_dir=self.repo)
        self.summary.write_text("changed evidence\n")
        with self.assertRaises(RecordError):
            self.outputs.validate_accepted_result(result, binding=self.binding, required_checks=self.requirements,
                                                    artifact_root=self.artifacts, work_dir=self.repo)

    def test_no_change_has_exact_replay_and_no_commits(self):
        self.binding["input_oid"] = self.oid
        result = self.qualified()
        result = self.outputs.make_member_result(self.binding, writer_step_id="producer", commit_oids=[],
                                                   checks=result["acceptance"]["project_checks"],
                                                   review=result["acceptance"]["independent_review"],
                                                   artifacts=[self.summary_ref], required_checks=self.requirements,
                                                   artifact_root=self.artifacts, work_dir=self.repo)
        self.assertEqual(result["status"], "no_change")
        self.assertEqual(record_sha256(result), record_sha256(copy.deepcopy(result)))

    def test_ancestry_valid_revert_fails_the_same_requirement_oracle(self):
        old = self.qualified()
        self.source.write_text("VALUE = 0\n")
        self.oid = self.commit("ancestry-valid behavioral revert")
        self.git("merge-base", "--is-ancestor", old["output_oid"], self.oid)
        self.binding["output_oid"] = self.oid
        checks = self.outputs.execute_checks(self.binding, self.repo, self.requirements, self.producer,
                                               self.artifacts / "revert")
        evidence = json.loads(Path(checks[0]["evidence_path"]).read_text())
        self.assertEqual(evidence["status"], "failed")
        self.assertNotEqual(checks[0]["exit_code"], 0)
        with self.assertRaises(RecordError):
            self.outputs.make_member_result(self.binding, writer_step_id="producer", commit_oids=[self.oid],
                                               checks=checks, review=old["acceptance"]["independent_review"],
                                               artifacts=[self.summary_ref], required_checks=self.requirements,
                                               artifact_root=self.artifacts, work_dir=self.repo)

    def test_same_session_review_and_review_source_drift_refuse(self):
        checks = self.outputs.execute_checks(self.binding, self.repo, self.requirements, self.producer,
                                               self.artifacts / "checks")
        with self.assertRaises(RecordError):
            self.outputs.begin_review(self.binding, self.repo, checks, self.requirements, self.producer,
                                         dict(self.reviewer, session_id=self.producer["session_id"]), [self.summary_ref], self.artifacts)
        context = self.outputs.begin_review(self.binding, self.repo, checks, self.requirements,
                                              self.producer, self.reviewer, [self.summary_ref], self.artifacts)
        self.source.write_text("VALUE = 43\n")
        report = self.artifacts / "drift.md"
        report.write_text("drift\n")
        with self.assertRaises(RecordError):
            self.outputs.complete_review(context, self.repo, report, "passed", self.artifacts / "drift.json", self.artifacts)

    def test_clean_index_during_an_unfinished_git_operation_cannot_be_approved(self):
        result = self.qualified()
        (self.repo / ".git/rebase-merge").mkdir()
        self.assertEqual(self.git("status", "--porcelain=v1"), "")
        with self.assertRaises(RecordError):
            self.outputs.validate_accepted_result(result, binding=self.binding, required_checks=self.requirements,
                                                    artifact_root=self.artifacts, work_dir=self.repo)

    def test_setup_failure_is_preserved_and_cannot_be_accepted(self):
        requirements = [dict(id="REQ-42", argv=["/does-not-exist/workspace-test"])]
        checks = self.outputs.execute_checks(self.binding, self.repo, requirements, self.producer,
                                               self.artifacts / "setup")
        evidence = json.loads(Path(checks[0]["evidence_path"]).read_text())
        self.assertEqual(evidence["status"], "setup_failure")
        self.assertIsNone(evidence["exit_code"])

    def test_terminal_output_requires_a_completed_member_result(self):
        with self.assertRaisesRegex(RecordError, "requires completed member results"):
            self.outputs.make_owner_output(self.plan, [], artifact_root=self.artifacts, qualifications={})

    def test_fix_canonical_cannot_replace_a_later_accepted_generation(self):
        _, current = self.canonical(self.qualified())
        stale_arguments = None
        for generation in (2, 3):
            self.plan.update(generation=generation, base_oid=self.oid,
                             parent_canonical_generation=current["generation"], parent_canonical_oid=self.oid)
            self.binding.update(generation=generation, input_oid=self.oid)
            result = self.qualified(label=f"generation-{generation}")
            output = self.outputs.make_owner_output(self.plan, [result], artifact_root=self.artifacts,
                    qualifications={"task": {"binding": self.binding, "required_checks": self.requirements}})
            arguments = dict(run=self.run, plan=copy.deepcopy(self.plan), output=output, result=result,
                             summary=self.summary_ref, writer_step_id="canonical",
                             binding=copy.deepcopy(self.binding), required_checks=self.requirements,
                             artifact_root=self.artifacts, work_dir=self.repo)
            current = self.outputs.canonical_payload(**arguments, current=current)
            if generation == 2:
                stale_arguments = arguments
        with self.assertRaisesRegex(RecordError, "fix canonical parent is stale or no longer current"):
            self.outputs.canonical_payload(**stale_arguments, current=current)

    def test_terminal_selection_exact_replay_and_stale_parent(self):
        result = self.qualified()
        output, canonical = self.canonical(result)
        self.assertEqual(self.outputs.canonical_payload(self.run, self.plan, output, result, self.summary_ref,
                           writer_step_id="canonical", binding=self.binding, required_checks=self.requirements,
                           artifact_root=self.artifacts, work_dir=self.repo, current=canonical, stored=canonical), canonical)
        self.assertEqual(self.outputs.canonical_payload(self.run, self.plan, output, result, self.summary_ref,
                           writer_step_id="new-recorder", binding=self.binding, required_checks=self.requirements,
                           artifact_root=self.artifacts, work_dir=self.repo, stored=canonical), canonical)
        wrong = dict(canonical, output_oid=self.base)
        with self.assertRaises(RecordError):
            self.outputs.canonical_payload(self.run, self.plan, output, result, self.summary_ref,
               writer_step_id="canonical", binding=self.binding, required_checks=self.requirements,
               artifact_root=self.artifacts, work_dir=self.repo, current=wrong)
        bad_plan = copy.deepcopy(self.plan)
        bad_plan["nodes"].append(dict(owner_id="unintegrated", strategy="isolated", member_ids=["unintegrated"],
                                     source_predecessor_owner_ids=[], single_lane=False))
        with self.assertRaises(RecordError):
            self.outputs.make_owner_output(bad_plan, [result], artifact_root=self.artifacts,
                    qualifications={"task": {"binding": self.binding, "required_checks": self.requirements}})

    def test_shared_final_output_binds_all_contiguous_qualified_checkpoints(self):
        self.plan["nodes"][0].update(strategy="shared-chain", member_ids=["first", "last"], single_lane=True)
        self.binding["member_id"] = "first"
        first_binding = copy.deepcopy(self.binding)
        first = self.qualified(label="first")
        self.source.write_text("VALUE = 42\n# final member\n")
        previous = self.oid
        self.oid = self.commit("final shared member")
        self.binding.update(member_id="last", input_oid=previous, output_oid=self.oid)
        last = self.qualified(label="last")
        qualifications = {"first": dict(binding=first_binding, required_checks=self.requirements),
                          "last": dict(binding=self.binding, required_checks=self.requirements)}
        output = self.outputs.make_owner_output(self.plan, [first, last], artifact_root=self.artifacts, qualifications=qualifications)
        canonical = self.outputs.canonical_payload(self.run, self.plan, output, last, self.summary_ref,
            writer_step_id="canonical", binding=self.binding, required_checks=self.requirements,
            artifact_root=self.artifacts, work_dir=self.repo)
        self.assertEqual(canonical["output_oid"], self.oid)
        self.assertEqual(output["input_oid"], self.base)
        with self.assertRaises(RecordError):
            self.outputs.make_owner_output(self.plan, [last], artifact_root=self.artifacts, qualifications=qualifications)

    def test_actual_integration_input_precedes_producer_changes(self):
        first = self.oid
        self.git("checkout", "-qb", "B", self.base)
        (self.repo / "extra.txt").write_text("accepted B\n")
        self.git("add", "extra.txt")
        self.git("commit", "-qm", "independent B")
        second = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "task")
        self.git("merge", "--no-ff", "--no-edit", "-m", "integrate B", "B")
        merged = self.git("rev-parse", "HEAD")
        self.source.write_text("VALUE = 42\n# C implements its own change\n")
        self.oid = self.commit("C behavior after input composition")
        self.plan.update(terminal_owner_id="C", nodes=[
            dict(owner_id="A", strategy="isolated", member_ids=["A"], source_predecessor_owner_ids=[], single_lane=False),
            dict(owner_id="B", strategy="isolated", member_ids=["B"], source_predecessor_owner_ids=[], single_lane=False),
            dict(owner_id="C", strategy="integration", member_ids=["C"], source_predecessor_owner_ids=["A", "B"], single_lane=False)])
        self.binding.update(workspace_owner_id="C", member_id="C", input_oid=merged, output_oid=self.oid)
        result = self.qualified(label="C")
        inputs = [dict(owner_id="A", output_oid=first, workspace_output_sha256="a" * 64),
                  dict(owner_id="B", output_oid=second, workspace_output_sha256="b" * 64)]
        evidence = self.outputs.immutable_json(self.artifacts / "integration.json", dict(output_oid=merged, integration_inputs=inputs))
        output = self.outputs.make_owner_output(self.plan, [result], artifact_root=self.artifacts,
            qualifications={"C": dict(binding=self.binding, required_checks=self.requirements)},
            integration_inputs=inputs, integration_evidence=evidence)
        canonical = self.outputs.canonical_payload(self.run, self.plan, output, result, self.summary_ref,
            writer_step_id="canonical", binding=self.binding, required_checks=self.requirements,
            artifact_root=self.artifacts, work_dir=self.repo)
        self.assertNotEqual(merged, canonical["output_oid"])
        self.assertEqual(output["input_oid"], merged)
        with self.assertRaises(RecordError):
            self.outputs.make_owner_output(self.plan, [result], artifact_root=self.artifacts,
                qualifications={"C": dict(binding=self.binding, required_checks=self.requirements)},
                integration_inputs=list(reversed(inputs)), integration_evidence=evidence)


class ReviewTests(ResultFixture):
    def test_canonical_review_reuses_only_identical_commit_and_required_scope(self):
        result, canonical, approval = self.approved()
        self.review.validate_approval(approval, canonical, result, binding=self.binding,
                                        required_checks=self.requirements, artifact_root=self.artifacts, work_dir=self.repo)
        with self.assertRaises(RecordError):
            self.review.validate_approval(approval, canonical, result, binding=self.binding,
                required_checks=[dict(id="NEW", argv=[sys.executable, "-c", "pass"])], artifact_root=self.artifacts, work_dir=self.repo)

    def test_fix_plan_is_parent_bound_and_exhaustion_is_visible(self):
        result, canonical, approval = self.approved()
        fix = self.review.fix_plan(canonical, approval, self.plan, writer_step_id="fix-planner",
                                    source_plan_owner_id="fix-plan", nodes=self.plan["nodes"],
                                    terminal_owner_id="task", max_iterations=2)
        self.assertEqual(fix["generation"], 2)
        self.assertEqual(fix["base_oid"], canonical["output_oid"])
        self.review.validate_fix_parent(fix, canonical)
        with self.assertRaises(RecordError):
            self.review.validate_fix_parent(fix, dict(canonical, generation=2))
        with self.assertRaisesRegex(RecordError, "exhaust"):
            self.review.fix_plan(dict(canonical, generation=3), approval, self.plan, writer_step_id="fix-planner",
                                 source_plan_owner_id="fix-plan", nodes=self.plan["nodes"], terminal_owner_id="task", max_iterations=2)

    def test_x_approval_cannot_approve_y_even_with_valid_ancestry(self):
        result, canonical, approval = self.approved()
        self.source.write_text("VALUE = 42\n# fix Y\n")
        self.oid = self.commit("fix Y")
        self.binding.update(output_oid=self.oid, generation=2, input_oid=canonical["output_oid"], source_plan_owner_id="fix-plan")
        new = self.qualified(label="Y")
        new_canonical = dict(canonical, generation=2, output_oid=self.oid, source_plan_owner_id="fix-plan")
        with self.assertRaises(RecordError):
            self.review.validate_approval(approval, new_canonical, new, binding=self.binding,
                required_checks=self.requirements, artifact_root=self.artifacts, work_dir=self.repo)


class CanonicalStoreTests(ResultFixture):
    """Exercise the real request builder with a narrow, atomic protocol double."""
    def store_fixture(self):
        from workspace_store import Attempt, CookedWriterMap, WorkspaceStore, StoreError, record_reference
        from workspace_records import canonical_bytes, contracts
        result = self.qualified()
        output, _ = self.canonical(result)

        class MemoryStore(WorkspaceStore):
            def _command(inner, arguments, attempt=None):
                if arguments[0].startswith("--snapshot="):
                    ids = arguments[0].split("=", 1)[1].split(",")
                    rows = [copy.deepcopy(inner.rows[bead_id]) for bead_id in ids]
                else:
                    request = json.loads(Path(arguments[0].split("=", 1)[1]).read_text())
                    for patch in request["rows"]:
                        row = inner.rows[patch["id"]]
                        if any(row[field] != patch["expected_" + field] for field in ("revision", "status", "assignee")):
                            raise StoreError("simulated native compare-and-swap conflict")
                    rows = []
                    for patch in request["rows"]:
                        row = inner.rows[patch["id"]]
                        row["metadata"].update(patch["set"])
                        row["revision"] = str(int(row["revision"]) + 1)
                        rows.append(dict(id=row["id"], revision=row["revision"], changed=True))
                return dict(schema_version="1", ok=True, store_ref=inner.store_ref, rows=rows)

        store = MemoryStore("rig:fixture", cwd=self.root, common_git_dir=self.repo / ".git")
        ids = ["run", "plan", "task", "producer", "reviewer", "canonical-writer", "authority",
               "run-record", "plan-record", "result-record", "output-record", "canonical-record", self.workspace["workspace_bead_id"]]
        store.rows = {bead_id: dict(id=bead_id, revision="1", status="closed", assignee="", type="task", labels=None, metadata={})
                      for bead_id in ids}
        for kind, record_id, owner_id, payload in [
                ("run", "run-record", "run", self.run), ("source-plan", "plan-record", "plan", self.plan),
                ("member-result", "result-record", "task", result), ("owner-output", "output-record", "task", output),
                ("workspace", self.workspace["workspace_bead_id"], "task", self.workspace)]:
            key = contracts()[kind]["metadata_key"]
            store.rows[record_id]["metadata"][key] = canonical_bytes(payload).decode()
            store.rows[owner_id]["metadata"][key + "_ref"] = canonical_bytes(record_reference(kind, record_id, payload)).decode()
        attempt = Attempt("canonical-session", "fixture-token", "canonical-writer")
        store.rows["canonical-writer"].update(status="in_progress", assignee="fixture")
        store.rows["canonical-writer"]["metadata"].update({"gc.session_id": attempt.session_id,
            "gc.root_bead_id": "run", "gc.root_store_ref": "rig:fixture", "gc.step_ref": "bind-canonical"})
        store.rows["run"]["metadata"]["gc.source_generation"] = "1"
        store.rows["run"]["metadata"].update({"gc.formula_name": "build-base", "gc.formula_hash": "a" * 64,
            "gc.formula_source": "/fixture/build-base.formula.toml", "gc.root_store_ref": "rig:fixture"})
        store.rows["task"]["metadata"].update({"gc.root_bead_id": "run", "gc.root_store_ref": "rig:fixture"})
        store.rows["canonical-writer"]["metadata"].update({"gc.step_id": "summarize-implementation",
            "gc.step_ref": "summarize-implementation", "gc.native_step_dependencies.v1": "[]",
            "gc.source_anchor_id": "task", "gc.run_target": "gc.run-operator"})
        writer_map = CookedWriterMap(canonical_bytes(dict(version=1, workflow_root_id="run", store_ref="rig:fixture",
            source_member_id="task", expansion_root_id="run", formula_name="build-base", formula_hash="a" * 64,
            formula_source="/fixture/build-base.formula.toml", steps=[dict(bead_id="canonical-writer",
                step_id="summarize-implementation", step_ref="summarize-implementation", dependencies=[], record_kinds=["canonical"])])))
        def native(result):
            return dict(verified=True, workflow_root_id="run", generation=1, workspace_owner_id="task", member_id="task",
                        store_ref="rig:fixture", head_oid=self.oid, clean=True, recorder_step_id="producer",
                        producer_step_id="producer", producer_session_id="producer-session", producer_attempt_id="producer-attempt",
                        reviewer_step_id="reviewer", reviewer_session_id="reviewer-session", reviewer_attempt_id="reviewer-attempt",
                        native_attempt_id=self.binding["native_attempt_id"], result_binding=self.binding,
                        current_generation=int(store.rows["run"]["metadata"]["gc.source_generation"]),
                        guard_rows={key: copy.deepcopy(store.rows[key]) for key in
                                    ("run", "producer", "reviewer", self.workspace["workspace_bead_id"])})
        args = dict(run_owner_id="run", plan_owner_id="plan", output_owner_id="task", result_member_id="task",
                    record_id="canonical-record", authority_id="authority", binding=self.binding,
                    required_checks=self.requirements, artifact_root=self.artifacts, work_dir=self.repo,
                    summary=self.summary_ref, qualify_native=native, writer_map=writer_map, initial_write=True)
        return store, attempt, args

    def test_record_written_pointer_missing_recovers_same_immutable_identity(self):
        store, attempt, args = self.store_fixture()
        prepared = self.outputs.prepare_canonical(store, attempt, **args)
        self.assertEqual(store.execute(prepared)["outcome"], "committed")
        args["initial_write"] = False
        immutable = store.rows["canonical-record"]["metadata"]["gc.canonical"]
        store.rows["run"]["metadata"].pop("gc.canonical_ref")
        store.rows["run"]["revision"] = str(int(store.rows["run"]["revision"]) + 1)
        replay = self.outputs.prepare_canonical(store, attempt, **args)
        self.assertEqual(store.execute(replay)["outcome"], "replayed")
        self.assertEqual(store.rows["canonical-record"]["metadata"]["gc.canonical"], immutable)
        self.assertEqual(json.loads(store.rows["run"]["metadata"]["gc.canonical_ref"])["bead_id"], "canonical-record")

    def test_paused_canonical_writer_cannot_overwrite_newer_pointer(self):
        store, attempt, args = self.store_fixture()
        prepared = self.outputs.prepare_canonical(store, attempt, **args)
        store.rows["run"]["metadata"]["gc.canonical_ref"] = json.dumps(dict(kind="canonical", identity=["run", 2, "new-plan"], bead_id="new-record"))
        store.rows["run"]["revision"] = str(int(store.rows["run"]["revision"]) + 1)
        newer = store.rows["run"]["metadata"]["gc.canonical_ref"]
        self.assertEqual(store.execute(prepared)["outcome"], "unknown")
        self.assertEqual(store.resolve(prepared)["outcome"], "unknown")
        self.assertEqual(store.rows["run"]["metadata"]["gc.canonical_ref"], newer)

    def test_old_generation_cannot_rebind_when_a_newer_pointer_is_temporarily_missing(self):
        store, attempt, args = self.store_fixture()
        prepared = self.outputs.prepare_canonical(store, attempt, **args)
        self.assertEqual(store.execute(prepared)["outcome"], "committed")
        args["initial_write"] = False
        store.rows["run"]["metadata"].pop("gc.canonical_ref")
        store.rows["run"]["metadata"]["gc.source_generation"] = "2"
        with self.assertRaisesRegex(RecordError, "currently selected"):
            self.outputs.prepare_canonical(store, attempt, **args)
        self.assertNotIn("gc.canonical_ref", store.rows["run"]["metadata"])


class PublicationTests(ResultFixture):
    def intent(self, *, open_pr=False):
        result, canonical, approval = self.approved()
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
        decision = dict(schema="gc.workspace.publication-authority.v1", binding=self.binding,
                        canonical_sha256=record_sha256(canonical), review_sha256=record_sha256(approval),
                        remote="origin", remote_url=str(self.remote), ref="refs/heads/delivery", expected_remote_oid=None,
                        push=True, open_pr=open_pr)
        if open_pr:
            decision["pr_spec"] = dict(repo="example/project", base="main", actor="fixture", mode="draft", marker="intent-publish")
        path = self.artifacts / "authority.json"
        path.write_text(json.dumps(decision))
        intent = self.publish.publication_intent(canonical, approval, result, binding=self.binding,
             required_checks=self.requirements, artifact_root=self.artifacts, work_dir=self.repo,
             authorization=dict(push=True, open_pr=open_pr, decision_path=str(path),
                                decision_sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
             remote="origin", ref="refs/heads/delivery", publish_id="publish", writer_step_id="publisher")
        self.publication_args = dict(canonical=canonical, approval=approval, result=result, binding=self.binding,
                                    required_checks=self.requirements, artifact_root=self.artifacts, work_dir=self.repo)
        return intent

    def test_exact_oid_push_lost_response_readback_and_no_duplicate_effect(self):
        intent = self.intent()
        journal = []
        def persist(value):
            journal.append(copy.deepcopy(value))
            return dict(outcome="committed", record_sha256=record_sha256(value))
        original_git = self.publish.git
        pushes = []
        def lost_response(work_dir, *argv):
            response = original_git(work_dir, *argv)
            if argv[0] == "push":
                self.assertEqual(response.returncode, 0, response.stderr)
                pushes.append(argv)
                raise RecordError("simulated response loss after the local Git effect")
            return response
        with mock.patch.object(self.publish, "git", side_effect=lost_response):
            observed = self.publish.push_publication(intent, persist=persist,
                             current=lambda: self.publication_args["canonical"], **self.publication_args)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(pushes[0][-1], self.oid + ":refs/heads/delivery")
        self.assertEqual(journal[0]["status"], "uncertain")
        self.assertEqual(observed["status"], "observed")
        self.assertEqual(observed["observed_oid"], self.oid)
        count = len(journal)
        replay = self.publish.push_publication(observed, persist=persist,
                         current=lambda: self.publication_args["canonical"], **self.publication_args)
        self.assertEqual(replay, observed)
        self.assertEqual(len(journal), count)

    def test_remote_divergence_and_missing_response_remain_uncertain(self):
        intent = self.intent()
        uncertain = dict(intent, status="uncertain")
        result = self.publish.reconcile_publication(uncertain, remote_oid=self.base)
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["observed_oid"])
        self.assertEqual(self.publish.reconcile_publication(uncertain, remote_oid=None), uncertain)

    def test_dirty_source_stale_approval_or_revoked_authority_fail_before_push(self):
        intent = self.intent()
        self.source.write_text("VALUE = 7\n")
        with self.assertRaises(RecordError):
            self.publish.push_publication(intent, persist=lambda value: None,
                current=lambda: self.publication_args["canonical"], **self.publication_args)
        remote = subprocess.run(["git", "--git-dir", str(self.remote), "show-ref"], capture_output=True)
        self.assertEqual(remote.returncode, 1)
        self.git("checkout", "--", "feature.py")
        for bad in (dict(intent, output_oid=self.base), dict(intent, authorization=dict(intent["authorization"], push=False))):
            with self.assertRaises(RecordError):
                self.publish.push_publication(bad, persist=lambda value: None,
                    current=lambda: self.publication_args["canonical"], **self.publication_args)
        with self.assertRaises(RecordError):
            self.publish.push_publication(intent, persist=lambda value: None,
                current=lambda: dict(self.publication_args["canonical"], generation=2), **self.publication_args)
        self.assertEqual(subprocess.run(["git", "--git-dir", str(self.remote), "show-ref"], capture_output=True).returncode, 1)

    def test_unknown_remote_and_missing_intent_readback_cannot_trigger_effect(self):
        intent = self.intent()
        def persist(value):
            return dict(outcome="committed", record_sha256=record_sha256(value))
        with mock.patch.object(self.publish, "remote_oid", side_effect=RecordError("remote state unavailable")):
            uncertain = self.publish.push_publication(intent, persist=persist,
                current=lambda: self.publication_args["canonical"], **self.publication_args)
        self.assertEqual(uncertain["status"], "uncertain")
        self.assertTrue(list(self.artifacts.glob("publish-blocker-*.json")))
        with self.assertRaises(RecordError):
            self.publish.push_publication(intent, persist=lambda value: None,
                current=lambda: self.publication_args["canonical"], **self.publication_args)
        self.assertEqual(subprocess.run(["git", "--git-dir", str(self.remote), "show-ref"], capture_output=True).returncode, 1)

    def test_pr_response_loss_reconciles_same_marker_and_never_duplicates(self):
        intent = self.intent(open_pr=True)
        intent["status"] = "uncertain"
        intent["observed_oid"] = self.oid
        self.git("push", "origin", self.oid + ":refs/heads/delivery")
        spec = dict(repo="example/project", base="main", actor="fixture", mode="draft", marker="intent-publish")
        reservation = self.artifacts / "pr-create.json"
        args = dict(self.publication_args, current=lambda: self.publication_args["canonical"])
        self.assertTrue(self.publish.reserve_pr_attempt(intent, spec, reservation, **args)["create_allowed"])
        self.assertFalse(self.publish.reserve_pr_attempt(intent, spec, reservation, **args)["create_allowed"])
        provider_rows = []
        def provider_create():
            provider_rows.append(dict(spec, head_oid=self.oid, url="https://example.invalid/project/pull/1"))
            raise RuntimeError("simulated provider response loss after creation")
        with self.assertRaises(RuntimeError):
            provider_create()
        self.assertFalse(self.publish.reserve_pr_attempt(intent, spec, reservation, **args)["create_allowed"])
        self.assertEqual(len(provider_rows), 1)
        receipt = provider_rows[0]
        observed = self.publish.reconcile_publication(intent, remote_oid=self.oid, pr_spec=spec, prs=provider_rows)
        self.assertEqual(observed["status"], "observed")
        self.assertEqual(observed["pr_url"], receipt["url"])
        self.assertEqual(self.publish.reconcile_publication(intent, remote_oid=self.oid, pr_spec=spec,
                                                          prs=[dict(receipt, head_oid=self.base)]), intent)


if __name__ == "__main__":
    unittest.main()
