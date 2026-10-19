"""Candidate source composition and native-command-port delivery regressions.

These tests use real Git and native protocol doubles. Worker acceptance is unrun.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib
import unittest
from unittest.mock import patch

from test_formula_assets import resolve_formula_from_dirs

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gascity/assets/scripts"))
PACKS = ("gascity", "compound-engineering", "superpowers", "bmad", "gstack")
DIRECTORIES = [REPO / name / "formulas" for name in PACKS]
POLICY_VARS = ("worktree_lifecycle", "worktree_base_ref", "worktree_checks")


class ComposedFormulaTests(unittest.TestCase):
    def resolve(self, name):
        return resolve_formula_from_dirs(DIRECTORIES, name)

    def test_actual_entries_preserve_policy_and_new_defaults(self):
        names = ("build-basic", "compound-build", "superpowers-build", "bmad-build", "gstack-build",
                 "implement", "build-from-convoy", "build-from-review", "github-issue-fix")
        for name in names:
            with self.subTest(formula=name):
                variables = self.resolve(name)["vars"]
                self.assertEqual(variables["worktree_lifecycle"]["default"], "new")
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

    def test_loaded_pack_imports_require_new_and_preserve_native_policy(self):
        for pack in PACKS:
            directories = [REPO / "gascity/formulas"]
            if pack != "gascity":
                definition = tomllib.loads((REPO / pack / "pack.toml").read_text())
                imported = (REPO / pack / definition["imports"]["gc"]["source"]).resolve()
                self.assertEqual(imported, REPO / "gascity")
                directories.append(REPO / pack / "formulas")
            for path in (REPO / pack / "formulas").glob("*.formula.toml"):
                name = path.name.removesuffix(".formula.toml")
                formula = resolve_formula_from_dirs(directories, name)
                mode = formula.get("vars", {}).get("worktree_lifecycle")
                if mode is not None:
                    with self.subTest(pack=pack, formula=name):
                        self.assertEqual(mode["default"], "new")
                        self.assertEqual(mode["enum"], ["new"])

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

    def test_superpowers_setup_uses_installed_helpers_with_their_pack_schemas(self):
        from test_workspace_entry import EntryTests
        fixture = EntryTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        store, _, _ = fixture.native_snapshot_store()
        port = Path(store.gc)
        registration = dict(city_path=str(fixture.root),
                            rigs=[dict(name="example", path=str(fixture.repo))])
        text = port.read_text().replace("assert args[:4]",
            "if args == ['--city', str(root), 'rig', 'list', '--json']:\n"
            " print(" + repr(json.dumps(registration)) + "); sys.exit(0)\n"
            "assert args[:4]")
        port.write_text(text)
        arguments = ["entry", "read", "--gc", str(port), "--city-root", str(fixture.root),
            "--store-ref", "rig:example", "--rig", "example", "--workflow-root", "root-1",
            "--claimed-step", "step-1", "--worktree-lifecycle", "new"]
        copied = fixture.repo / ".gc/scripts"
        shutil.copytree(REPO / "gascity/assets/scripts", copied)
        before = (fixture.root / "native-rows.json").read_bytes()
        relocated = subprocess.run([sys.executable, "-B", str(copied / "workspace_entry.py"),
            *arguments[1:]], cwd=fixture.repo, text=True, capture_output=True, timeout=15)
        self.assertEqual(relocated.returncode, 1)
        self.assertIn(str(fixture.repo / "schemas/workspace/records.v1.json"), relocated.stderr)
        installed = subprocess.run([str(REPO / "gascity/commands/workspace/run.sh"), *arguments],
            cwd=fixture.repo, env=dict(os.environ, GC_PACK_DIR=str(REPO / "gascity"),
                PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]),
            text=True, capture_output=True, timeout=15)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout)["run"], fixture.record)
        self.assertEqual((fixture.root / "native-rows.json").read_bytes(), before)
        for stage in ("brainstorming", "plan-review"):
            setup = (REPO / "superpowers/assets/workflows" / ("superpowers-" + stage)
                     / ("{target}.setup-superpowers-" + stage + ".md")).read_text()
            with self.subTest(stage=stage):
                self.assertIn("gc.check_path", setup)
                self.assertNotIn(".gc/scripts", setup)
        contract = (REPO / "gascity/assets/workflows/workspace-entry.md").read_text()
        self.assertIn("gc gc workspace entry", contract)
        self.assertIn("schemas/workspace/records.v1.json", contract)

    def test_superpowers_callers_keep_native_control_identity_and_imported_validators(self):
        assets = REPO / "superpowers/assets/workflows"
        for path in assets.rglob("*.md"):
            with self.subTest(asset=path.relative_to(assets)):
                self.assertNotIn(".gc/scripts", path.read_text())
        for stage in ("brainstorming", "code-review"):
            text = (assets / ("superpowers-" + stage) / "{target}.md").read_text()
            with self.subTest(stage=stage):
                self.assertIn('GC_BEAD_ID=<control-bead-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"', text)
                self.assertNotIn("GC_BEAD_ID=<claimed-step-id>", text)
        for stage, feedback in (("brainstorming", "spec"), ("plan-review", "plan")):
            text = (assets / ("superpowers-" + stage)
                    / ("{target}.apply-" + feedback + "-feedback.md")).read_text()
            with self.subTest(stage=stage):
                self.assertIn("canonical imported `gc` pack's `assets/scripts`", text)
                self.assertIn('python3 "<gc-scripts-dir>/validate_build_artifact.py" --schema gc.build.requirements.v1', text)
                if stage == "plan-review":
                    self.assertIn('python3 "<gc-scripts-dir>/validate_build_artifact.py" --schema gc.build.plan.v1', text)

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
        script = "import json,sys; sys.path.insert(0,sys.argv.pop(1)); from workspace_store import WorkspaceStore; from workspace_requests import resolve_request; store=WorkspaceStore(sys.argv[1],gc=sys.argv[2],cwd=sys.argv[3]); print(json.dumps(resolve_request(store,sys.argv[4])))"
        resolved = subprocess.run([sys.executable, "-B", "-c", script, str(REPO / "gascity/assets/scripts"), f.store.store_ref,
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
        for number in range(105):
            bead_id = "readonly-" + str(number)
            step = "do-work." + bead_id
            designation = {"gc.run_target": "gc.implementation-worker"}
            f.formula["steps"].append({"id": step, "metadata": designation})
            f.rows[bead_id] = f.row(bead_id, dict(designation, **{"gc.step_id": step,
                "gc.step_ref": step, "gc.attach_root_id": "expansion", "gc.source_anchor_id": "member",
                "gc.drain_member_id": "member", "gc.native_step_dependencies.v1": "[]"}), status="closed")
        f.workspace.update(phase="active", current_oid=f.base, output_oid=None)
        from workspace_records import contracts
        from workspace_entry import allocate_placeholder
        from workspace_dependency import FrozenRecords
        from workspace_store import NativeWorktreeReference, RecordWrite, ReferenceWrite, merge_cooked_context, record_reference
        f.rows["workspace-record"]["metadata"].pop(contracts()["workspace"]["metadata_key"])
        f.select_role("producer")
        authority = allocate_placeholder(f.store, title="Workspace writer")
        runtime = f.adapter("producer")
        writer_map = runtime.writer_map
        selected = runtime.guard_rows
        selected.update(f.store.snapshot([authority, "workspace-record", "member"]))
        launch = json.loads(f.rows["producer"]["metadata"]["gc.worktree_ref"])
        prepared = f.store.install_grant(f.attempts["producer"],
            dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="workspace"),
            authority, [RecordWrite("workspace", "workspace-record", f.workspace)],
            [ReferenceWrite("member", "gc.workspace_ref", record_reference("workspace", "workspace-record", f.workspace))],
            writer_map=writer_map, expected_rows=merge_cooked_context(runtime.original_rows, selected),
            guards=FrozenRecords(f.store, selected).guards,
            projections=[NativeWorktreeReference(role, "workspace-record", dict(launch, binding_step_id=role))
                         for role in ("producer", "reviewer", "recorder")])
        self.assertEqual("committed", f.store.execute(prepared)["outcome"])
        self.assertEqual("committed", f.store.resolve(prepared)["outcome"])
        state = json.loads((f.root / "port.json").read_text())
        f.rows, f.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
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
        self.assertEqual(state["allocation_counter"], 5)
        member = state["stores"]["rig:fixture"]["member"]["metadata"]
        self.assertIn("gc.workspace_result_ref", member)
        self.assertIn("gc.workspace_output_ref", member)
        self.assertGreater(len(flow.runtime.original_rows), 100)
        self.assertLessEqual(len(flow.runtime.guard_rows), 100)
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

    def test_overlapping_actual_flow_commands_retain_each_accepted_publication(self):
        from workspace_records import canonical_bytes, contracts
        f = self.fixture
        recorded, output = self.accepted_flow()
        state_path = f.root / "port.json"
        before = json.loads(state_path.read_text())
        for row in before["stores"]["rig:fixture"].values():
            row["metadata"]["typed-sibling"] = [True, 3, {"x": None}]
        state_path.write_text(json.dumps(before))
        wrapper = f.root / "overlapping-flow.py"
        wrapper.write_text('''import contextlib, pathlib, sys, time
import workspace_flow, workspace_runtime, workspace_store
role, directory = sys.argv[1:3]
directory = pathlib.Path(directory)
def wait(path):
    deadline = time.monotonic() + 20
    while not path.exists():
        if time.monotonic() >= deadline: raise RuntimeError("missing overlap signal: " + str(path))
        time.sleep(0.01)
original_init = workspace_runtime.NativeSourceRuntime.__init__
def admitted(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    (directory / (role + "-admitted")).touch()
    if role == "first": wait(directory / "release-first")
workspace_runtime.NativeSourceRuntime.__init__ = admitted
original_lock = workspace_store.transition_locks
@contextlib.contextmanager
def observed_lock(*args, **kwargs):
    if role == "second": (directory / "second-lock-attempt").touch()
    with original_lock(*args, **kwargs): yield
workspace_store.transition_locks = observed_lock
workspace_runtime.transition_locks = observed_lock
raise SystemExit(workspace_flow.main(sys.argv[3:]))
''')
        evidence = {}
        for name, value in (("checks", recorded["result"]["acceptance"]["project_checks"]),
                            ("review", recorded["result"]["acceptance"]["independent_review"]),
                            ("artifacts", recorded["result"]["acceptance"]["artifacts"])):
            path = f.artifacts / ("overlap-" + name + ".json")
            path.write_bytes(canonical_bytes(value))
            evidence[name] = str(path)
        common = ["--gc", str(f.port), "--city-root", str(f.city), "--store-ref", "rig:fixture",
            "--rig-name", "fixture", "--workflow-root-id", "root", "--claimed-step-id", "recorder",
            "--generation", "1", "--artifact-root", str(f.artifacts), "--evidence-dir", str(f.diagnostics),
            "--owner-id", "member"]
        args = ["record-result", *common, "--member-id", "member", "--output-oid", f.oid,
            "--checks", evidence["checks"], "--review", evidence["review"], "--artifacts", evidence["artifacts"]]
        environment = dict(os.environ, PYTHONPATH=str(REPO / "gascity/assets/scripts"))
        children = []
        def launch(role, arguments):
            child = subprocess.Popen([sys.executable, "-B", str(wrapper), role, str(f.root), *arguments],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
            children.append(child)
            return child
        def wait_signal(name):
            deadline = time.monotonic() + 20
            while not (f.root / name).exists():
                self.assertTrue(all(child.poll() is None for child in children), "flow exited before overlap")
                self.assertLess(time.monotonic(), deadline, "missing overlap signal: " + name)
                time.sleep(0.01)
        try:
            first = launch("first", args)
            wait_signal("first-admitted")
            second = launch("second", ["owner-output", *common])
            wait_signal("second-lock-attempt")
            (f.root / "release-first").touch()
            first_out, first_err = first.communicate(timeout=60)
            second_out, second_err = second.communicate(timeout=60)
            self.assertEqual(first.returncode, 0, first_err)
            self.assertEqual(second.returncode, 0, second_err)
        finally:
            (f.root / "release-first").touch()
            for child in children:
                if child.poll() is None: child.terminate()
                child.communicate(timeout=10)
        self.assertEqual(json.loads(first_out)["result"], recorded["result"])
        self.assertEqual(json.loads(second_out)["output"], output["output"])
        after = json.loads(state_path.read_text())
        self.assertEqual(after["allocation_counter"], before["allocation_counter"])
        self.assertEqual(set(after["stores"]["rig:fixture"]), set(before["stores"]["rig:fixture"]))
        keys = [definition["metadata_key"] for definition in contracts().values()]
        for bead_id, row in before["stores"]["rig:fixture"].items():
            current = after["stores"]["rig:fixture"][bead_id]
            self.assertEqual(current["metadata"]["typed-sibling"], row["metadata"]["typed-sibling"])
            for key in keys:
                self.assertEqual(current["metadata"].get(key), row["metadata"].get(key))
                self.assertEqual(current["metadata"].get(key + "_ref"), row["metadata"].get(key + "_ref"))


if __name__ == "__main__":
    unittest.main()
