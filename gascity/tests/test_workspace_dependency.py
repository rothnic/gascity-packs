from __future__ import annotations

import copy
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
    state_path.write_text(json.dumps(data))
    emit(rows[key])
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

    def prepare_fixture(self, *, integration=False, conflict=False):
        from workspace_records import canonical_bytes, contracts, record_sha256
        from workspace_store import Attempt, TOPOLOGY
        import workspace_outputs as outputs
        f = self.fixture
        f.git(f.repo,'config','user.name','Fixture')
        f.git(f.repo,'config','user.email','fixture@example.invalid')
        f.rows['recorder'].update(status='closed', assignee='')
        f.rows['recorder']['metadata']['gc.outcome'] = 'pass'
        f.sessions['recorder-session']['metadata'].update(state='asleep', current_claim_bead_id='')
        f.plan['nodes'] = [node('member')]
        if integration:
            f.plan['nodes'].append(node('B'))
        f.plan['nodes'].append(node('C', ['member', 'B'] if integration else ['member']))
        f.plan['terminal_owner_id'] = 'C'
        f.formula['steps'].insert(0, dict(id='do-work.prepare-worktree', metadata={'gc.run_target':'gc.run-operator'}))
        f.formula['deps'].append(dict(step_id='do-work.implement', depends_on_id='do-work.prepare-worktree', type='blocks'))
        f.rows['producer']['metadata'][TOPOLOGY] = canonical_bytes(['do-work.prepare-worktree']).decode()
        f.rows['prepare-A'] = f.row('prepare-A', {
            'gc.step_id':'do-work.prepare-worktree','gc.step_ref':'do-work.prepare-worktree',
            'gc.run_target':'gc.run-operator','gc.attach_root_id':'expansion',
            'gc.source_anchor_id':'member','gc.drain_member_id':'member', TOPOLOGY:'[]','gc.outcome':'pass'}, status='closed')
        for member in ('C', *(['B'] if integration else [])):
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

        def accepted(member, work, workspace, producer, reviewer, recorder):
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
            owner_output=outputs.make_owner_output(f.plan,[result],artifact_root=f.artifacts,
                qualifications={member:{'binding':binding,'required_checks':f.requirements}})
            for kind,key,payload in (('member-result','result-'+member,result),('owner-output','output-'+member,owner_output)):
                f.rows[key]=f.row(key,{contracts()[kind]['metadata_key']:canonical_bytes(payload).decode()},status='closed',scoped=False)
            f.rows[member]['metadata'].update({'gc.workspace_result_ref':f.ref('member-result','result-'+member,result),
                                             'gc.workspace_output_ref':f.ref('owner-output','output-'+member,owner_output)})
            return result,owner_output

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
        return self.helper.prepare_dependency_workspace(f.store,f.attempts['prepare-C'],gc=str(f.port),city_root=str(f.city),
            rig_name='fixture',workflow_root_id='root',input_convoy_id='convoy',generation=1,
            workspace_owner_id='C',member_id='C',artifact_root=f.artifacts,evidence_dir=f.diagnostics,
            parent=str(f.work.parent),allow_external_parent=True, **options)

    def state(self):
        return json.loads((self.fixture.root/'port.json').read_text())

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
