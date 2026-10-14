"""Native drain shape through the actual adapter; backend acceptance is separate."""
from __future__ import annotations
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets/scripts"))
from test_workspace_store import MemoryPort, row
from workspace_records import canonical_bytes, contracts, record_identity, record_sha256
from workspace_store import (Attempt, CookedWriterMap, NativeRunContinuation, InheritedRunReference,
    RecordWrite, ReferenceWrite, GuardRead, StoreError, WorkspaceStore, record_reference,
    validate_cooked_writer_map, validate_native_continuation, CONTINUATION_KEY, GRANT_KEY,
    NativeOwnerProjection, NativeWorktreeReference, OWNER_PROJECTION_KEYS, SuccessorRelation)

class NativeInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.city = Path(self.tmp.name)
        self.common = self.city / '.git'; self.common.mkdir()
        samples = json.loads((Path(__file__).parent / 'fixtures/workspace-records/valid.json').read_text())
        self.run = copy.deepcopy(samples['run']); self.run['worktree_lifecycle'] = 'new'
        self.plan = copy.deepcopy(samples['source-plan'])
        self.run_ref = record_reference('run', 'run-record', self.run)
        self.plan_ref = record_reference('source-plan', 'plan-record', self.plan)
        checks = [{'id': 'unit', 'argv': ['true']}]
        self.policy = dict(version=1, workflow_root_id='run-example', run_record_id='run-record',
            run_identity=list(record_identity('run', self.run)), base_oid=self.run['base_oid'],
            required_checks=checks, policy_sha256=hashlib.sha256(canonical_bytes({'required_checks': checks})).hexdigest())
        native = {'gc.root_bead_id': 'run-example', 'gc.root_store_ref': 'rig:example'}
        source = dict(native, **{'gc.source_root_id': 'run-example', 'gc.source_generation': '1'})
        self.rows = {
            'run-example': row('run-example', status='in_progress', metadata=dict(native, **{
                'gc.kind': 'workflow',
                'gc.input_convoy_id': 'implementation-convoy', 'gc.build.implementation_convoy_id': 'implementation-convoy',
                'gc.implementation_run_ref': canonical_bytes(self.run_ref).decode()})),
            'run-record': row('run-record', metadata={contracts()['run']['metadata_key']: canonical_bytes(self.run).decode(),
                'gc.workspace_required_checks.v1': canonical_bytes(self.policy).decode()}),
            'plan-record': row('plan-record', metadata={contracts()['source-plan']['metadata_key']: canonical_bytes(self.plan).decode()}),
            'plan-owner-example': row('plan-owner-example', metadata=dict(source, **{'gc.source_plan_ref': canonical_bytes(self.plan_ref).decode()})),
            'implementation-convoy': row('implementation-convoy', metadata=dict(source, **{'gc.source_plan_owner_id': 'plan-owner-example',
                'gc.source_plan_sha256': record_sha256(self.plan)})),
            'control': row('control', status='in_progress', metadata=dict(native, **{'gc.kind': 'drain'})),
            'task-a': row('task-a', status='open', metadata=source),
            'child': row('child', status='in_progress', metadata={'gc.root_bead_id': 'child', 'gc.root_store_ref': 'rig:example',
                'gc.kind': 'workflow',
                'gc.input_convoy_id': 'unit', 'gc.drain_control_id': 'control', 'gc.drain_member_id': 'task-a',
                'gc.formula_name': 'do-work', 'gc.formula_hash': 'a'*64, 'gc.formula_source': '/fixture/do-work.formula.toml'}),
            'unit': row('unit', status='open', metadata={'gc.synthetic_kind': 'drain-unit-convoy', 'gc.parent_convoy_id': 'implementation-convoy',
                'gc.drain_control_id': 'control', 'gc.drain_member_id': 'task-a'}),
            'prepare': row('prepare', status='in_progress', assignee='worker', metadata={'gc.root_bead_id': 'child',
                'gc.root_store_ref': 'rig:example', 'gc.session_id': 'session', 'gc.step_id': 'prepare-worktree',
                'gc.step_ref': 'do-work.prepare-worktree', 'gc.run_target': 'gc.run-operator', 'gc.native_step_dependencies.v1': '[]'}),
            'implement': row('implement', status='open', metadata={'gc.root_bead_id': 'child', 'gc.root_store_ref': 'rig:example',
                'gc.step_id': 'implement', 'gc.step_ref': 'do-work.implement', 'gc.build.artifact_schema': 'gc.build.implementation-summary.v1',
                'gc.native_step_dependencies.v1': '["prepare-worktree"]'}),
            'inspection': row('inspection', status='open', metadata={'gc.root_bead_id': 'child', 'gc.root_store_ref': 'rig:example',
                'gc.step_id': 'write-failing-test', 'gc.step_ref': 'do-work.write-failing-test',
                'gc.native_step_dependencies.v1': '["implement"]'}),
            'grant': row('grant'), 'workspace': row('workspace')}
        self.rows['implementation-convoy']['type'] = self.rows['unit']['type'] = 'convoy'
        self.port = MemoryPort(self.rows)
        self.store = WorkspaceStore('rig:example', cwd=self.city, common_git_dir=self.common)
        self.command = patch.object(self.store, '_command', side_effect=self.port); self.command.start(); self.addCleanup(self.command.stop)
        self.attempt = Attempt('session', 'token', 'prepare')
        self.scope = dict(workflow_root_id='run-example', generation=1, writer_scope_id='task-a', record_kind='workspace')
        binding = dict(version=1, workflow_root_id='run-example', store_ref='rig:example', generation=1, child_root_id='child',
            unit_convoy_id='unit', implementation_convoy_id='implementation-convoy', drain_control_id='control', member_id='task-a',
            run_ref=self.run_ref, source_plan_ref=self.plan_ref, run_sha256=record_sha256(self.run),
            source_plan_sha256=record_sha256(self.plan), check_policy_sha256=hashlib.sha256(canonical_bytes(self.policy)).hexdigest())
        self.context = NativeRunContinuation(canonical_bytes(binding))
        self.map = self.writer_map()
        self.workspace = copy.deepcopy(samples['workspace'])
        self.workspace.update(workspace_bead_id='workspace', workspace_owner_id='task-a', active_member_id='task-a',
            strategy='isolated', integration_inputs=[], native_provenance=None, native_attempt_id='native-attempt',
            writer_step_id='prepare', writer_attempt_id=self.attempt.writer_attempt_id)
        self.workspace['claim_binding'].update(workspace_owner_id='task-a', writer_step_id='prepare', writer_attempt_id=self.attempt.writer_attempt_id)

    def writer_map(self):
        entries = []
        for key, kinds in (('prepare', ['blocker', 'workspace']), ('implement', ['workspace']), ('inspection', [])):
            native = self.port.rows[key]['metadata']
            entries.append(dict(bead_id=key, step_id=native['gc.step_id'], step_ref=native['gc.step_ref'],
                dependencies=json.loads(native['gc.native_step_dependencies.v1']), record_kinds=kinds))
        return CookedWriterMap(canonical_bytes(dict(version=1, workflow_root_id='run-example', store_ref='rig:example', source_member_id='task-a',
            expansion_root_id='child', formula_name='do-work', formula_hash='a'*64,
            formula_source='/fixture/do-work.formula.toml', steps=entries)), continuation=self.context)

    def prepare(self, *, projections=None, expected_rows=None):
        return self.store.install_grant(self.attempt, self.scope, 'grant', [RecordWrite('workspace', 'workspace', self.workspace)],
            [ReferenceWrite('task-a', 'gc.workspace_ref', record_reference('workspace', 'workspace', self.workspace))],
            writer_map=self.map, projections=[InheritedRunReference(self.context)] if projections is None else projections,
            expected_rows=expected_rows)

    def publish(self):
        prepared = self.prepare(); self.assertEqual(self.store.execute(prepared)['outcome'], 'committed'); return prepared

    def test_native_chain_validates_without_rewriting_physical_roots(self):
        before = copy.deepcopy(self.port.rows)
        self.assertEqual(validate_native_continuation(self.context, self.port.rows, store_ref='rig:example', workflow_root_id='run-example', claimed_step_id='prepare'), self.context.binding)
        self.assertEqual(self.port.rows, before)

    def test_first_workspace_atomically_inherits_original_run_without_recapture(self):
        self.publish()
        self.assertEqual(self.port.rows['child']['metadata']['gc.implementation_run_ref'], canonical_bytes(self.run_ref).decode())
        self.assertEqual(self.port.rows['child']['metadata'][CONTINUATION_KEY], self.context.binding_bytes.decode())
        self.assertEqual(self.port.rows['prepare']['metadata']['gc.root_bead_id'], 'child')
        self.assertEqual(json.loads(self.port.rows['workspace']['metadata']['gc.workspace'])['workflow_root_id'], 'run-example')
        self.assertEqual(self.port.rows['run-record']['metadata'][contracts()['run']['metadata_key']], canonical_bytes(self.run).decode())
        request = self.port.requests[0]
        self.assertTrue(set(self.context.row_ids).issubset({p['id'] for p in request['rows']}))
        self.assertEqual(json.loads(self.port.rows['grant']['metadata'][GRANT_KEY])['writer_map_sha256'], self.map.sha256)

    def test_readonly_nonwriter_context_does_not_authorize_mutation(self):
        self.assertEqual(validate_cooked_writer_map(self.map, self.port.rows, store_ref='rig:example', workflow_root_id='run-example',
            record_kind=None, claimed_step_id='inspection', read_only=True)['source_member_id'], 'task-a')
        self.port.rows['inspection'].update(status='in_progress', assignee='worker')
        self.port.rows['inspection']['metadata']['gc.session_id'] = 'session'
        attempt = Attempt('session', 'token', 'inspection')
        with self.assertRaises(StoreError):
            self.store.install_grant(attempt, self.scope, 'grant', [RecordWrite('workspace', 'workspace', self.workspace)], writer_map=self.map)
        self.assertEqual(self.port.requests, [])

    def test_ordinary_map_hash_is_compatible_and_context_changes_hash(self):
        ordinary = CookedWriterMap(self.map.declaration_bytes)
        self.assertEqual(ordinary.sha256, hashlib.sha256(ordinary.declaration_bytes).hexdigest())
        self.assertNotEqual(self.map.sha256, ordinary.sha256)

    def test_tampered_native_chain_or_authority_refuses_without_writes(self):
        mutations = [('child','gc.drain_member_id','task-b'), ('unit','gc.parent_convoy_id','foreign'),
            ('child','gc.kind','step'), ('run-example','gc.kind','step'), ('control','gc.kind','step'),
            ('run-example','workflow_id','foreign'), ('plan-owner-example','gc.source_generation','2'),
            ('unit','gc.drain_control_id','other'), ('unit','gc.synthetic_kind','invented'),
            ('control','gc.root_bead_id','foreign'), ('task-a','gc.source_generation','2'),
            ('task-a','workflow_id','foreign'), ('task-a','gc.root_store_ref','rig:foreign'),
            ('implementation-convoy','gc.source_plan_sha256','b'*64),
            ('run-example','gc.build.implementation_convoy_id','foreign'),
            ('child','gc.implementation_run_ref',canonical_bytes(self.run_ref).decode()),
            ('child',CONTINUATION_KEY,self.context.binding_bytes.decode()),
            ('run-record','gc.workspace_required_checks.v1','{}')]
        original = copy.deepcopy(self.port.rows)
        for bead_id, key, value in mutations:
            with self.subTest(bead_id=bead_id,key=key):
                self.port.rows = copy.deepcopy(original); self.port.rows[bead_id]['metadata'][key] = value
                with self.assertRaises(StoreError): self.prepare()
                self.assertEqual(self.port.requests, [])
        self.port.rows = original

    def test_initial_publication_requires_joined_projection(self):
        with self.assertRaises(StoreError): self.prepare(projections=[])
        self.assertEqual(self.port.requests, [])

    def test_missing_original_row_refuses_without_partial_publication(self):
        before=copy.deepcopy(self.port.rows); before.pop('control')
        with self.assertRaises(StoreError): self.prepare(expected_rows=before)
        self.assertEqual(self.port.requests, [])

    def current_write(self, workspace=None):
        return self.store.write_records(self.attempt, self.scope, 'grant',
            [RecordWrite('workspace', 'workspace', workspace or self.workspace)], writer_map=self.map)

    def test_later_write_revalidates_retained_reference_and_full_chain(self):
        self.publish()
        before = copy.deepcopy(self.port.rows)
        for bead_id, key, value in [('child', CONTINUATION_KEY, '{}'),
                                    ('control', 'gc.kind', 'step'),
                                    ('run-record', 'gc.workspace_required_checks.v1', '{}')]:
            with self.subTest(bead_id=bead_id, key=key):
                self.port.rows = copy.deepcopy(before)
                self.port.rows[bead_id]['metadata'][key] = value
                with self.assertRaises(StoreError): self.current_write()
                self.assertEqual(len(self.port.requests), 1)
        self.port.rows = before
        self.assertEqual(self.store.execute(self.current_write())['outcome'], 'replayed')

    def test_original_row_race_never_partially_installs_child_authority(self):
        prepared = self.prepare()
        self.port.rows['control']['revision'] = '2'
        before = copy.deepcopy(self.port.rows)
        self.assertEqual(self.store.execute(prepared)['outcome'], 'unknown')
        self.assertEqual(self.port.rows, before)
        self.assertEqual(self.store.resolve(prepared)['outcome'], 'unknown')
        self.assertNotIn(CONTINUATION_KEY, self.port.rows['child']['metadata'])

    def test_lost_ack_reads_back_one_exact_transaction_and_never_resubmits(self):
        prepared = self.prepare(); self.port.lose_ack = True
        self.assertEqual(self.store.execute(prepared)['outcome'], 'unknown')
        self.assertEqual(self.store.resolve(prepared)['outcome'], 'committed')
        with self.assertRaisesRegex(StoreError, 'already submitted'): self.store.execute(prepared)
        self.assertEqual(len(self.port.requests), 1)
        self.assertEqual(self.port.rows['child']['metadata'][CONTINUATION_KEY], self.context.binding_bytes.decode())

    def test_same_child_handoff_requires_closed_native_predecessor_and_fences_old_writer(self):
        self.publish()
        old = self.current_write()
        grant = json.loads(self.port.rows['grant']['metadata'][GRANT_KEY])
        self.port.rows['implement'].update(status='in_progress', assignee='worker')
        self.port.rows['implement']['metadata']['gc.session_id'] = 'next-session'
        successor = Attempt('next-session', 'next-token', 'implement')
        with self.assertRaisesRegex(StoreError, 'closed native predecessor'):
            self.store.accept_replacement(successor, self.scope, 'grant', [], expected_grant=grant, writer_map=self.map)
        self.port.rows['prepare']['status'] = 'closed'
        request = self.store.accept_replacement(successor, self.scope, 'grant', [], expected_grant=grant, writer_map=self.map)
        self.assertEqual(self.store.execute(request)['outcome'], 'committed')
        state = copy.deepcopy(self.port.rows)
        self.assertEqual(self.store.execute(old)['outcome'], 'unknown')
        self.assertEqual(self.port.rows, state)

    def native_projection(self):
        self.run.update(rig_root=str(self.city), common_git_dir=str(self.common))
        self.run_ref = record_reference('run', 'run-record', self.run)
        self.port.rows['run-example']['metadata']['gc.implementation_run_ref'] = canonical_bytes(self.run_ref).decode()
        self.port.rows['run-record']['metadata'][contracts()['run']['metadata_key']] = canonical_bytes(self.run).decode()
        self.policy['run_identity'] = list(record_identity('run', self.run))
        self.port.rows['run-record']['metadata']['gc.workspace_required_checks.v1'] = canonical_bytes(self.policy).decode()
        work_root = self.city / 'workspaces'; work_dir = work_root / 'owner'; work_dir.mkdir(parents=True)
        self.workspace['work_dir'] = str(work_dir)
        samples = json.loads((Path(__file__).parent / 'fixtures/workspace-records/valid.json').read_text())
        native = copy.deepcopy(samples['workspace']['native_provenance'])
        native.update(schema_version=2, bead_id='workspace', repo_identity=str(self.common), path=str(work_dir),
            branch=self.workspace['work_branch'], owner=self.workspace['workspace_owner_id'],
            attempt_id=self.workspace['native_attempt_id'], mode='attached', placement='outside-worktrees')
        self.workspace['native_provenance'] = native
        binding = self.context.binding
        binding.update(run_ref=self.run_ref, run_sha256=record_sha256(self.run), source_plan_sha256=record_sha256(self.plan),
            check_policy_sha256=hashlib.sha256(canonical_bytes(self.policy)).hexdigest())
        self.context = NativeRunContinuation(canonical_bytes(binding)); self.map = self.writer_map()
        return self.owner_projections('child', 'prepare')

    def owner_projections(self, child_id, step_id):
        native = self.workspace['native_provenance']
        owner = {'gc.root_bead_id': child_id, 'gc.root_store_ref': 'rig:example',
            'gc.work_dir': self.workspace['work_dir'], 'gc.work_branch': self.workspace['work_branch'],
            'gc.worktree_repo': str(self.city), 'gc.worktree_root': str(Path(self.workspace['work_dir']).parent),
            'gc.worktree_owner': self.workspace['workspace_owner_id'], 'gc.worktree_generation': '1'}
        owner.update({'gc.worktree_' + k: native[k] for k in ('base_ref', 'base_sha', 'creator', 'lifecycle', 'mode', 'placement')})
        reference = dict(version=1, binding_step_id=step_id, workflow_root_id=child_id, generation=1,
            workspace_owner_id=self.workspace['workspace_owner_id'], workspace_bead_id='workspace',
            store_ref='rig:example', native_attempt_id=self.workspace['native_attempt_id'])
        return [NativeOwnerProjection('workspace', owner), NativeWorktreeReference(step_id, 'workspace', reference)]

    def test_native_owner_and_launch_reference_use_physical_child_not_logical_root(self):
        projections = self.native_projection()
        prepared = self.prepare(projections=[InheritedRunReference(self.context), *projections])
        self.assertEqual(self.store.execute(prepared)['outcome'], 'committed')
        self.assertEqual(self.port.rows['workspace']['metadata']['gc.root_bead_id'], 'child')
        reference = json.loads(self.port.rows['prepare']['metadata']['gc.worktree_ref'])
        self.assertEqual(reference['workflow_root_id'], 'child')
        self.assertEqual(json.loads(self.port.rows['workspace']['metadata']['gc.workspace'])['workflow_root_id'], 'run-example')

    def test_workspace_read_requires_exact_published_retained_child_context(self):
        projections = self.native_projection()
        self.assertEqual(self.store.execute(self.prepare(projections=[InheritedRunReference(self.context), *projections]))['outcome'], 'committed')
        with self.assertRaises(StoreError): self.store.read_record('workspace', 'workspace')
        self.assertEqual(self.store.read_record('workspace', 'workspace', continuation=self.context), self.workspace)
        self.port.rows['control']['metadata']['gc.kind'] = 'step'
        with self.assertRaises(StoreError): self.store.read_record('workspace', 'workspace', continuation=self.context)
        self.assertEqual(len(self.port.requests), 1)

    def test_shared_workspace_read_uses_old_published_context_until_successor_commits(self):
        _, _, old_context = self.shared_chain()
        self.assertEqual(self.store.read_record('workspace', 'workspace', continuation=old_context)['active_member_id'], 'task-a')
        with self.assertRaisesRegex(StoreError, 'has not been published'):
            self.store.read_record('workspace', 'workspace', continuation=self.context)
        self.assertEqual(len(self.port.requests), 3)

    def shared_chain(self, members=('task-a', 'task-b')):
        self.plan['nodes'] = [dict(owner_id='integration-example', strategy='shared-chain', member_ids=list(members),
            source_predecessor_owner_ids=[], single_lane=True)]
        self.plan['terminal_owner_id'] = 'integration-example'
        self.port.rows['plan-record']['metadata'][contracts()['source-plan']['metadata_key']] = canonical_bytes(self.plan).decode()
        self.port.rows['implementation-convoy']['metadata']['gc.source_plan_sha256'] = record_sha256(self.plan)
        self.port.rows['integration-example'] = row('integration-example', status='open', metadata={
            'gc.root_bead_id': 'run-example', 'gc.root_store_ref': 'rig:example',
            'gc.source_root_id': 'run-example', 'gc.source_generation': '1'})
        self.workspace.update(workspace_owner_id='integration-example', strategy='shared-chain')
        self.workspace['claim_binding']['workspace_owner_id'] = 'integration-example'
        self.scope['writer_scope_id'] = 'integration-example'
        self.native_projection()
        request = self.store.install_grant(self.attempt, self.scope, 'grant', [RecordWrite('workspace', 'workspace', self.workspace)],
            [ReferenceWrite('integration-example', 'gc.workspace_ref', record_reference('workspace', 'workspace', self.workspace))],
            writer_map=self.map, projections=[InheritedRunReference(self.context), *self.owner_projections('child', 'prepare')])
        self.assertEqual(self.store.execute(request)['outcome'], 'committed')
        self.workspace['phase'] = 'active'
        self.assertEqual(self.store.execute(self.current_write())['outcome'], 'committed')
        self.workspace.update(phase='result', current_oid='b'*40, output_oid='b'*40)
        self.assertEqual(self.store.execute(self.current_write())['outcome'], 'committed')
        old_context = self.context; old_map = self.map
        old_grant = json.loads(self.port.rows['grant']['metadata'][GRANT_KEY])
        self.port.rows['prepare']['status'] = 'closed'
        self.port.rows['task-b'] = copy.deepcopy(self.port.rows['task-a']); self.port.rows['task-b']['id'] = 'task-b'
        child = copy.deepcopy(self.port.rows['child']); child['id'] = 'child-b'
        for key in (CONTINUATION_KEY, 'gc.implementation_run_ref'): child['metadata'].pop(key)
        child['metadata'].update({'gc.root_bead_id':'child-b', 'gc.input_convoy_id':'unit-b', 'gc.drain_member_id':'task-b'})
        self.port.rows['child-b'] = child
        unit = copy.deepcopy(self.port.rows['unit']); unit['id'] = 'unit-b'; unit['metadata']['gc.drain_member_id'] = 'task-b'
        self.port.rows['unit-b'] = unit
        step = copy.deepcopy(self.port.rows['prepare']); step['id'] = 'prepare-b'; step.update(status='in_progress', assignee='worker')
        step['metadata'].pop('gc.worktree_ref'); step['metadata'].update({'gc.root_bead_id':'child-b', 'gc.session_id':'next-session'})
        self.port.rows['prepare-b'] = step
        binding = old_context.binding; binding.update(child_root_id='child-b', unit_convoy_id='unit-b', member_id='task-b')
        self.context = NativeRunContinuation(canonical_bytes(binding))
        declaration = old_map.declaration; declaration.update(source_member_id='task-b', expansion_root_id='child-b')
        declaration['steps'] = [dict(declaration['steps'][0], bead_id='prepare-b')]
        self.map = CookedWriterMap(canonical_bytes(declaration), self.context)
        self.attempt = Attempt('next-session', 'next-token', 'prepare-b')
        candidate = copy.deepcopy(self.workspace)
        candidate.update(phase='entry', active_member_id='task-b', next_member_position=1, input_oid='b'*40,
            writer_step_id='prepare-b', writer_attempt_id=self.attempt.writer_attempt_id)
        candidate['claim_binding'].update(writer_step_id='prepare-b', writer_attempt_id=self.attempt.writer_attempt_id)
        return candidate, old_grant, old_context

    def test_shared_successor_atomically_moves_active_native_root_and_preserves_git_identity(self):
        candidate, grant, old_context = self.shared_chain()
        before_identity = {k:v for k,v in self.port.rows['workspace']['metadata'].items() if k in OWNER_PROJECTION_KEYS and k != 'gc.root_bead_id'}
        request = self.store.accept_replacement(self.attempt, self.scope, 'grant', [RecordWrite('workspace','workspace',candidate)],
            expected_grant=grant, successor_relation=SuccessorRelation('plan-record','plan-owner-example'),
            writer_map=self.map, projections=[InheritedRunReference(self.context), *self.owner_projections('child-b','prepare-b')])
        self.assertEqual(self.store.execute(request)['outcome'], 'committed')
        self.assertEqual(self.port.rows['workspace']['metadata']['gc.root_bead_id'], 'child-b')
        self.assertEqual(before_identity, {k:v for k,v in self.port.rows['workspace']['metadata'].items() if k in before_identity})
        self.assertEqual(self.port.rows['child']['metadata'][CONTINUATION_KEY], old_context.binding_bytes.decode())
        self.assertEqual(json.loads(self.port.rows['prepare']['metadata']['gc.worktree_ref'])['workflow_root_id'], 'child')
        self.assertEqual(json.loads(self.port.rows['prepare-b']['metadata']['gc.worktree_ref'])['workflow_root_id'], 'child-b')
        self.assertTrue(set(old_context.row_ids) | set(self.context.row_ids) <= {p['id'] for p in request.request['rows']})

    def test_shared_successor_needs_declared_adjacency_and_cannot_skip_native_root_projection(self):
        candidate, grant, _ = self.shared_chain()
        with self.assertRaisesRegex(StoreError, 'successor relation'):
            self.store.accept_replacement(self.attempt, self.scope, 'grant', [RecordWrite('workspace','workspace',candidate)],
                expected_grant=grant, writer_map=self.map, projections=[InheritedRunReference(self.context)])
        with self.assertRaisesRegex(StoreError, 'atomically move'):
            self.store.accept_replacement(self.attempt, self.scope, 'grant', [RecordWrite('workspace','workspace',candidate)],
                expected_grant=grant, successor_relation=SuccessorRelation('plan-record','plan-owner-example'),
                writer_map=self.map, projections=[InheritedRunReference(self.context)])
        before = copy.deepcopy(self.port.rows)
        self.port.rows['plan-owner-example']['metadata']['gc.source_plan_ref'] = '{}'
        with self.assertRaises(StoreError):
            self.store.accept_replacement(self.attempt, self.scope, 'grant', [RecordWrite('workspace','workspace',candidate)],
                expected_grant=grant, successor_relation=SuccessorRelation('plan-record','plan-owner-example'),
                writer_map=self.map, projections=[InheritedRunReference(self.context), *self.owner_projections('child-b','prepare-b')])
        self.assertEqual(len(self.port.requests), 3)
        self.port.rows = before

    def test_nonadjacent_native_child_cannot_skip_shared_chain_members(self):
        candidate, grant, _ = self.shared_chain(('task-a', 'task-between', 'task-b'))
        before = copy.deepcopy(self.port.rows)
        with self.assertRaisesRegex(StoreError, 'immediate shared-chain successor'):
            self.store.accept_replacement(self.attempt, self.scope, 'grant', [RecordWrite('workspace','workspace',candidate)],
                expected_grant=grant, successor_relation=SuccessorRelation('plan-record','plan-owner-example'),
                writer_map=self.map, projections=[InheritedRunReference(self.context), *self.owner_projections('child-b','prepare-b')])
        self.assertEqual(self.port.rows, before)
        self.assertEqual(len(self.port.requests), 3)

if __name__ == '__main__': unittest.main()
