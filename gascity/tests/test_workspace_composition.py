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

    def test_compiled_fix_planner_keeps_its_actual_source_writer_role(self):
        from workspace_store import _kinds
        steps = {step["id"]: step for step in self.resolve("fix-loop-base")["steps"]}
        actual = steps["plan-fixes"]["metadata"]
        self.assertEqual(actual["gc.run_target"], "gc.review-synthesizer")
        self.assertEqual(_kinds(dict(actual, **{"gc.step_id": "fix-loop-base.plan-fixes"}), "fix-loop-base.plan-fixes"), ["source-plan"])
        self.assertEqual(_kinds({"gc.run_target": "gc.publisher", "gc.step_id": "plan-fixes"}, "plan-fixes"), [])


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
    while key in data['stores']['rig:fixture']:
        data['allocation_counter'] += 1
        key = 'allocated-' + str(data['allocation_counter'])
    data['stores']['rig:fixture'][key] = dict(id=key, revision='1', status='closed',
        assignee='', type='task', labels=[], metadata={},
        title=args[args.index('create')+1], description=option('description'))
    state_path.write_text(json.dumps(data))
    emit(dict(id=key))
if 'bd' in args and 'show' in args:
    emit(data['stores']['rig:fixture'][args[args.index('show')+1]])
if 'bd' in args and 'list' in args and '--desc-contains' in args:
    value=option('desc-contains')
    emit([row for row in data['stores']['rig:fixture'].values() if value in row.get('description','')][:2])
