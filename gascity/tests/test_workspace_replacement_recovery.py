"""Replacement recovery over real Git and the native command protocol doubles."""
from __future__ import annotations

import copy
import json
import os
import hashlib
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workspace_composition as composition
import test_workspace_run as run_fixtures
from workspace_records import RecordError, canonical_bytes
from workspace_store import Attempt, CookedWriterMap, GRANT_KEY
import workspace_entry as entry
import workspace_flow as flow_module
from workspace_requests import allocation_directory, journal_directory, resolve_request


class FlowReplacementTests(unittest.TestCase):
    def setUp(self):
        self.original = composition.ComposedFlowTests("runTest")
        self.original.setUp()
        self.addCleanup(self.original.doCleanups)
        self.fixture = self.original.fixture

    def rotate(self):
        f = self.fixture
        state = json.loads((f.root / "port.json").read_text())
        f.rows.update(copy.deepcopy(state["stores"]["rig:fixture"]))
        old = f.attempts["recorder"]
        current = Attempt(old.session_id, "replacement-recorder-instance", old.claimed_bead_id)
        f.attempts["recorder"] = current
        f.sessions[old.session_id]["metadata"]["instance_token"] = current.instance_token
        f.rows[old.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
        f.rows[old.claimed_bead_id]["revision"] = str(int(f.rows[old.claimed_bead_id]["revision"]) + 1)
        f.select_role("recorder")
        return current

    def test_ready_native_ids_survive_actual_recorder_replacement_without_new_creation(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocated = original._allocation("member-result", "member", "member")
        before = json.loads((f.root / "port.json").read_text())
        self.rotate()
        recovered = flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(recovered, allocated)
        after = json.loads((f.root / "port.json").read_text())
        self.assertEqual(set(after["stores"]["rig:fixture"]), set(before["stores"]["rig:fixture"]))
        self.assertEqual(after["stores"]["rig:fixture"][allocated["record_id"]],
                         before["stores"]["rig:fixture"][allocated["record_id"]])
        with self.assertRaises(RecordError):
            original._allocation("member-result", "member", "member")

    def commands(self):
        return [json.loads(line) for line in (self.fixture.root / "port.commands").read_text().splitlines()]

    def creates(self):
        return sum("create" in command and "bd" in command for command in self.commands())

    def lose_next_reply(self, index=1):
        f = self.fixture
        port = f.port.read_text()
        port = port.replace("    emit(dict(id=key))", "    if data.get('lose_allocation_ack_at') == data['allocation_counter']:\n"
                            "        sys.exit('native create committed; acknowledgement lost')\n    emit(dict(id=key))")
        port = port.replace("    value=option('desc-contains')", "    value=option('desc-contains')\n"
            "    if 'allocation_lookup_response' in data: emit(data['allocation_lookup_response'])")
        f.port.write_text(port)
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        state["lose_allocation_ack_at"] = index
        path.write_text(json.dumps(state))

    def fresh_allocation(self, *, expected_success=True):
        f = self.fixture
        script = """import json,sys
from pathlib import Path
from workspace_store import WorkspaceStore
from workspace_runtime import NativeSourceRuntime
from workspace_flow import WorkspaceFlow
p,city,common,artifacts,evidence=sys.argv[1:]
state=json.loads(Path(p).with_name('port.json').read_text());rows=state['stores']['rig:fixture']
run=json.loads(rows['run-record']['metadata']['gc.implementation_run'])
plan=json.loads(rows['plan-record']['metadata']['gc.source_plan'])
store=WorkspaceStore('rig:fixture',gc=p,cwd=city,common_git_dir=common)
runtime=NativeSourceRuntime(store,gc=p,city_root=city,rig_name='fixture',run=run,plan=plan,
 artifact_root=artifacts,evidence_dir=evidence,claimed_step_id='recorder')
print(json.dumps(WorkspaceFlow(runtime)._allocation('member-result','member','member')))
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(flow_module.__file__).parent))
        result = subprocess.run([sys.executable, "-B", "-c", script, str(f.port), str(f.city),
            str(f.repo / ".git"), str(f.artifacts), str(f.diagnostics)], text=True,
            capture_output=True, env=environment, timeout=60)
        if expected_success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def test_unknown_created_role_is_found_readonly_by_original_description_in_new_process(self):
        f = self.fixture
        self.lose_next_reply(index=2)
        original = flow_module.WorkspaceFlow(f.adapter())
        with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
            original._allocation("member-result", "member", "member")
        intent = next(allocation_directory(f.store).glob("*.intent.json"))
        before = intent.read_bytes()
        self.rotate()
        recovered = self.fresh_allocation()
        self.assertEqual(recovered["record_id"], "allocated-1")
        self.assertEqual(recovered["authority_id"], "allocated-2")
        self.assertEqual(self.creates(), 2)
        self.assertEqual(intent.read_bytes(), before)
        query = [command for command in self.commands() if "--desc-contains" in command]
        self.assertEqual(len(query), 1)
        self.assertTrue(all(flag in query[0] for flag in ("--all", "--limit", "--json", "--readonly")))
        self.assertEqual(query[0][query[0].index("--limit") + 1], "2")
        self.assertFalse(any("sling" in command or "start" in command for command in self.commands()))

    def test_zero_duplicate_object_or_wrong_identity_lookup_blocks_without_another_create(self):
        f = self.fixture
        self.lose_next_reply()
        with self.assertRaises(RecordError):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.rotate()
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        row = copy.deepcopy(state["stores"]["rig:fixture"]["allocated-1"])
        for value in ([], [row, row], row, None, [dict(row, title="wrong")],
                      [dict(row, description="wrong")], [dict(row, id="")]):
            with self.subTest(response=value):
                current = json.loads(path.read_text())
                current["allocation_lookup_response"] = value
                path.write_text(json.dumps(current))
                refused = self.fresh_allocation(expected_success=False)
                self.assertIn("no known physical ID", refused.stderr)
                self.assertEqual(self.creates(), 1)

    def test_ready_receipt_keeps_original_revision_across_replacement(self):
        f = self.fixture
        flow = flow_module.WorkspaceFlow(f.adapter())
        allocated = flow._allocation("member-result", "member", "member")
        self.rotate()
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        state["stores"]["rig:fixture"][allocated["record_id"]]["revision"] = "2"
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(RecordError, "changed since its original receipt"):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(self.creates(), 2)

    def test_null_origin_or_invalid_attempt_or_nonce_refuses_before_native_allocation_reads(self):
        f = self.fixture
        flow = flow_module.WorkspaceFlow(f.adapter())
        flow._allocation("member-result", "member", "member")
        intent = next(allocation_directory(f.store).glob("*.intent.json"))
        original = json.loads(intent.read_text())
        for change in ({"origin": None}, {"origin": dict(original["origin"], attempt={"session_id": None,
                       "instance_token": "token", "claimed_bead_id": "recorder"})}, {"nonce": "g" * 64}):
            with self.subTest(change=change):
                intent.write_bytes(canonical_bytes(dict(original, **change)))
                before = len(self.commands())
                with self.assertRaises(RecordError):
                    flow._allocation("member-result", "member", "member")
                added = self.commands()[before:]
                self.assertFalse(any("create" in command or "show" in command or "--desc-contains" in command
                                     for command in added))
        intent.write_bytes(canonical_bytes(original))

    def test_installed_result_replay_replaces_only_current_native_writer_in_same_batch(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocation = original._allocation("member-result", "member", "member")
        prepared = original.runtime.prepare_member_result(f.result, **allocation)
        original._commit(prepared, f.result)
        state = json.loads((f.root / "port.json").read_text())
        payload = state["stores"]["rig:fixture"][allocation["record_id"]]["metadata"]["gc.workspace_result"]
        current = self.rotate()
        replacement = flow_module.WorkspaceFlow(f.adapter())
        existing = replacement._allocation("member-result", "member", "member")
        self.assertFalse(existing["initial_write"])
        prepared = replacement.runtime.prepare_member_result(f.result, **existing)
        request = json.loads(prepared.request_bytes)
        authority = next(row for row in request["rows"] if row["id"] == allocation["authority_id"])
        self.assertEqual(json.loads(authority["set"][GRANT_KEY])["attempt"], current.admission)
        self.assertIn(allocation["record_id"], {row["id"] for row in request["rows"]})
        self.assertIn("member", {row["id"] for row in request["rows"]})
        receipt = replacement._commit(prepared, f.result)
        self.assertEqual(receipt["outcome"], "replayed")
        state = json.loads((f.root / "port.json").read_text())
        self.assertEqual(state["stores"]["rig:fixture"][allocation["record_id"]]["metadata"]["gc.workspace_result"], payload)
        self.assertEqual(self.creates(), 2)
        with self.assertRaises(RecordError):
            original._allocation("member-result", "member", "member")


    def test_pending_original_write_blocks_replacement_before_new_effects(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocated = original._allocation("member-result", "member", "member")
        prepared = original.runtime.prepare_member_result(f.result, **allocated)
        state_path = f.root / "port.json"
        state = json.loads(state_path.read_text())
        state["lose_write_ack"] = True
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(RecordError, "original request"):
            original._commit(prepared, f.result)
        pending = next(journal_directory(f.store).glob("*.pending"))
        request = Path(pending.read_text())
        retained = request.read_bytes()
        state = json.loads(state_path.read_text())
        state.pop("lose_write_ack"); state.pop("block_readback")
        state_path.write_text(json.dumps(state))
        self.rotate()
        other = f.root / "other-diagnostics"
        other.mkdir()
        f.diagnostics = other
        with self.assertRaisesRegex(RecordError, "original retained request"):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(self.creates(), 2)
        # A changed native claim cannot be guessed into the original after-state.
        resolved = resolve_request(f.store, request)
        self.assertEqual(resolved["outcome"], "unknown")
        self.assertTrue(pending.exists())
        self.assertEqual(request.read_bytes(), retained)
        writes = [command for command in self.commands() if "guarded-metadata-batch" in command
                  and any(arg == "--request" or arg.startswith("--request=") for arg in command)]
        self.assertEqual(len(writes), 1)


    def test_malformed_existing_record_or_grant_reference_refuses_before_creation(self):
        from workspace_store import GRANT_REFS_KEY
        f = self.fixture
        path = f.root / "port.json"
        original = json.loads(path.read_text())
        scope = dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="member-result")
        scope_hash = hashlib.sha256(canonical_bytes(scope)).hexdigest()
        sibling = dict(scope, writer_scope_id="plan-owner", record_kind="canonical")
        sibling_hash = hashlib.sha256(canonical_bytes(sibling)).hexdigest()
        malformed_indices = [dict(version=1, scopes={scope_hash: value}) for value in (None, "", {})]
        malformed_indices += [dict(version=1, scopes={"sibling": None}),
            dict(version=1, scopes={scope_hash: dict(scope=scope, authority_id="same-authority"),
                sibling_hash: dict(scope=sibling, authority_id="same-authority")}),
            dict(version=1, scopes={scope_hash: dict(scope=dict(scope, workflow_root_id="wrong-root"), authority_id="record")})]
        changes = [("member", "gc.workspace_result_ref", None), ("member", "gc.workspace_result_ref", ""),
            ("root", GRANT_REFS_KEY, None), ("root", GRANT_REFS_KEY, ""), ("root", GRANT_REFS_KEY, "{}")]
        changes += [("root", GRANT_REFS_KEY, canonical_bytes(value).decode()) for value in malformed_indices]
        for owner, key, value in changes:
            with self.subTest(owner=owner, value=value):
                current = copy.deepcopy(original)
                current["stores"]["rig:fixture"][owner]["metadata"][key] = value
                path.write_text(json.dumps(current))
                with self.assertRaises(RecordError):
                    flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
                self.assertEqual(self.creates(), 0)
        path.write_text(json.dumps(original))


    def test_canonical_review_and_fix_resume_exact_source_in_fresh_cli_processes(self):
        from test_workspace_dependency import WORKTREE_PORT
        from workspace_dependency import FrozenRecords
        from workspace_entry import allocate_placeholder
        from workspace_records import contracts, record_sha256
        from workspace_store import (NativeWorktreeReference, RecordWrite, ReferenceWrite,
                                     TOPOLOGY, merge_cooked_context, record_reference)
        import workspace_outputs as outputs

        f = self.fixture
        scripts = Path(flow_module.__file__).parent
        # These are initial cooked occurrences, not repairs to an accepted record.
        previous = 'do-work.record-result'
        for role, stage, target in (('canonical', 'record-canonical', 'gc.run-operator'),
                ('canonical-reviewer', 'review-result', 'gc.implementation-reviewer'),
                ('fixer', 'plan-fixes', 'gc.review-synthesizer')):
            ref = 'do-work.' + stage
            f.attempts[role] = Attempt(role + '-session', role + '-private-instance', role)
            metadata = {'gc.run_target': target}
            f.formula['steps'].append(dict(id=ref, metadata=metadata))
            f.formula['deps'].append(dict(step_id=ref, depends_on_id=previous, type='blocks'))
            f.rows[role] = f.row(role, dict(metadata, **{'gc.step_id': ref, 'gc.step_ref': ref,
                'gc.attach_root_id': 'expansion', 'gc.source_anchor_id': 'member',
                'gc.drain_member_id': 'member', 'gc.session_id': role + '-session',
                'gc.session_name': role + '-runtime', TOPOLOGY: canonical_bytes([previous]).decode()}))
            f.sessions[role + '-session'] = f.row(role + '-session', {
                'template': 'fixture/' + target, 'session_name': role + '-runtime',
                'instance_token': f.attempts[role].instance_token, 'session_origin': 'ephemeral',
                'state': 'asleep', 'current_claim_bead_id': ''}, scoped=False)
            f.sessions[role + '-session']['type'] = 'session'
            previous = ref
        scope = {'gc.source_root_id': 'root', 'gc.source_generation': '2'}
        f.rows['fix-member'] = f.row('fix-member', scope)
        f.rows['fix-convoy'] = f.row('fix-convoy', scope)
        f.rows['fix-convoy']['type'] = 'convoy'
        f.rows['fix-expansion'] = f.row('fix-expansion', copy.deepcopy(f.rows['expansion']['metadata']))
        role = 'fix-prepare'
        f.attempts[role] = Attempt(role + '-session', role + '-private-instance', role)
        metadata = {'gc.run_target': 'gc.run-operator'}
        f.formula['steps'].append(dict(id='do-work.prepare-worktree', metadata=metadata))
        f.rows[role] = f.row(role, dict(metadata, **{'gc.step_id': 'do-work.prepare-worktree',
            'gc.step_ref': 'do-work.prepare-worktree', 'gc.attach_root_id': 'fix-expansion',
            'gc.source_anchor_id': 'fix-member', 'gc.drain_member_id': 'fix-member',
            'gc.session_id': role + '-session', 'gc.session_name': role + '-runtime', TOPOLOGY: '[]'}))
        f.sessions[role + '-session'] = f.row(role + '-session', {
            'template': 'fixture/gc.run-operator', 'session_name': role + '-runtime',
            'instance_token': f.attempts[role].instance_token, 'session_origin': 'ephemeral',
            'state': 'asleep', 'current_claim_bead_id': ''}, scoped=False)
        f.sessions[role + '-session']['type'] = 'session'
        f.rows['root']['metadata'].update({'gc.var.worktree_parent': str(f.work.parent),
                                         'gc.var.worktree_allow_external_parent': 'true'})
        port = f.port.read_text()
        f.port.write_text(port[:port.index("if 'worktree' in args:")] + WORKTREE_PORT +
                          "\nsys.exit('unsupported command ' + repr(args))\n")
        f.workspace.update(phase='active', current_oid=f.base, output_oid=None)
        f.rows['workspace-record']['metadata'].pop(contracts()['workspace']['metadata_key'])
        f.select_role('producer')
        runtime = f.adapter('producer')
        authority = allocate_placeholder(f.store, title='Workspace writer')
        selected = runtime.guard_rows
        selected.update(f.store.snapshot([authority, 'workspace-record', 'member']))
        launch = json.loads(f.rows['producer']['metadata']['gc.worktree_ref'])
        prepared = f.store.install_grant(f.attempts['producer'],
            dict(workflow_root_id='root', generation=1, writer_scope_id='member', record_kind='workspace'),
            authority, [RecordWrite('workspace', 'workspace-record', f.workspace)],
            [ReferenceWrite('member', 'gc.workspace_ref', record_reference('workspace', 'workspace-record', f.workspace))],
            writer_map=runtime.writer_map, expected_rows=merge_cooked_context(runtime.original_rows, selected),
            guards=FrozenRecords(f.store, selected).guards,
            projections=[NativeWorktreeReference(role, 'workspace-record', dict(launch, binding_step_id=role))
                         for role in ('producer', 'reviewer', 'recorder', 'canonical', 'canonical-reviewer', 'fixer')])
        self.assertEqual('committed', f.store.execute(prepared)['outcome'])
        self.assertEqual('committed', f.store.resolve(prepared)['outcome'])
        state_path = f.root / 'port.json'
        state = json.loads(state_path.read_text())
        f.rows, f.sessions = state['stores']['rig:fixture'], state['stores']['city:fixture']
        recorded, published = self.original.accepted_flow()
        result, owner_output = recorded['result'], published['output']
        self.assertEqual('accepted', result['acceptance']['status'])
        self.assertEqual(record_sha256(result), owner_output['final_member_result_sha256'])
        before_workspace = json.loads(f.rows['workspace-record']['metadata']['gc.workspace'])
        before_run = f.rows['run-record']['metadata']['gc.implementation_run']
        before_checks = copy.deepcopy(result['acceptance']['project_checks'])

        def select(role):
            state = json.loads(state_path.read_text())
            f.rows, f.sessions = state['stores']['rig:fixture'], state['stores']['city:fixture']
            f.select_role(role)

        def cli(role, action, *arguments, code=0):
            command = [sys.executable, '-B', str(scripts / 'workspace_flow.py'), action,
                '--gc', str(f.port), '--city-root', str(f.city), '--store-ref', 'rig:fixture',
                '--rig-name', 'fixture', '--workflow-root-id', 'root', '--claimed-step-id', role,
                '--artifact-root', str(f.artifacts), '--evidence-dir', str(f.diagnostics),
                '--generation', '1', *arguments]
            completed = subprocess.run(command, text=True, capture_output=True, timeout=120)
            self.assertEqual(code, completed.returncode, completed.stdout + completed.stderr)
            return json.loads(completed.stdout) if completed.stdout else None

        select('canonical')
        canonical = cli('canonical', 'canonical', '--summary', str(f.summary))['canonical']
        self.assertEqual(f.oid, canonical['output_oid'])
        self.assertEqual(f.base, result['input_oid'])
        (f.repo / 'feature.py').write_text('VALUE = -1 # later controller default\n')
        f.git(f.repo, 'add', 'feature.py')
        f.git(f.repo, 'commit', '-qm', 'move controller default after accepted canonical')
        controller_head = f.git(f.repo, 'rev-parse', 'HEAD')
        self.assertNotEqual(f.oid, controller_head)
        select('canonical-reviewer')
        baseline = json.loads(state_path.read_text())
        for fault in ('store', 'owner', 'generation', 'malformed'):
            with self.subTest(replacement_refusal=fault):
                changed = copy.deepcopy(baseline)
                rows = changed['stores']['rig:fixture']
                if fault == 'store':
                    rows['root']['metadata']['gc.root_store_ref'] = 'rig:foreign'
                else:
                    result_ref = json.loads(rows['member']['metadata']['gc.workspace_result_ref'])
                    if fault == 'malformed':
                        value = '{'
                    else:
                        value = canonical_bytes(dict(result, **({'workspace_owner_id': 'foreign'}
                            if fault == 'owner' else {'generation': 2}))).decode()
                    rows[result_ref['bead_id']]['metadata']['gc.workspace_result'] = value
                state_path.write_text(json.dumps(changed))
                try:
                    self.assertIsNone(cli('canonical-reviewer', 'begin-canonical-review', code=1))
                    self.assertEqual(changed, json.loads(state_path.read_text()))
                    self.assertEqual(f.oid, f.git(f.work, 'rev-parse', 'HEAD'))
                    self.assertEqual(controller_head, f.git(f.repo, 'rev-parse', 'HEAD'))
                finally:
                    state_path.write_text(json.dumps(baseline))
        context = cli('canonical-reviewer', 'begin-canonical-review')
        self.assertEqual(record_sha256(result), context['result_sha256'])
        self.assertEqual(record_sha256(canonical), context['canonical_sha256'])
        self.assertEqual(before_checks, context['context']['checks'])
        context_path = f.artifacts / 'replacement-canonical-context.json'
        outputs.immutable_json(context_path, context)
        report = f.artifacts / 'replacement-canonical-findings.md'
        report.write_text('The exact accepted source needs the bounded follow-up in generation two.\n')
        complete = ('--context', str(context_path), '--report', str(report), '--status', 'failed',
                    '--review-evidence', str(f.artifacts / 'replacement-canonical-review.json'))
        state = json.loads(state_path.read_text())
        stale_path = f.artifacts / 'stale-canonical-context.json'
        stale_path.write_bytes(canonical_bytes(dict(context, result_sha256='0' * 64)))
        stale = list(complete); stale[1] = str(stale_path)
        self.assertIsNone(cli('canonical-reviewer', 'complete-canonical-review', *stale, code=1))
        self.assertEqual(state, json.loads(state_path.read_text()))
        summary = f.summary.read_bytes()
        try:
            f.summary.write_bytes(summary + b'artifact drift\n')
            self.assertIsNone(cli('canonical-reviewer', 'complete-canonical-review', *complete, code=1))
            self.assertEqual(state, json.loads(state_path.read_text()))
        finally:
            f.summary.write_bytes(summary)
        # A failed review is a recorded finding, so its native CLI exits one.
        reviewed = cli('canonical-reviewer', 'complete-canonical-review', *complete, code=1)
        findings = reviewed['review']
        self.assertEqual('changes_required', findings['verdict'])
        self.assertEqual(record_sha256(canonical), findings['canonical_record_sha256'])
        self.assertEqual(f.oid, findings['reviewed_oid'])
        state = json.loads(state_path.read_text())
        review_ref = json.loads(state['stores']['rig:fixture']['root']['metadata']['gc.review_ref'])
        self.assertEqual(findings, json.loads(state['stores']['rig:fixture'][review_ref['bead_id']]['metadata']['gc.review']))

        select('fixer')
        nodes = [dict(owner_id='fix-member', strategy='isolated', member_ids=['fix-member'],
                      source_predecessor_owner_ids=[], single_lane=False)]
        nodes_path = f.artifacts / 'replacement-fix-nodes.json'
        nodes_path.write_bytes(canonical_bytes(nodes))
        fixed = cli('fixer', 'fix-plan', '--nodes', str(nodes_path), '--plan-owner-id', 'fixer',
                    '--terminal-owner-id', 'fix-member', '--implementation-convoy-id', 'fix-convoy',
                    '--max-iterations', '2')['source_plan']
        self.assertEqual(2, fixed['generation'])
        self.assertEqual(f.oid, fixed['base_oid'])
        self.assertEqual(f.oid, fixed['parent_canonical_oid'])
        self.assertEqual(1, fixed['parent_canonical_generation'])
        state = json.loads(state_path.read_text())
        rows = state['stores']['rig:fixture']
        self.assertEqual(before_run, rows['run-record']['metadata']['gc.implementation_run'])
        self.assertEqual(before_workspace, json.loads(rows['workspace-record']['metadata']['gc.workspace']))
        result_ref = json.loads(rows['member']['metadata']['gc.workspace_result_ref'])
        retained = json.loads(rows[result_ref['bead_id']]['metadata']['gc.workspace_result'])
        self.assertEqual(result, retained)
        self.assertEqual(before_checks, retained['acceptance']['project_checks'])
        self.assertEqual(f.oid, f.git(f.work, 'rev-parse', 'HEAD'))

        # Prepare and continue the published fix in two more fresh CLI processes.
        select('fix-prepare')
        command = [sys.executable, '-B', str(scripts / 'workspace_dependency.py'),
            '--gc', str(f.port), '--worktree-lifecycle', 'new', '--city-root', str(f.city),
            '--rig-name', 'fixture', '--store-ref', 'rig:fixture', '--workflow-root-id', 'root',
            '--input-convoy-id', 'fix-convoy', '--generation', '2', '--workspace-owner-id', 'fix-member',
            '--member-id', 'fix-member', '--claimed-step-id', 'fix-prepare',
            '--artifact-root', str(f.artifacts), '--evidence-dir', str(f.diagnostics),
            '--parent', str(f.work.parent), '--allow-external-parent']
        prepared = subprocess.run(command, text=True, capture_output=True, timeout=120)
        self.assertEqual(0, prepared.returncode, prepared.stderr)
        initial = json.loads(prepared.stdout)
        self.assertEqual(f.oid, initial['input_oid'])
        self.assertEqual(f.oid, initial['workspace']['native_provenance']['base_sha'])
        self.assertNotEqual(controller_head, initial['input_oid'])
        self.assertEqual(f.run['common_git_dir'], initial['workspace']['native_provenance']['repo_identity'])
        self.assertEqual('fix-member', initial['workspace']['native_provenance']['owner'])
        self.assertEqual('2', initial['workspace']['native_provenance']['generation'])
        native_ids = set(json.loads(state_path.read_text())['stores']['rig:fixture'])
        continued = subprocess.run(command, text=True, capture_output=True, timeout=120)
        self.assertEqual(0, continued.returncode, continued.stderr)
        resumed = json.loads(continued.stdout)
        self.assertEqual('continuation', resumed['state'])
        for key in ('workspace_record_id', 'authority_id', 'path', 'input_oid'):
            self.assertEqual(initial[key], resumed[key])
        self.assertEqual(initial['workspace']['native_provenance'], resumed['workspace']['native_provenance'])
        self.assertEqual(native_ids, set(json.loads(state_path.read_text())['stores']['rig:fixture']))
        self.assertEqual(f.oid, f.git(Path(resumed['path']), 'rev-parse', 'HEAD'))



class RunReplacementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = run_fixtures.RunStoreTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_known_initial_ids_survive_replacement_with_original_base_and_source_intent(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=2)
        args = f.allocation_args()
        with patch.object(module, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                module.allocate_run_placeholders(f.store, f.attempt, **args)
            intent = next((f.repo / ".git" / "gc-workspace-locks").rglob("*.intent.json"))
            original = intent.read_bytes()
            (f.repo / "file").write_text("later default\n")
            f.git("commit", "-am", "later default")
            current = Attempt(f.attempt.session_id, "replacement-native-instance", f.attempt.claimed_bead_id)
            f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
            f.port.rows[current.claimed_bead_id]["revision"] = "2"
            recovered = module.allocate_run_placeholders(f.store, current,
                authority_id=list(created)[1], **args)
        self.assertEqual(recovered["captured_run"]["base_oid"], f.base)
        self.assertEqual(intent.read_bytes(), original)
        self.assertEqual(len(created), 2)
        self.assertEqual(f.port.requests, [])


    def test_published_run_replay_accepts_native_replacement_but_rejects_stale_original(self):
        f = self.fixture
        captured = run_fixtures.run.capture_run(f.store, f.attempt, **f.kwargs)
        current = Attempt(f.attempt.session_id, "current-native-instance", f.attempt.claimed_bead_id)
        f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
        f.port.rows[current.claimed_bead_id]["revision"] = str(int(f.port.rows[current.claimed_bead_id]["revision"]) + 1)
        replay = run_fixtures.run.capture_run(f.store, current, **f.kwargs)
        self.assertEqual(replay["record"], captured["record"])
        self.assertEqual(replay["receipt"]["outcome"], "replayed")
        self.assertEqual(json.loads(f.port.rows["authority-1"]["metadata"][GRANT_KEY])["attempt"], current.admission)
        with self.assertRaisesRegex(RecordError, "stale native claim"):
            run_fixtures.run.capture_run(f.store, f.attempt, **f.kwargs)
        self.assertEqual(len(f.port.requests), 2)

    def test_null_run_origin_refuses_without_native_create_or_lookup(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=1)
        with patch.object(module, "native_json", side_effect=native):
            with self.assertRaises(RecordError):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
            path = next(allocation_directory(f.store).glob("*.intent.json"))
            value = json.loads(path.read_text())
            value["origin"] = None
            path.write_bytes(canonical_bytes(value))
            before = list(calls)
            with self.assertRaisesRegex(RecordError, "no original cooked writer"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
        self.assertEqual(calls, before)
        self.assertEqual(len(created), 1)


    def test_claim_change_after_first_role_prevents_second_native_create(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator()
        def changed(gc, city, args, rig=None, **kwargs):
            value = native(gc, city, args, rig, **kwargs)
            if args[:2] == ["bd", "show"]:
                claim = f.port.rows[f.attempt.claimed_bead_id]
                claim["metadata"]["gc.session_attempt_id"] = Attempt(f.attempt.session_id,
                    "new-owner", f.attempt.claimed_bead_id).writer_attempt_id
                claim["revision"] = "2"
            return value
        with patch.object(module, "native_json", side_effect=changed):
            with self.assertRaisesRegex(RecordError, "changed after admission"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
        self.assertEqual(len(created), 1)
        self.assertEqual(sum(call[:2] == ["bd", "create"] for call in calls), 1)
        self.assertEqual(f.port.requests, [])

    def test_unacknowledged_authority_query_survives_replacement_and_first_publication(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=2)
        def lookup(gc, city, args, rig=None, **kwargs):
            if args[:2] == ["bd", "list"]:
                calls.append(list(args))
                self.assertTrue(kwargs["require_array"])
                value = args[args.index("--desc-contains") + 1]
                matches = [row for row in created.values() if row["description"] == value]
                self.assertEqual(len(matches), 1)
                return copy.deepcopy(matches[0])
            return native(gc, city, args, rig, **kwargs)
        with patch.object(module, "native_json", side_effect=lookup):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
            intent = next(allocation_directory(f.store).glob("*.intent.json"))
            retained = intent.read_bytes()
            (f.repo / "file").write_text("new default after lost acknowledgement\n")
            f.git("commit", "-am", "new default")
            current = Attempt(f.attempt.session_id, "actual-replacement", f.attempt.claimed_bead_id)
            f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
            f.port.rows[current.claimed_bead_id]["revision"] = "2"
            allocated = module.allocate_run_placeholders(f.store, current, **f.allocation_args())
        captured = run_fixtures.run.capture_run(f.store, current, **dict(f.kwargs,
            record_bead_id=allocated["run_record_id"], authority_id=allocated["authority_id"],
            captured_run=allocated["captured_run"], allocation_rows=allocated["allocation_rows"],
            captured_checks_config=f.allocation_args()["checks_config"]))
        self.assertEqual(captured["receipt"]["outcome"], "committed")
        self.assertEqual(captured["record"]["base_oid"], f.base)
        self.assertEqual(captured["record"]["writer_step_id"], f.attempt.claimed_bead_id)
        self.assertEqual(intent.read_bytes(), retained)
        self.assertEqual(len(created), 2)
        self.assertEqual(sum(call[:2] == ["bd", "create"] for call in calls), 2)
        self.assertEqual(len(f.port.requests), 1)
