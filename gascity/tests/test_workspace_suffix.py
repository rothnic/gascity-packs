"""Native standalone suffixes keep the recorded run and physical claim separate."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workspace_entry as fixture
import workspace_entry as entry
from workspace_records import RecordError, canonical_bytes, contracts, record_identity, record_sha256
from workspace_store import (_kinds, Attempt, CONTINUATION_KEY, CookedWriterMap, NativeRunContinuation,
                             WorkspaceStore, validate_native_continuation)


class SuffixEntryTests(unittest.TestCase):
    setUp = fixture.EntryTests.setUp
    row = staticmethod(fixture.EntryTests.row)
    git = fixture.EntryTests.git
    read = fixture.EntryTests.read
    drain_child = fixture.EntryTests.drain_child

    def suffix(self):
        self.drain_child()
        self.rows['suffix-1'] = self.row('suffix-1', metadata={
            'gc.kind': 'workflow', 'gc.root_store_ref': 'rig:example',
            'gc.input_convoy_id': 'implementation-1', 'gc.var.worktree_lifecycle': 'new'})
        self.rows['step-1']['metadata'].update({
            'gc.root_bead_id': 'suffix-1', 'gc.step_ref': 'prepare-convoy'})

    def test_fresh_plan_and_decompose_are_designated_run_writers(self):
        for stage in ('prepare-plan', 'prepare-decompose'):
            with self.subTest(stage=stage):
                self.assertEqual(_kinds({'gc.step_id': stage, 'gc.lifecycle': 'new'}, stage), ['run'])

    def test_same_root_selector_preserves_original_recorded_and_missing_run_routes(self):
        for selected in ('argument', 'native-variable'):
            with self.subTest(selected=selected):
                args = {'recorded_root_id': 'root-1'} if selected == 'argument' else {}
                if selected == 'native-variable':
                    self.rows['root-1']['metadata']['gc.var.worktree_run_root'] = 'root-1'
                self.assertEqual(self.read(**args)['run'], self.record)
                raw = self.rows['root-1']['metadata'].pop(entry.RUN_REF)
                with self.assertRaisesRegex(entry.EntryError, 'recorded run|migration'):
                    self.read(**args)
                self.rows['root-1']['metadata'][entry.RUN_REF] = raw

    def test_original_drain_refuses_foreign_explicit_recorded_root(self):
        self.drain_child()
        before = copy.deepcopy(self.rows)
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='child-1', input_convoy_id='unit-1',
                      require_plan=True, recorded_root_id='foreign-root')
        self.assertEqual(self.rows, before)
        self.rows['child-1']['metadata']['gc.var.worktree_run_root'] = 'foreign-root'
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='child-1', input_convoy_id='unit-1', require_plan=True)

    def test_cli_refuses_foreign_drain_selector_before_legacy_gate_return(self):
        import contextlib
        import io
        self.drain_child()
        for mode in ('new', 'legacy'):
            self.record['worktree_lifecycle'] = mode
            self.reference['identity'] = list(record_identity('run', self.record))
            self.rows['record-1']['metadata'][contracts()['run']['metadata_key']] = canonical_bytes(self.record).decode()
            self.rows['root-1']['metadata'][entry.RUN_REF] = canonical_bytes(self.reference).decode()
            for root in ('root-1', 'child-1'):
                self.rows[root]['metadata']['gc.var.worktree_lifecycle'] = mode
            for action in ('gate', 'read', 'prepare'):
                with self.subTest(mode=mode, action=action), \
                     patch('workspace_store.WorkspaceStore', return_value=self.store), \
                     patch('workspace_store.Attempt.from_env', return_value=Attempt('session-1', 'instance-1', 'step-1')), \
                     patch.object(entry, 'registered_rig', return_value=str(self.repo)), \
                     contextlib.redirect_stdout(io.StringIO()) as stdout, \
                     contextlib.redirect_stderr(io.StringIO()) as stderr:
                    before = copy.deepcopy(self.rows)
                    rc = entry.main([action, '--city-root', str(self.root), '--store-ref', 'rig:example',
                        '--rig', 'example', '--workflow-root', 'child-1', '--claimed-step', 'step-1',
                        '--entrypoint', 'convoy', '--recorded-root', 'foreign-root'])
                    self.assertEqual(rc, 1, stdout.getvalue())
                    self.assertIn('does not continue the requested workflow', stderr.getvalue())
                    self.assertEqual(stdout.getvalue(), '')
                    self.assertEqual(self.rows, before)

    def test_rendered_suffix_entries_preserve_routes_and_layout_for_shipped_methodologies(self):
        import re
        from test_formula_assets import resolve_formula_from_dirs
        repo = Path(fixture.__file__).parents[2]
        base = repo / 'gascity'
        builds = {'gascity': 'build-basic', 'compound-engineering': 'compound-build',
                  'superpowers': 'superpowers-build', 'bmad': 'bmad-build', 'gstack': 'gstack-build'}
        layouts = ('worktree_base_ref', 'worktree_checks', 'worktree_parent',
                   'worktree_name_prefix', 'worktree_allow_external_parent', 'worktree_lifecycle')
        supplied = {'pack_root': str(base), 'artifact_root': 'artifacts/accepted',
                    'requirements_path': 'artifacts/accepted/requirements.md',
                    'plan_path': 'artifacts/accepted/plan.md', 'worktree_run_root': 'root-1'}
        for pack, build in builds.items():
            layers = [base / 'formulas'] + ([] if pack == 'gascity' else [repo / pack / 'formulas'])
            concrete = resolve_formula_from_dirs(layers, build)
            for stage in ('requirements', 'plan', 'decompose', 'convoy', 'review'):
                with self.subTest(pack=pack, stage=stage):
                    formula = resolve_formula_from_dirs(layers, 'build-from-' + stage)
                    for name in layouts:
                        self.assertEqual(formula['vars'][name]['default'], concrete['vars'][name]['default'])
                    self.assertEqual(formula['vars']['worktree_run_root']['default'], '')
                    node = next(node for node in formula['steps'] if node['id'] == 'prepare-' + stage)
                    asset = base / 'formulas' / node['description_file']
                    values = {key: value.get('default', '') for key, value in formula['vars'].items()}
                    values.update({key: value['default'] for key, value in concrete['vars'].items()
                                   if key in formula['vars'] and 'default' in value})
                    values.update(supplied)
                    rendered = re.sub(r'\{\{([a-z_]+)\}\}',
                                      lambda match: str(values.get(match[1], match[0])), asset.read_text())
                    self.assertIn(str(base / 'assets/scripts/workspace_entry.py') + '" gate', rendered)
                    self.assertIn('--entrypoint ' + stage, rendered)
                    self.assertIn('--claimed-step "$CLAIMED_BEAD_ID"', rendered)
                    if stage in ('convoy', 'review'):
                        self.assertIn('--require-plan', rendered)
                    if stage == 'review':
                        self.assertIn('Recorded root selector: `root-1`', rendered)
                        self.assertNotIn('{{worktree_run_root}}', rendered)
                    selected = {'requirements': ('planning_formula',), 'plan': ('planning_formula',),
                                'decompose': ('decomposition_formula',), 'convoy': ('implementation_target',),
                                'review': ('code_review_formula', 'review_fix_formula')}[stage]
                    for name in selected:
                        self.assertIn(values[name], rendered)
                    self.assertNotIn('{{pack_root}}', rendered)

    def test_convoy_suffix_reads_original_run_without_stamping_or_recapture(self):
        self.suffix()
        before = copy.deepcopy(self.rows)
        (self.repo / 'file').write_text('new HEAD after the captured base\n')
        self.git('commit', '-am', 'later default')
        result = self.read(workflow_root_id='suffix-1', require_plan=True,
                           input_convoy_id='implementation-1')
        self.assertEqual(result['run'], self.record)
        self.assertEqual(result['source_plan'], self.plan)
        self.assertEqual(result['workflow_root_id'], 'root-1')
        self.assertEqual(result['native_workflow_root_id'], 'suffix-1')
        self.assertEqual(result['native_continuation']['version'], 2)
        self.assertEqual(self.rows, before)

    def test_selector_locates_only_and_foreign_native_input_refuses(self):
        self.suffix()
        self.rows['suffix-1']['metadata']['gc.input_convoy_id'] = 'foreign-1'
        self.rows['suffix-1']['metadata']['gc.var.worktree_run_root'] = 'root-1'
        self.rows['foreign-1'] = self.row('foreign-1', kind='convoy', metadata={
            'gc.root_store_ref': 'rig:example'})
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='suffix-1', require_plan=True)

    def test_suffix_rejects_wrong_store_generation_plan_and_inactive_physical_root(self):
        self.suffix()
        original = copy.deepcopy(self.rows)
        for bead, key, value in (
            ('suffix-1', 'gc.root_store_ref', 'rig:other'),
            ('implementation-1', 'gc.source_generation', '2'),
            ('implementation-1', 'gc.source_plan_sha256', '0' * 64),
            ('suffix-1', 'gc.var.worktree_run_root', 'member-1')):
            with self.subTest(bead=bead, key=key):
                self.rows.clear(); self.rows.update(copy.deepcopy(original))
                self.rows[bead]['metadata'][key] = value
                with self.assertRaises(entry.EntryError):
                    self.read(workflow_root_id='suffix-1', require_plan=True)
        self.rows.clear(); self.rows.update(original)
        self.rows['suffix-1']['status'] = 'closed'
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='suffix-1', require_plan=True)

    def test_actual_drain_under_suffix_keeps_both_physical_relationships(self):
        self.suffix()
        self.rows['control-1']['metadata']['gc.root_bead_id'] = 'suffix-1'
        self.rows['step-1']['metadata'].update({
            'gc.root_bead_id': 'child-1', 'gc.step_ref': 'do-work.prepare-worktree'})
        result = self.read(workflow_root_id='child-1', require_plan=True,
                           input_convoy_id='unit-1')
        binding = result['native_continuation']
        self.assertEqual(binding['workflow_root_id'], 'root-1')
        self.assertEqual(binding['suffix_root_id'], 'suffix-1')
        self.assertEqual(binding['child_root_id'], 'child-1')
        self.assertEqual(binding['drain_control_id'], 'control-1')
        self.assertEqual(binding['member_id'], 'member-1')
        self.assertTrue({'root-1', 'suffix-1', 'child-1', 'control-1', 'unit-1'} <= result['_native_rows'].keys())

    def test_original_drain_keeps_exact_version_one_binding_bytes(self):
        from workspace_run import CHECKS_POLICY_KEY
        self.drain_child()
        result = self.read(workflow_root_id='child-1', input_convoy_id='unit-1', require_plan=True)
        plan_ref = json.loads(self.rows['plan-owner']['metadata'][entry.PLAN_REF])
        policy = json.loads(self.rows['record-1']['metadata'][CHECKS_POLICY_KEY])
        original = dict(version=1, workflow_root_id='root-1', store_ref='rig:example', generation=1,
            child_root_id='child-1', unit_convoy_id='unit-1', implementation_convoy_id='implementation-1',
            drain_control_id='control-1', member_id='member-1', run_ref=self.reference,
            source_plan_ref=plan_ref, run_sha256=record_sha256(self.record),
            source_plan_sha256=record_sha256(self.plan), check_policy_sha256=record_sha256(policy))
        context = NativeRunContinuation(canonical_bytes(result['native_continuation']))
        self.assertEqual(context.binding_bytes, canonical_bytes(original))
        self.assertEqual(context.reference_bytes, canonical_bytes(original))
        self.assertEqual(validate_native_continuation(context, result['_native_rows'],
            store_ref='rig:example', workflow_root_id='root-1', claimed_step_id='step-1'), original)

    def test_root_reference_alone_cannot_authorize_a_suffix(self):
        self.suffix()
        self.rows['suffix-1']['metadata'][entry.RUN_REF] = canonical_bytes(self.reference).decode()
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='suffix-1', require_plan=True)

    def accepted_canonical(self):
        payloads = json.loads((Path(fixture.__file__).parent / 'fixtures/workspace-records/valid.json').read_text())
        canonical = dict(payloads['canonical'], workflow_root_id='root-1', generation=1,
            source_plan_owner_id=self.plan['source_plan_owner_id'], workspace_owner_id=self.plan['terminal_owner_id'],
            output_oid=self.record['base_oid'])
        ref = {'kind': 'canonical', 'bead_id': 'canonical-1', 'identity': list(record_identity('canonical', canonical))}
        self.rows['canonical-1'] = self.row('canonical-1', status='closed', metadata={
            contracts()['canonical']['metadata_key']: canonical_bytes(canonical).decode()})
        self.rows['root-1']['metadata']['gc.canonical_ref'] = canonical_bytes(ref).decode()
        return canonical

    def test_closed_original_requires_its_exact_accepted_subject_and_active_physical_suffix(self):
        self.suffix()
        self.accepted_canonical()
        self.rows['root-1'].update(status='closed')
        self.rows['root-1']['metadata']['gc.outcome'] = 'pass'
        self.assertEqual(self.read(workflow_root_id='suffix-1', require_plan=True)['run'], self.record)
        before = copy.deepcopy(self.rows)
        for change in ('no-canonical', 'wrong-subject', 'failed', 'held', 'canceled', 'physical-closed'):
            with self.subTest(change=change):
                self.rows.clear(); self.rows.update(copy.deepcopy(before))
                if change == 'no-canonical':
                    self.rows['root-1']['metadata'].pop('gc.canonical_ref')
                elif change == 'wrong-subject':
                    canonical = json.loads(self.rows['canonical-1']['metadata'][contracts()['canonical']['metadata_key']])
                    canonical['workspace_owner_id'] = 'foreign-1'
                    self.rows['canonical-1']['metadata'][contracts()['canonical']['metadata_key']] = canonical_bytes(canonical).decode()
                elif change == 'failed':
                    self.rows['root-1']['metadata']['gc.outcome'] = 'fail'
                elif change == 'held':
                    self.rows['root-1']['labels'] = ['hold:review']
                elif change == 'canceled':
                    self.rows['root-1']['metadata']['gc.cancel_requested'] = 'true'
                else:
                    self.rows['suffix-1']['status'] = 'closed'
                with self.assertRaises(entry.EntryError):
                    self.read(workflow_root_id='suffix-1', require_plan=True)

    def test_suffix_cannot_change_captured_layout_or_check_policy(self):
        self.suffix()
        before = copy.deepcopy(self.rows)
        for key, value in (('worktree_parent', str(self.root)), ('worktree_name_prefix', 'another-'),
                           ('worktree_allow_external_parent', 'true'),
                           ('worktree_checks', canonical_bytes({'required_checks': [{'id': 'easier', 'argv': ['true']}]}).decode())):
            with self.subTest(key=key):
                self.rows.clear(); self.rows.update(copy.deepcopy(before))
                self.rows['suffix-1']['metadata']['gc.var.' + key] = value
                with self.assertRaises(entry.EntryError):
                    self.read(workflow_root_id='suffix-1', require_plan=True)

    def test_pending_original_intent_blocks_recorded_suffix_before_any_allocation(self):
        from workspace_requests import journal_directory
        from workspace_run import run_scope
        self.suffix()
        directory = journal_directory(self.store)
        pending = directory / (hashlib.sha256(canonical_bytes(run_scope('root-1'))).hexdigest() + '.pending')
        pending.write_text(str(directory / 'original-request.json'))
        with patch.object(entry, 'registered_rig', return_value=str(self.repo)), \
             patch.object(entry, 'allocate_run_placeholders') as allocate, \
             self.assertRaisesRegex(RecordError, 'original retained request'):
            entry.prepare_entry(self.store, Attempt('session-1', 'instance-1', 'step-1'), gc='gc',
                city_root=str(self.root), rig_name='example', workflow_root_id='suffix-1',
                entrypoint='convoy', worktree_lifecycle='new', require_plan=True)
        allocate.assert_not_called()

    def test_canonical_review_and_publish_first_writes_join_suffix_only_with_payload(self):
        from test_workspace_store import MemoryPort
        from workspace_outputs import prepare_record
        self.suffix()
        before = copy.deepcopy(self.rows)
        fixtures = json.loads((Path(fixture.__file__).parent / 'fixtures/workspace-records/valid.json').read_text())
        for kind, stage, target in (('canonical', 'record-canonical', 'gc.run-operator'),
                                    ('review', 'review-result', 'gc.implementation-reviewer'),
                                    ('publish', 'publish', 'gc.publisher')):
            with self.subTest(kind=kind):
                self.rows.clear(); self.rows.update(copy.deepcopy(before))
                formula = Path(fixture.__file__).parents[1] / 'formulas/build-from-decompose.formula.toml'
                self.rows['suffix-1']['metadata'].update({'gc.formula_name': 'build-from-decompose',
                    'gc.formula_source': str(formula), 'gc.formula_hash': hashlib.sha256(formula.read_bytes()).hexdigest()})
                self.rows['step-1']['metadata'].update({'gc.session_id': 'session-1', 'gc.step_id': stage,
                    'gc.step_ref': stage, 'gc.run_target': target, 'gc.native_step_dependencies.v1': '[]'})
                result = self.read(workflow_root_id='suffix-1', require_plan=True)
                context = NativeRunContinuation(canonical_bytes(result['native_continuation']))
                metadata = self.rows['suffix-1']['metadata']
                writer_map = CookedWriterMap(canonical_bytes({'version': 1, 'workflow_root_id': 'root-1',
                    'store_ref': 'rig:example', 'source_member_id': 'root-1', 'expansion_root_id': 'suffix-1',
                    'formula_name': metadata['gc.formula_name'], 'formula_hash': metadata['gc.formula_hash'],
                    'formula_source': metadata['gc.formula_source'], 'steps': [{'bead_id': 'step-1',
                        'step_id': stage, 'step_ref': stage, 'dependencies': [], 'record_kinds': [kind]}]}), continuation=context)
                payload = dict(fixtures[kind], workflow_root_id='root-1', writer_step_id='step-1', source_plan_owner_id='plan-owner')
                if kind == 'canonical': payload['workspace_owner_id'] = 'member-1'
                self.rows['new-record'] = self.row('new-record', status='closed')
                self.rows['new-grant'] = self.row('new-grant', status='closed')
                port = MemoryPort(self.rows)
                store = WorkspaceStore('rig:example', cwd=self.root, common_git_dir=self.repo / '.git')
                store._command = port
                prepared = prepare_record(store, Attempt('session-1', 'instance-1', 'step-1'), payload,
                    kind=kind, record_id='new-record', authority_id='new-grant', reference_owner_id='root-1',
                    writer_map=writer_map, native_rows=port.rows, initial_write=True)
                self.assertNotIn(CONTINUATION_KEY, port.rows['suffix-1']['metadata'])
                self.assertEqual(store.execute(prepared)['outcome'], 'committed')
                self.assertEqual(port.rows['suffix-1']['metadata'][CONTINUATION_KEY], context.reference_bytes.decode())
                self.assertEqual(port.rows['step-1']['metadata']['gc.root_bead_id'], 'suffix-1')

    def planning_suffix(self):
        self.rows['root-1']['metadata']['gc.input_convoy_id'] = 'initial-1'
        self.rows['suffix-1'] = self.row('suffix-1', metadata={
            'gc.kind': 'workflow', 'gc.root_store_ref': 'rig:example',
            'gc.input_convoy_id': 'initial-1', 'gc.var.worktree_run_root': 'root-1'})
        self.rows['step-1']['metadata'].update({'gc.root_bead_id': 'suffix-1',
            'gc.session_id': 'session-1', 'gc.step_id': 'decompose', 'gc.step_ref': 'decompose',
            'gc.build.artifact_schema': 'gc.build.decomposition.v1', 'gc.native_step_dependencies.v1': '[]'})
        formula = Path(fixture.__file__).parents[1] / 'formulas' / 'build-from-decompose.formula.toml'
        self.rows['suffix-1']['metadata'].update({'gc.formula_name': 'build-from-decompose',
            'gc.formula_source': str(formula), 'gc.formula_hash': hashlib.sha256(formula.read_bytes()).hexdigest()})
        for bead in ('new-plan', 'new-grant'):
            self.rows[bead] = self.row(bead, status='closed')
        scope = {'gc.root_bead_id': 'root-1', 'gc.root_store_ref': 'rig:example',
                 'gc.source_root_id': 'root-1', 'gc.source_generation': '1'}
        self.rows['member-1'] = self.row('member-1', metadata=scope)
        self.rows['new-convoy'] = self.row('new-convoy', kind='convoy', metadata=scope)
        self.plan = {'version': 1, 'workflow_root_id': 'root-1', 'generation': 1,
            'writer_step_id': 'step-1', 'source_plan_owner_id': 'step-1', 'base_oid': self.record['base_oid'],
            'parent_canonical_generation': None, 'parent_canonical_oid': None,
            'nodes': [{'owner_id': 'member-1', 'strategy': 'isolated', 'member_ids': ['member-1'],
                       'source_predecessor_owner_ids': [], 'single_lane': False}], 'terminal_owner_id': 'member-1'}
        result = self.read(workflow_root_id='suffix-1')
        continuation = NativeRunContinuation(canonical_bytes(result['native_continuation']))
        metadata = self.rows['suffix-1']['metadata']
        writer_map = CookedWriterMap(canonical_bytes({'version': 1, 'workflow_root_id': 'root-1',
            'store_ref': 'rig:example', 'source_member_id': 'root-1', 'expansion_root_id': 'suffix-1',
            'formula_name': metadata['gc.formula_name'], 'formula_hash': metadata['gc.formula_hash'],
            'formula_source': metadata['gc.formula_source'], 'steps': [{'bead_id': 'step-1',
                'step_id': 'decompose', 'step_ref': 'decompose', 'dependencies': [], 'record_kinds': ['source-plan']}]}),
            continuation=continuation)
        return continuation, writer_map

    def test_first_plan_publication_atomically_joins_real_suffix_and_preserves_original_run(self):
        from test_workspace_store import MemoryPort
        from workspace_source_plan import declare_plan, validate_source_plan
        continuation, writer_map = self.planning_suffix()
        port = MemoryPort(self.rows)
        store = WorkspaceStore('rig:example', cwd=self.root, common_git_dir=self.repo / '.git')
        store._command = port
        original = copy.deepcopy(self.record)
        prepared = declare_plan(store, Attempt('session-1', 'instance-1', 'step-1'), self.plan,
            run_record_id='record-1', record_bead_id='new-plan', authority_id='new-grant',
            implementation_convoy_id='new-convoy', writer_map=writer_map, writer_rows=port.rows)
        for bead in continuation.row_ids:
            self.assertIn(bead, {item['id'] for item in prepared.request['rows']})
        self.assertNotIn(CONTINUATION_KEY, port.rows['suffix-1']['metadata'])
        self.assertEqual(store.execute(prepared)['outcome'], 'committed')
        self.assertEqual(port.rows['step-1']['metadata']['gc.root_bead_id'], 'suffix-1')
        self.assertEqual(port.rows['step-1']['metadata']['gc.source_root_id'], 'root-1')
        self.assertEqual(port.rows['suffix-1']['metadata'][CONTINUATION_KEY], continuation.reference_bytes.decode())
        self.assertEqual(self.record, original)
        self.assertEqual(port.rows['root-1']['metadata']['gc.input_convoy_id'], 'new-convoy')
        self.assertEqual(port.rows['root-1']['metadata'][entry.RUN_REF], canonical_bytes(self.reference).decode())
        validate_source_plan(self.plan, self.record, port.rows, store_ref='rig:example', stored=self.plan)
        # A different physical owner cannot borrow that joined reference.
        port.rows['step-1']['metadata']['gc.root_bead_id'] = 'foreign-1'
        with self.assertRaisesRegex(RecordError, 'published suffix route'):
            validate_source_plan(self.plan, self.record, port.rows, store_ref='rig:example', stored=self.plan)

    def test_first_plan_stale_original_row_refuses_without_join_or_payload(self):
        from test_workspace_store import MemoryPort
        from workspace_source_plan import declare_plan
        _, writer_map = self.planning_suffix()
        port = MemoryPort(self.rows)
        store = WorkspaceStore('rig:example', cwd=self.root, common_git_dir=self.repo / '.git')
        store._command = port
        prepared = declare_plan(store, Attempt('session-1', 'instance-1', 'step-1'), self.plan,
            run_record_id='record-1', record_bead_id='new-plan', authority_id='new-grant',
            implementation_convoy_id='new-convoy', writer_map=writer_map, writer_rows=port.rows)
        port.rows['root-1']['revision'] = '2'
        before = copy.deepcopy(port.rows)
        self.assertEqual(store.execute(prepared)['outcome'], 'unknown')
        self.assertEqual(port.rows, before)
        self.assertNotIn(CONTINUATION_KEY, port.rows['suffix-1']['metadata'])
        self.assertNotIn(contracts()['source-plan']['metadata_key'], port.rows['new-plan']['metadata'])

    def test_fix_plan_publication_preserves_intake_proof_and_fresh_stale_sibling_refuses(self):
        from test_workspace_store import MemoryPort
        from workspace_source_plan import declare_plan
        self.suffix()
        canonical = self.accepted_canonical()
        self.rows['step-1']['metadata'].update({'gc.session_id': 'session-1', 'gc.step_id': 'plan-fixes',
            'gc.step_ref': 'plan-fixes', 'gc.run_target': 'gc.run-operator', 'gc.native_step_dependencies.v1': '[]'})
        formula = Path(fixture.__file__).parents[1] / 'formulas/build-from-decompose.formula.toml'
        self.rows['suffix-1']['metadata'].update({'gc.formula_name': 'build-from-decompose',
            'gc.formula_source': str(formula), 'gc.formula_hash': hashlib.sha256(formula.read_bytes()).hexdigest()})
        result = self.read(workflow_root_id='suffix-1', generation=2)
        context = NativeRunContinuation(canonical_bytes(result['native_continuation']))
        metadata = self.rows['suffix-1']['metadata']
        writer_map = CookedWriterMap(canonical_bytes({'version': 1, 'workflow_root_id': 'root-1',
            'store_ref': 'rig:example', 'source_member_id': 'root-1', 'expansion_root_id': 'suffix-1',
            'formula_name': metadata['gc.formula_name'], 'formula_hash': metadata['gc.formula_hash'],
            'formula_source': metadata['gc.formula_source'], 'steps': [{'bead_id': 'step-1',
                'step_id': 'plan-fixes', 'step_ref': 'plan-fixes', 'dependencies': [], 'record_kinds': ['source-plan']}]}),
            continuation=context)
        scope = {'gc.root_bead_id': 'root-1', 'gc.root_store_ref': 'rig:example',
                 'gc.source_root_id': 'root-1', 'gc.source_generation': '2'}
        self.rows['member-2'] = self.row('member-2', metadata=scope)
        self.rows['convoy-2'] = self.row('convoy-2', kind='convoy', metadata=scope)
        self.rows['plan-2'] = self.row('plan-2', status='closed')
        self.rows['grant-2'] = self.row('grant-2', status='closed')
        plan = dict(self.plan, generation=2, writer_step_id='step-1', source_plan_owner_id='step-1',
            base_oid=canonical['output_oid'], parent_canonical_generation=1, parent_canonical_oid=canonical['output_oid'],
            nodes=[dict(owner_id='member-2', strategy='isolated', member_ids=['member-2'],
                        source_predecessor_owner_ids=[], single_lane=False)], terminal_owner_id='member-2')
        port = MemoryPort(self.rows)
        store = WorkspaceStore('rig:example', cwd=self.root, common_git_dir=self.repo / '.git')
        store._command = port
        prepared = declare_plan(store, Attempt('session-1', 'instance-1', 'step-1'), plan,
            run_record_id='record-1', record_bead_id='plan-2', authority_id='grant-2',
            implementation_convoy_id='convoy-2', writer_map=writer_map, writer_rows=port.rows)
        self.assertEqual(store.execute(prepared)['outcome'], 'committed')
        self.rows.clear(); self.rows.update(copy.deepcopy(port.rows))
        continued = self.read(workflow_root_id='suffix-1', generation=2, require_plan=True)
        self.assertEqual(continued['source_plan'], plan)
        self.assertEqual(continued['native_continuation']['suffix_input_plan_ref']['bead_id'], 'plan-record')
        self.assertIn('plan-record', continued['_native_rows'])
        self.assertEqual(port.rows['suffix-1']['metadata'][CONTINUATION_KEY], context.reference_bytes.decode())
        # A new physical sibling has not joined that original route. Supplying
        # the now-old convoy cannot select an old source generation for it.
        self.rows['sibling-1'] = self.row('sibling-1', metadata={
            'gc.kind': 'workflow', 'gc.root_store_ref': 'rig:example', 'gc.input_convoy_id': 'implementation-1'})
        self.rows['step-1']['metadata']['gc.root_bead_id'] = 'sibling-1'
        with self.assertRaises(entry.EntryError):
            self.read(workflow_root_id='sibling-1', generation=2, require_plan=True)


class InitialSuffixCaptureTests(unittest.TestCase):
    from test_workspace_run import RunStoreTests as _fixture
    setUp = _fixture.setUp
    git = _fixture.git
    args = _fixture.args
    source_store = _fixture.source_store
    native_allocator = _fixture.native_allocator

    def capture(self, stage):
        import workspace_cooked
        self.port.rows['writer-1']['metadata'].update({'gc.step_id': stage, 'gc.step_ref': stage})
        declaration = self.writer_map.declaration
        declaration['steps'][0].update(step_id=stage, step_ref=stage)
        self.writer_map = CookedWriterMap(canonical_bytes(declaration))
        _, created, calls, native = self.native_allocator()
        with patch.object(entry, 'native_json', side_effect=native), \
             patch.object(entry, 'registered_rig', return_value=str(self.repo)), \
             patch('workspace_run.registered_rig', return_value=str(self.repo)), \
             patch.object(workspace_cooked, 'read_cooked_writer_map', side_effect=lambda *a, **k:
                 (self.writer_map, self.store.snapshot(['root-1', 'writer-1']))):
            args = dict(gc='gc', city_root=str(self.root), rig_name='example', workflow_root_id='root-1',
                entrypoint='plan' if stage == 'prepare-plan' else 'decompose', worktree_lifecycle='new')
            first = entry.prepare_entry(self.store, self.attempt, **args)
            self.assertEqual(first['receipt']['outcome'], 'committed')
            (self.repo / 'source.txt').write_text('moving branch after capture\n')
            self.git('add', 'source.txt'); self.git('commit', '-m', 'later source')
            second = entry.prepare_entry(self.store, self.attempt, **args)
        self.assertEqual(first['run'], second['run'])
        self.assertEqual(first['run']['base_oid'], self.base)
        self.assertEqual(len(created), 2)
        self.assertEqual(sum(call[:2] == ['bd', 'create'] for call in calls), 2)
        self.assertEqual(len(self.port.requests), 1)

    def test_initial_plan_captures_run_and_policy_once_through_real_adapter(self):
        self.capture('prepare-plan')

    def test_initial_decompose_captures_run_and_policy_once_through_real_adapter(self):
        self.capture('prepare-decompose')


if __name__ == '__main__':
    unittest.main()
