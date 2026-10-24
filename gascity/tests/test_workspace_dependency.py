from __future__ import annotations

import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_workspace_source_plan import node, plan_record

SCRIPTS = Path(__file__).resolve().parents[1] / 'assets' / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def module():
    spec = importlib.util.spec_from_file_location('workspace_dependency', SCRIPTS / 'workspace_dependency.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


class NativeRows:
    def __init__(self, rows):
        self.rows = rows
        self.reads = []

    def snapshot(self, ids):
        self.reads.append(list(ids))
        return {key: copy.deepcopy(self.rows[key]) for key in ids}


def row(bead_id, metadata=None, *, status='closed', assignee='', revision='1'):
    return dict(id=bead_id, metadata=metadata or {}, status=status,
                assignee=assignee, revision=revision, type='task', labels=[])


def output():
    return dict(version=1, workflow_root_id='root-1', generation=1,
        writer_step_id='record-A', source_plan_owner_id='convoy-1',
        workspace_owner_id='A', strategy='isolated', input_oid='a'*40,
        output_oid='b'*40, final_member_id='A', final_member_result_sha256='1'*64,
        integration_inputs=None, integration_evidence_path=None, integration_evidence_sha256=None)


class FrozenSourceReadTests(unittest.TestCase):
    def setUp(self):
        self.helper = module()
        from workspace_records import canonical_bytes, record_identity
        self.payload = output()
        self.reference = dict(kind='owner-output', bead_id='output-A',
                              identity=list(record_identity('owner-output', self.payload)))
        self.rows = {
            'A': row('A', {'gc.workspace_output_ref': canonical_bytes(self.reference).decode()}, status='open'),
            'output-A': row('output-A', {'gc.workspace_output': canonical_bytes(self.payload).decode()}),
        }
        self.port = NativeRows(self.rows)

    def test_reference_and_payload_keep_original_native_revision(self):
        frozen = self.helper.FrozenRecords(self.port)
        self.assertEqual(self.payload, frozen.read('owner-output', 'A', 'gc.workspace_output_ref'))
        self.rows['A']['revision'] = '2'
        self.rows['A']['metadata']['gc.workspace_output_ref'] = '{}'
        self.assertEqual(self.payload, frozen.read('owner-output', 'A', 'gc.workspace_output_ref'))
        self.assertEqual('1', frozen.rows['A']['revision'])
        self.assertEqual([['A'], ['output-A']], self.port.reads)

    def test_missing_reference_is_guarded_as_absent_not_null(self):
        from workspace_store import MISSING
        frozen = self.helper.FrozenRecords(NativeRows({'A': row('A')}))
        self.assertIsNone(frozen.read('owner-output', 'A', 'gc.workspace_output_ref', required=False))
        guard = next(g for g in frozen.guards if g.key == 'gc.workspace_output_ref')
        self.assertIs(MISSING, guard.expected_value)
        with self.assertRaises(self.helper.RecordError):
            self.helper.FrozenRecords(NativeRows({'A': row('A', {'gc.workspace_output_ref': None})})).read(
                'owner-output', 'A', 'gc.workspace_output_ref', required=False)

    def test_wrong_physical_identity_and_claimed_record_refuse(self):
        for changes in ({'status':'in_progress','assignee':'foreign-worker'},
                        {'assignee':'foreign-worker'}, {'type':'session'}, {'labels':['held']}):
            rs = copy.deepcopy(self.rows)
            rs['output-A'].update(changes)
            with self.subTest(changes=changes), self.assertRaisesRegex(self.helper.RecordError, 'dedicated'):
                self.helper.FrozenRecords(NativeRows(rs)).read('owner-output', 'A', 'gc.workspace_output_ref')
        rs = copy.deepcopy(self.rows)
        ref = dict(self.reference, identity=['foreign-root', 1, 'convoy-1', 'A'])
        rs['A']['metadata']['gc.workspace_output_ref'] = json.dumps(ref)
        with self.assertRaisesRegex(self.helper.RecordError, 'identity'):
            self.helper.FrozenRecords(NativeRows(rs)).read('owner-output', 'A', 'gc.workspace_output_ref')

    def test_merging_later_snapshot_cannot_refresh_original_proof(self):
        frozen = self.helper.FrozenRecords(self.port)
        frozen.ensure(['A'])
        later = copy.deepcopy(frozen.rows)
        later['A']['revision'] = '2'
        with self.assertRaisesRegex(self.helper.RecordError, 'changed'):
            frozen.merge(later)
        self.assertEqual('1', frozen.rows['A']['revision'])

    def test_complete_batch_over_one_hundred_rows_refuses_without_chunking(self):
        ids = ['row-' + str(i) for i in range(101)]
        port = NativeRows({key: row(key) for key in ids})
        with self.assertRaisesRegex(self.helper.RecordError, '100'):
            self.helper.FrozenRecords(port).ensure(ids)
        self.assertEqual([], port.reads)

    def test_cooked_context_is_not_a_guard_until_its_original_row_is_used(self):
        context = {'step-' + str(i): row('step-' + str(i)) for i in range(110)}
        frozen = self.helper.FrozenRecords(NativeRows(context))
        frozen.merge(context, context_only=True)
        self.assertEqual(110, len(frozen.original_rows))
        self.assertEqual({}, frozen.rows)
        self.assertEqual([], frozen.guards)
        frozen.metadata('step-103', 'absent')
        self.assertEqual({'step-103'}, set(frozen.rows))
        self.assertEqual({'step-103'}, {guard.bead_id for guard in frozen.guards})
        changed = copy.deepcopy(context['step-103'])
        changed['revision'] = '2'
        with self.assertRaisesRegex(self.helper.RecordError, 'changed'):
            frozen.merge({'step-103': changed})

    def test_cooked_context_cannot_refresh_a_nested_boolean_to_an_integer(self):
        original = row('step', {'typed': True})
        frozen = self.helper.FrozenRecords(NativeRows({'step': original}))
        frozen.merge({'step': original}, context_only=True)
        changed = copy.deepcopy(original)
        changed['metadata']['typed'] = 1
        with self.assertRaisesRegex(self.helper.RecordError, 'changed'):
            frozen.merge({'step': changed})
        self.assertIs(True, frozen.original_rows['step']['metadata']['typed'])

    def test_cooked_readback_preserves_original_nested_metadata_types(self):
        from workspace_runtime import _ReadFence
        original = row('step', {'typed': True})
        port = NativeRows({'step': original})
        fence = _ReadFence(port)
        fence.retain({'step': original})
        port.rows['step']['metadata']['typed'] = 1
        with self.assertRaisesRegex(self.helper.RecordError, 'changed'):
            fence.cooked_snapshot(['step'])
        self.assertIs(True, fence.rows['step']['metadata']['typed'])


class WorkspaceInputCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.helper = module()
        from workspace_store import Attempt
        self.attempt = Attempt('session-1', 'private-instance', 'prepare-C')
        self.plan = plan_record()
        self.bundle = dict(workflow_root_id='root-1', generation=1, source_plan_owner_id='convoy-1',
            workspace_owner_id='C', member_id='C', member_position=0, strategy='integration',
            store_ref='rig:project', base_oid='a'*40, input_oid=None,
            predecessors=[dict(owner_id='B', output_oid='b'*40, workspace_output_sha256='1'*64),
                          dict(owner_id='A', output_oid='c'*40, workspace_output_sha256='2'*64)])

    def initial(self):
        return self.helper.initial_workspace(self.bundle, self.attempt,
            workspace_record_id='native-workspace-17', work_dir='/project/worktrees/C-g1', work_branch=None)

    def test_integration_starts_at_base_and_keeps_ordered_accepted_sources(self):
        workspace = self.initial()
        self.assertEqual('preparing', workspace['phase'])
        self.assertEqual('a'*40, workspace['input_oid'])
        self.assertEqual(workspace['input_oid'], workspace['current_oid'])
        self.assertEqual(['B', 'A'], [source['owner_id'] for source in workspace['integration_inputs']])
        self.assertIsNone(workspace['native_provenance'])
        self.assertEqual(self.attempt.writer_attempt_id, workspace['writer_attempt_id'])
        self.assertNotIn('private-instance', json.dumps(workspace))

    def test_dependent_workspace_starts_at_exact_accepted_output(self):
        self.bundle.update(strategy='dependent', workspace_owner_id='D', member_id='D', input_oid='d'*40,
                           predecessors=[self.bundle['predecessors'][0]])
        workspace = self.initial()
        self.assertEqual('d'*40, workspace['input_oid'])
        self.assertIsNone(workspace['integration_inputs'])

    def test_shared_successor_preserves_native_owner_base_path_and_attempt(self):
        self.bundle.update(strategy='shared-chain', workspace_owner_id='chain', member_id='first', input_oid='b'*40,
                           predecessors=[])
        workspace = self.initial()
        workspace.update(phase='result', current_oid='c'*40, output_oid='c'*40,
                         native_attempt_id='native-attempt', native_provenance={'base_sha':'b'*40})
        successor = dict(self.bundle, member_id='second', member_position=1, input_oid='c'*40)
        candidate = self.helper.select_checkpoint(workspace, successor, self.attempt)
        self.assertEqual('entry', candidate['phase'])
        self.assertEqual('second', candidate['active_member_id'])
        self.assertEqual('c'*40, candidate['input_oid'])
        for key in ('workspace_bead_id','work_dir','work_branch','native_attempt_id','native_provenance'):
            self.assertEqual(workspace[key], candidate[key])
        self.assertIsNone(candidate['output_oid'])

    def test_blocked_skipped_or_changed_member_checkpoint_cannot_be_reused(self):
        self.bundle.update(strategy='shared-chain', workspace_owner_id='chain', member_id='first', input_oid='b'*40,
                           predecessors=[])
        workspace = self.initial()
        for candidate in (dict(workspace, phase='blocked'),
                          dict(workspace, input_oid='e'*40),
                          dict(workspace, active_member_id='foreign-member')):
            with self.subTest(candidate=candidate), self.assertRaises(self.helper.RecordError):
                self.helper.select_checkpoint(candidate, self.bundle, self.attempt)


# This port executes actual Git and all production Python validators. It is
# deliberately labelled component evidence, not native backend/worker acceptance.
WORKTREE_PORT = r'''
from datetime import datetime, timezone
if 'create' in args and 'bd' in args:
    rows = data['stores']['rig:fixture']
    number = data.get('allocation_number', 0) + 1
    data['allocation_number'] = number
    key = 'native-allocation-' + str(number)
    rows[key] = dict(id=key, revision='1', status='closed', assignee='', type='task', labels=[], metadata={})
    data.setdefault('allocation_details', {})[key] = dict(title=args[args.index('create') + 1], description=option('description'))
    state_path.write_text(json.dumps(data))
    if data.get('lose_allocation_ack_at') == number:
        sys.exit('native protocol fixture: create committed but acknowledgement lost')
    emit(rows[key])
if 'show' in args and 'bd' in args:
    key = args[args.index('show') + 1]
    emit([{**data['stores']['rig:fixture'][key], **data['allocation_details'][key]}])
if 'worktree' in args:
    action = args[args.index('worktree') + 1]
    if '--help' in args:
        print('--repo --root --path --branch --mode --base --base-sha --bead --store-ref --creator --owner --generation --lifecycle --placement --lock-timeout --json')
        sys.exit(0)
    path = pathlib.Path(option('path'))
    created = False
    def git(*argv):
        return subprocess.check_output(['git', '-C', option('repo'), *argv], text=True, stderr=subprocess.PIPE).strip()
    if action == 'ensure' and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if option('mode') == 'detached':
            git('worktree', 'add', '--detach', str(path), option('base'))
        else:
            git('worktree', 'add', '-b', option('branch'), str(path), option('base'))
        created = True
        provenance = dict(schema_version=2, bead_id=option('bead'), store_ref=option('store-ref'),
            repo_identity=git('rev-parse', '--path-format=absolute', '--git-common-dir'),
            path=str(path), branch=option('branch'), mode=option('mode'),
            placement=option('placement') or 'outside-worktrees', base_ref=option('base'), base_sha=option('base-sha'),
            creator=option('creator'), owner=option('owner'), generation=option('generation'),
            lifecycle=option('lifecycle'), created_at=datetime.now(timezone.utc).isoformat().replace('+00:00','Z'), attempt_id='native-' + option('bead'))
        data.setdefault('provenances', {})[str(path)] = provenance
        state_path.write_text(json.dumps(data))
        if data.get('lose_first_ensure_ack'):
            sys.exit('native protocol fixture: provisioned worktree but acknowledgement lost')
    else:
        provenance = data.get('provenances', {}).get(str(path), data['provenance'])
    head = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    emit(dict(schema_version='1', ok=True, command='worktree ' + action, action=action, path=str(path),
        branch=option('branch'), mode=option('mode'), placement=option('placement') or 'outside-worktrees',
        head=head, created=created, branch_created=created and option('mode') == 'attached', provenance=provenance))
'''


class DependencyNativeCompositionTests(unittest.TestCase):
    def setUp(self):
        from test_workspace_runtime import NativeRuntimeTests, PORT
        self.fixture = NativeRuntimeTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.helper = module()
        self.port_source = PORT[:PORT.index("if 'worktree' in args:")] + WORKTREE_PORT + "\nsys.exit('unsupported command ' + repr(args))\n"
        self.port_source = self.port_source.replace(
            "        request = json.loads(pathlib.Path(option('request')).read_text())\n",
            "        request = json.loads(pathlib.Path(option('request')).read_text())\n"
            "        data.setdefault('requests', []).append(copy.deepcopy(request))\n")
        self.port_source = self.port_source.replace("    key, value = option('metadata-field').split('=', 1)\n", """    if option('desc-contains'):
        if 'allocation_lookup_response' in data: emit(data['allocation_lookup_response'])
        value = option('desc-contains')
        emit([{**data['stores']['rig:fixture'][key], **details}
              for key, details in data.get('allocation_details', {}).items()
              if value in (details.get('description') or '')][:2])
    key, value = option('metadata-field').split('=', 1)
""")

    def prepare_fixture(self, *, integration=False, conflict=False, shared=False):
        from workspace_records import canonical_bytes, contracts, record_sha256
        from workspace_store import Attempt, TOPOLOGY
        import workspace_outputs as outputs
        f = self.fixture
        f.rows['root']['metadata'].update({'gc.var.worktree_parent': str(f.work.parent),
                                         'gc.var.worktree_allow_external_parent': 'true'})
        f.git(f.repo,'config','user.name','Fixture')
        f.git(f.repo,'config','user.email','fixture@example.invalid')
        f.rows['recorder'].update(status='closed', assignee='')
        f.rows['recorder']['metadata']['gc.outcome'] = 'pass'
        f.sessions['recorder-session']['metadata'].update(state='asleep', current_claim_bead_id='')
        f.plan['nodes'] = [node('member')]
        if integration:
            f.plan['nodes'].append(node('B'))
        f.plan['nodes'].append(node('C', ['member', 'B'] if integration else ['member']))
        if shared:
            f.plan['nodes'][-1].update(strategy='shared-chain', member_ids=['C', 'D'], single_lane=True)
        f.plan['terminal_owner_id'] = 'C'
        f.formula['steps'].insert(0, dict(id='do-work.prepare-worktree', metadata={'gc.run_target':'gc.run-operator'}))
        f.formula['deps'].append(dict(step_id='do-work.implement', depends_on_id='do-work.prepare-worktree', type='blocks'))
        f.rows['producer']['metadata'][TOPOLOGY] = canonical_bytes(['do-work.prepare-worktree']).decode()
        f.rows['prepare-A'] = f.row('prepare-A', {
            'gc.step_id':'do-work.prepare-worktree','gc.step_ref':'do-work.prepare-worktree',
            'gc.run_target':'gc.run-operator','gc.attach_root_id':'expansion',
            'gc.source_anchor_id':'member','gc.drain_member_id':'member', TOPOLOGY:'[]','gc.outcome':'pass'}, status='closed')
        for member in ('C', *(['B'] if integration else []), *(['D'] if shared else [])):
            f.rows[member] = f.row(member, {'gc.source_root_id':'root','gc.source_generation':'1'})
            expansion = 'expansion-' + member
            f.rows[expansion] = f.row(expansion, {key:value for key,value in f.rows['expansion']['metadata'].items()
                                                if key.startswith('gc.formula_')})
            previous = None
            for role, stage, target in (('prepare','prepare-worktree','gc.run-operator'),
                    ('producer','implement','gc.implementation-worker'),
                    ('reviewer','independent-acceptance','gc.implementation-reviewer'),
                    ('recorder','record-result','gc.run-operator')):
                key = role + '-' + member
                meta = {'gc.step_id':'do-work.'+stage,'gc.step_ref':'do-work.'+stage,
                    'gc.run_target':target,'gc.attach_root_id':expansion,'gc.source_anchor_id':member,
                    'gc.drain_member_id':member, TOPOLOGY:canonical_bytes([previous] if previous else []).decode()}
                if role == 'producer':meta['gc.build.artifact_schema'] = 'gc.build.implementation-summary.v1'
                if member == 'B' or role == 'prepare':
                    attempt = Attempt(key+'-session', key+'-private-instance', key)
                    f.attempts[key] = attempt
                    meta.update({'gc.session_id':attempt.session_id,'gc.session_name':key+'-runtime'})
                    session = f.row(attempt.session_id, {'template':'fixture/'+target,'session_name':key+'-runtime',
                        'instance_token':attempt.instance_token,'session_origin':'ephemeral',
                        'state':'active' if member=='C' else 'asleep',
                        'current_claim_bead_id':key if member=='C' else ''}, scoped=False)
                    session['type']='session'; f.sessions[session['id']]=session
                closed = member == 'B'
                if closed:meta['gc.outcome']='pass'
                f.rows[key] = f.row(key, meta, status='closed' if closed else 'in_progress' if role=='prepare' else 'open')
                if member=='C' and role=='prepare':f.rows[key]['assignee']=f.attempts[key].session_id
                previous='do-work.'+stage
        f.rows['plan-record']['metadata']['gc.source_plan'] = canonical_bytes(f.plan).decode()
        f.rows['convoy']['metadata']['gc.source_plan_sha256'] = record_sha256(f.plan)
        self.provenances = {str(f.work):f.provenance}

        def accepted(member, work, workspace, producer, reviewer, recorder, *, publish_owner=True):
            binding = outputs.result_binding(f.run,f.plan,workspace,store_ref='rig:fixture',member_id=member,
                                             output_oid=workspace['output_oid'])
            identities = {}
            for name,key in (('producer',producer),('reviewer',reviewer),('recorder',recorder)):
                a = f.attempts[key]
                identities[name] = dict(step_id=key,session_id=a.session_id,attempt_id=a.writer_attempt_id)
            evidence=f.artifacts/member; evidence.mkdir(exist_ok=True)
            checks=outputs.execute_checks(binding,work,f.requirements,identities['producer'],evidence/'checks')
            policy=dict(f.policy_binding,source_plan_sha256=record_sha256(f.plan))
            for i,check in enumerate(checks):
                proof=outputs.read_artifact({'path':check['evidence_path'],'sha256':check['evidence_sha256']},f.artifacts)
                bound=outputs.immutable_json(evidence/('bound-check-'+str(i)+'.json'),dict(proof,policy_binding=policy))
                check.update(evidence_path=bound['path'],evidence_sha256=bound['sha256'])
            summary=evidence/'summary.md';summary.write_text('Required project check and exact member source reviewed.\n')
            artifacts=[outputs.artifact(summary,f.artifacts)]
            context=outputs.begin_review(binding,work,checks,f.requirements,identities['producer'],identities['reviewer'],artifacts,f.artifacts)
            context['policy_binding']=policy
            report=evidence/'review.md';report.write_text('Exact source and check evidence reviewed.\n')
            review=outputs.complete_review(context,work,report,'passed',evidence/'review.json',f.artifacts)
            result=outputs.make_member_result(binding,writer_step_id=recorder,
                commit_oids=f.git(work,'rev-list','--reverse',binding['input_oid']+'..'+binding['output_oid']).splitlines(),
                checks=checks,review=review,artifacts=artifacts,required_checks=f.requirements,artifact_root=f.artifacts,work_dir=work)
            owner_output=(outputs.make_owner_output(f.plan,[result],artifact_root=f.artifacts,
                qualifications={member:{'binding':binding,'required_checks':f.requirements}}) if publish_owner else None)
            payloads=[('member-result','result-'+member,result)]
            if owner_output is not None:payloads.append(('owner-output','output-'+member,owner_output))
            for kind,key,payload in payloads:
                f.rows[key]=f.row(key,{contracts()[kind]['metadata_key']:canonical_bytes(payload).decode()},status='closed',scoped=False)
            f.rows[member]['metadata']['gc.workspace_result_ref']=f.ref('member-result','result-'+member,result)
            if owner_output is not None:
                f.rows[member]['metadata']['gc.workspace_output_ref']=f.ref('owner-output','output-'+member,owner_output)
            return result,owner_output

        self.accepted = accepted
        accepted('member',f.work,f.workspace,'producer','reviewer','recorder')
        if integration:
            work=f.work.parent/'B';f.git(f.repo,'worktree','add','--detach',str(work),f.base)
            (work/'feature.py').write_text('VALUE = 42 # conflicting B\n' if conflict else 'VALUE = 42\n')
            (work/'other.py').write_text('FLAG = 7\n')
            f.git(work,'add','.');f.git(work,'commit','-qm','accepted B')
            oid=f.git(work,'rev-parse','HEAD')
            provenance=dict(f.provenance,bead_id='workspace-B',path=str(work),owner='B',attempt_id='native-B')
            workspace=dict(f.workspace,workspace_owner_id='B',workspace_bead_id='workspace-B',work_dir=str(work),
                active_member_id='B',current_oid=oid,output_oid=oid,writer_step_id='producer-B',
                writer_attempt_id=f.attempts['producer-B'].writer_attempt_id,native_attempt_id='native-B',native_provenance=provenance)
            workspace['claim_binding']={k:workspace[k] for k in f.workspace['claim_binding']}
            from workspace_checkout import WorkspaceCheckout
            engine=WorkspaceCheckout(f.run,workspace,store_ref='rig:fixture',evidence_dir=str(f.diagnostics),
                                      parent=str(work.parent),allow_external_parent=True,gc=str(f.port),city_root=str(f.city))
            owner=engine._result({'provenance':provenance,'head':oid})['owner_metadata']
            f.rows['workspace-B']=f.row('workspace-B',{'gc.workspace':canonical_bytes(workspace).decode(),**owner},status='closed',scoped=False)
            f.rows['B']['metadata']['gc.workspace_ref']=f.ref('workspace','workspace-B',workspace)
            launch=dict(version=1,binding_step_id='producer-B',workflow_root_id='root',generation=1,
                workspace_owner_id='B',workspace_bead_id='workspace-B',store_ref='rig:fixture',native_attempt_id='native-B')
            f.rows['producer-B']['metadata']['gc.worktree_ref']=canonical_bytes(launch).decode()
            self.provenances[str(work)]=provenance
            accepted('B',work,workspace,'producer-B','reviewer-B','recorder-B')
        f.save()
        state=json.loads((f.root/'port.json').read_text());state['provenances']=self.provenances
        (f.root/'port.json').write_text(json.dumps(state))
        f.port.write_text(self.port_source)
        self.environment=patch.dict(os.environ,{'GC_SESSION_ID':f.attempts['prepare-C'].session_id,
            'GC_INSTANCE_TOKEN':f.attempts['prepare-C'].instance_token,
            'GIT_CONFIG_COUNT':'2','GIT_CONFIG_KEY_0':'user.name','GIT_CONFIG_VALUE_0':'Fixture',
            'GIT_CONFIG_KEY_1':'user.email','GIT_CONFIG_VALUE_1':'fixture@example.invalid'})
        self.environment.start();self.addCleanup(self.environment.stop)

    def prepare(self, **options):
        f=self.fixture
        member = options.pop('member_id', 'C')
        attempt = options.pop('attempt', f.attempts['prepare-'+member])
        return self.helper.prepare_dependency_workspace(f.store,attempt,gc=str(f.port),city_root=str(f.city),
            rig_name='fixture',workflow_root_id=options.pop('workflow_root_id', 'root'),
            input_convoy_id=options.pop('input_convoy_id', 'convoy'),generation=options.pop('generation',1),
            workspace_owner_id=options.pop('workspace_owner_id', 'C'),member_id=member,artifact_root=f.artifacts,evidence_dir=f.diagnostics,
            parent=str(f.work.parent),allow_external_parent=True, **options)

    def state(self):
        return json.loads((self.fixture.root/'port.json').read_text())

    def child_fixture(self, *, integration=False):
        self.prepare_fixture(integration=integration)
        f = self.fixture
        f.provenances = self.provenances
        return f.native_child('child-C', 'C',
            roles=('prepare-C', 'producer-C', 'reviewer-C', 'recorder-C'),
            expansion='expansion-C', published=False)

    def test_native_child_prepares_exact_dependency_and_inherits_original_run_atomically(self):
        from workspace_entry import read_entry
        from workspace_store import CONTINUATION_KEY
        self.child_fixture(); f = self.fixture
        before = self.state()
        discovered = read_entry(f.store, gc=str(f.port), city_root=str(f.city), rig_name='fixture',
            workflow_root_id='child-C', claimed_step_id='prepare-C', worktree_lifecycle='new',
            generation=1, require_plan=True)
        member_id = discovered['native_continuation']['member_id']
        owners = [node['owner_id'] for node in discovered['source_plan']['nodes'] if member_id in node['member_ids']]
        self.assertEqual(['C'], owners)
        self.assertNotIn('gc.source_plan_ref', before['stores']['rig:fixture']['child-C']['metadata'])
        self.assertNotIn('gc.source_plan_ref', before['stores']['rig:fixture']['root']['metadata'])
        result = self.prepare(workflow_root_id=discovered['workflow_root_id'],
            input_convoy_id=discovered['native_input_convoy_id'],
            member_id=member_id, workspace_owner_id=owners[0])
        rows = self.state()['stores']['rig:fixture']
        workspace = result['workspace']
        self.assertEqual(f.oid, result['input_oid'])
        self.assertEqual('root', workspace['workflow_root_id'])
        self.assertEqual('child-C', rows[workspace['workspace_bead_id']]['metadata']['gc.root_bead_id'])
        self.assertEqual('root', rows['C']['metadata']['gc.root_bead_id'])
        self.assertEqual(before['stores']['rig:fixture']['run-record']['metadata']['gc.implementation_run'],
                         rows['run-record']['metadata']['gc.implementation_run'])
        self.assertIn(CONTINUATION_KEY, rows['child-C']['metadata'])
        for step_id in result['launch_step_ids']:
            reference = json.loads(rows[step_id]['metadata']['gc.worktree_ref'])
            self.assertEqual('child-C', reference['workflow_root_id'])
            self.assertEqual(step_id, reference['binding_step_id'])
        first = self.state()['requests'][0]
        changed = {row['id']: row.get('set', {}) for row in first['rows']}
        self.assertIn(CONTINUATION_KEY, changed['child-C'])
        self.assertIn('gc.workspace', changed[workspace['workspace_bead_id']])

    def test_native_child_ordered_integration_and_readonly_dirty_continuation(self):
        self.child_fixture(integration=True); f = self.fixture
        first = self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
        work = Path(first['path'])
        self.assertEqual('FLAG = 7\n', (work/'other.py').read_text())
        (work/'partial.py').write_text('PARTIAL = 1\n')
        f.git(work, 'add', 'partial.py'); f.git(work, 'commit', '-qm', 'child partial implementation')
        head = f.git(work, 'rev-parse', 'HEAD')
        (work/'notes.txt').write_text('unfinished child work\n')
        before = self.state()
        continued = self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
        self.assertEqual('continuation', continued['state'])
        self.assertEqual(first['input_oid'], continued['input_oid'])
        self.assertEqual(head, continued['head'])
        self.assertFalse(continued['accepted'])
        self.assertEqual(before, self.state())
        self.assertEqual('unfinished child work\n', (work/'notes.txt').read_text())

    def test_changed_native_child_relationship_refuses_before_allocating_or_creating_git(self):
        self.child_fixture(); f = self.fixture
        original = self.state()
        for bead_id, key, value in (('child-C-unit', 'gc.parent_convoy_id', 'foreign'),
                                   ('child-C-control', 'gc.root_store_ref', 'rig:foreign'),
                                   ('C', 'gc.source_generation', '2')):
            with self.subTest(bead_id=bead_id, key=key):
                changed = copy.deepcopy(original)
                changed['stores']['rig:fixture'][bead_id]['metadata'][key] = value
                (f.root/'port.json').write_text(json.dumps(changed))
                with self.assertRaises(self.helper.RecordError):
                    self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
                self.assertEqual(changed, self.state())
                self.assertFalse((f.work.parent/'C-g1').exists())
        (f.root/'port.json').write_text(json.dumps(original))

    def test_unknown_child_write_survives_new_process_and_blocks_new_intent(self):
        self.child_fixture(); f = self.fixture
        script = self.port_source.replace(
            "    if option('snapshot'):\n",
            "    if option('snapshot'):\n"
            "        if data.get('block_snapshots'): sys.exit('native readback unavailable')\n")
        script = script.replace("        state_path.write_text(json.dumps(data))\n    emit(dict(schema_version=",
            "        if data.pop('lose_next_reply', False):\n"
            "            data['block_snapshots'] = True\n"
            "            state_path.write_text(json.dumps(data))\n"
            "            sys.exit('lost native acknowledgement')\n"
            "        state_path.write_text(json.dumps(data))\n    emit(dict(schema_version=")
        f.port.write_text(script)
        state = self.state(); state['lose_next_reply'] = True
        (f.root/'port.json').write_text(json.dumps(state))
        with self.assertRaises(self.helper.DependencyError) as caught:
            self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
        path = Path(caught.exception.request_path)
        self.assertTrue(path.is_file())
        packet = json.loads(path.read_text())
        self.assertEqual(packet['request_sha256']+'.json', path.name)
        self.assertEqual({'request_bytes','before_bytes','after_bytes','scope_bytes','binding_bytes',
                          'replay','request_sha256'}, set(packet))
        before = self.state()
        self.assertEqual(1, len(before['requests']))
        self.assertFalse((f.work.parent/'C-g1').exists())
        command = [sys.executable, str(SCRIPTS/'workspace_dependency.py'), '--gc', str(f.port),
            '--city-root', str(f.city), '--store-ref', 'rig:fixture', '--resolve-request', str(path)]
        unresolved = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(1, unresolved.returncode, unresolved.stderr)
        self.assertEqual('unknown', json.loads(unresolved.stdout)['outcome'])
        self.assertEqual(before, self.state())
        before.pop('block_snapshots')
        (f.root/'port.json').write_text(json.dumps(before))
        with self.assertRaisesRegex(self.helper.DependencyError, 'unresolved'):
            self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
        self.assertEqual(before, self.state())
        resolved = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, resolved.returncode, resolved.stderr)
        self.assertEqual('committed', json.loads(resolved.stdout)['outcome'])
        self.assertEqual(before, self.state())
        self.assertEqual([], list(path.parent.glob('*.pending')))
        self.assertNotIn('private-instance', resolved.stdout)

    def shared_successor_fixture(self):
        from workspace_store import Attempt
        from workspace_runtime import NativeSourceRuntime
        self.prepare_fixture(shared=True); f = self.fixture
        f.provenances = self.provenances
        f.native_child('child-C', 'C', roles=('prepare-C','producer-C','reviewer-C','recorder-C'),
                       expansion='expansion-C', published=False)
        first = self.prepare(workflow_root_id='child-C', input_convoy_id='child-C-unit')
        work = Path(first['path'])
        (work/'c.py').write_text('C = 1\n')
        f.git(work,'add','c.py'); f.git(work,'commit','-qm','completed C')
        head = f.git(work,'rev-parse','HEAD')
        state = self.state(); f.rows = state['stores']['rig:fixture']; f.sessions = state['stores']['city:fixture']
        f.provenances = state['provenances']
        for role, target in (('producer','gc.implementation-worker'),('reviewer','gc.implementation-reviewer'),
                             ('recorder','gc.run-operator')):
            key = role+'-C'; attempt = Attempt(key+'-session', key+'-private-instance', key)
            f.attempts[key] = attempt
            f.rows[key]['metadata'].update({'gc.session_id':attempt.session_id, 'gc.session_name':key+'-runtime'})
            session = f.row(attempt.session_id, {'template':'fixture/'+target,'session_name':key+'-runtime',
                'instance_token':attempt.instance_token,'session_origin':'ephemeral','state':'asleep',
                'current_claim_bead_id':''}, scoped=False)
            session['type']='session'; f.sessions[session['id']]=session
        f.rows['prepare-C'].update(status='closed',assignee=''); f.rows['prepare-C']['metadata']['gc.outcome']='pass'
        f.sessions['prepare-C-session']['metadata'].update(state='asleep',current_claim_bead_id='')
        f.rows['producer-C'].update(status='in_progress',assignee='producer-C-session')
        f.sessions['producer-C-session']['metadata'].update(state='active',current_claim_bead_id='producer-C')
        (f.root/'port.json').write_text(json.dumps(state))
        os.environ.update(GC_SESSION_ID=f.attempts['producer-C'].session_id,
                          GC_INSTANCE_TOKEN=f.attempts['producer-C'].instance_token)
        runtime = NativeSourceRuntime(f.store,gc=str(f.port),city_root=str(f.city),rig_name='fixture',run=f.run,plan=f.plan,
            artifact_root=f.artifacts,evidence_dir=f.diagnostics,claimed_step_id='producer-C')
        writer_map = runtime.writer_map
        frozen = self.helper.FrozenRecords(f.store, runtime.guard_rows)
        frozen.ensure([first['workspace_record_id'],first['authority_id']])
        checkpoint = self.helper.writer_checkpoint(dict(first['workspace'], phase='result',
            current_oid=head, output_oid=head), f.attempts['producer-C'])
        self.helper.publish_checkpoint(frozen,f.attempts['producer-C'],checkpoint,authority_id=first['authority_id'],
            writer_map=writer_map,plan_record_id='plan-record',native_runtime=runtime)
        state = self.state(); f.rows=state['stores']['rig:fixture']; f.sessions=state['stores']['city:fixture']
        for role in ('producer','reviewer','recorder'):
            key=role+'-C'; f.rows[key].update(status='closed',assignee=''); f.rows[key]['metadata']['gc.outcome']='pass'
            f.sessions[key+'-session']['metadata'].update(state='asleep',current_claim_bead_id='')
        self.accepted('C',work,checkpoint,'producer-C','reviewer-C','recorder-C',publish_owner=False)
        # Native fixture expansion supplies a separate actual child and unit;
        # authority transfer itself goes through the production guarded writer.
        f.native_child('child-D','D',roles=('prepare-D','producer-D','reviewer-D','recorder-D'),
                       expansion='expansion-D',published=False)
        state['stores']={'rig:fixture':f.rows,'city:fixture':f.sessions}
        f.rows['prepare-D'].update(status='in_progress',assignee='prepare-D-session')
        f.sessions['prepare-D-session']['metadata'].update(state='active',current_claim_bead_id='prepare-D')
        (f.root/'port.json').write_text(json.dumps(state))
        os.environ.update(GC_SESSION_ID=f.attempts['prepare-D'].session_id,
                          GC_INSTANCE_TOKEN=f.attempts['prepare-D'].instance_token)
        return first, head

    def test_shared_child_successor_keeps_git_identity_and_atomically_moves_native_owner(self):
        from workspace_store import CONTINUATION_KEY
        first, head = self.shared_successor_fixture(); before = self.state(); f = self.fixture
        continued = self.prepare(workflow_root_id='child-D',input_convoy_id='child-D-unit',member_id='D')
        workspace = continued['workspace']; rows = self.state()['stores']['rig:fixture']
        self.assertEqual(head, continued['input_oid'])
        self.assertEqual('D',workspace['active_member_id'])
        self.assertEqual(1,workspace['next_member_position'])
        for key in ('workspace_bead_id','work_dir','work_branch','native_attempt_id','native_provenance'):
            self.assertEqual(first['workspace'][key],workspace[key])
        self.assertEqual('child-D',rows[workspace['workspace_bead_id']]['metadata']['gc.root_bead_id'])
        self.assertEqual(before['stores']['rig:fixture']['child-C']['metadata'][CONTINUATION_KEY],
                         rows['child-C']['metadata'][CONTINUATION_KEY])
        request = self.state()['requests'][len(before['requests'])]
        changed = {item['id']:item.get('set',{}) for item in request['rows']}
        self.assertIn(CONTINUATION_KEY,changed['child-D'])
        self.assertEqual('child-D',changed[workspace['workspace_bead_id']]['gc.root_bead_id'])
        self.assertEqual('D',json.loads(changed[workspace['workspace_bead_id']]['gc.workspace'])['active_member_id'])
        for step_id in continued['launch_step_ids']:
            reference=json.loads(changed[step_id]['gc.worktree_ref'])
            self.assertEqual('child-D',reference['workflow_root_id'])
            self.assertEqual(step_id,reference['binding_step_id'])

    def test_shared_child_successor_rejects_changed_old_published_relationship(self):
        self.shared_successor_fixture(); f = self.fixture
        changed=self.state()
        changed['stores']['rig:fixture']['child-C-control']['metadata']['gc.root_store_ref']='rig:foreign'
        (f.root/'port.json').write_text(json.dumps(changed))
        with self.assertRaises(self.helper.RecordError):
            self.prepare(workflow_root_id='child-D',input_convoy_id='child-D-unit',member_id='D')
        self.assertEqual(changed,self.state())

    def test_actual_runtime_selects_accepted_output_and_prepares_native_checkout(self):
        self.prepare_fixture()
        result=self.prepare();f=self.fixture
        self.assertEqual(f.oid,result['input_oid'])
        self.assertEqual(f.oid,f.git(Path(result['path']),'rev-parse','HEAD'))
        self.assertEqual('active',result['workspace']['phase'])
        self.assertEqual(f.oid,result['workspace']['native_provenance']['base_sha'])
        self.assertNotIn('private-instance',json.dumps(result))

    def test_actual_cli_resolves_registered_git_identity_and_returns_prepared_input(self):
        self.prepare_fixture();f=self.fixture
        command=[sys.executable,str(SCRIPTS/'workspace_dependency.py'),'--gc',str(f.port),
            '--worktree-lifecycle','new','--city-root',str(f.city),'--rig-name','fixture','--store-ref','rig:fixture',
            '--workflow-root-id','root','--input-convoy-id','convoy','--generation','1',
            '--workspace-owner-id','C','--member-id','C','--claimed-step-id','prepare-C',
            '--artifact-root',str(f.artifacts),'--evidence-dir',str(f.diagnostics),
            '--parent',str(f.work.parent),'--allow-external-parent']
        completed=subprocess.run(command,text=True,capture_output=True,timeout=60)
        self.assertEqual(0,completed.returncode,completed.stderr)
        result=json.loads(completed.stdout)
        self.assertEqual('prepared',result['state'])
        self.assertEqual(f.oid,result['input_oid'])
        self.assertEqual(f.oid,f.git(Path(result['path']),'rev-parse','HEAD'))
        self.assertNotIn('private-instance',completed.stdout)

    def test_missing_acceptance_policy_or_predecessor_has_no_native_effect(self):
        self.prepare_fixture();f=self.fixture
        for kind in ('policy','output'):
            with self.subTest(kind=kind):
                original=self.state();changed=copy.deepcopy(original)
                if kind=='policy':changed['stores']['rig:fixture']['run-record']['metadata'].pop('gc.workspace_required_checks.v1')
                else:changed['stores']['rig:fixture']['member']['metadata'].pop('gc.workspace_output_ref')
                (f.root/'port.json').write_text(json.dumps(changed))
                with self.assertRaises(self.helper.RecordError):self.prepare()
                after=self.state()
                self.assertEqual(changed,after)
                self.assertFalse((f.work.parent/'C-g1').exists())
                self.assertEqual(0,after.get('allocation_number',0))
                (f.root/'port.json').write_text(json.dumps(original))

    def test_native_unfinished_producer_and_mutated_policy_refuse_before_allocation(self):
        self.prepare_fixture();f=self.fixture
        for failure in ('producer','policy'):
            original=self.state();changed=copy.deepcopy(original)
            rows=changed['stores']['rig:fixture']
            if failure=='producer':rows['producer'].update(status='in_progress',assignee='foreign')
            else:rows['root']['metadata']['gc.var.worktree_checks']='{"required_checks":[{"id":"other","argv":["false"]}]}'
            (f.root/'port.json').write_text(json.dumps(changed))
            with self.subTest(failure=failure), self.assertRaises(self.helper.RecordError):self.prepare()
            self.assertEqual(changed,self.state())
            self.assertFalse((f.work.parent/'C-g1').exists())
            (f.root/'port.json').write_text(json.dumps(original))

    def test_ordered_ab_integration_records_merged_input_and_keeps_native_base(self):
        self.prepare_fixture(integration=True)
        result=self.prepare();f=self.fixture
        self.assertEqual('active',result['workspace']['phase'])
        self.assertEqual(f.base,result['workspace']['native_provenance']['base_sha'])
        self.assertEqual(['member','B'],[source['owner_id'] for source in result['workspace']['integration_inputs']])
        self.assertEqual('VALUE = 42\n',(Path(result['path'])/'feature.py').read_text())
        self.assertEqual('FLAG = 7\n',(Path(result['path'])/'other.py').read_text())
        self.assertEqual(result['input_oid'],f.git(Path(result['path']),'rev-parse','HEAD'))
        receipt=json.loads(Path(result['integration_evidence']['path']).read_text())
        self.assertEqual(result['input_oid'],receipt['output_oid'])
        self.assertEqual(result['workspace']['integration_inputs'],receipt['integration_inputs'])
        self.assertIsNone(result['workspace']['output_oid'])
        work=Path(result['path'])
        (work/'c.py').write_text('C = 1\n')
        f.git(work,'add','c.py');f.git(work,'commit','-qm','partial C implementation')
        (work/'notes.txt').write_text('unfinished C work\n')
        before=self.state();continued=self.prepare()
        self.assertEqual('continuation',continued['state'])
        self.assertEqual(result['input_oid'],continued['input_oid'])
        self.assertEqual(result['integration_evidence'],continued['integration_evidence'])
        self.assertFalse(continued['accepted'])
        self.assertEqual(before,self.state())

    def test_conflict_keeps_merge_state_and_publishes_exact_blocker_checkpoint(self):
        self.prepare_fixture(integration=True,conflict=True);f=self.fixture
        with self.assertRaisesRegex(self.helper.DependencyError,'blocked') as caught:self.prepare()
        self.assertTrue(Path(caught.exception.evidence_path).is_file())
        work=f.work.parent/'C-g1'
        self.assertTrue(Path(f.git(work,'rev-parse','--git-path','MERGE_HEAD')).exists())
        self.assertIn('<<<<<<<',(work/'feature.py').read_text())
        rows=self.state()['stores']['rig:fixture']
        ref=json.loads(rows['C']['metadata']['gc.workspace_ref'])
        workspace=json.loads(rows[ref['bead_id']]['metadata']['gc.workspace'])
        self.assertEqual('blocked',workspace['phase'])
        self.assertEqual(f.base,workspace['input_oid'])
        self.assertEqual(f.base,workspace['current_oid'])
        blocker_ref=json.loads(rows['C']['metadata']['gc.workspace_blocker_ref'])
        blocker=json.loads(rows[blocker_ref['bead_id']]['metadata']['gc.workspace_blocker'])
        self.assertEqual('entry',blocker['blocked_from_phase'])
        self.assertNotEqual(workspace['current_oid'],blocker['actual_head_oid'])
        self.assertIsNone(blocker['resolution'])

    def test_same_member_continuation_preserves_dirty_advanced_work_without_writes(self):
        self.prepare_fixture();f=self.fixture
        first=self.prepare();work=Path(first['path'])
        (work/'partial.py').write_text('PARTIAL = 1\n')
        f.git(work,'add','partial.py');f.git(work,'commit','-qm','partial implementation')
        head=f.git(work,'rev-parse','HEAD')
        (work/'notes.txt').write_text('unfinished work\n')
        before=self.state()
        continued=self.prepare()
        self.assertEqual('continuation',continued['state'])
        self.assertFalse(continued['accepted'])
        self.assertTrue(continued['checkpoint_required'])
        self.assertEqual(first['input_oid'],continued['input_oid'])
        self.assertEqual(head,continued['head'])
        self.assertEqual(before,self.state())
        self.assertEqual('unfinished work\n',(work/'notes.txt').read_text())

    def test_interrupted_pristine_first_prepare_replays_exact_checkpoint_with_receipt(self):
        self.prepare_fixture();f=self.fixture
        publish=self.helper.publish_checkpoint
        interrupted=[]
        def lose_final_response(*args,**kwargs):
            result=publish(*args,**kwargs)
            workspace=args[2]
            if workspace['phase']=='active' and workspace['workspace_owner_id']=='C' and not interrupted:
                interrupted.append(True)
                raise self.helper.RecordError('fixture: response lost after active checkpoint publication')
            return result
        with patch.object(self.helper,'publish_checkpoint',side_effect=lose_final_response):
            with self.assertRaisesRegex(self.helper.RecordError,'response lost'):
                self.prepare()
        self.assertEqual([True],interrupted)
        failed=self.state()
        rows=failed['stores']['rig:fixture']
        workspace_ref=json.loads(rows['C']['metadata']['gc.workspace_ref'])
        active=json.loads(rows[workspace_ref['bead_id']]['metadata']['gc.workspace'])
        self.assertEqual('active',active['phase'])
        self.assertEqual(0,active['next_member_position'])
        self.assertEqual(active['input_oid'],active['current_oid'])
        self.assertIsNone(active['output_oid'])
        self.assertNotIn('gc.workspace_result_ref',rows['C']['metadata'])
        self.assertNotIn('gc.workspace_output_ref',rows['C']['metadata'])

        before_retry=self.state()
        allocations=before_retry['allocation_number']
        existing_records=set(before_retry['stores']['rig:fixture'])
        request_count=len(before_retry.get('requests',[]))
        launch_refs={key:row['metadata']['gc.worktree_ref'] for key,row in before_retry['stores']['rig:fixture'].items()
                     if 'gc.worktree_ref' in row['metadata']}
        result=self.prepare()
        after_retry=self.state()
        self.assertEqual('prepared',result['state'])
        self.assertEqual(active['workspace_bead_id'],result['workspace']['workspace_bead_id'])
        self.assertEqual(active['work_dir'],result['path'])
        self.assertEqual(active['input_oid'],result['input_oid'])
        self.assertIsNone(result['workspace']['output_oid'])
        self.assertEqual(allocations,after_retry['allocation_number'])
        self.assertEqual(existing_records,set(after_retry['stores']['rig:fixture']))
        self.assertEqual(request_count+1,len(after_retry['requests']))
        self.assertEqual(1,len(result['receipts']))
        receipt=result['receipts'][0]
        self.assertIn(receipt['outcome'],('committed','replayed'))
        self.assertTrue(Path(receipt['request_path']).is_file())
        self.assertEqual(receipt['request_sha256'],json.loads(Path(receipt['request_path']).read_text())['request_sha256'])
        rows=after_retry['stores']['rig:fixture']
        self.assertEqual(workspace_ref,json.loads(rows['C']['metadata']['gc.workspace_ref']))
        replayed=json.loads(rows[active['workspace_bead_id']]['metadata']['gc.workspace'])
        self.assertEqual(active,replayed)
        self.assertEqual(launch_refs,{key:row['metadata']['gc.worktree_ref'] for key,row in rows.items()
                                      if 'gc.worktree_ref' in row['metadata']})

    def test_interrupted_prepare_with_ahead_and_dirty_work_continues_without_writes(self):
        self.prepare_fixture();f=self.fixture
        publish=self.helper.publish_checkpoint
        def lose_final_response(*args,**kwargs):
            result=publish(*args,**kwargs)
            workspace=args[2]
            if workspace['phase']=='active' and workspace['workspace_owner_id']=='C':
                raise self.helper.RecordError('fixture: response lost after active checkpoint publication')
            return result
        with patch.object(self.helper,'publish_checkpoint',side_effect=lose_final_response):
            with self.assertRaisesRegex(self.helper.RecordError,'response lost'):
                self.prepare()
        rows=self.state()['stores']['rig:fixture']
        workspace_ref=json.loads(rows['C']['metadata']['gc.workspace_ref'])
        active=json.loads(rows[workspace_ref['bead_id']]['metadata']['gc.workspace'])
        work=Path(active['work_dir'])
        (work/'partial.py').write_text('PARTIAL = 1\n')
        f.git(work,'add','partial.py');f.git(work,'commit','-qm','partial implementation')
        head=f.git(work,'rev-parse','HEAD')
        (work/'notes.txt').write_text('unfinished work\n')
        before=self.state()

        result=self.prepare()

        self.assertEqual('continuation',result['state'])
        self.assertFalse(result['accepted'])
        self.assertTrue(result['checkpoint_required'])
        self.assertEqual(head,result['head'])
        self.assertEqual([],result['receipts'])
        self.assertEqual(before,self.state())
        self.assertEqual('unfinished work\n',(work/'notes.txt').read_text())
        self.assertEqual('PARTIAL = 1\n',(work/'partial.py').read_text())

    def test_interrupted_shared_chain_prepare_keeps_continuation_behavior(self):
        self.prepare_fixture(shared=True);f=self.fixture
        publish=self.helper.publish_checkpoint
        def lose_final_response(*args,**kwargs):
            result=publish(*args,**kwargs)
            workspace=args[2]
            if workspace['phase']=='active' and workspace['workspace_owner_id']=='C':
                raise self.helper.RecordError('fixture: response lost after active checkpoint publication')
            return result
        with patch.object(self.helper,'publish_checkpoint',side_effect=lose_final_response):
            with self.assertRaisesRegex(self.helper.RecordError,'response lost'):
                self.prepare()
        before=self.state()

        result=self.prepare()

        self.assertEqual('continuation',result['state'])
        self.assertFalse(result['accepted'])
        self.assertTrue(result['checkpoint_required'])
        self.assertEqual([],result['receipts'])
        self.assertEqual(before,self.state())

    def test_pristine_prepare_replay_rejects_wrong_claim_and_generation(self):
        self.prepare_fixture();f=self.fixture
        publish=self.helper.publish_checkpoint
        def lose_final_response(*args,**kwargs):
            result=publish(*args,**kwargs)
            workspace=args[2]
            if workspace['phase']=='active' and workspace['workspace_owner_id']=='C':
                raise self.helper.RecordError('fixture: response lost after active checkpoint publication')
            return result
        with patch.object(self.helper,'publish_checkpoint',side_effect=lose_final_response):
            with self.assertRaisesRegex(self.helper.RecordError,'response lost'):
                self.prepare()
        before=self.state()
        with self.assertRaises(self.helper.RecordError):
            self.prepare(attempt=f.attempts['producer'])
        self.assertEqual(before,self.state())
        with self.assertRaises(self.helper.RecordError):
            self.prepare(generation=2)
        self.assertEqual(before,self.state())
        stale=copy.deepcopy(before)
        stale['stores']['rig:fixture']['convoy']['metadata']['gc.source_plan_sha256']='f'*64
        (f.root/'port.json').write_text(json.dumps(stale))
        with self.assertRaises(self.helper.RecordError):
            self.prepare()
        self.assertEqual(stale,self.state())

    def test_resolved_integration_requires_exact_decision_and_resumes_original_checkpoint(self):
        self.prepare_fixture(integration=True,conflict=True);f=self.fixture
        with self.assertRaises(self.helper.DependencyError):self.prepare()
        rows=self.state()['stores']['rig:fixture']
        blocker_ref=json.loads(rows['C']['metadata']['gc.workspace_blocker_ref'])
        blocker=json.loads(rows[blocker_ref['bead_id']]['metadata']['gc.workspace_blocker'])
        work=f.work.parent/'C-g1'
        (work/'feature.py').write_text('VALUE = 42 # resolved\n')
        f.git(work,'add','feature.py');f.git(work,'commit','-qm','resolve accepted source conflict')
        head=f.git(work,'rev-parse','HEAD')
        decision=dict(workflow_root_id='root',generation=1,source_plan_owner_id='plan-owner',
            workspace_owner_id='C',store_ref='rig:fixture',blocker_id=blocker['blocker_id'],expected_head_oid=head)
        wrong=f.artifacts/'wrong-recovery.json';wrong.write_text(json.dumps(dict(decision,expected_head_oid=f.base)))
        before=self.state()
        with self.assertRaises(self.helper.RecordError):self.prepare(resume_decision=str(wrong))
        self.assertEqual(before,self.state())
        path=f.artifacts/'recovery.json';path.write_text(json.dumps(decision))
        resumed=self.prepare(resume_decision=str(path))
        self.assertEqual('active',resumed['workspace']['phase'])
        self.assertEqual(head,resumed['input_oid'])
        self.assertEqual(f.base,resumed['workspace']['native_provenance']['base_sha'])
        self.assertIsNone(resumed['workspace']['output_oid'])
        after=self.state()['stores']['rig:fixture']
        resolved=json.loads(after[blocker_ref['bead_id']]['metadata']['gc.workspace_blocker'])
        self.assertEqual('resolved',resolved['status'])
        self.assertEqual(head,resolved['resolution']['expected_head_oid'])
        receipt=json.loads(Path(resumed['integration_evidence']['path']).read_text())
        self.assertEqual(head,receipt['output_oid'])
        self.assertEqual(2,len(receipt['merge_oids']))
        self.assertFalse(Path(f.git(work,'rev-parse','--git-path','MERGE_HEAD')).exists())

    def test_conflict_replacement_recovers_exact_checkpoint_and_accepts_only_fresh_output(self):
        from workspace_flow import WorkspaceFlow
        from workspace_records import canonical_bytes, RecordError, record_sha256
        from workspace_store import Attempt, GRANT_KEY
        import workspace_outputs as outputs

        self.prepare_fixture(integration=True, conflict=True); f = self.fixture

        # Each preparation/resume enters the shipped CLI in a new interpreter.
        def prepare(**options):
            attempt = options.pop('attempt', f.attempts['prepare-C'])
            command = [sys.executable, '-B', str(SCRIPTS / 'workspace_dependency.py'),
                '--gc', str(f.port), '--worktree-lifecycle', 'new', '--city-root', str(f.city),
                '--rig-name', 'fixture', '--store-ref', 'rig:fixture', '--workflow-root-id', 'root',
                '--input-convoy-id', 'convoy', '--generation', '1', '--workspace-owner-id', 'C',
                '--member-id', 'C', '--claimed-step-id', attempt.claimed_bead_id,
                '--artifact-root', str(f.artifacts), '--evidence-dir', str(f.diagnostics),
                '--parent', str(f.work.parent), '--allow-external-parent']
            if 'resume_decision' in options:
                command += ['--resume-decision', options.pop('resume_decision')]
            self.assertEqual({}, options)
            environment = dict(os.environ, GC_SESSION_ID=attempt.session_id,
                               GC_INSTANCE_TOKEN=attempt.instance_token)
            completed = subprocess.run(command, text=True, capture_output=True, env=environment, timeout=120)
            if completed.returncode:
                self.assertEqual(1, completed.returncode, completed.stderr)
                failure = json.loads(completed.stderr)
                self.assertEqual('blocked', failure['state'])
                raise self.helper.DependencyError(failure['reason'])
            return json.loads(completed.stdout)
        with self.assertRaisesRegex(self.helper.DependencyError, 'blocked'):
            prepare()
        blocked = self.state()
        rows = blocked['stores']['rig:fixture']
        workspace_ref = json.loads(rows['C']['metadata']['gc.workspace_ref'])
        workspace = json.loads(rows[workspace_ref['bead_id']]['metadata']['gc.workspace'])
        blocker_ref = json.loads(rows['C']['metadata']['gc.workspace_blocker_ref'])
        blocker = json.loads(rows[blocker_ref['bead_id']]['metadata']['gc.workspace_blocker'])
        work = Path(workspace['work_dir'])
        conflict = (work / 'feature.py').read_bytes()
        self.assertIn(b'<<<<<<<', conflict)
        self.assertIsNone(blocker['resolution'])
        self.assertNotIn('gc.workspace_output_ref', rows['C']['metadata'])

        # Move to the distinct declared successor writer, retaining the old
        # native claim/session as history. Recovery must transfer its grant.
        roles = ('prepare-C', 'producer-C', 'reviewer-C', 'recorder-C')
        for role in roles[1:]:
            attempt = Attempt(role+'-session', role+'-private-instance', role)
            f.attempts[role] = attempt
            rows[role]['metadata'].update({'gc.session_id': attempt.session_id,
                                          'gc.session_name': role+'-runtime'})
            session = copy.deepcopy(blocked['stores']['city:fixture'][role.replace('-C', '-B')+'-session'])
            session['id'] = attempt.session_id
            session['metadata'].update(instance_token=attempt.instance_token, session_name=role+'-runtime')
            blocked['stores']['city:fixture'][attempt.session_id] = session
        state_path = f.root / 'port.json'
        state_path.write_text(json.dumps(blocked))

        def activate(role):
            state = self.state()
            for position, key in enumerate(roles):
                row = state['stores']['rig:fixture'][key]
                active = key == role
                closed = position < roles.index(role)
                row.update(status='in_progress' if active else 'closed' if closed else 'open',
                           assignee=f.attempts[key].session_id if active else '')
                row['metadata'].pop('gc.outcome', None)
                if closed: row['metadata']['gc.outcome'] = 'pass'
                state['stores']['city:fixture'][f.attempts[key].session_id]['metadata'].update(
                    state='active' if active else 'asleep', current_claim_bead_id=key if active else '')
            os.environ.update(GC_SESSION_ID=f.attempts[role].session_id,
                              GC_INSTANCE_TOKEN=f.attempts[role].instance_token)
            state_path.write_text(json.dumps(state))

        activate('producer-C')
        self.assertEqual(conflict, (work / 'feature.py').read_bytes())
        self.assertEqual(workspace, json.loads(self.state()['stores']['rig:fixture'][workspace_ref['bead_id']]['metadata']['gc.workspace']))
        (work / 'feature.py').write_text('VALUE = 42 # recovered conflict\n')
        f.git(work, 'add', 'feature.py'); f.git(work, 'commit', '-qm', 'resolve accepted source conflict')
        head = f.git(work, 'rev-parse', 'HEAD')
        decision = dict(workflow_root_id='root', generation=1, source_plan_owner_id='plan-owner',
            workspace_owner_id='C', store_ref='rig:fixture', blocker_id=blocker['blocker_id'], expected_head_oid=head)
        path = f.artifacts / 'replacement-recovery.json'
        path.write_text(json.dumps(decision))
        decision_ref = outputs.artifact(path, f.artifacts)
        before = self.state()
        for fault in ('snapshot', 'decision'):
            with self.subTest(fault=fault):
                stale = copy.deepcopy(before)
                if fault == 'snapshot':
                    changed = copy.deepcopy(workspace)
                    changed['integration_inputs'][0]['workspace_output_sha256'] = '0'*64
                    stale['stores']['rig:fixture'][workspace_ref['bead_id']]['metadata']['gc.workspace'] = canonical_bytes(changed).decode()
                else:
                    path.write_text(json.dumps(dict(decision, expected_head_oid=f.base)))
                state_path.write_text(json.dumps(stale))
                with self.assertRaises(RecordError):
                    prepare(attempt=f.attempts['producer-C'], resume_decision=str(path))
                self.assertEqual(stale, self.state())
                self.assertEqual(head, f.git(work, 'rev-parse', 'HEAD'))
                self.assertEqual('VALUE = 42 # recovered conflict\n', (work / 'feature.py').read_text())
                path.write_text(json.dumps(decision))
        state_path.write_text(json.dumps(before))
        recovery_pending = copy.deepcopy(before)
        resumed = prepare(attempt=f.attempts['producer-C'], resume_decision=str(path))
        self.assertFalse(resumed['accepted'])
        self.assertEqual(head, resumed['input_oid'])
        self.assertEqual(workspace['native_provenance'], resumed['workspace']['native_provenance'])
        self.assertEqual(workspace['integration_inputs'], resumed['workspace']['integration_inputs'])
        recovered = self.state()['stores']['rig:fixture']
        resolution = json.loads(recovered[blocker_ref['bead_id']]['metadata']['gc.workspace_blocker'])['resolution']
        self.assertEqual(dict(decision_path=decision_ref['path'], decision_sha256=decision_ref['sha256'], expected_head_oid=head), resolution)
        self.assertEqual(f.attempts['producer-C'].admission,
            json.loads(recovered[resumed['authority_id']]['metadata'][GRANT_KEY])['attempt'])
        self.assertNotEqual(workspace['writer_attempt_id'], resumed['workspace']['writer_attempt_id'])
        self.assertNotIn('gc.workspace_result_ref', recovered['C']['metadata'])
        self.assertNotIn('gc.workspace_output_ref', recovered['C']['metadata'])
        receipt = outputs.read_artifact(resumed['integration_evidence'], f.artifacts)
        self.assertEqual(head, receipt['output_oid'])
        self.assertEqual(2, len(receipt['merge_oids']))
        self.assertEqual('FLAG = 7\n', (work / 'other.py').read_text())
        for source in workspace['integration_inputs']:
            f.git(work, 'merge-base', '--is-ancestor', source['output_oid'], head)

        producer = f.adapter('producer-C')
        checks = producer.execute_checks('C', 'C', head)
        proof = outputs.read_artifact(dict(path=checks[0]['evidence_path'], sha256=checks[0]['evidence_sha256']), f.artifacts)
        self.assertEqual('passed', proof['status'])
        self.assertEqual(head, proof['binding']['output_oid'])
        self.assertEqual('producer-C', proof['producer']['step_id'])
        summary = f.artifacts / 'recovered-summary.md'; summary.write_text('Recovered both exact accepted inputs.\n')
        report = f.artifacts / 'recovered-review.md'; report.write_text('Reviewed resolved source and fresh required check.\n')
        artifacts = [outputs.artifact(summary, f.artifacts)]
        activate('reviewer-C')
        reviewer = f.adapter('reviewer-C')
        with self.assertRaises(RecordError):
            reviewer.begin_review('C', 'C', head, f.result['acceptance']['project_checks'], artifacts)
        context = reviewer.begin_review('C', 'C', head, checks, artifacts)
        review = reviewer.complete_review(context, report, 'passed', f.artifacts / 'recovered-review.json')
        activate('recorder-C')
        flow = WorkspaceFlow(f.adapter('recorder-C'))
        before = self.state()
        with self.assertRaises(RecordError):
            flow.record_result('C', 'C', head, checks, f.result['acceptance']['independent_review'], artifacts)
        self.assertEqual(before, self.state())
        recorded = flow.record_result('C', 'C', head, checks, review, artifacts)
        result = recorded['result']
        self.assertEqual('accepted', result['acceptance']['status'])
        self.assertEqual(head, result['input_oid'])
        self.assertEqual(head, result['output_oid'])
        published = flow.owner_output('C', resumed['integration_evidence']['path'])
        self.assertEqual('committed', published['receipt']['outcome'])
        accepted = published['output']
        self.assertEqual(record_sha256(result), accepted['final_member_result_sha256'])
        self.assertEqual(workspace['integration_inputs'], accepted['integration_inputs'])
        self.assertEqual(head, accepted['output_oid'])
        installed = self.state()
        checkpoint = json.loads(installed['stores']['rig:fixture'][workspace_ref['bead_id']]['metadata']['gc.workspace'])
        self.assertEqual('result', checkpoint['phase'])
        self.assertEqual(head, checkpoint['output_oid'])
        output_ref = json.loads(installed['stores']['rig:fixture']['C']['metadata']['gc.workspace_output_ref'])
        competing = copy.deepcopy(installed)
        changed = dict(accepted, output_oid=f.base)
        competing['stores']['rig:fixture'][output_ref['bead_id']]['metadata']['gc.workspace_output'] = canonical_bytes(changed).decode()
        state_path.write_text(json.dumps(competing))
        with self.assertRaises(RecordError):
            WorkspaceFlow(f.adapter('recorder-C')).owner_output('C', resumed['integration_evidence']['path'])
        self.assertEqual(competing, self.state())
        state_path.write_text(json.dumps(installed))

        # Reuse the real output just accepted above, rather than inventing an
        # accepted record. Its presence conflicts with the retained blocked
        # checkpoint and must refuse recovery before any store or Git mutation.
        with self.subTest(fault='existing-output-before-resume'):
            competing = copy.deepcopy(recovery_pending)
            competing_rows = competing['stores']['rig:fixture']
            competing_rows[output_ref['bead_id']] = copy.deepcopy(installed['stores']['rig:fixture'][output_ref['bead_id']])
            competing_rows['C']['metadata']['gc.workspace_output_ref'] = installed['stores']['rig:fixture']['C']['metadata']['gc.workspace_output_ref']
            state_path.write_text(json.dumps(competing))
            os.environ.update(GC_SESSION_ID=f.attempts['producer-C'].session_id,
                              GC_INSTANCE_TOKEN=f.attempts['producer-C'].instance_token)
            git_state = f.git(work, 'status', '--porcelain=v1', '--untracked-files=all')
            contents = (work / 'feature.py').read_bytes()
            try:
                with self.assertRaisesRegex(RecordError, 'existing.*output|output.*existing'):
                    prepare(attempt=f.attempts['producer-C'], resume_decision=str(path))
                self.assertEqual(competing, self.state())
                self.assertEqual(head, f.git(work, 'rev-parse', 'HEAD'))
                self.assertEqual(git_state, f.git(work, 'status', '--porcelain=v1', '--untracked-files=all'))
                self.assertEqual(contents, (work / 'feature.py').read_bytes())
            finally:
                state_path.write_text(json.dumps(installed))
                os.environ.update(GC_SESSION_ID=f.attempts['recorder-C'].session_id,
                                  GC_INSTANCE_TOKEN=f.attempts['recorder-C'].instance_token)

    def block_initial_prepare(self, *, shared=False, integration=False, child=False):
        self.prepare_fixture(shared=shared, integration=integration)
        f = self.fixture
        if child:
            f.native_child('child-C', 'C', roles=('prepare-C', 'producer-C', 'reviewer-C', 'recorder-C'),
                           expansion='expansion-C', published=False)
        f.rows['prepare-blocker'] = f.row('prepare-blocker', status='closed', scoped=False)
        f.save()
        state = self.state()
        state['provenances'] = self.provenances
        lock = f.diagnostics / 'prepare.lock'
        state['prepare_lock_path'] = str(lock)
        (f.root / 'port.json').write_text(json.dumps(state))
        port = self.port_source.replace("    created = False\n", """    created = False
    if action == 'ensure' and data.get('prepare_lock_path'):
        import fcntl
        with open(data['prepare_lock_path'], 'a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                sys.exit('native protocol fixture: worktree lock timeout')
""")
        f.port.write_text(port)
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaisesRegex(self.helper.RecordError, 'ensure failed'):
                options = dict(workflow_root_id='child-C', input_convoy_id='child-C-unit') if child else {}
                self.prepare(blocker_record_id='prepare-blocker', blocker_id='prepare-blocker', **options)
        rows = self.state()['stores']['rig:fixture']
        ref = json.loads(rows['C']['metadata']['gc.workspace_ref'])
        workspace = json.loads(rows[ref['bead_id']]['metadata']['gc.workspace'])
        blocker = json.loads(rows['prepare-blocker']['metadata']['gc.workspace_blocker'])
        self.assertEqual('blocked', workspace['phase'])
        self.assertEqual('preparing', blocker['blocked_from_phase'])
        self.assertEqual('prepare', blocker['stage'])
        self.assertFalse(Path(workspace['work_dir']).exists())
        self.assertIsNone(workspace['native_provenance'])
        decision = {key: workspace[key] for key in
                    ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id')}
        decision.update(store_ref='rig:fixture', blocker_id='prepare-blocker',
                        expected_head_oid=workspace['input_oid'])
        path = f.artifacts / 'retry-prepare.json'
        path.write_text(json.dumps(decision))
        return workspace, blocker, path

    def test_blocked_first_prepare_retries_exact_input_without_recapturing_source(self):
        workspace, blocker, decision = self.block_initial_prepare()
        f = self.fixture
        before = self.state()['stores']['rig:fixture']
        result = self.prepare(resume_decision=str(decision))
        after = self.state()['stores']['rig:fixture']
        self.assertEqual('active', result['workspace']['phase'])
        self.assertEqual(workspace['input_oid'], result['input_oid'])
        for key in ('work_dir', 'workspace_bead_id', 'strategy', 'layout', 'active_member_id'):
            self.assertEqual(workspace[key], result['workspace'][key])
        from workspace_store import TRANSITION_NONCE_KEY
        for row_id in ('run-record', 'plan-record'):
            unchanged = []
            for rows in (before, after):
                record = copy.deepcopy(rows[row_id])
                record.pop('revision')
                record['metadata'].pop(TRANSITION_NONCE_KEY)
                unchanged.append(record)
            self.assertEqual(*unchanged)
            self.assertGreater(int(after[row_id]['revision']), int(before[row_id]['revision']))
            change = next(item for item in self.state()['requests'][-1]['rows'] if item['id'] == row_id)
            self.assertEqual(change['set'][TRANSITION_NONCE_KEY], after[row_id]['metadata'][TRANSITION_NONCE_KEY])
        resolved = json.loads(after['prepare-blocker']['metadata']['gc.workspace_blocker'])
        self.assertEqual('resolved', resolved['status'])
        self.assertEqual(workspace['input_oid'], resolved['resolution']['expected_head_oid'])
        self.assertIsNone(result['workspace']['output_oid'])
        self.assertEqual(workspace['input_oid'], f.git(result['path'], 'rev-parse', 'HEAD'))

    def test_blocked_first_prepare_requires_explicit_exact_decision_before_effects(self):
        workspace, _, path = self.block_initial_prepare()
        before = self.state()
        with self.assertRaisesRegex(self.helper.RecordError, 'workspace is blocked'):
            self.prepare()
        self.assertEqual(before, self.state())
        decision = json.loads(path.read_text())
        for key, value in (('generation', True), ('workspace_owner_id', 'foreign'),
                           ('store_ref', 'rig:foreign'), ('blocker_id', 'foreign'),
                           ('expected_head_oid', self.fixture.base)):
            with self.subTest(key=key):
                path.write_text(json.dumps(dict(decision, **{key: value})))
                with self.assertRaises(self.helper.RecordError):
                    self.prepare(resume_decision=str(path))
                self.assertEqual(before, self.state())
                self.assertFalse(Path(workspace['work_dir']).exists())

    def test_blocked_first_prepare_refuses_stale_native_claim_and_foreign_path(self):
        workspace, _, decision = self.block_initial_prepare()
        before = self.state()
        with patch.dict(os.environ, {'GC_INSTANCE_TOKEN': 'stale-private-instance'}):
            with self.assertRaises(self.helper.RecordError):
                self.prepare(resume_decision=str(decision))
        self.assertEqual(before, self.state())
        work = Path(workspace['work_dir'])
        work.mkdir()
        (work / 'foreign.txt').write_text('preserve foreign work\n')
        with self.assertRaisesRegex(self.helper.RecordError, 'registration'):
            self.prepare(resume_decision=str(decision))
        self.assertEqual(before, self.state())
        self.assertEqual('preserve foreign work\n', (work / 'foreign.txt').read_text())

    def test_blocked_first_shared_prepare_keeps_original_chain_owner_and_member(self):
        workspace, _, decision = self.block_initial_prepare(shared=True)
        result = self.prepare(resume_decision=str(decision))
        self.assertEqual('shared-chain', result['workspace']['strategy'])
        self.assertEqual(workspace['active_member_id'], result['workspace']['active_member_id'])
        self.assertEqual(workspace['next_member_position'], result['workspace']['next_member_position'])
        self.assertEqual(workspace['workspace_owner_id'], result['workspace']['workspace_owner_id'])
        self.assertEqual(workspace['input_oid'], result['input_oid'])

    def test_blocked_first_native_child_prepare_keeps_inherited_source_and_physical_owner(self):
        workspace, _, decision = self.block_initial_prepare(child=True)
        result = self.prepare(resume_decision=str(decision), workflow_root_id='child-C', input_convoy_id='child-C-unit')
        rows = self.state()['stores']['rig:fixture']
        self.assertEqual('root', result['workspace']['workflow_root_id'])
        self.assertEqual('child-C', rows[workspace['workspace_bead_id']]['metadata']['gc.root_bead_id'])
        for step in result['launch_step_ids']:
            self.assertEqual('child-C', json.loads(rows[step]['metadata']['gc.worktree_ref'])['workflow_root_id'])

    def test_blocked_first_integration_prepare_merges_only_after_retry_is_admitted(self):
        workspace, _, decision = self.block_initial_prepare(integration=True)
        result = self.prepare(resume_decision=str(decision))
        self.assertEqual(self.fixture.base, workspace['input_oid'])
        self.assertNotEqual(workspace['input_oid'], result['input_oid'])
        self.assertEqual(workspace['integration_inputs'], result['workspace']['integration_inputs'])
        self.assertEqual('FLAG = 7\n', (Path(result['path']) / 'other.py').read_text())
        self.assertIsNone(result['workspace']['output_oid'])

    def test_interrupted_first_prepare_resolution_reuses_the_original_decision(self):
        workspace, _, decision = self.block_initial_prepare()
        publish = self.helper.publish_checkpoint
        def interrupt(*args, **kwargs):
            result = publish(*args, **kwargs)
            if kwargs.get('extra_writes'):
                raise self.helper.RecordError('fixture: interrupted after resolved preparation checkpoint')
            return result
        with patch.object(self.helper, 'publish_checkpoint', side_effect=interrupt):
            with self.assertRaisesRegex(self.helper.RecordError, 'interrupted'):
                self.prepare(resume_decision=str(decision))
        before = self.state()['stores']['rig:fixture']
        restored = json.loads(before[workspace['workspace_bead_id']]['metadata']['gc.workspace'])
        self.assertEqual('preparing', restored['phase'])
        other = self.fixture.artifacts / 'other-decision.json'
        other.write_bytes(decision.read_bytes())
        with self.assertRaisesRegex(self.helper.RecordError, 'changed its recorded decision'):
            self.prepare(resume_decision=str(other))
        result = self.prepare(resume_decision=str(decision))
        after = self.state()['stores']['rig:fixture']
        self.assertEqual('active', result['workspace']['phase'])
        self.assertEqual(before['prepare-blocker']['metadata']['gc.workspace_blocker'],
                         after['prepare-blocker']['metadata']['gc.workspace_blocker'])

    def test_second_prepare_timeout_keeps_prior_resolution_and_records_a_new_blocker(self):
        workspace, _, decision = self.block_initial_prepare()
        f = self.fixture
        with (f.diagnostics / 'prepare.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaisesRegex(self.helper.RecordError, 'ensure failed'):
                self.prepare(resume_decision=str(decision))
        rows = self.state()['stores']['rig:fixture']
        prior = copy.deepcopy(rows['prepare-blocker'])
        self.assertEqual('resolved', json.loads(prior['metadata']['gc.workspace_blocker'])['status'])
        ref = json.loads(rows['C']['metadata']['gc.workspace_blocker_ref'])
        self.assertNotEqual('prepare-blocker', ref['bead_id'])
        next_blocker = json.loads(rows[ref['bead_id']]['metadata']['gc.workspace_blocker'])
        self.assertEqual('open', next_blocker['status'])
        self.assertEqual('blocked', json.loads(rows[workspace['workspace_bead_id']]['metadata']['gc.workspace'])['phase'])
        before = self.state()
        with self.assertRaises(self.helper.RecordError):
            self.prepare(resume_decision=str(decision))
        self.assertEqual(before, self.state())
        payload = json.loads(decision.read_text())
        payload['blocker_id'] = next_blocker['blocker_id']
        next_decision = f.artifacts / 'retry-next-prepare.json'
        next_decision.write_text(json.dumps(payload))
        result = self.prepare(resume_decision=str(next_decision))
        self.assertEqual('active', result['workspace']['phase'])
        self.assertEqual(prior['metadata']['gc.workspace_blocker'],
                         self.state()['stores']['rig:fixture']['prepare-blocker']['metadata']['gc.workspace_blocker'])

    def test_blocked_registered_first_prepare_verifies_original_provisioning_without_another_ensure(self):
        self.prepare_fixture()
        f = self.fixture
        f.rows['prepare-blocker'] = f.row('prepare-blocker', status='closed', scoped=False)
        f.save()
        state = self.state()
        state.update(provenances=self.provenances, lose_first_ensure_ack=True)
        (f.root / 'port.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(self.helper.RecordError, 'ensure failed'):
            self.prepare(blocker_record_id='prepare-blocker', blocker_id='prepare-blocker')
        before = self.state()
        rows = before['stores']['rig:fixture']
        ref = json.loads(rows['C']['metadata']['gc.workspace_ref'])
        workspace = json.loads(rows[ref['bead_id']]['metadata']['gc.workspace'])
        work = Path(workspace['work_dir'])
        original_provenance = before['provenances'][str(work)]
        self.assertEqual('blocked', workspace['phase'])
        self.assertIsNone(workspace['native_provenance'])
        self.assertEqual(workspace['input_oid'], f.git(work, 'rev-parse', 'HEAD'))
        decision = {key: workspace[key] for key in
                    ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id')}
        decision.update(store_ref='rig:fixture', blocker_id='prepare-blocker', expected_head_oid=workspace['input_oid'])
        path = f.artifacts / 'registered-prepare-recovery.json'
        path.write_text(json.dumps(decision))
        note = work / 'notes.txt'
        note.write_text('preserve unfinished work\n')
        with self.assertRaises(self.helper.RecordError):
            self.prepare(resume_decision=str(path))
        self.assertEqual(before, self.state())
        self.assertEqual('preserve unfinished work\n', note.read_text())
        note.unlink()
        result = self.prepare(resume_decision=str(path))
        self.assertEqual('active', result['workspace']['phase'])
        self.assertEqual(original_provenance, result['workspace']['native_provenance'])
        self.assertEqual(original_provenance['attempt_id'], result['workspace']['native_attempt_id'])
        self.assertEqual(workspace['input_oid'], result['input_oid'])
        self.assertIsNone(result['workspace']['output_oid'])
        commands = [json.loads(line) for line in (f.root / 'port.commands').read_text().splitlines()]
        self.assertEqual(1, sum('worktree' in command and 'ensure' in command and '--help' not in command
                                for command in commands))

    def test_uncertain_retry_blocker_allocation_recovers_exact_native_id_in_fresh_process(self):
        from workspace_requests import allocation_directory
        workspace, _, decision = self.block_initial_prepare()
        f = self.fixture
        state = self.state()
        number = state['allocation_number'] + 1
        state['lose_allocation_ack_at'] = number
        (f.root / 'port.json').write_text(json.dumps(state))
        with self.assertRaisesRegex(self.helper.RecordError, 'blocker allocation unresolved'):
            self.prepare(resume_decision=str(decision))
        pending = next(allocation_directory(f.store).glob('prepare-retry-*.blocker.pending.json'))
        pending_bytes = pending.read_bytes()
        state = self.state()
        key = 'native-allocation-' + str(number)
        row = {**state['stores']['rig:fixture'][key], **state['allocation_details'][key]}
        prior = state['stores']['rig:fixture']['prepare-blocker']['metadata']['gc.workspace_blocker']
        self.assertEqual('resolved', json.loads(prior)['status'])
        self.assertEqual('preparing', json.loads(state['stores']['rig:fixture'][workspace['workspace_bead_id']]['metadata']['gc.workspace'])['phase'])
        command = [sys.executable, '-B', str(SCRIPTS / 'workspace_dependency.py'),
            '--store-ref', 'rig:fixture', '--city-root', str(f.city), '--gc', str(f.port),
            '--rig-name', 'fixture', '--workflow-root-id', 'root', '--input-convoy-id', 'convoy',
            '--generation', '1', '--workspace-owner-id', 'C', '--member-id', 'C',
            '--claimed-step-id', 'prepare-C', '--artifact-root', str(f.artifacts),
            '--evidence-dir', str(f.diagnostics), '--parent', str(f.work.parent),
            '--allow-external-parent', '--worktree-lifecycle', 'new', '--resume-decision', str(decision)]
        environment = dict(os.environ, PYTHONPATH=str(SCRIPTS))
        for response in ([], [row, row], row, None, [dict(row, title='foreign')],
                         [dict(row, description='foreign')], [dict(row, id='')]):
            with self.subTest(response=response):
                current = self.state()
                current['allocation_lookup_response'] = response
                (f.root / 'port.json').write_text(json.dumps(current))
                result = subprocess.run(command, text=True, capture_output=True, env=environment, timeout=120)
                self.assertNotEqual(0, result.returncode)
                self.assertIn('no known physical ID', result.stderr)
                self.assertEqual(current, self.state())
                self.assertEqual(pending_bytes, pending.read_bytes())
                self.assertFalse(Path(workspace['work_dir']).exists())
        current = self.state()
        current.pop('allocation_lookup_response')
        (f.root / 'port.json').write_text(json.dumps(current))
        result = subprocess.run(command, text=True, capture_output=True, env=environment, timeout=120)
        self.assertEqual(0, result.returncode, result.stderr)
        recovered = json.loads(result.stdout)
        self.assertEqual('active', recovered['workspace']['phase'])
        self.assertEqual(workspace['input_oid'], recovered['input_oid'])
        self.assertEqual(number, self.state()['allocation_number'])
        self.assertEqual(pending_bytes, pending.read_bytes())
        self.assertEqual(key, json.loads(pending.with_name(pending.name.replace('.pending', '')).read_text())['bead_id'])
        self.assertEqual(prior, self.state()['stores']['rig:fixture']['prepare-blocker']['metadata']['gc.workspace_blocker'])
        commands = [json.loads(line) for line in (f.root / 'port.commands').read_text().splitlines()]
        queries = [command for command in commands if '--desc-contains' in command]
        self.assertEqual(8, len(queries))
        for query in queries:
            self.assertTrue(all(flag in query for flag in ('--all', '--json', '--readonly')))
            self.assertEqual('2', query[query.index('--limit') + 1])


class HistoricalNativeConsumerTests(unittest.TestCase):
    def test_shared_input_consumes_qualified_old_checkpoint_at_current_native_head(self):
        from test_workspace_runtime import NativeRuntimeTests
        from workspace_store import Attempt
        from workspace_records import canonical_bytes,contracts,record_sha256
        import workspace_outputs as outputs
        import workspace_inputs as inputs
        f=NativeRuntimeTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        f.plan['nodes'][0].update(strategy='shared-chain',member_ids=['member','member-next'],single_lane=True)
        f.rows['plan-record']['metadata']['gc.source_plan']=canonical_bytes(f.plan).decode()
        f.rows['plan-owner']['metadata']['gc.source_plan_ref']=f.ref('source-plan','plan-record',f.plan)
        f.policy_binding['source_plan_sha256']=record_sha256(f.plan)
        checks=copy.deepcopy(f.result['acceptance']['project_checks'])
        for i,check in enumerate(checks):
            proof=outputs.read_artifact({'path':check['evidence_path'],'sha256':check['evidence_sha256']},f.artifacts)
            ref=outputs.immutable_json(f.artifacts/('historical-'+str(i)+'.json'),dict(proof,policy_binding=f.policy_binding))
            check.update(evidence_path=ref['path'],evidence_sha256=ref['sha256'])
        review=f.result['acceptance']['independent_review']
        proof=outputs.read_artifact({'path':review['report_path'],'sha256':review['report_sha256']},f.artifacts)
        ref=outputs.immutable_json(f.artifacts/'historical-review.json',dict(proof,checks=checks,policy_binding=f.policy_binding))
        f.result['acceptance']['project_checks']=checks;review.update(report_path=ref['path'],report_sha256=ref['sha256'])
        f.rows['first-result']=f.row('first-result',{'gc.workspace_result':canonical_bytes(f.result).decode()},status='closed',scoped=False)
        f.rows['member']['metadata']['gc.workspace_result_ref']=f.ref('member-result','first-result',f.result)
        (f.work/'next.py').write_text('NEXT = 1\n');f.git(f.work,'add','next.py');f.git(f.work,'commit','-qm','next shared member')
        head=f.git(f.work,'rev-parse','HEAD')
        attempt=Attempt('aggregate-session','aggregate-private-instance','aggregate')
        f.rows['aggregate']=f.row('aggregate',{'gc.run_target':'gc.run-operator','gc.session_id':attempt.session_id,
            'gc.session_name':'aggregate-runtime','gc.step_ref':'root.aggregate'},status='in_progress')
        f.rows['aggregate']['assignee']=attempt.session_id
        f.sessions[attempt.session_id]=f.row(attempt.session_id,{'template':'fixture/gc.run-operator',
            'session_name':'aggregate-runtime','instance_token':attempt.instance_token,'state':'active',
            'current_claim_bead_id':'aggregate','session_origin':'ephemeral'},scoped=False)
        f.sessions[attempt.session_id]['type']='session'
        f.rows['recorder'].update(status='closed',assignee='');f.rows['recorder']['metadata']['gc.outcome']='pass'
        f.sessions['recorder-session']['metadata'].update(state='asleep',current_claim_bead_id='')
        f.rows['member-next']=f.row('member-next',{'gc.source_root_id':'root','gc.source_generation':'1'})
        f.workspace.update(strategy='shared-chain',input_oid=f.oid,current_oid=head,output_oid=head,
            active_member_id='member-next',next_member_position=1,writer_step_id='aggregate',writer_attempt_id=attempt.writer_attempt_id)
        f.workspace['claim_binding']={key:f.workspace[key] for key in f.workspace['claim_binding']}
        f.rows['workspace-record']['metadata']['gc.workspace']=canonical_bytes(f.workspace).decode()
        f.rows['member']['metadata']['gc.workspace_ref']=f.ref('workspace','workspace-record',f.workspace)
        os.environ.update(GC_SESSION_ID=attempt.session_id,GC_INSTANCE_TOKEN=attempt.instance_token);f.save()
        adapter=f.adapter('aggregate')
        bundle=inputs.resolve_member_input(f.plan,'member','member-next',load_owner_output=lambda _:None,
            load_member_result=lambda member:f.result if member=='member' else None,
            qualify_native=adapter.qualify_native,acceptance_context=adapter.acceptance_context,
            store_ref='rig:fixture',artifact_root=f.artifacts)
        self.assertEqual(f.oid,bundle['input_oid'])
        self.assertEqual(head,f.git(f.work,'rev-parse','HEAD'))
        (f.artifacts/'summary.md').write_text('changed retained artifact\n')
        with self.assertRaises(inputs.RecordError):
            inputs.resolve_member_input(f.plan,'member','member-next',load_owner_output=lambda _:None,
                load_member_result=lambda _:f.result,qualify_native=adapter.qualify_native,
                acceptance_context=adapter.acceptance_context,store_ref='rig:fixture',artifact_root=f.artifacts)


if __name__ == '__main__':
    unittest.main()
