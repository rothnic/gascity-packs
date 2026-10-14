from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_workspace_source_plan import node, plan_record


SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def module():
    spec = importlib.util.spec_from_file_location("workspace_inputs", SCRIPTS / "workspace_inputs.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class InputFixture(unittest.TestCase):
    def setUp(self):
        self.helper = module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.plan = plan_record()
        self.results, self.outputs = {}, {}
        self.contexts = {}
        self.native_calls = []

    def evidence(self, name, text):
        path = self.root / name
        path.write_text(text)
        return str(path), hashlib.sha256(path.read_bytes()).hexdigest()

    def accepted(self, owner, output_oid, *, input_oid=None, member=None, strategy="isolated"):
        member = member or owner
        input_oid = input_oid or self.plan["base_oid"]
        check_path, check_digest = self.evidence(member + "-check.txt", "project check passed at " + output_oid)
        identities = {
            "producer": {"step_id": "implement-" + member, "session_id": "producer-session", "attempt_id": "producer-attempt-1"},
            "reviewer": {"step_id": "reviewer-" + member, "session_id": "review-session", "attempt_id": "review-attempt-1"},
        }
        review_path, review_digest = self.evidence(member + "-review.json", json.dumps(identities))
        result = {
            "version": 1, "workflow_root_id": self.plan["workflow_root_id"], "generation": self.plan["generation"],
            "writer_step_id": "writer-" + member, "source_plan_owner_id": self.plan["source_plan_owner_id"],
            "workspace_owner_id": owner, "member_id": member,
            "status": "changed" if input_oid != output_oid else "no_change",
            "input_oid": input_oid, "output_oid": output_oid,
            "commit_oids": [output_oid] if input_oid != output_oid else [],
            "acceptance": {
                "status": "accepted", "subject_oid": output_oid, "artifacts": [],
                "project_checks": [{"command": "project-check", "subject_oid": output_oid, "exit_code": 0,
                                    "evidence_path": check_path, "evidence_sha256": check_digest}],
                "independent_review": {"status": "passed", "reviewed_oid": output_oid,
                                       "reviewer": "reviewer-" + member, "report_path": review_path, "report_sha256": review_digest},
            },
        }
        self.results[member] = result
        output = {
            "version": 1, "workflow_root_id": self.plan["workflow_root_id"], "generation": self.plan["generation"],
            "writer_step_id": result["writer_step_id"], "source_plan_owner_id": self.plan["source_plan_owner_id"],
            "workspace_owner_id": owner, "strategy": strategy, "input_oid": input_oid, "output_oid": output_oid,
            "final_member_id": member, "final_member_result_sha256": self.helper.record_sha256(result),
            "integration_inputs": None, "integration_evidence_path": None, "integration_evidence_sha256": None,
        }
        if strategy == "shared-chain":
            first_id = next(node for node in self.plan["nodes"] if node["owner_id"] == owner)["member_ids"][0]
            if first_id in self.results:
                output["input_oid"] = self.results[first_id]["input_oid"]
        self.outputs[owner] = output
        self.contexts[member] = {"binding": {
            **{field: result[field] for field in ("workflow_root_id", "generation", "source_plan_owner_id",
                                                 "workspace_owner_id", "member_id", "input_oid", "output_oid")},
            "store_ref": "rig:project", "native_attempt_id": "workspace-attempt-1",
            "work_dir": str(self.root), "common_git_dir": str(self.root),
        }, "required_checks": [{"id": "fixture-check", "argv": ["project-check"]}], "work_dir": self.root}
        return output, result

    def native(self, result):
        self.native_calls.append(result["member_id"])
        return {
            "verified": True, "workflow_root_id": result["workflow_root_id"], "generation": result["generation"],
            "workspace_owner_id": result["workspace_owner_id"], "member_id": result["member_id"],
            "store_ref": "rig:project", "head_oid": result["output_oid"], "clean": True,
            "recorder_step_id": result["writer_step_id"], "recorder_session_id": "record-session",
            "recorder_attempt_id": "record-attempt-1", "producer_step_id": "implement-" + result["member_id"],
            "producer_session_id": "producer-session",
            "producer_attempt_id": "producer-attempt-1", "reviewer_step_id": result["acceptance"]["independent_review"]["reviewer"],
            "reviewer_session_id": "review-session", "reviewer_attempt_id": "review-attempt-1",
            "native_attempt_id": "workspace-attempt-1",
            "work_dir": self.contexts[result["member_id"]]["binding"]["work_dir"],
            "common_git_dir": self.contexts[result["member_id"]]["binding"]["common_git_dir"],
        }

    def resolve(self, owner, member=None, *, qualify=None):
        return self.helper.resolve_member_input(
            self.plan, owner, member or owner, load_owner_output=self.outputs.get,
            load_member_result=self.results.get, qualify_native=qualify or self.native,
            acceptance_context=lambda result, native: self.contexts[result["member_id"]],
            store_ref="rig:project", artifact_root=self.root,
        )


class SourceInputTests(InputFixture):
    def setUp(self):
        super().setUp()
        # Pure graph/consumer cases use a qualification port. Real-Git cases below
        # compose the actual producer validator and executed check manifests.
        self.validator = mock.patch.object(self.helper, "validate_accepted_result", side_effect=lambda result, **_: result)
        self.qualification_port = self.validator.start()
        self.addCleanup(self.validator.stop)

    def test_isolated_base_requires_no_predecessor_output(self):
        bundle = self.resolve("A")
        self.assertEqual(bundle["input_oid"], self.plan["base_oid"])
        self.assertEqual(bundle["predecessors"], [])
        self.assertEqual(self.native_calls, [])

    def test_integration_requires_both_accepted_outputs_and_preserves_declared_order(self):
        self.accepted("A", "b" * 40)
        with self.assertRaisesRegex(self.helper.RecordError, "missing.*B"):
            self.resolve("C")
        self.accepted("B", "c" * 40)
        bundle = self.resolve("C")
        self.assertIsNone(bundle["input_oid"])
        self.assertEqual([entry["owner_id"] for entry in bundle["predecessors"]], ["B", "A"])
        self.assertEqual([entry["output_oid"] for entry in bundle["predecessors"]], ["c" * 40, "b" * 40])
        self.assertEqual(self.native_calls[-2:], ["B", "A"])

    def test_rejected_metadata_only_or_missing_acceptance_gets_no_credit(self):
        output, result = self.accepted("A", "b" * 40)
        self.plan["nodes"] = [node("A"), node("D", ["A"])]
        for status in ["rejected", "unverified"]:
            result["acceptance"]["status"] = status
            output["final_member_result_sha256"] = self.helper.record_sha256(result)
            with self.subTest(status=status), self.assertRaisesRegex(self.helper.RecordError, "accepted"):
                self.resolve("D")
        result["acceptance"]["status"] = "accepted"
        result["acceptance"]["project_checks"] = []
        with self.assertRaisesRegex(self.helper.RecordError, "accepted"):
            self.resolve("D")

    def test_changed_record_bytes_foreign_scope_and_wrong_final_member_are_refused(self):
        output, result = self.accepted("A", "b" * 40)
        self.plan["nodes"] = [node("A"), node("D", ["A"])]
        original_output, original_result = copy.deepcopy(output), copy.deepcopy(result)
        for target, field, value in [("result", "writer_step_id", "changed-writer"), ("output", "generation", 2),
                                     ("output", "workflow_root_id", "foreign-root"), ("output", "workspace_owner_id", "B"),
                                     ("output", "final_member_id", "foreign-member"), ("output", "output_oid", "c" * 40)]:
            self.outputs["A"], self.results["A"] = copy.deepcopy(original_output), copy.deepcopy(original_result)
            (self.results["A"] if target == "result" else self.outputs["A"])[field] = value
            with self.subTest(field=field), self.assertRaises(self.helper.RecordError):
                self.resolve("D")

    def test_receipt_bytes_and_admitted_artifact_root_are_checked(self):
        output, result = self.accepted("A", "b" * 40)
        self.plan["nodes"] = [node("A"), node("D", ["A"])]
        check = pathlib.Path(result["acceptance"]["project_checks"][0]["evidence_path"])
        check.write_text("changed after acceptance")
        with self.assertRaisesRegex(self.helper.RecordError, "artifact.*(?:digest|hash)"):
            self.resolve("D")
        check.write_text("project check passed at " + result["output_oid"])
        with tempfile.TemporaryDirectory() as outside:
            alien = pathlib.Path(outside) / "review.md"
            alien.write_text("foreign receipt")
            result["acceptance"]["independent_review"]["report_path"] = str(alien)
            result["acceptance"]["independent_review"]["report_sha256"] = hashlib.sha256(alien.read_bytes()).hexdigest()
            output["final_member_result_sha256"] = self.helper.record_sha256(result)
            with self.assertRaisesRegex(self.helper.RecordError, "artifact.*root"):
                self.resolve("D")

    def test_current_native_head_store_attempt_and_independent_session_are_required(self):
        self.accepted("A", "b" * 40)
        self.plan["nodes"] = [node("A"), node("D", ["A"])]
        for field, value in [("verified", False), ("verified", 1), ("head_oid", "c" * 40), ("clean", False),
                             ("store_ref", "rig:elsewhere"), ("generation", 2), ("workspace_owner_id", "B"),
                             ("recorder_step_id", "foreign-step"), ("producer_attempt_id", ""),
                             ("native_attempt_id", ""), ("reviewer_session_id", "producer-session")]:
            def invalid(result, field=field, value=value):
                return dict(self.native(result), **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(self.helper.RecordError, "native"):
                self.resolve("D", qualify=invalid)
        with self.assertRaisesRegex(self.helper.RecordError, "native"):
            self.resolve("D", qualify=lambda result: True)

    def test_producer_policy_failure_and_native_identity_mismatch_cannot_be_consumed(self):
        self.accepted("A", "b" * 40)
        self.plan["nodes"] = [node("A"), node("D", ["A"])]
        self.qualification_port.side_effect = self.helper.RecordError("required checks were skipped")
        with self.assertRaisesRegex(self.helper.RecordError, "required checks"):
            self.resolve("D")
        self.qualification_port.side_effect = lambda result, **_: result
        self.assertEqual(self.resolve("D")["input_oid"], "b" * 40)
        with self.assertRaisesRegex(self.helper.RecordError, "producer identity"):
            self.resolve("D", qualify=lambda result: dict(self.native(result), producer_step_id="foreign-implementation"))

    def test_accepted_owner_cannot_substitute_its_initial_base_or_declared_predecessor(self):
        self.plan["nodes"] = [node("A"), node("D", ["A"]), node("E", ["D"])]
        self.plan["terminal_owner_id"] = "E"
        self.accepted("A", "b" * 40, input_oid="c" * 40)
        with self.assertRaisesRegex(self.helper.RecordError, "owner input.*plan base"):
            self.resolve("D")
        self.accepted("A", "b" * 40)
        self.accepted("D", "c" * 40, input_oid=self.plan["base_oid"], strategy="dependent")
        with self.assertRaisesRegex(self.helper.RecordError, "owner input.*predecessor"):
            self.resolve("E")

    def test_shared_chain_uses_only_previous_accepted_member_and_preserves_owner(self):
        self.plan["nodes"] = [node("chain", strategy="shared-chain", members=["first", "second", "last"])]
        self.plan["terminal_owner_id"] = "chain"
        first = self.resolve("chain", "first")
        self.assertEqual(first["input_oid"], self.plan["base_oid"])
        with self.assertRaisesRegex(self.helper.RecordError, "missing.*first"):
            self.resolve("chain", "second")
        self.accepted("chain", "b" * 40, member="first", strategy="shared-chain")
        second = self.resolve("chain", "second")
        self.assertEqual(second["input_oid"], "b" * 40)
        self.assertEqual(second["workspace_owner_id"], "chain")
        self.accepted("chain", "c" * 40, input_oid="b" * 40, member="second", strategy="shared-chain")
        self.assertEqual(self.resolve("chain", "last")["input_oid"], "c" * 40)
        with self.assertRaisesRegex(self.helper.RecordError, "member"):
            self.resolve("chain", "foreign")

    def test_shared_member_cannot_accept_a_gap_in_its_declared_input_chain(self):
        self.plan["nodes"] = [node("chain", strategy="shared-chain", members=["first", "second", "last"])]
        self.plan["terminal_owner_id"] = "chain"
        self.accepted("chain", "b" * 40, member="first", input_oid="d" * 40, strategy="shared-chain")
        with self.assertRaisesRegex(self.helper.RecordError, "declared source chain"):
            self.resolve("chain", "second")
        self.accepted("chain", "b" * 40, member="first", strategy="shared-chain")
        self.accepted("chain", "c" * 40, member="second", strategy="shared-chain")
        with self.assertRaisesRegex(self.helper.RecordError, "declared source chain"):
            self.resolve("chain", "last")

    def test_shared_owner_output_must_bind_the_last_member(self):
        self.plan["nodes"] = [node("chain", strategy="shared-chain", members=["first", "last"]), node("D", ["chain"])]
        self.plan["terminal_owner_id"] = "D"
        self.accepted("chain", "b" * 40, member="first", strategy="shared-chain")
        with self.assertRaisesRegex(self.helper.RecordError, "final member"):
            self.resolve("D")
        self.accepted("chain", "c" * 40, input_oid="b" * 40, member="last", strategy="shared-chain")
        self.assertEqual(self.resolve("D")["input_oid"], "c" * 40)


class RealGitIntegrationTests(InputFixture):
    def setUp(self):
        super().setUp()
        self.repo = self.root / "project with spaces"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Workspace test")
        self.git("config", "user.email", "workspace-test@example.invalid")
        (self.repo / "base.txt").write_text("base\n")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.plan["base_oid"] = self.base
        self.git("checkout", "-b", "source-a")
        (self.repo / "a.txt").write_text("accepted A\n")
        self.git("add", ".")
        self.git("commit", "-m", "A")
        self.a = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-b", "source-b", self.base)
        (self.repo / "b.txt").write_text("accepted B\n")
        self.git("add", ".")
        self.git("commit", "-m", "B")
        self.b = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "--detach", self.base)
        self.accepted("A", self.a)
        self.accepted("B", self.b)
        self.verifications = []

    def git(self, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        result = subprocess.run(["git", "-C", str(self.repo), *args], env=env, text=True, capture_output=True, timeout=10)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

    def accepted(self, owner, output_oid, *, input_oid=None, member=None, strategy="isolated"):
        import workspace_outputs as producer
        member = member or owner
        output, result = super().accepted(owner, output_oid, input_oid=input_oid, member=member, strategy=strategy)
        work = self.repo
        if self.git("rev-parse", "HEAD").strip() != output_oid:
            work = self.root / (member + "-" + output_oid[:12])
            if not work.exists():
                self.git("worktree", "add", "--detach", str(work), output_oid)
        fixtures = json.loads((SCRIPTS.parents[1] / "tests/fixtures/workspace-records/valid.json").read_text())
        run = dict(fixtures["run"], workflow_root_id=self.plan["workflow_root_id"], rig_root=str(self.repo),
                   common_git_dir=str(self.repo / ".git"), base_oid=self.base, worktree_lifecycle="new")
        workspace = dict(fixtures["workspace"], **{key: self.plan[key] for key in
                                                   ("workflow_root_id", "generation", "source_plan_owner_id")},
                         workspace_owner_id=owner, strategy=strategy, work_dir=str(work), work_branch=None,
                         phase="active", active_member_id=member, input_oid=result["input_oid"], current_oid=output_oid,
                         native_attempt_id="workspace-attempt-1")
        workspace["integration_inputs"] = ([{"owner_id": source, "output_oid": self.outputs[source]["output_oid"],
                                             "workspace_output_sha256": self.helper.record_sha256(self.outputs[source])}
                                            for source in next(n for n in self.plan["nodes"] if n["owner_id"] == owner)
                                            ["source_predecessor_owner_ids"]] if strategy == "integration" else None)
        workspace["claim_binding"] = {key: workspace[key] for key in
                                        ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        workspace["native_provenance"].update(repo_identity=str(self.repo / ".git"), path=str(work), owner=owner,
                                               branch=None, store_ref="rig:project", base_ref=self.base, base_sha=self.base,
                                               generation=str(self.plan["generation"]), attempt_id="workspace-attempt-1")
        binding = producer.result_binding(run, self.plan, workspace, store_ref="rig:project", member_id=member,
                                            output_oid=output_oid)
        if owner == "C":
            command = "from pathlib import Path; assert Path('a.txt').read_text() == 'accepted A\\n'; assert Path('b.txt').read_text() == 'accepted B\\n'"
        else:
            name = owner.lower() + ".txt"
            name = name if (work / name).exists() else "base.txt"
            command = "from pathlib import Path; assert Path(" + repr(name) + ").read_text() == " + repr((work / name).read_text())
        required = [{"id": "required-" + member, "argv": [sys.executable, "-c", command]}]
        native = super().native(result)
        identities = {role: {key: native[role + "_" + key] for key in ("step_id", "session_id", "attempt_id")}
                      for role in ("producer", "reviewer")}
        evidence_dir = self.root / (member + "-proof-" + output_oid[:12])
        checks = producer.execute_checks(binding, work, required, identities["producer"], evidence_dir)
        path, _ = self.evidence(member + "-summary.md", "Required source behavior at " + output_oid)
        artifacts = [producer.artifact(path, self.root)]
        context = producer.begin_review(binding, work, checks, required, identities["producer"], identities["reviewer"],
                                           artifacts, self.root)
        report, _ = self.evidence(member + "-independent-report.md", "Independent fixture source inspection at " + output_oid)
        review = producer.complete_review(context, work, report, "passed", evidence_dir / "review.json", self.root)
        result = producer.make_member_result(binding, writer_step_id=result["writer_step_id"], commit_oids=result["commit_oids"],
                                              checks=checks, review=review, artifacts=artifacts, required_checks=required,
                                              artifact_root=self.root, work_dir=work)
        self.results[member] = result
        output["final_member_result_sha256"] = producer.record_sha256(result)
        self.contexts[member] = {"binding": binding, "required_checks": required, "work_dir": work}
        return output, result

    def native(self, result):
        import workspace_outputs as producer
        native = super().native(result)
        context = self.contexts[result["member_id"]]
        native["head_oid"] = producer.git_value(context["work_dir"], "rev-parse", "HEAD")
        native["clean"] = not producer.git_value(context["work_dir"], "status", "--porcelain=v1", "--untracked-files=all")
        native["common_git_dir"] = str(pathlib.Path(producer.git_value(
            context["work_dir"], "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve())
        return native

    def verify(self, work_dir, bundle, expected_head):
        self.verifications.append(expected_head)
        return {"verified": True, "workspace_owner_id": bundle["workspace_owner_id"],
                "native_attempt_id": "fixture-native-attempt", "base_oid": self.base,
                "workflow_root_id": bundle["workflow_root_id"], "generation": bundle["generation"],
                "member_id": bundle["member_id"], "store_ref": bundle["store_ref"],
                "head_oid": self.git("rev-parse", "HEAD").strip(), "clean": not self.git("status", "--porcelain").strip()}

    def integrate(self, *, verify=None):
        return self.helper.materialize_integration(self.repo, self.resolve("C"), verify_native=verify or self.verify)

    def test_actual_merges_materialize_ab_then_c_delivers_that_exact_result_to_d(self):
        integrated = self.integrate()
        head = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(integrated["output_oid"], head)
        self.assertEqual([i["owner_id"] for i in integrated["integration_inputs"]], ["B", "A"])
        self.assertEqual((self.repo / "a.txt").read_text(), "accepted A\n")
        self.assertEqual((self.repo / "b.txt").read_text(), "accepted B\n")
        for parent in [self.a, self.b]:
            self.git("merge-base", "--is-ancestor", parent, head)
        self.assertGreaterEqual(len(self.git("rev-list", "--min-parents=2", head + "^@", head).splitlines()), 1)
        (self.repo / "c.txt").write_text("C consumed both prerequisites\n")
        self.git("add", ".")
        self.git("commit", "-m", "C")
        c = self.git("rev-parse", "HEAD").strip()
        output, _ = self.accepted("C", c, input_oid=head, strategy="integration")
        evidence_path, digest = self.evidence("integration.json", json.dumps(integrated, sort_keys=True))
        output.update(integration_inputs=integrated["integration_inputs"], integration_evidence_path=evidence_path,
                      integration_evidence_sha256=digest)
        self.assertEqual(self.resolve("D")["input_oid"], c)

    def test_recovery_inspects_exact_ordered_merge_history_without_mutating_git(self):
        integrated = self.integrate()
        before = self.git("rev-parse", "HEAD").strip()
        inspected = self.helper.inspect_integrated_history(self.repo, self.resolve("C"), before)
        self.assertEqual(integrated, inspected)
        self.assertEqual(before, self.git("rev-parse", "HEAD").strip())
        bundle = self.resolve("C")
        bundle["predecessors"].reverse()
        with self.assertRaisesRegex(self.helper.RecordError, "source order"):
            self.helper.inspect_integrated_history(self.repo, bundle, before)
        self.assertEqual(before, self.git("rev-parse", "HEAD").strip())

    def test_recovery_refuses_undeclared_commits_and_unfinished_git_state(self):
        integrated = self.integrate()
        head = integrated["output_oid"]
        (self.repo / "extra.txt").write_text("undeclared implementation change\n")
        with self.assertRaisesRegex(self.helper.RecordError, "clean checkout"):
            self.helper.inspect_integrated_history(self.repo, self.resolve("C"), head)
        self.git("add", ".");self.git("commit", "-m", "extra source outside integration")
        extra = self.git("rev-parse", "HEAD").strip()
        with self.assertRaisesRegex(self.helper.RecordError, "undeclared commits"):
            self.helper.inspect_integrated_history(self.repo, self.resolve("C"), extra)
        self.assertEqual(extra, self.git("rev-parse", "HEAD").strip())

    def test_integration_receipt_binds_exact_input_and_current_predecessor_bytes(self):
        integrated = self.integrate()
        head = self.git("rev-parse", "HEAD").strip()
        output, _ = self.accepted("C", head, input_oid=head, strategy="integration")
        path, digest = self.evidence("integration.json", json.dumps(integrated, sort_keys=True))
        output.update(integration_inputs=integrated["integration_inputs"], integration_evidence_path=path,
                      integration_evidence_sha256=digest)
        self.assertEqual(self.resolve("D")["input_oid"], head)
        for field, value in [("base_oid", self.a), ("output_oid", self.a), ("integration_inputs", [])]:
            bad = dict(integrated, **{field: value})
            output["integration_evidence_path"], output["integration_evidence_sha256"] = self.evidence(
                "integration.json", json.dumps(bad, sort_keys=True))
            with self.subTest(field=field), self.assertRaisesRegex(self.helper.RecordError, "integration receipt"):
                self.resolve("D")
        output["integration_evidence_path"], output["integration_evidence_sha256"] = self.evidence(
            "integration.json", json.dumps(integrated, sort_keys=True))
        self.outputs["A"]["writer_step_id"] = "changed-after-integration"
        with self.assertRaisesRegex(self.helper.RecordError, "integration receipt.*predecessor"):
            self.resolve("D")

    def test_ancestry_valid_behavior_revert_fails_the_same_actual_requirement_check(self):
        import workspace_outputs as producer
        integrated = self.integrate()
        head = integrated["output_oid"]
        output, result = self.accepted("C", head, input_oid=head, strategy="integration")
        path, digest = self.evidence("integration.json", json.dumps(integrated, sort_keys=True))
        output.update(integration_inputs=integrated["integration_inputs"], integration_evidence_path=path,
                      integration_evidence_sha256=digest)
        self.assertEqual(self.resolve("D")["input_oid"], head)
        self.git("rm", "a.txt")
        self.git("commit", "-m", "ancestry-valid removal of required A behavior")
        reverted = self.git("rev-parse", "HEAD").strip()
        self.git("merge-base", "--is-ancestor", self.a, reverted)
        self.git("merge-base", "--is-ancestor", self.b, reverted)
        context = self.contexts["C"]
        binding = dict(context["binding"], output_oid=reverted)
        native = super().native(result)
        identity = {key: native["producer_" + key] for key in ("step_id", "session_id", "attempt_id")}
        checks = producer.execute_checks(binding, self.repo, context["required_checks"], identity, self.root / "revert-proof")
        proof = json.loads(pathlib.Path(checks[0]["evidence_path"]).read_text())
        self.assertEqual(proof["status"], "failed")
        self.assertNotEqual(proof["exit_code"], 0)
        with self.assertRaises(self.helper.RecordError):
            producer.make_member_result(binding, writer_step_id=result["writer_step_id"], commit_oids=[reverted],
                                          checks=checks, review=result["acceptance"]["independent_review"],
                                          artifacts=result["acceptance"]["artifacts"], required_checks=context["required_checks"],
                                          artifact_root=self.root, work_dir=self.repo)
        with self.assertRaisesRegex(self.helper.RecordError, "native acceptance"):
            self.resolve("D")

    def test_dirty_or_advanced_checkout_is_preserved_without_merge(self):
        (self.repo / "work-in-progress.txt").write_text("keep me")
        with self.assertRaisesRegex(self.helper.RecordError, "clean|dirty"):
            self.integrate()
        self.assertEqual((self.repo / "work-in-progress.txt").read_text(), "keep me")
        (self.repo / "work-in-progress.txt").unlink()
        self.git("checkout", "--detach", self.a)
        with self.assertRaisesRegex(self.helper.RecordError, "HEAD|head|base"):
            self.integrate()
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.a)

    def test_integration_requires_native_verifier_before_git_mutation(self):
        with self.assertRaisesRegex(self.helper.RecordError, "native"):
            self.integrate(verify=lambda *_: {"verified": False})
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_attempt_replacement_between_merges_retains_the_completed_first_merge(self):
        def replaced(work_dir, bundle, head):
            result = self.verify(work_dir, bundle, head)
            if len(self.verifications) > 1:
                result["native_attempt_id"] = "replacement-attempt"
            return result
        with self.assertRaisesRegex(self.helper.RecordError, "native"):
            self.integrate(verify=replaced)
        self.assertTrue((self.repo / "b.txt").exists())
        self.assertFalse((self.repo / "a.txt").exists())
        self.git("merge-base", "--is-ancestor", self.b, self.git("rev-parse", "HEAD").strip())

    def test_final_native_refusal_retains_merges_without_returning_accepted_input(self):
        def revoked(work_dir, bundle, head):
            result = self.verify(work_dir, bundle, head)
            if len(self.verifications) == 3:
                result["verified"] = False
            return result
        with self.assertRaisesRegex(self.helper.RecordError, "native"):
            self.integrate(verify=revoked)
        self.assertTrue((self.repo / "a.txt").exists())
        self.assertTrue((self.repo / "b.txt").exists())

    def test_clean_but_unfinished_git_operation_is_refused_without_removal(self):
        marker = self.repo / ".git" / "CHERRY_PICK_HEAD"
        marker.write_text(self.a + "\n")
        with self.assertRaisesRegex(self.helper.RecordError, "prior Git operations"):
            self.integrate()
        self.assertTrue(marker.exists())
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_actual_merge_conflict_is_left_for_explicit_recovery(self):
        self.git("checkout", "-b", "conflict-a", self.base)
        (self.repo / "base.txt").write_text("A version\n")
        self.git("commit", "-am", "conflicting A")
        a = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-b", "conflict-b", self.base)
        (self.repo / "base.txt").write_text("B version\n")
        self.git("commit", "-am", "conflicting B")
        b = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "--detach", self.base)
        self.accepted("A", a)
        self.accepted("B", b)
        with self.assertRaisesRegex(self.helper.RecordError, "conflict|merge"):
            self.integrate()
        self.assertTrue(self.git("diff", "--name-only", "--diff-filter=U").strip())
        self.assertIn("<<<<<<<", (self.repo / "base.txt").read_text())


if __name__ == "__main__":
    unittest.main()
