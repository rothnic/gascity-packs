from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace
from unittest.mock import patch
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'assets' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from workspace_store import (Attempt, GRANT_KEY, GuardRead, InheritedRunReference, MISSING, NativeWorktreeReference,
                             RecordWrite, ReferenceWrite, StoreError, WorkspaceStore, record_reference)
from workspace_records import RecordError, canonical_bytes, contracts


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
               GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
               GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
    return subprocess.check_output(['git', '-C', str(path), *args], env=env, stderr=subprocess.PIPE, text=True).strip()


# This command double checks the wire and uses real Git; it is not native acceptance.
NATIVE = r'''#!/usr/bin/env python3
import datetime, json, os, pathlib, subprocess, sys
args=sys.argv[1:]
action=args[args.index('worktree')+1]
if '--help' in args:
 print('--repo --root --path --branch --mode --base --base-sha --bead --store-ref --creator --owner --generation --lifecycle --json' + (' --lock-timeout' if action=='ensure' else '') + (' --placement' if os.environ.get('TEST_PLACEMENT')=='1' else ''))
 sys.exit(0)
flags={}
for a in args[args.index('worktree')+2:]:
 if a.startswith('--') and '=' in a:
  k,v=a[2:].split('=',1);flags[k]=v
 elif a=='--json': pass
 else: raise SystemExit('unexpected argument '+a)
if 'lock-timeout' in flags and action!='ensure': raise SystemExit('verify has no lock flag')
if any(k.startswith('GIT_') and k not in ('GIT_CONFIG_NOSYSTEM','GIT_CONFIG_GLOBAL','GIT_OPTIONAL_LOCKS','GIT_NO_LAZY_FETCH','GIT_TERMINAL_PROMPT','GIT_CONFIG_COUNT','GIT_CONFIG_KEY_0','GIT_CONFIG_VALUE_0','GIT_CONFIG_KEY_1','GIT_CONFIG_VALUE_1') for k in os.environ): raise SystemExit('ambient Git env leaked')
log=pathlib.Path(os.environ['TEST_NATIVE_LOG'])
with log.open('a') as f:f.write(json.dumps({'action':action,'flags':flags})+'\n')
p=pathlib.Path(flags['path'])
def git(*a):return subprocess.check_output(['git','-C',flags['repo'],*a],text=True,stderr=subprocess.PIPE).strip()
created=False
if action=='ensure' and not p.exists():
 p.parent.mkdir(parents=True,exist_ok=True)
 if flags['mode']=='detached':git('worktree','add','--detach',str(p),flags['base'])
 else:git('worktree','add','-b',flags['branch'],str(p),flags['base'])
 created=True
if not p.is_dir():raise SystemExit('missing')
gitdir=pathlib.Path(git('-C',str(p),'rev-parse','--absolute-git-dir'))
file=gitdir/'gascity-worktree-provenance.json'
if created:
 provenance=dict(schema_version=2,bead_id=flags['bead'],store_ref=flags['store-ref'],repo_identity=git('rev-parse','--path-format=absolute','--git-common-dir'),path=str(p),branch=flags['branch'],mode=flags['mode'],placement=flags.get('placement','outside-worktrees'),base_ref=flags['base'],base_sha=flags['base-sha'],creator=flags['creator'],owner=flags['owner'],generation=flags['generation'],lifecycle=flags['lifecycle'],created_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z'),attempt_id='native-attempt-1')
 file.write_text(json.dumps(provenance))
else:provenance=json.loads(file.read_text())
head=git('-C',str(p),'rev-parse','HEAD')
print(json.dumps(dict(schema_version='1',ok=True,command='worktree '+action,action=action,path=str(p),branch=flags['branch'],mode=flags['mode'],placement=flags.get('placement','outside-worktrees'),head=head,created=created,branch_created=created and flags['mode']=='attached',provenance=provenance)))
'''


class StorePort(WorkspaceStore):
    """Actual writer policy with a synthetic whole-batch native command port."""
    def __init__(self, rows, common, *, gc, cwd):
        super().__init__('rig:fixture', gc=gc, cwd=cwd, common_git_dir=common)
        self.rows = copy.deepcopy(rows)
        self.transactions = []
        self.admitted = True
        self.fail_projection = False
        self.before_apply = None
        self.lose_ack = False

    def _command(self, arguments, attempt=None):
        if arguments[0].startswith('--snapshot='):
            ids = arguments[0].partition('=')[2].split(',')
            return dict(schema_version='1', ok=True, store_ref=self.store_ref,
                        rows=[copy.deepcopy(self.rows[i]) for i in ids])
        request = json.loads(Path(arguments[0].partition('=')[2]).read_text())
        if self.before_apply:
            self.before_apply(request)
        if not self.admitted:
            raise StoreError('retained writer grant is stale')
        if self.fail_projection and any('gc.work_dir' in p['set'] for p in request['rows']):
            raise StoreError('synthetic projection refusal')
        for p in request['rows']:
            row = self.rows[p['id']]
            if row['revision'] != p['expected_revision'] or any(row[f] != p['expected_' + f] for f in ('status', 'assignee')):
                raise StoreError('synthetic original revision/claim refusal')
            if p['require_change'] and not any(row['metadata'].get(k, MISSING) != v for k, v in p['set'].items()):
                raise StoreError('synthetic no-effect refusal')
        result = []
        for p in request['rows']:
            row = self.rows[p['id']]
            row['metadata'].update(p['set'])
            row['revision'] = str(int(row['revision']) + 1)
            result.append(dict(id=p['id'], revision=row['revision'], changed=True))
        if self.lose_ack:
            raise StoreError('synthetic native reply lost after commit')
        return dict(schema_version='1', ok=True, store_ref=self.store_ref, rows=result)

    def execute(self, prepared):
        keys = {key for row in prepared.request['rows'] for key in row['set']}
        projections = [row for row in prepared.request['rows'] if 'gc.work_dir' in row['set'] or 'gc.worktree_ref' in row['set']]
        self.transactions.append(SimpleNamespace(before=json.loads(prepared.before_bytes),
            after=json.loads(prepared.after_bytes), scope=json.loads(prepared.scope_bytes), projections=projections,
            record_kinds=[kind for kind, contract in contracts().items() if contract['metadata_key'] in keys],
            prepared=prepared))
        return super().execute(prepared)


class PrepareAssetTests(unittest.TestCase):
    def test_prepare_asset_routes_new_mode_to_recorded_workspace_before_fetch(self):
        asset = (SCRIPTS.parent / 'workflows' / 'do-work' / 'prepare-worktree.md').read_text()
        self.assertIn('workspace_dependency.py', asset)
        self.assertLess(asset.index('workspace_dependency.py'), asset.index('git fetch'))
        self.assertIn('worktree_lifecycle', asset)
        self.assertIn('fall through', asset)
        self.assertNotIn('must already have frozen', asset)
        self.assertIn('atomically', asset)
        self.assertIn('workspace_checkout.py continue', asset)


class CheckoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = importlib.import_module('workspace_checkout')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='checkout-component-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'project with spaces'
        self.repo.mkdir()
        git(self.repo, 'init', '-b', 'main')
        (self.repo / 'tracked').write_text('input\n')
        git(self.repo, 'add', 'tracked')
        git(self.repo, 'commit', '-qm', 'input')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.parent = self.root / 'workspace parent'
        self.parent.mkdir()
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        self.native = self.root / 'gc-double'
        self.native.write_text(NATIVE)
        self.native.chmod(0o700)
        self.log = self.root / 'native.jsonl'
        self.previous = {k: os.environ.get(k) for k in ('TEST_NATIVE_LOG', 'TEST_PLACEMENT')}
        os.environ['TEST_NATIVE_LOG'] = str(self.log)
        os.environ.pop('TEST_PLACEMENT', None)
        self.addCleanup(self.restore_env)
        self.run = dict(version=1, workflow_root_id='root-1', generation=1,
                        writer_step_id='capture-1', input_convoy_id='convoy-1',
                        source_anchor_id='source-1', rig_root=str(self.repo),
                        common_git_dir=git(self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'),
                        base_oid=self.base, worktree_lifecycle='new')
        self.workspace = dict(version=1, workflow_root_id='root-1', generation=1,
                              writer_step_id='prepare-1', source_plan_owner_id='plan-1',
                              workspace_owner_id='owner-1', workspace_bead_id='record-1', strategy='isolated',
                              work_dir=str(self.parent / 'owner-1'), work_branch=None,
                              phase='preparing', input_oid=self.base, current_oid=self.base,
                              active_member_id='member-1', next_member_position=0, output_oid=None,
                              integration_inputs=None, writer_attempt_id='writer-attempt-1',
                              native_attempt_id=None, native_provenance=None,
                              claim_binding=dict(workflow_root_id='root-1', generation=1,
                                                 workspace_owner_id='owner-1', writer_step_id='prepare-1',
                                                 writer_attempt_id='writer-attempt-1'))

    def restore_env(self):
        for key, value in self.previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value

    def checkout(self, **kw):
        return self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture',
                                         evidence_dir=str(self.evidence), parent=str(self.parent),
                                         allow_external_parent=True, gc=str(self.native), **kw)

    def prepared(self):
        result = self.checkout().prepare()
        self.workspace = result['workspace']
        return result

    def change(self, content='output\n'):
        work = Path(self.workspace['work_dir'])
        (work / 'tracked').write_text(content)
        git(work, 'add', 'tracked')
        git(work, 'commit', '-qm', 'owned output')
        return git(work, 'rev-parse', 'HEAD')

    def test_prepare_enters_recorded_input_and_returns_native_launch_evidence(self):
        result = self.prepared()
        self.assertEqual(result['head'], self.base)
        self.assertEqual(result['workspace']['phase'], 'entry')
        self.assertEqual(result['workspace']['native_attempt_id'], 'native-attempt-1')
        self.assertEqual(result['owner_metadata']['gc.worktree_owner'], 'owner-1')
        self.assertEqual(result['launch_reference']['workspace_bead_id'], 'record-1')
        self.assertEqual(self.checkout().path(), self.workspace['work_dir'])

    def test_preparing_registered_input_recovers_without_another_ensure(self):
        prepared = self.prepared()
        self.workspace = dict(self.workspace, phase='preparing', native_provenance=None, native_attempt_id=None)
        result = self.checkout().prepare()
        self.assertEqual(result['workspace'], prepared['workspace'])
        calls = [json.loads(s)['action'] for s in self.log.read_text().splitlines()]
        self.assertEqual(calls.count('ensure'), 1)

    def test_preexisting_advanced_head_is_preserved_and_blocked_at_first_entry(self):
        self.prepared()
        head = self.change()
        self.workspace = dict(self.workspace, phase='preparing', native_provenance=None, native_attempt_id=None)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'input'):
            self.checkout().prepare()
        self.assertEqual(git(self.workspace['work_dir'], 'rev-parse', 'HEAD'), head)
        self.assertTrue(list(self.evidence.glob('*.json')))

    def test_unexplained_active_advance_is_blocked(self):
        self.prepared()
        self.workspace['phase'] = 'active'
        head = self.change()
        with self.assertRaisesRegex(self.mod.CheckoutError, 'unexplained'):
            self.checkout().recover(member_id='member-1')
        self.assertEqual(git(self.workspace['work_dir'], 'rev-parse', 'HEAD'), head)

    def test_dirty_and_git_operation_state_are_preserved(self):
        self.prepared()
        work = Path(self.workspace['work_dir'])
        (work / 'private-work').write_text('keep')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'dirty'):
            self.checkout().verify()
        self.assertEqual((work / 'private-work').read_text(), 'keep')
        (work / 'private-work').unlink()
        gitdir = Path(git(work, 'rev-parse', '--absolute-git-dir'))
        for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'BISECT_LOG', 'rebase-merge', 'rebase-apply', 'sequencer', 'index.lock', 'HEAD.lock'):
            with self.subTest(operation=name):
                marker = gitdir / name
                marker.write_text(self.base)
                with self.assertRaisesRegex(self.mod.CheckoutError, 'operation'):
                    self.checkout().verify()
                self.assertTrue(marker.exists())
                marker.unlink()

    def test_missing_rollout_refuses_without_native_effects(self):
        self.run['worktree_lifecycle'] = 'legacy'
        with self.assertRaisesRegex(self.mod.CheckoutError, 'new'):
            self.checkout().prepare()
        self.assertFalse(self.log.exists())

    def test_evidence_in_checkout_and_symlink_parent_refuse(self):
        with self.assertRaisesRegex(self.mod.CheckoutError, 'evidence'):
            self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture',
                                      evidence_dir=str(self.repo), parent=str(self.parent), allow_external_parent=True)
        alias = self.root / 'alias'
        alias.symlink_to(self.parent, target_is_directory=True)
        self.workspace['work_dir'] = str(alias / 'owner-1')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'symlink'):
            self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture',
                                      evidence_dir=str(self.evidence), parent=str(alias), allow_external_parent=True)

    def test_owner_projection_uses_native_transport_keys(self):
        metadata = self.prepared()['owner_metadata']
        self.assertEqual(metadata['gc.worktree_repo'], str(self.repo))
        self.assertEqual(metadata['gc.worktree_base_ref'], self.base)

    def test_bare_root_and_control_root_are_real_git_topologies(self):
        for control in (False, True):
            with self.subTest(control_root=control):
                root = self.root / ('control root' if control else 'bare root')
                root.mkdir()
                bare = root / '.git' if control else root
                subprocess.check_call(['git', 'clone', '--bare', str(self.repo), str(bare)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.run.update(rig_root=str(root), common_git_dir=str(bare))
                parent = root / 'editable'
                parent.mkdir()
                self.workspace.update(work_dir=str(parent / 'owner-1'), phase='preparing', native_provenance=None, native_attempt_id=None)
                os.environ['TEST_PLACEMENT'] = '1'
                checkout = self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), parent=str(parent), gc=str(self.native))
                result = checkout.prepare()
                self.assertEqual(result['head'], self.base)
                self.assertEqual(result['native_report']['placement'], 'within-repo-root')
                self.assertEqual(git(result['path'], 'rev-parse', '--path-format=absolute', '--git-common-dir'), str(bare))

    def test_default_and_direct_child_placement_require_native_support(self):
        for parent in (self.repo / 'worktrees', self.repo):
            self.workspace['work_dir'] = str(parent / 'owner-1')
            checkout = self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), parent=str(parent), gc=str(self.native))
            with self.assertRaisesRegex(self.mod.CheckoutError, 'placement'):
                checkout.prepare()
            self.assertFalse(Path(self.workspace['work_dir']).exists())
        os.environ['TEST_PLACEMENT'] = '1'
        result = checkout.prepare()
        self.assertEqual(result['head'], self.base)

    def result(self, head):
        return dict(version=1, workflow_root_id='root-1', generation=1, writer_step_id='member-1',
                    source_plan_owner_id='plan-1', workspace_owner_id='owner-1', member_id='member-1',
                    status='changed' if head != self.base else 'no_change', input_oid=self.base, output_oid=head,
                    commit_oids=[head] if head != self.base else [], acceptance=dict(status='unverified', subject_oid=head,
                    project_checks=[], artifacts=[], independent_review=dict(status='unrun', reviewed_oid=None,
                    reviewer=None, report_path=None, report_sha256=None)))

    def test_exact_unrecorded_linear_result_and_checkpoint_pending_replay(self):
        self.prepared()
        self.workspace['phase'] = 'active'
        head = self.change()
        declaration = self.result(head)
        recovered = self.checkout().recover(member_id='member-1', result=declaration, result_unrecorded=True, writer_step_id='member-1')
        self.assertTrue(recovered['record_result'])
        self.assertEqual(recovered['workspace']['current_oid'], head)
        self.assertEqual(recovered['workspace']['phase'], 'result')
        checkpoint = self.checkout().recover(member_id='member-1', result=declaration)
        self.assertFalse(checkpoint['record_result'])
        self.workspace = recovered['workspace']
        replay = self.checkout().recover(member_id='member-1', result=declaration)
        self.assertEqual(replay['workspace'], recovered['workspace'])
        with self.assertRaisesRegex(self.mod.CheckoutError, 'member'):
            self.checkout().recover(member_id='foreign')

    def test_sanitized_git_environment_and_no_default_recapture(self):
        (self.repo / 'tracked').write_text('launcher moved after capture\n')
        git(self.repo, 'add', 'tracked')
        git(self.repo, 'commit', '-qm', 'launcher advance')
        launcher = git(self.repo, 'rev-parse', 'HEAD')
        self.assertNotEqual(launcher, self.base)
        self.prepared()
        self.assertEqual(git(self.repo, 'rev-parse', 'HEAD'), launcher)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ.update(GIT_DIR='/no/such/repository', GIT_WORK_TREE='/no/such/worktree', GIT_INDEX_FILE='/no/index',
                          GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.repositoryformatversion', GIT_CONFIG_VALUE_0='99')
        self.assertEqual(self.checkout().path(), self.workspace['work_dir'])
        self.assertEqual(self.workspace['input_oid'], self.base)

    def test_unknown_metadata_and_foreign_native_attempt_preserve_state(self):
        self.prepared()
        for field, value in (('version', 2), ('phase', 'unknown'), ('native_attempt_id', 'foreign-attempt')):
            with self.subTest(field=field):
                saved = copy.deepcopy(self.workspace)
                self.workspace[field] = value
                with self.assertRaises(self.mod.RecordError):
                    self.checkout().prepare()
                self.workspace = saved
        provenance_file = Path(git(self.workspace['work_dir'], 'rev-parse', '--absolute-git-dir')) / 'gascity-worktree-provenance.json'
        provenance = json.loads(provenance_file.read_text())
        provenance['attempt_id'] = 'foreign-attempt'
        provenance_file.write_text(json.dumps(provenance))
        with self.assertRaisesRegex(self.mod.CheckoutError, 'attempt'):
            self.checkout().verify()
        self.assertEqual(json.loads(provenance_file.read_text())['attempt_id'], 'foreign-attempt')

    def test_external_parent_and_foreign_checkout_parent_are_refused(self):
        with self.assertRaisesRegex(self.mod.CheckoutError, 'external'):
            self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), parent=str(self.parent))
        foreign = self.root / 'foreign'
        foreign.mkdir()
        git(foreign, 'init', '-b', 'main')
        self.workspace['work_dir'] = str(foreign / 'owner-1')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'foreign'):
            self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), parent=str(foreign), allow_external_parent=True)
        self.assertFalse((foreign / 'owner-1').exists())

    def test_registration_collision_and_prunable_path_preserve_git_metadata(self):
        path = Path(self.workspace['work_dir'])
        path.mkdir()
        (path / 'foreign').write_text('keep')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'registration'):
            self.checkout().prepare()
        self.assertEqual((path / 'foreign').read_text(), 'keep')
        (path / 'foreign').unlink()
        path.rmdir()
        self.prepared()
        moved = path.with_name('moved-by-owner')
        path.rename(moved)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'prunable'):
            self.checkout().verify()
        self.assertTrue((moved / 'tracked').exists())
        self.assertIn(str(path), git(self.repo, 'worktree', 'list', '--porcelain'))

    def test_bad_input_and_merge_result_never_receive_recovery_credit(self):
        self.prepared()
        self.workspace['phase'] = 'active'
        work = Path(self.workspace['work_dir'])
        git(work, 'checkout', '-qb', 'side')
        (work / 'side').write_text('side')
        git(work, 'add', 'side'); git(work, 'commit', '-qm', 'side')
        side = git(work, 'rev-parse', 'HEAD')
        git(work, 'checkout', '--detach', self.base)
        head = self.change()
        git(work, 'merge', '--no-ff', '-m', 'merge', side)
        merged = git(work, 'rev-parse', 'HEAD')
        declaration = self.result(merged)
        declaration['commit_oids'] = git(work, 'rev-list', '--reverse', '--topo-order', self.base + '..' + merged).splitlines()
        with self.assertRaisesRegex(self.mod.CheckoutError, 'linear'):
            self.checkout().recover(member_id='member-1', result=declaration, result_unrecorded=True, writer_step_id='member-1')
        self.assertEqual(git(work, 'rev-parse', 'HEAD'), merged)
        self.assertEqual(self.workspace['current_oid'], self.base)

    def test_traversal_alias_and_evidence_in_other_worktree_are_refused(self):
        for path in (str(self.parent / 'x') + '/../owner-1', str(self.parent) + '//owner-1'):
            with self.subTest(path=path):
                self.workspace['work_dir'] = path
                with self.assertRaises(self.mod.CheckoutError): self.checkout()
        self.workspace['work_dir'] = str(self.parent / 'owner-1')
        other = self.root / 'other-worktree'
        git(self.repo, 'worktree', 'add', '--detach', str(other), self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'evidence'):
            self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(other), parent=str(self.parent), allow_external_parent=True)

    def test_owned_recorded_descendant_reuse_and_no_change_result(self):
        self.prepared()
        self.workspace['phase'] = 'active'
        recovered = self.checkout().recover(member_id='member-1', result=self.result(self.base))
        self.assertEqual(recovered['workspace']['phase'], 'result')
        head = self.change()
        self.workspace.update(phase='result', current_oid=head, output_oid=head)
        result = self.checkout().verify()
        self.assertEqual(result['head'], head)
        self.assertEqual(result['workspace']['native_provenance']['base_sha'], self.base)

    def managed_context(self, *, inherited=False, shared=False):
        import workspace_cooked as cooked
        import workspace_run as run_api
        from workspace_records import record_sha256
        def row(bead_id, metadata=None, status='closed', assignee=''):
            return dict(id=bead_id, revision='1', metadata=metadata or {}, status=status,
                        assignee=assignee, type='task', labels=[])
        native = {'gc.root_bead_id': 'root-1', 'gc.root_store_ref': 'rig:fixture',
                  'gc.source_root_id': 'root-1', 'gc.source_generation': '1'}
        plan = dict(version=1, workflow_root_id='root-1', generation=1, writer_step_id='plan-writer', source_plan_owner_id='plan-1',
                    base_oid=self.base, parent_canonical_generation=None, parent_canonical_oid=None,
                    nodes=[dict(owner_id='owner-1', strategy='isolated', member_ids=['member-1'], source_predecessor_owner_ids=[], single_lane=False)],
                    terminal_owner_id='owner-1')
        if shared:
            plan['nodes'][0].update(strategy='shared-chain', member_ids=['member-1', 'member-2'], single_lane=True)
            self.workspace['strategy'] = 'shared-chain'
        rows = {i: row(i) for i in ('root-1', 'run-record', 'plan-record', 'record-1', 'plan-1', 'owner-1', 'member-1',
                                   'authority-1', 'blocker-record', 'convoy-1', 'source-1', 'attach-1')}
        rows['root-1'].update(status='in_progress', metadata={'gc.implementation_run_ref': canonical_bytes(record_reference('run', 'run-record', self.run)).decode(),
                         'gc.kind': 'workflow', 'gc.root_store_ref': 'rig:fixture', 'gc.input_convoy_id': 'convoy-1'})
        checks = {'required_checks': [{'id': 'unit', 'argv': ['true']}]}
        rows['root-1']['metadata']['gc.var.worktree_checks'] = canonical_bytes(checks).decode()
        policy = run_api.capture_check_policy(self.run, 'run-record', canonical_bytes(checks).decode())
        rows['run-record']['metadata'].update({'gc.implementation_run': canonical_bytes(self.run).decode(),
                                              run_api.CHECKS_POLICY_KEY: canonical_bytes(policy).decode()})
        rows['convoy-1'].update(type='convoy', metadata=dict(native, **{'gc.source_plan_owner_id': 'plan-1',
                                                                   'gc.source_plan_sha256': record_sha256(plan)}))
        rows['source-1']['metadata']['gc.source_store_ref'] = 'rig:fixture'
        rows['plan-record']['metadata']['gc.source_plan'] = canonical_bytes(plan).decode()
        rows['plan-1']['metadata'] = dict(native, **{'gc.source_plan_ref': canonical_bytes(record_reference('source-plan', 'plan-record', plan)).decode()})
        rows['owner-1']['metadata'] = dict(native)
        rows['member-1']['metadata'] = dict(native)
        rows['member-1']['status'] = 'open'
        if shared:
            rows['member-2'] = row('member-2', dict(native), status='open')
        formula_path = self.root / 'do-work.formula.toml'
        formula_path.write_text('formula = "do-work"\n')
        rows['attach-1']['metadata'] = dict(native, **{'gc.formula_name': 'do-work',
            'gc.formula_hash': hashlib.sha256(formula_path.read_bytes()).hexdigest(), 'gc.formula_source': str(formula_path)})
        self.compiled = {'ok': True, 'name': 'do-work', 'steps': [], 'deps': []}
        self.sessions = {}
        previous = None
        stages = [('prepare-1', 'prepare-worktree', 'gc.run-operator', None),
                  ('test-1', 'write-failing-test', 'gc.implementation-worker', None),
                  ('story-1', 'implement-story', 'gc.implementation-worker', None),
                  ('producer-1', 'implement', 'gc.implementation-worker', 'gc.build.implementation-summary.v1'),
                  ('reviewer-1', 'independent-acceptance', 'gc.implementation-reviewer', None),
                  ('recorder-1', 'record-result', 'gc.run-operator', None)]
        for bead_id, stage, target, schema in stages:
            ref = 'do-work.' + stage
            designation = {'gc.run_target': target}
            if schema: designation['gc.build.artifact_schema'] = schema
            metadata = dict(native, **designation, **{'gc.step_ref': ref, 'gc.step_id': ref,
                'gc.source_anchor_id': 'member-1', 'gc.drain_member_id': 'member-1', 'gc.attach_root_id': 'attach-1',
                'gc.session_id': 'session-' + bead_id, 'gc.session_name': 'fixture-' + bead_id,
                cooked.TOPOLOGY: canonical_bytes([previous] if previous else []).decode()})
            rows[bead_id] = row(bead_id, metadata, status='in_progress' if bead_id == 'prepare-1' else 'open',
                               assignee='fixture-' + bead_id if bead_id == 'prepare-1' else '')
            self.compiled['steps'].append({'id': ref, 'metadata': designation})
            if previous: self.compiled['deps'].append({'step_id': ref, 'depends_on_id': previous, 'type': 'blocks'})
            previous = ref
            session = row('session-' + bead_id, {'instance_token': 'incarnation-' + bead_id, 'template': target,
                'session_name': 'fixture-' + bead_id, 'state': 'active', 'current_claim_bead_id': bead_id}, status='in_progress')
            session['type'] = 'session'; self.sessions[session['id']] = session
        if inherited:
            rows['root-1']['metadata']['gc.build.implementation_convoy_id'] = 'convoy-1'
            rows['root-1']['metadata']['gc.var.worktree_lifecycle'] = 'new'
            rows['control-1'] = row('control-1', dict(native, **{'gc.kind': 'drain'}))
            rows['unit-1'] = row('unit-1', dict(native, **{'gc.synthetic_kind': 'drain-unit-convoy',
                'gc.parent_convoy_id': 'convoy-1', 'gc.drain_control_id': 'control-1', 'gc.drain_member_id': 'member-1'}))
            rows['unit-1']['type'] = 'convoy'
            formula = {k: v for k, v in rows['attach-1']['metadata'].items() if k.startswith('gc.formula_')}
            rows['child-1'] = row('child-1', dict(formula, **{'gc.kind': 'workflow',
                'gc.root_store_ref': 'rig:fixture', 'gc.input_convoy_id': 'unit-1',
                'gc.drain_control_id': 'control-1', 'gc.drain_member_id': 'member-1'}), status='in_progress')
            for bead_id, *_ in stages:
                rows[bead_id]['metadata']['gc.root_bead_id'] = 'child-1'
                for key in ('gc.attach_root_id', 'gc.source_anchor_id', 'gc.drain_member_id'):
                    rows[bead_id]['metadata'].pop(key, None)
        store = StorePort(rows, self.run['common_git_dir'], gc=str(self.native), cwd=str(self.root))
        def registration(*args, **kwargs):
            return dict(city_path=str(self.root), city_name='fixture-city', rigs=[dict(name='fixture', path=str(self.repo))])
        self.registration = registration
        for patcher in (patch.object(run_api, 'native_json', side_effect=registration),
                        patch.object(cooked, '_native_list', return_value=[item[0] for item in stages]),
                        patch.object(cooked, 'native_json', side_effect=lambda *a, **kw: copy.deepcopy(self.compiled))):
            patcher.start(); self.addCleanup(patcher.stop)
        attempt = Attempt('session-prepare-1', 'incarnation-prepare-1', 'prepare-1')
        self.workspace = self.mod._writer(self.workspace, attempt)
        continuation, context_rows = None, None
        if inherited:
            from workspace_entry import read_native_continuation
            continuation, context_rows = read_native_continuation(store, claimed_step_id='prepare-1', requested_root_id='root-1')
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1',
            continuation=continuation, continuation_rows=context_rows)
        original.update(store.snapshot(['root-1', 'record-1', 'owner-1', 'authority-1']))
        initial = store.install_grant(attempt, dict(workflow_root_id='root-1', generation=1, writer_scope_id='owner-1', record_kind='workspace'),
            'authority-1', [RecordWrite('workspace', 'record-1', self.workspace)],
            [ReferenceWrite('owner-1', 'gc.workspace_ref', record_reference('workspace', 'record-1', self.workspace))],
            writer_map=writer_map, expected_rows=original,
            projections=[InheritedRunReference(continuation)] if inherited else ())
        self.assertEqual(store.execute(initial)['outcome'], 'committed')
        store.transactions.clear()
        kwargs = dict(gc=str(self.native), city_root=str(self.root), rig_name='fixture', workflow_root_id='root-1', input_convoy_id='convoy-1',
                      run_record_id='run-record', plan_record_id='plan-record', workspace_record_id='record-1', evidence_dir=str(self.evidence),
                      selected_mode='new', parent=str(self.parent), allow_external_parent=True)
        if inherited:
            kwargs.update(workflow_root_id='child-1', input_convoy_id='unit-1')
        return store, attempt, kwargs

    def admit_recorder(self, store):
        import workspace_cooked as cooked
        for bead_id in ('prepare-1', 'test-1', 'story-1', 'producer-1', 'reviewer-1'):
            store.rows[bead_id]['status'] = 'closed'
            store.rows[bead_id]['metadata']['gc.outcome'] = 'pass'
        row = store.rows['recorder-1']
        row.update(status='in_progress', assignee='fixture-recorder-1')
        attempt = Attempt('session-recorder-1', 'incarnation-recorder-1', 'recorder-1')
        continuation = self.mod._occurrence_continuation(store, 'root-1', 'recorder-1', {})
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='recorder-1',
            continuation=continuation)
        original.update(store.snapshot(['root-1', 'record-1', 'owner-1', 'authority-1', 'run-record']))
        workspace = self.mod._writer(dict(self.workspace, phase='active'), attempt)
        native_ref = dict(self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref=store.store_ref,
            evidence_dir=str(self.evidence), parent=str(self.parent), allow_external_parent=True, gc=str(self.native),
            continuation=continuation, native_rows=original)._result(
                {'provenance': self.workspace['native_provenance'], 'head': self.base})['launch_reference'], binding_step_id='recorder-1')
        prepared = store.accept_replacement(attempt,
            dict(workflow_root_id='root-1', generation=1, writer_scope_id='owner-1', record_kind='workspace'),
            'authority-1', [RecordWrite('workspace', 'record-1', workspace)], writer_map=writer_map,
            expected_grant=json.loads(store.rows['authority-1']['metadata'][GRANT_KEY]), expected_rows=original,
            guards=[GuardRead(key, field, value) for key, row in original.items() for field, value in row['metadata'].items()],
            projections=[NativeWorktreeReference('recorder-1', 'record-1', native_ref)])
        self.assertEqual(store.execute(prepared)['outcome'], 'committed')
        self.workspace = workspace
        for bead_id in ('result-record', 'result-authority'):
            store.rows[bead_id] = dict(id=bead_id, revision='1', metadata={}, status='closed', assignee='', type='task', labels=[])
        return attempt

    def test_inherited_prepare_keeps_logical_payload_and_physical_native_references(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        child = store.rows['child-1']['metadata']
        self.assertIn('gc.workspace_run_continuation.v1', child)
        self.assertEqual(json.loads(child['gc.implementation_run_ref'])['identity'][0], 'root-1')
        result = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['test-1', 'producer-1', 'recorder-1'], **kwargs)
        self.workspace = result['workspace']
        self.assertEqual(self.workspace['workflow_root_id'], 'root-1')
        self.assertEqual(store.rows['record-1']['metadata']['gc.root_bead_id'], 'child-1')
        for step in ('test-1', 'producer-1', 'recorder-1'):
            reference = json.loads(store.rows[step]['metadata']['gc.worktree_ref'])
            self.assertEqual(reference['workflow_root_id'], 'child-1')
            self.assertEqual(reference['binding_step_id'], step)
        self.assertNotIn('gc.worktree_ref', store.rows['member-1']['metadata'])
        self.assertEqual(git(result['path'], 'rev-parse', 'HEAD'), self.base)
        logical = dict(kwargs, workflow_root_id='root-1', input_convoy_id='convoy-1')
        count = len(store.transactions)
        observed = self.mod.manage_workspace(store, action='path', claimed_step_id='prepare-1', **logical)
        self.assertEqual(observed['path'], result['path'])
        self.assertEqual(len(store.transactions), count)

    def test_inherited_dirty_continuation_keeps_callable_and_does_not_advance_checkpoint(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        result = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['test-1', 'producer-1'], **kwargs)
        self.workspace = result['workspace']
        store.rows['prepare-1'].update(status='closed', assignee='')
        store.rows['prepare-1']['metadata']['gc.outcome'] = 'pass'
        store.rows['test-1'].update(status='in_progress', assignee='fixture-test-1')
        attempt = Attempt('session-test-1', 'incarnation-test-1', 'test-1')
        self.native_session_ports(attempt)
        (Path(result['path']) / 'private-edit').write_text('unfinished work')
        before, count = copy.deepcopy(store.rows), len(store.transactions)
        continued = self.mod.manage_workspace(store, attempt, action='continue', authority_id='authority-1',
            artifact_root=str(self.evidence), **kwargs)
        self.assertEqual(continued['git_state'], 'dirty')
        self.assertFalse(continued['accepted'])
        self.assertTrue(continued['checkpoint_required'])
        self.assertEqual(continued['launch_reference']['workflow_root_id'], 'child-1')
        self.assertEqual(continued['launch_reference']['binding_step_id'], 'test-1')
        self.assertEqual(continued['workspace']['current_oid'], self.base)
        self.assertEqual(store.rows, before)
        self.assertEqual(len(store.transactions), count)

    def test_inherited_native_chain_refusals_preserve_git_and_metadata(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        baseline = copy.deepcopy(store.rows)
        changes = [('control-1', 'gc.root_bead_id', 'foreign-root'),
                   ('child-1', 'gc.root_store_ref', 'rig:foreign'),
                   ('unit-1', 'gc.parent_convoy_id', 'foreign-convoy'),
                   ('child-1', 'gc.drain_member_id', 'member-2'),
                   ('convoy-1', 'gc.source_generation', '2'),
                   ('child-1', 'gc.implementation_run_ref', 'null')]
        for bead_id, key, value in changes:
            with self.subTest(bead_id=bead_id, key=key):
                store.rows = copy.deepcopy(baseline)
                store.rows[bead_id]['metadata'][key] = value
                changed = copy.deepcopy(store.rows)
                with self.assertRaises((self.mod.CheckoutError, RecordError, KeyError)):
                    self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                        launch_step_ids=['producer-1'], **kwargs)
                self.assertEqual(store.rows, changed)
                self.assertFalse(self.log.exists())
                self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_inherited_late_control_revision_change_stops_before_git(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        def race(request):
            store.rows['control-1']['revision'] = str(int(store.rows['control-1']['revision']) + 1)
        store.before_apply = race
        with self.assertRaisesRegex(self.mod.CheckoutError, 'unresolved|unknown') as error:
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                launch_step_ids=['producer-1'], **kwargs)
        self.assertTrue(Path(error.exception.evidence_path).is_file())
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())
        self.assertEqual(json.loads(store.rows['record-1']['metadata']['gc.workspace'])['phase'], 'preparing')

    def test_inherited_recovery_records_result_without_recapturing_run_or_acceptance(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['recorder-1'], **kwargs)
        self.workspace = prepared['workspace']
        run_before = store.rows['run-record']['metadata']['gc.implementation_run']
        attempt = self.admit_recorder(store)
        head = self.change()
        declared = dict(self.result(head), writer_step_id='recorder-1')
        recovered = self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1',
            launch_step_ids=['recorder-1'], result_record_id='result-record', declared_result=declared,
            result_authority_id='result-authority', **kwargs)
        self.assertEqual(recovered['workspace']['current_oid'], head)
        self.assertEqual(recovered['launch_reference']['workflow_root_id'], 'child-1')
        self.assertEqual(recovered['launch_reference']['binding_step_id'], 'recorder-1')
        result = json.loads(store.rows['result-record']['metadata']['gc.workspace_result'])
        self.assertEqual(result['acceptance'], declared['acceptance'])
        self.assertEqual(store.rows['run-record']['metadata']['gc.implementation_run'], run_before)

    def test_shared_historical_workspace_uses_published_old_child_context(self):
        from workspace_entry import read_native_continuation
        store, attempt, kwargs = self.managed_context(inherited=True, shared=True)
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['producer-1'], **kwargs)
        self.workspace = prepared['workspace']
        old, original = read_native_continuation(store, claimed_step_id='prepare-1', requested_root_id='root-1')
        for old_id, new_id in [('child-1', 'child-2'), ('unit-1', 'unit-2'), ('prepare-1', 'prepare-2')]:
            store.rows[new_id] = copy.deepcopy(store.rows[old_id])
            store.rows[new_id]['id'] = new_id
        store.rows['unit-2']['metadata']['gc.drain_member_id'] = 'member-2'
        store.rows['child-2']['metadata'].update({'gc.input_convoy_id': 'unit-2', 'gc.drain_member_id': 'member-2'})
        for key in ('gc.implementation_run_ref', 'gc.workspace_run_continuation.v1'):
            store.rows['child-2']['metadata'].pop(key)
        store.rows['prepare-2']['metadata']['gc.root_bead_id'] = 'child-2'
        store.rows['prepare-2']['metadata'].pop('gc.worktree_ref', None)
        newer, _ = read_native_continuation(store, claimed_step_id='prepare-2', requested_root_id='root-1')
        before = copy.deepcopy(store.rows)
        loaded = self.mod.load_workspace_context(store, gc=str(self.native), city_root=str(self.root),
            rig_name='fixture', workflow_root_id='child-2', input_convoy_id='unit-2',
            run_record_id='run-record', plan_record_id='plan-record', workspace_record_id='record-1',
            claimed_step_id='prepare-2', record_kind=None)
        self.assertEqual(loaded[2], self.workspace)
        observed = self.mod.WorkspaceCheckout(loaded[0], loaded[2], store_ref=store.store_ref,
            evidence_dir=str(self.evidence), parent=str(self.parent), allow_external_parent=True,
            gc=str(self.native), continuation=old, native_rows=loaded[3]).verify()
        self.assertEqual(observed['owner_metadata']['gc.root_bead_id'], 'child-1')
        self.assertEqual(store.read_record('workspace', 'record-1', continuation=old), self.workspace)
        with self.assertRaises(RecordError):
            store.read_record('workspace', 'record-1', continuation=newer)
        self.assertEqual(store.rows, before)

    def test_lost_publication_reply_blocks_new_intent_until_fresh_process_readback(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        store.lose_ack = True
        with patch.object(store, 'resolve', return_value={'outcome': 'unknown'}):
            with self.assertRaisesRegex(self.mod.CheckoutError, 'original request') as error:
                self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                    launch_step_ids=['producer-1'], **kwargs)
        store.lose_ack = False
        request_path = Path(error.exception.evidence_path)
        self.assertTrue(request_path.is_file())
        self.assertFalse(self.log.exists())
        count = len(store.transactions)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'unresolved'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                launch_step_ids=['producer-1'], **kwargs)
        other_evidence = self.root / 'other-evidence'
        other_evidence.mkdir(mode=0o700)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'unresolved'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                launch_step_ids=['producer-1'], **dict(kwargs, evidence_dir=str(other_evidence)))
        self.assertEqual(len(store.transactions), count)
        self.assertFalse(self.log.exists())
        packet = json.loads(request_path.read_text())
        state_path = self.root / 'lost-reply-state.json'
        state_path.write_text(json.dumps(dict(rows=store.rows, common=store.common_git_dir,
            gc=str(self.native), cwd=store.cwd, paths=sys.path, request=str(request_path))))
        program = '''import json, sys
from pathlib import Path
state=json.loads(Path(sys.argv[1]).read_text())
sys.path[:0]=state['paths']
from test_workspace_checkout import StorePort
from workspace_requests import resolve_request
store=StorePort(state['rows'],state['common'],gc=state['gc'],cwd=state['cwd'])
receipt=resolve_request(store,state['request'])
assert not store.transactions, 'readback submitted a new effect'
print(json.dumps(receipt))
'''
        fresh = subprocess.run([sys.executable, '-c', program, str(state_path)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        receipt = json.loads(fresh.stdout)
        self.assertIn(receipt['outcome'], ('committed', 'replayed'))
        self.assertEqual(receipt['request_sha256'], packet['request_sha256'])
        self.assertNotIn('rows', receipt)
        self.assertFalse(list(request_path.parent.glob('*.pending')))
        self.assertTrue(request_path.exists())
        resumed = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['producer-1'], **kwargs)
        self.assertEqual(resumed['head'], self.base)

    def test_failed_exact_write_acknowledgement_preserves_request_without_blocker_or_git_effects(self):
        store, attempt, kwargs = self.managed_context(inherited=True)
        observed = []
        def reject(prepared, resolved):
            observed.append((prepared.sha256, resolved['request_sha256'], resolved['outcome']))
            raise RecordError('caller original source rows differ')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'acknowledgement is unresolved') as error:
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
                launch_step_ids=['producer-1'], blocker_record_id='blocker-record', blocker_id='ack-failed',
                acknowledge=reject, **kwargs)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], observed[0][1])
        self.assertIn(observed[0][2], ('committed', 'replayed'))
        self.assertEqual(len(store.transactions), 1)
        self.assertEqual(store.rows['blocker-record']['metadata'], {})
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())
        request = Path(error.exception.request_path)
        self.assertEqual(str(request), error.exception.evidence_path)
        self.assertTrue(request.is_file())
        self.assertTrue(list(request.parent.glob('*.pending')))

    def test_shared_successor_projection_is_pure_intent_and_preserves_persisted_admission(self):
        import workspace_cooked as cooked
        from workspace_entry import read_native_continuation
        store, attempt, kwargs = self.managed_context(inherited=True, shared=True)
        self.workspace = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['recorder-1'], **kwargs)['workspace']
        attempt = self.admit_recorder(store)
        head = self.change()
        self.workspace = self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1',
            launch_step_ids=['recorder-1'], result_record_id='result-record',
            declared_result=dict(self.result(head), writer_step_id='recorder-1'),
            result_authority_id='result-authority', **kwargs)['workspace']
        store.rows['recorder-1'].update(status='closed', assignee='')
        store.rows['recorder-1']['metadata']['gc.outcome'] = 'pass'
        for old_id, new_id in [('child-1', 'child-2'), ('unit-1', 'unit-2')]:
            store.rows[new_id] = copy.deepcopy(store.rows[old_id]); store.rows[new_id]['id'] = new_id
        store.rows['child-2']['metadata'].update({'gc.input_convoy_id': 'unit-2', 'gc.drain_member_id': 'member-2'})
        store.rows['unit-2']['metadata']['gc.drain_member_id'] = 'member-2'
        for key in ('gc.implementation_run_ref', 'gc.workspace_run_continuation.v1'):
            store.rows['child-2']['metadata'].pop(key)
        new_ids = []
        for old_id in ('prepare-1', 'test-1', 'story-1', 'producer-1', 'reviewer-1', 'recorder-1'):
            new_id = old_id + '-next'; new_ids.append(new_id)
            store.rows[new_id] = copy.deepcopy(store.rows[old_id]); store.rows[new_id]['id'] = new_id
            store.rows[new_id]['metadata']['gc.root_bead_id'] = 'child-2'
            store.rows[new_id]['metadata'].pop('gc.worktree_ref', None)
            store.rows[new_id].update(status='in_progress' if old_id == 'prepare-1' else 'open',
                assignee='fixture-next' if old_id == 'prepare-1' else '')
        current = Attempt('session-next', 'incarnation-next', new_ids[0])
        old, _ = read_native_continuation(store, claimed_step_id='recorder-1', requested_root_id='root-1')
        new, original = read_native_continuation(store, claimed_step_id=current.claimed_bead_id, requested_root_id='root-1')
        with patch.object(cooked, '_native_list', return_value=new_ids):
            writer_map, rows = cooked.read_cooked_writer_map(store, workflow_root_id='root-1',
                claimed_step_id=current.claimed_bead_id, continuation=new, continuation_rows=original)
        rows.update(store.snapshot(list(store.rows)))
        checkout = self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref=store.store_ref,
            evidence_dir=str(self.evidence), parent=str(self.parent), allow_external_parent=True,
            gc=str(self.native), continuation=old, native_rows=rows)
        candidate = self.mod._writer(dict(self.workspace, phase='entry', active_member_id='member-2',
            next_member_position=1, input_oid=head, current_oid=head, output_oid=None), current)
        before, log = copy.deepcopy(store.rows), self.log.read_bytes()
        with patch.object(self.mod, 'git', side_effect=AssertionError('successor projection must not perform Git')):
            intent = checkout.successor_projection(candidate, continuation=new, native_rows=rows, writer_map=writer_map)
            self.assertEqual(intent['owner_metadata']['gc.root_bead_id'], 'child-2')
            self.assertEqual(intent['launch_reference']['workflow_root_id'], 'child-2')
            self.assertEqual(intent['launch_reference']['binding_step_id'], current.claimed_bead_id)
            self.assertEqual(intent['workspace']['native_provenance'], self.workspace['native_provenance'])
            self.assertEqual(intent['evidence_level'], 'guarded-successor-intent')
            for field, value in [('work_branch', 'different'), ('next_member_position', 2), ('input_oid', self.base)]:
                with self.subTest(field=field), self.assertRaises(RecordError):
                    checkout.successor_projection(dict(candidate, **{field: value}), continuation=new,
                        native_rows=rows, writer_map=writer_map)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'not been published'):
            self.mod.WorkspaceCheckout(self.run, candidate, store_ref=store.store_ref,
                evidence_dir=str(self.evidence), parent=str(self.parent), allow_external_parent=True,
                gc=str(self.native), continuation=new, native_rows=rows)
        self.assertEqual(store.rows, before)
        self.assertEqual(self.log.read_bytes(), log)

    def test_managed_preparation_publishes_actual_native_consumer_with_checkpoint(self):
        store, attempt, kwargs = self.managed_context()
        result = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertEqual(result['evidence_level'], 'native-record-component')
        self.assertEqual(result['path'], self.workspace['work_dir'])
        record = json.loads(store.rows['record-1']['metadata']['gc.workspace'])
        owner = store.rows['record-1']['metadata']
        reference = json.loads(store.rows['producer-1']['metadata']['gc.worktree_ref'])
        self.assertEqual(record['phase'], 'entry')
        self.assertEqual(owner['gc.worktree_base_ref'], self.base)
        self.assertEqual(owner['gc.worktree_owner'], 'owner-1')
        self.assertEqual(owner['gc.root_store_ref'], 'rig:fixture')
        self.assertEqual(reference['binding_step_id'], 'producer-1')
        self.assertEqual(reference['native_attempt_id'], record['native_attempt_id'])
        self.assertEqual(len(store.transactions[-1].projections), 2)
        self.assertEqual(record['native_provenance']['schema_version'], 2)

    def test_managed_stale_grant_stops_before_native_provisioning(self):
        store, attempt, kwargs = self.managed_context()
        store.admitted = False
        with self.assertRaises(ValueError):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_managed_failed_projection_never_returns_path_and_preserves_created_worktree(self):
        store, attempt, kwargs = self.managed_context()
        store.fail_projection = True
        with self.assertRaisesRegex(self.mod.CheckoutError, 'publication'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertTrue(Path(self.workspace['work_dir']).exists())
        self.assertNotIn('gc.worktree_ref', store.rows['member-1']['metadata'])
        self.assertEqual(json.loads(store.rows['record-1']['metadata']['gc.workspace'])['phase'], 'preparing')

    def test_managed_dirty_recovery_writes_durable_blocker_outside_checkout(self):
        store, attempt, kwargs = self.managed_context()
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        (Path(prepared['path']) / 'private-work').write_text('keep')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'dirty'):
            self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1', launch_step_ids=['producer-1'],
                                      blocker_record_id='blocker-record', blocker_id='dirty-1', **kwargs)
        self.assertEqual(json.loads(store.rows['record-1']['metadata']['gc.workspace'])['phase'], 'blocked')
        blocker = json.loads(store.rows['blocker-record']['metadata']['gc.workspace_blocker'])
        self.assertEqual(blocker['status'], 'open')
        self.assertEqual(blocker['actual_head_oid'], self.base)
        self.assertTrue(Path(blocker['evidence_path']).is_relative_to(self.evidence))
        self.assertEqual((Path(prepared['path']) / 'private-work').read_text(), 'keep')

    def test_status_classifies_absent_and_preserves_dirty_diagnostics(self):
        status = self.checkout().status()
        self.assertTrue(status['ok'])
        self.assertEqual(status['state'], 'absent')
        self.assertFalse(self.log.exists())
        self.prepared()
        (Path(self.workspace['work_dir']) / 'untracked').write_text('keep')
        status = self.checkout().status()
        self.assertFalse(status['ok'])
        evidence = json.loads(Path(status['evidence_path']).read_text())
        self.assertIn('untracked', evidence['git']['status'])
        self.assertEqual(evidence['git']['head'], self.base)
        self.assertEqual(os.stat(status['evidence_path']).st_mode & 0o777, 0o600)

    def test_managed_foreign_existing_consumer_blocks_before_provisioning(self):
        store, attempt, kwargs = self.managed_context()
        store.rows['producer-1']['metadata']['gc.worktree_ref'] = '{"version":2}'
        with self.assertRaisesRegex(self.mod.CheckoutError, 'prior reference'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertFalse(Path(self.workspace['work_dir']).exists())
        self.assertFalse(self.log.exists())
        self.assertEqual(store.rows['producer-1']['metadata']['gc.worktree_ref'], '{"version":2}')

    def test_managed_read_only_path_checks_projection_without_store_write(self):
        store, attempt, kwargs = self.managed_context()
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        count = len(store.transactions)
        path = self.mod.manage_workspace(store, action='path', claimed_step_id='prepare-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertEqual(path['path'], prepared['path'])
        self.assertEqual(len(store.transactions), count)
        store.rows['record-1']['metadata']['gc.worktree_owner'] = 'foreign'
        with self.assertRaisesRegex(self.mod.CheckoutError, 'projection'):
            self.mod.manage_workspace(store, action='path', claimed_step_id='prepare-1', **kwargs)
        self.assertEqual(len(store.transactions), count)

    def test_managed_unrecorded_result_is_written_once_then_checkpoint_replays(self):
        store, attempt, kwargs = self.managed_context()
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.workspace = prepared['workspace']
        attempt = self.admit_recorder(store)
        head = self.change()
        declared = dict(self.result(head), writer_step_id='recorder-1')
        recovered = self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1', launch_step_ids=['recorder-1'],
                                              result_record_id='result-record', declared_result=declared,
                                              result_authority_id='result-authority', **kwargs)
        self.assertEqual(recovered['workspace']['phase'], 'result')
        self.assertEqual(recovered['workspace']['current_oid'], head)
        result_rows = [t for t in store.transactions if 'member-result' in t.record_kinds]
        self.assertEqual(len(result_rows), 1)
        self.assertEqual(result_rows[0].scope['record_kind'], 'member-result')
        grant = json.loads(store.rows['result-authority']['metadata'][GRANT_KEY])
        self.assertEqual(grant['scope']['record_kind'], 'member-result')
        replay = self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1', launch_step_ids=['recorder-1'],
                                           result_record_id='result-record', **kwargs)
        self.assertEqual(replay['workspace']['current_oid'], head)
        self.assertEqual(len([t for t in store.transactions if 'member-result' in t.record_kinds]), 1)

    def test_evidence_inside_bare_administration_is_refused_before_metadata_parsing(self):
        bare = self.root / 'bare-evidence'
        bare.mkdir()
        git(bare, 'init', '--bare')
        malformed = dict(self.workspace, version=2)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'evidence'):
            self.mod.WorkspaceCheckout(self.run, malformed, store_ref='rig:fixture', evidence_dir=str(bare),
                                      parent=str(self.parent), allow_external_parent=True)
        self.assertFalse(list(bare.glob('workspace-blocker-*.json')))

    def test_managed_native_producer_step_is_distinct_from_logical_member(self):
        store, attempt, kwargs = self.managed_context()
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.workspace = prepared['workspace']
        self.assertEqual(json.loads(store.rows['producer-1']['metadata']['gc.worktree_ref'])['binding_step_id'], 'producer-1')
        self.assertNotIn('gc.worktree_ref', store.rows['member-1']['metadata'])
        attempt = self.admit_recorder(store)
        head = self.change()
        declared = dict(self.result(head), writer_step_id='recorder-1')
        result = self.mod.manage_workspace(store, attempt, action='recover', authority_id='authority-1', launch_step_ids=['recorder-1'],
                                           result_record_id='result-record', declared_result=declared, result_authority_id='result-authority', **kwargs)
        self.assertEqual(result['workspace']['current_oid'], head)
        self.assertEqual(json.loads(store.rows['result-record']['metadata']['gc.workspace_result'])['writer_step_id'], 'recorder-1')

    def test_managed_conflicting_member_pins_preserve_state_before_native_effects(self):
        store, attempt, kwargs = self.managed_context()
        store.rows['producer-1']['metadata'].update({'gc.source_anchor_id': 'member-1', 'gc.drain_member_id': 'foreign'})
        with self.assertRaisesRegex(self.mod.CheckoutError, 'member'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertFalse(Path(self.workspace['work_dir']).exists())
        self.assertFalse(self.log.exists())

    def test_attached_mode_reuses_only_same_branch_owned_descendants(self):
        self.workspace['work_branch'] = 'gc/root-1/gen-1/owner-1'
        result = self.prepared()
        self.assertEqual(result['native_report']['mode'], 'attached')
        head = self.change()
        self.workspace.update(phase='result', current_oid=head, output_oid=head)
        self.assertEqual(self.checkout().verify()['head'], head)
        git(self.workspace['work_dir'], 'checkout', '--detach', head)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'mode or branch'):
            self.checkout().verify()
        self.assertEqual(git(self.workspace['work_dir'], 'rev-parse', 'HEAD'), head)

    def test_topology_safe_default_parents_prepare_exact_input(self):
        os.environ['TEST_PLACEMENT'] = '1'
        self.workspace['work_dir'] = str(self.repo / 'worktrees' / 'owner-1')
        checkout = self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), gc=str(self.native))
        self.assertEqual(checkout.prepare()['head'], self.base)
        bare = self.root / 'default bare'
        subprocess.check_call(['git', 'clone', '--bare', str(self.repo), str(bare)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.run.update(rig_root=str(bare), common_git_dir=str(bare))
        self.workspace['work_dir'] = str(bare / 'workspaces' / 'owner-1')
        checkout = self.mod.WorkspaceCheckout(self.run, self.workspace, store_ref='rig:fixture', evidence_dir=str(self.evidence), gc=str(self.native))
        result = checkout.prepare()
        self.assertEqual(result['head'], self.base)
        self.assertEqual(result['owner_metadata']['gc.worktree_root'], str(bare / 'workspaces'))

    def test_shared_successor_keeps_initial_native_base_and_stable_owner(self):
        first = self.prepared()
        head = self.change()
        self.workspace.update(strategy='shared-chain', phase='entry', input_oid=head, current_oid=head,
                              output_oid=None, active_member_id='member-2', next_member_position=1)
        result = self.checkout().prepare()
        self.assertEqual(result['head'], head)
        self.assertEqual(result['workspace']['input_oid'], head)
        self.assertEqual(result['native_report']['provenance']['base_sha'], self.base)
        self.assertEqual(result['workspace']['native_attempt_id'], first['workspace']['native_attempt_id'])
        self.assertEqual(result['launch_reference']['workspace_owner_id'], 'owner-1')
        self.assertEqual(result['launch_reference']['binding_step_id'], self.workspace['writer_step_id'])
        calls = [json.loads(line)['action'] for line in self.log.read_text().splitlines()]
        self.assertEqual(calls.count('ensure'), 1)

    def test_managed_entry_uses_current_convoy_without_recapturing_original_run(self):
        store, attempt, kwargs = self.managed_context()
        current = copy.deepcopy(store.rows['convoy-1'])
        current['id'] = 'implementation-convoy'
        store.rows[current['id']] = current
        store.rows['root-1']['metadata']['gc.input_convoy_id'] = current['id']
        kwargs['input_convoy_id'] = current['id']
        result = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertEqual(result['head'], self.base)
        self.assertEqual(self.run['input_convoy_id'], 'convoy-1')
        self.assertEqual(json.loads(store.rows['run-record']['metadata']['gc.implementation_run'])['input_convoy_id'], 'convoy-1')
        self.assertTrue(any('implementation-convoy' in t.before for t in store.transactions))

    def test_managed_changed_convoy_generation_blocks_before_native_effects(self):
        store, attempt, kwargs = self.managed_context()
        store.rows['convoy-1']['metadata']['gc.source_generation'] = '2'
        with self.assertRaisesRegex(self.mod.CheckoutError, 'convoy'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_status_git_observation_failure_has_durable_external_evidence(self):
        checkout = self.checkout()
        with patch.object(checkout, 'observe', side_effect=self.mod.CheckoutError('synthetic Git observation unavailable')):
            status = checkout.status()
        self.assertFalse(status['ok'])
        self.assertIsNotNone(status['evidence_path'])
        evidence = json.loads(Path(status['evidence_path']).read_text())
        self.assertEqual(evidence['state'], 'blocked')
        self.assertIn('Git observation', evidence['reason'])

    def test_partial_continuation_preserves_dirty_edits_and_linear_commits_without_acceptance(self):
        self.prepared()
        work = Path(self.workspace['work_dir'])
        (work / 'tracked').write_text('partial test\n')
        (work / 'new-test').write_text('untracked test\n')
        before = git(work, 'status', '--porcelain')
        partial = self.checkout().continuation()
        self.assertEqual(partial['git_state'], 'dirty')
        self.assertFalse(partial['accepted'])
        self.assertTrue(partial['checkpoint_required'])
        self.assertEqual(partial['workspace']['current_oid'], self.base)
        self.assertEqual(git(work, 'status', '--porcelain'), before)
        head = self.change('legitimate partial commit\n')
        continued = self.checkout().continuation()
        self.assertEqual(continued['head'], head)
        self.assertEqual(continued['commit_oids'], [head])
        self.assertEqual(continued['workspace']['current_oid'], self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'dirty'):
            self.checkout().verify()

    def test_partial_continuation_same_head_reset_keeps_checkpoint_and_rewind_refuses(self):
        self.prepared()
        head = self.change()
        self.workspace.update(phase='active', input_oid=head, current_oid=head)
        work = Path(self.workspace['work_dir'])
        git(work, 'reset', '--hard', head)
        continued = self.checkout().continuation()
        self.assertEqual(continued['head'], head)
        self.assertFalse(continued['accepted'])
        self.assertTrue(continued['checkpoint_required'])
        git(work, 'reset', '--hard', self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'rewound'):
            self.checkout().continuation()
        self.assertEqual(git(work, 'rev-parse', 'HEAD'), self.base)

    def test_partial_continuation_refuses_operations_and_result_advancement(self):
        self.prepared()
        gitdir = Path(git(self.workspace['work_dir'], 'rev-parse', '--absolute-git-dir'))
        for operation in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REBASE_HEAD', 'REVERT_HEAD', 'BISECT_LOG', 'sequencer', 'index.lock'):
            with self.subTest(operation=operation):
                path = gitdir / operation
                path.write_text(self.base)
                try:
                    with self.assertRaisesRegex(self.mod.CheckoutError, 'Git operation'):
                        self.checkout().continuation()
                    self.assertEqual(path.read_text(), self.base)
                finally:
                    path.unlink()
        self.workspace.update(phase='result', output_oid=self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'unfinished member'):
            self.checkout().continuation()

    def continuation_context(self, step='test-1'):
        store, attempt, kwargs = self.managed_context()
        prepared = self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1',
            launch_step_ids=['test-1', 'story-1', 'producer-1', 'recorder-1'], **kwargs)
        self.workspace = prepared['workspace']
        for prior in ('prepare-1',) + (('test-1',) if step == 'story-1' else ()):
            store.rows[prior]['status'] = 'closed'
            store.rows[prior]['metadata']['gc.outcome'] = 'pass'
        store.rows[step].update(status='in_progress', assignee='fixture-' + step)
        attempt = Attempt('session-' + step, 'incarnation-' + step, step)
        self.native_session_ports(attempt)
        kwargs.update(artifact_root=str(self.evidence))
        return store, attempt, kwargs

    def native_session_ports(self, attempt):
        import workspace_runtime as runtime
        def session_command(session_store, arguments, attempt=None):
            self.assertEqual(session_store.store_ref, 'city:fixture-city')
            self.assertTrue(arguments[0].startswith('--snapshot='))
            ids = arguments[0].partition('=')[2].split(',')
            return dict(schema_version='1', ok=True, store_ref=session_store.store_ref,
                        rows=[copy.deepcopy(self.sessions[i]) for i in ids])
        for patcher in (patch.object(WorkspaceStore, '_command', new=session_command),
                        patch.object(runtime, 'native_json', side_effect=self.registration),
                        patch.dict(os.environ, {'GC_SESSION_ID': attempt.session_id,
                                              'GC_INSTANCE_TOKEN': attempt.instance_token, 'GC_BEAD_ID': attempt.claimed_bead_id})):
            patcher.start(); self.addCleanup(patcher.stop)

    def test_native_same_member_dirty_test_continuation_makes_no_store_writes(self):
        store, attempt, kwargs = self.continuation_context()
        (Path(self.workspace['work_dir']) / 'tracked').write_text('failing test in progress\n')
        before, count = copy.deepcopy(store.rows), len(store.transactions)
        result = self.mod.manage_workspace(store, attempt, action='continue', authority_id='authority-1', **kwargs)
        self.assertEqual(result['path'], self.workspace['work_dir'])
        self.assertEqual(result['identity']['step_id'], 'test-1')
        self.assertEqual(result['launch_reference']['binding_step_id'], 'test-1')
        self.assertEqual(result['git_state'], 'dirty')
        self.assertFalse(result['accepted'])
        self.assertEqual(store.rows, before)
        self.assertEqual(len(store.transactions), count)

    def test_native_story_continuation_keeps_committed_partial_before_checkpoint(self):
        store, attempt, kwargs = self.continuation_context('story-1')
        head = self.change()
        before = copy.deepcopy(store.rows)
        result = self.mod.manage_workspace(store, attempt, action='continue', authority_id='authority-1', **kwargs)
        self.assertEqual(result['head'], head)
        self.assertEqual(result['commit_oids'], [head])
        self.assertEqual(result['workspace']['current_oid'], self.base)
        self.assertTrue(result['checkpoint_required'])
        self.assertEqual(store.rows, before)

    def test_native_continuation_refuses_wrong_owner_member_attempt_policy_generation_and_ref(self):
        store, attempt, kwargs = self.continuation_context()
        original = copy.deepcopy(store.rows)
        for fault in ('owner', 'member', 'attempt', 'policy', 'generation', 'ref', 'closed-member', 'dependency'):
            with self.subTest(fault=fault):
                store.rows = copy.deepcopy(original)
                invoking = attempt
                if fault == 'owner': store.rows['record-1']['metadata']['gc.worktree_owner'] = 'foreign'
                elif fault == 'member':
                    workspace = json.loads(store.rows['record-1']['metadata']['gc.workspace'])
                    workspace['active_member_id'] = 'foreign'
                    store.rows['record-1']['metadata']['gc.workspace'] = canonical_bytes(workspace).decode()
                elif fault == 'attempt': invoking = Attempt(attempt.session_id, 'foreign-incarnation', attempt.claimed_bead_id)
                elif fault == 'policy': store.rows['root-1']['metadata']['gc.var.worktree_checks'] = '{"required_checks":[{"argv":["false"],"id":"unit"}]}'
                elif fault == 'generation': store.rows['convoy-1']['metadata']['gc.source_generation'] = '2'
                elif fault == 'ref':
                    ref = json.loads(store.rows['test-1']['metadata']['gc.worktree_ref'])
                    ref['native_attempt_id'] = 'foreign'
                    store.rows['test-1']['metadata']['gc.worktree_ref'] = canonical_bytes(ref).decode()
                elif fault == 'closed-member': store.rows['member-1']['status'] = 'closed'
                else:
                    store.rows['prepare-1']['status'] = 'in_progress'
                before, count = copy.deepcopy(store.rows), len(store.transactions)
                with self.assertRaises(self.mod.CheckoutError) as refusal:
                    self.mod.manage_workspace(store, invoking, action='continue', authority_id='authority-1', **kwargs)
                self.assertTrue(Path(refusal.exception.evidence_path).is_file())
                self.assertEqual(store.rows, before)
                self.assertEqual(len(store.transactions), count)
                self.assertEqual(git(self.workspace['work_dir'], 'rev-parse', 'HEAD'), self.base)

    def test_original_source_rows_and_native_reference_race_refuse_before_provisioning(self):
        import workspace_cooked as cooked
        store, attempt, kwargs = self.managed_context()
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1')
        original.update(store.snapshot(list(store.rows)))
        store.rows['root-1']['revision'] = str(int(store.rows['root-1']['revision']) + 1)
        store.rows['root-1']['metadata']['gc.implementation_run_ref'] = '{"bead_id":"foreign","identity":["root-1"],"kind":"run"}'
        before = copy.deepcopy(store.rows)
        with patch.object(store, 'snapshot', wraps=store.snapshot) as observed:
            with self.assertRaisesRegex(self.mod.CheckoutError, 'changed after source selection'):
                self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'],
                    writer_map=writer_map, writer_rows=original, **kwargs)
        self.assertFalse(any('foreign' in call.args[0] for call in observed.call_args_list))
        self.assertEqual(store.rows, before)
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_original_source_typed_metadata_change_refuses_without_revision_change(self):
        import workspace_cooked as cooked
        store, attempt, kwargs = self.managed_context()
        store.rows['root-1']['metadata']['unrelated'] = True
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1')
        original.update(store.snapshot(list(store.rows)))
        store.rows['root-1']['metadata']['unrelated'] = 1
        before = copy.deepcopy(store.rows)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'changed after source selection'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'],
                writer_map=writer_map, writer_rows=original, **kwargs)
        self.assertEqual(canonical_bytes(store.rows), canonical_bytes(before))
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_late_source_revision_race_has_no_effect_and_does_not_launder_rows(self):
        store, attempt, kwargs = self.managed_context()
        record_before = copy.deepcopy(store.rows['record-1'])
        def race(request):
            row = store.rows['member-1']
            row['revision'] = str(int(row['revision']) + 1)
            row['metadata']['concurrent-input'] = 'preserved'
        store.before_apply = race
        with self.assertRaisesRegex(self.mod.CheckoutError, 'publication is unknown'):
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'], **kwargs)
        self.assertEqual(store.rows['record-1'], record_before)
        self.assertEqual(store.rows['member-1']['metadata']['concurrent-input'], 'preserved')
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_original_writer_rows_advance_only_from_own_exact_publication(self):
        import workspace_cooked as cooked
        store, attempt, kwargs = self.managed_context()
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1')
        original.update(store.snapshot(list(store.rows)))
        prior = copy.deepcopy(original)
        self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'],
                                  writer_map=writer_map, writer_rows=original, **kwargs)
        self.assertNotEqual(prior['member-1']['revision'], original['member-1']['revision'])
        self.assertEqual(original, store.snapshot(list(original)))
        self.assertEqual(original['run-record']['metadata']['gc.workspace_required_checks.v1'],
                         prior['run-record']['metadata']['gc.workspace_required_checks.v1'])

    def test_rejected_ack_does_not_advance_caller_originals(self):
        import workspace_cooked as cooked
        store, attempt, kwargs = self.managed_context()
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1')
        original.update(store.snapshot(list(store.rows)))
        prior = copy.deepcopy(original)
        def reject(prepared, resolved):
            raise RecordError('caller refused the exact acknowledgement')
        with self.assertRaisesRegex(self.mod.CheckoutError, 'acknowledgement is unresolved') as refusal:
            self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'],
                writer_map=writer_map, writer_rows=original, acknowledge=reject, **kwargs)
        self.assertEqual(canonical_bytes(original), canonical_bytes(prior))
        self.assertNotEqual(original['member-1']['revision'], store.rows['member-1']['revision'])
        self.assertTrue(Path(refusal.exception.request_path).is_file())
        self.assertTrue(list(Path(refusal.exception.request_path).parent.glob('*.pending')))
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def test_unknown_publication_does_not_advance_caller_originals(self):
        import workspace_cooked as cooked
        store, attempt, kwargs = self.managed_context()
        writer_map, original = cooked.read_cooked_writer_map(store, workflow_root_id='root-1', claimed_step_id='prepare-1')
        original.update(store.snapshot(list(store.rows)))
        prior = copy.deepcopy(original)
        with patch.object(store, 'resolve', return_value={'outcome': 'unknown'}):
            with self.assertRaisesRegex(self.mod.CheckoutError, 'publication is unknown') as refusal:
                self.mod.manage_workspace(store, attempt, action='prepare', authority_id='authority-1', launch_step_ids=['producer-1'],
                    writer_map=writer_map, writer_rows=original, **kwargs)
        self.assertEqual(canonical_bytes(original), canonical_bytes(prior))
        self.assertTrue(Path(refusal.exception.request_path).is_file())
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())

    def integration_input(self):
        inputs = []
        for name in ('a', 'b'):
            git(self.repo, 'checkout', '-b', 'input-' + name, self.base)
            (self.repo / name).write_text('accepted fixture ' + name + '\n')
            git(self.repo, 'add', name)
            git(self.repo, 'commit', '-qm', 'fixture input ' + name)
            inputs.append(dict(owner_id='owner-' + name, output_oid=git(self.repo, 'rev-parse', 'HEAD'),
                               workspace_output_sha256=hashlib.sha256(name.encode()).hexdigest()))
        git(self.repo, 'checkout', 'main')
        self.workspace.update(strategy='integration', integration_inputs=inputs)
        self.prepared()
        for item in inputs:
            git(self.workspace['work_dir'], 'merge', '--no-ff', '--no-edit', '-m', 'fixture accepted ' + item['owner_id'], item['output_oid'])
        merged = git(self.workspace['work_dir'], 'rev-parse', 'HEAD')
        self.workspace.update(phase='active', input_oid=merged, current_oid=merged)
        return merged

    def test_recorded_integration_input_allows_partial_linear_commit_without_advancement(self):
        merged = self.integration_input()
        entry = self.checkout().continuation()
        self.assertEqual(entry['head'], merged)
        self.assertFalse(entry['accepted'])
        head = self.change('C implementation partial\n')
        result = self.checkout().continuation()
        self.assertEqual(result['head'], head)
        self.assertEqual(result['commit_oids'], [head])
        self.assertEqual(result['workspace']['current_oid'], merged)
        self.assertTrue(result['checkpoint_required'])

    def test_integration_continuation_refuses_rewind_and_foreign_native_owner(self):
        merged = self.integration_input()
        original = copy.deepcopy(self.workspace)
        self.workspace['native_provenance']['owner'] = 'foreign'
        with self.assertRaisesRegex(self.mod.CheckoutError, 'provenance'):
            self.checkout().continuation()
        self.workspace = original
        git(self.workspace['work_dir'], 'reset', '--hard', self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'rewound'):
            self.checkout().continuation()
        self.assertEqual(git(self.workspace['work_dir'], 'rev-parse', 'HEAD'), self.base)
        self.assertEqual(self.workspace['current_oid'], merged)

    def test_integration_continuation_refuses_unfinished_merge_state(self):
        self.integration_input()
        marker = Path(git(self.workspace['work_dir'], 'rev-parse', '--absolute-git-dir')) / 'MERGE_HEAD'
        marker.write_text(self.base)
        with self.assertRaisesRegex(self.mod.CheckoutError, 'Git operation'):
            self.checkout().continuation()
        self.assertEqual(marker.read_text(), self.base)

    def bridge_context(self):
        from workspace_store import GRANT_REFS_KEY
        store, attempt, kwargs = self.managed_context()
        store.rows['root-1']['metadata'].update({'gc.var.worktree_parent': str(self.parent),
                                               'gc.var.worktree_allow_external_parent': 'true'})
        store.rows['record-1']['metadata'].clear()
        store.rows['authority-1']['metadata'].clear()
        store.rows['owner-1']['metadata'].pop('gc.workspace_ref')
        store.rows['root-1']['metadata'].pop(GRANT_REFS_KEY)
        self.native_session_ports(attempt)
        store.transactions.clear()
        arguments = {key: kwargs[key] for key in ('gc', 'city_root', 'rig_name', 'workflow_root_id', 'input_convoy_id',
                                                   'evidence_dir', 'parent', 'allow_external_parent')}
        arguments.update(generation=1, workspace_owner_id='owner-1', member_id='member-1',
            artifact_root=str(self.evidence), workspace_record_id='record-1', authority_id='authority-1',
            launch_step_ids=['test-1', 'story-1', 'producer-1', 'recorder-1'])
        return store, attempt, arguments

    def test_actual_dependency_bridge_creates_first_payload_ref_grant_and_prepares_input(self):
        from workspace_dependency import prepare_dependency_workspace
        store, attempt, arguments = self.bridge_context()
        result = prepare_dependency_workspace(store, attempt, **arguments)
        self.assertEqual(result['state'], 'prepared')
        self.assertEqual(result['workspace']['phase'], 'active')
        self.assertEqual(result['input_oid'], self.base)
        self.assertEqual(result['path'], result['workspace']['work_dir'])
        self.assertEqual(Path(result['path']).parent, self.parent)
        self.assertEqual(store.rows['record-1']['metadata']['gc.work_dir'], result['path'])
        self.assertTrue(all(receipt['outcome'] in ('committed', 'replayed') for receipt in result['receipts']))
        first = store.transactions[0]
        self.assertIn(GRANT_KEY, first.after['authority-1']['metadata'])
        self.assertIn('gc.workspace', first.after['record-1']['metadata'])
        self.assertIn('gc.workspace_ref', first.after['owner-1']['metadata'])
        self.assertEqual(first.record_kinds, ['workspace'])

    def test_actual_dependency_bridge_missing_immutable_policy_refuses_without_effect(self):
        from workspace_dependency import prepare_dependency_workspace
        from workspace_records import RecordError
        store, attempt, arguments = self.bridge_context()
        store.rows['run-record']['metadata'].pop('gc.workspace_required_checks.v1')
        before = copy.deepcopy(store.rows)
        with self.assertRaisesRegex(RecordError, 'policy'):
            prepare_dependency_workspace(store, attempt, **arguments)
        self.assertEqual(store.rows, before)
        self.assertFalse(store.transactions)
        self.assertFalse(self.log.exists())
        self.assertFalse(Path(self.workspace['work_dir']).exists())


if __name__ == '__main__':
    unittest.main()