'''
        text = text.replace("if 'list' in args and 'bd' in args:", insert + "if 'list' in args and 'bd' in args:")
        text = text.replace("        result = [rows[i] for i in option('snapshot').split(',')]",
            "        fields={'id','revision','status','assignee','type','labels','metadata','close_reason','closed_by_session'}\n"
            "        result = [{key:value for key,value in rows[i].items() if key in fields} for i in option('snapshot').split(',')]")
        text = text.replace("            for key in item.get('delete', []): row['metadata'].pop(key, None)",
            "            for key in item.get('delete', []): row['metadata'].pop(key, None)\n"
            "            if 'close_reason' in item:\n"
            "                row.update(status='closed', close_reason=item['close_reason'], closed_by_session=request['admission']['session_id'])")
        port.write_text(text)

    def source_closure_fixture(self):
        import hashlib
        from workspace_entry import allocate_placeholder
        from workspace_cooked import read_cooked_writer_map
        from workspace_records import canonical_bytes, contracts
        from workspace_store import Attempt, RecordWrite, ReferenceWrite, record_reference
        from workspace_dependency import FrozenRecords
        f = self.fixture
        f.attempts["closer"] = Attempt("closer-session", "closer-private-instance", "closer")
        metadata = {"gc.run_target": "gc.run-operator"}
        f.rows["closer"] = f.row("closer", dict(metadata, **{"gc.step_id": "do-work.close-source-anchor",
            "gc.step_ref": "do-work.close-source-anchor", "gc.attach_root_id": "expansion",
            "gc.source_anchor_id": "member", "gc.drain_member_id": "member", "gc.session_id": "closer-session",
            "gc.session_name": "closer-runtime", "gc.native_step_dependencies.v1": '["do-work.record-result"]'}))
        session = f.row("closer-session", {"template": "fixture/gc.run-operator", "session_name": "closer-runtime",
            "instance_token": f.attempts["closer"].instance_token, "session_origin": "ephemeral", "state": "asleep",
            "current_claim_bead_id": ""}, scoped=False)
        session["type"] = "session"; f.sessions["closer-session"] = session
        f.formula["steps"].append({"id": "do-work.close-source-anchor", "metadata": metadata})
        f.formula["deps"].append({"step_id": "do-work.close-source-anchor", "depends_on_id": "do-work.record-result", "type": "blocks"})
        # The fixture's provisioned native owner remains, while the first record
        # and authority are published through the actual admitted writer.
        f.rows["workspace-record"]["metadata"].pop(contracts()["workspace"]["metadata_key"])
        f.select_role("producer")
        authority = allocate_placeholder(f.store, title="Workspace writer")
        writer_map, _ = read_cooked_writer_map(f.store, workflow_root_id="root", claimed_step_id="producer")
        state = json.loads((f.root / "port.json").read_text())
        rows = f.store.snapshot(list(state["stores"]["rig:fixture"]))
        scope = dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="workspace")
        prepared = f.store.install_grant(f.attempts["producer"], scope, authority,
            [RecordWrite("workspace", "workspace-record", f.workspace)],
            [ReferenceWrite("member", "gc.workspace_ref", record_reference("workspace", "workspace-record", f.workspace))],
            writer_map=writer_map, expected_rows=rows, guards=FrozenRecords(f.store, rows).guards)
        self.assertEqual(f.store.execute(prepared)["outcome"], "committed")
        self.assertEqual(f.store.resolve(prepared)["outcome"], "committed")
        state = json.loads((f.root / "port.json").read_text())
        f.rows, f.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
        return self.accepted_flow()

    def accepted_flow(self):
        from workspace_flow import WorkspaceFlow
        from workspace_outputs import artifact
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
        output = flow.owner_output("member")
        state = json.loads((f.root / "port.json").read_text())
        f.rows, f.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
        return recorded, output

    def close_flow(self):
        from workspace_flow import WorkspaceFlow
        f = self.fixture
        f.select_role("closer")
        return WorkspaceFlow(f.adapter("closer"))

    def test_connected_accepted_result_closes_source_with_native_reason_and_session(self):
        self.source_closure_fixture()
        f = self.fixture
        result = self.close_flow().close_source("member")
        self.assertEqual(result["status"], "closed")
        state = json.loads((f.root / "port.json").read_text())
        member = state["stores"]["rig:fixture"]["member"]
        self.assertEqual(member["metadata"]["gc.work_outcome"], "shipped")
        self.assertEqual(member["metadata"]["gc.work_commit"], f.oid)
        self.assertNotIn("gc.work_branch", member["metadata"])
        self.assertEqual(member["close_reason"], "Accepted exact workspace result and checkpoint")
        self.assertEqual(member["closed_by_session"], "closer-session")
        commands = [json.loads(line) for line in (f.root / "port.commands").read_text().splitlines()]
        self.assertFalse(any("bd" in command and ("close" in command or "update" in command) for command in commands))

    def test_source_close_late_policy_race_has_no_partial_close_or_writer_transfer(self):
        from workspace_records import RecordError
        self.source_closure_fixture(); f = self.fixture
        flow = self.close_flow()
        before = json.loads((f.root / "port.json").read_text())
        changed = json.loads(json.dumps(before))
        changed["stores"]["rig:fixture"]["run-record"]["revision"] = "999"
        (f.root / "port.json").write_text(json.dumps(changed))
        with self.assertRaises(RecordError):
            flow.close_source("member")
        self.assertEqual(json.loads((f.root / "port.json").read_text()), changed)
        self.assertEqual(changed["stores"]["rig:fixture"]["member"]["status"], "open")

    def test_source_close_lost_reply_resolves_original_in_a_new_process(self):
        from workspace_records import RecordError
        from workspace_store import StoreError
        from workspace_requests import journal_directory, require_resolved_scope
        self.source_closure_fixture(); f = self.fixture
        flow = self.close_flow()
        original = f.store._command
        lost_reply = False

        def unavailable(arguments, attempt=None):
            nonlocal lost_reply
            if any(value.startswith("--request=") for value in arguments):
                original(arguments, attempt)
                lost_reply = True
                raise StoreError("native close response lost after commit")
            if lost_reply:
                raise StoreError("native readback temporarily unavailable")
            return original(arguments, attempt)

        with patch.object(f.store, "_command", side_effect=unavailable):
            with self.assertRaisesRegex(RecordError, "original request without another effect"):
                flow.close_source("member")
        pending = list(journal_directory(f.store).glob("*.pending"))
        self.assertEqual(len(pending), 1)
        path = Path(pending[0].read_text())
        packet = path.read_bytes()
        scope = json.loads(json.loads(packet)["scope_bytes"])
        with self.assertRaises(RecordError):
            require_resolved_scope(f.store, scope)
        commands_before = (f.root / "port.commands").read_text().splitlines()
        script = "from workspace_store import WorkspaceStore; from workspace_requests import resolve_request; import json,sys; store=WorkspaceStore(sys.argv[1],gc=sys.argv[2],cwd=sys.argv[3]); print(json.dumps(resolve_request(store,sys.argv[4])))"
        resolved = subprocess.run([sys.executable, "-B", "-c", script, f.store.store_ref,
            str(f.port), f.store.cwd, str(path)], capture_output=True, text=True, timeout=15)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(json.loads(resolved.stdout)["outcome"], "committed")
        self.assertFalse(pending[0].exists())
        self.assertEqual(path.read_bytes(), packet)
        commands_after = (f.root / "port.commands").read_text().splitlines()
        writes = lambda lines: [line for line in lines if any(value.startswith("--request=") for value in json.loads(line))]
        self.assertEqual(writes(commands_before), writes(commands_after))
        member = json.loads((f.root / "port.json").read_text())["stores"]["rig:fixture"]["member"]
        self.assertEqual(member["status"], "closed")
        self.assertEqual(member["closed_by_session"], "closer-session")

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
