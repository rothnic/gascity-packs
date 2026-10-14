#!/usr/bin/env python3
"""Prepare and resume recorded workspaces through native ensure/verify only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from workspace_records import (RecordError, canonical_bytes, parse_record,
                               record_identity, validate_record, verify_replay)

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z')
OID = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')
CREATOR = 'gascity.workspace.v1'
OPERATIONS = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'REBASE_HEAD',
              'BISECT_LOG', 'BISECT_START', 'rebase-merge', 'rebase-apply', 'sequencer',
              'index.lock', 'HEAD.lock', 'ORIG_HEAD.lock')
OWNERSHIP = {'gc.worktree_repo': 'repo', 'gc.worktree_root': 'root', 'gc.work_dir': 'path',
             'gc.work_branch': 'branch', 'gc.worktree_base_ref': 'base',
             'gc.worktree_base_sha': 'base-sha', 'gc.worktree_creator': 'creator',
             'gc.worktree_owner': 'owner', 'gc.worktree_generation': 'generation',
             'gc.worktree_lifecycle': 'lifecycle', 'gc.worktree_mode': 'mode'}


class CheckoutError(RecordError):
    def __init__(self, message, evidence_path=None):
        super().__init__(message)
        self.evidence_path = evidence_path


def canonical_path(value: str, *, directory=False) -> Path:
    if (not isinstance(value, str) or not value.startswith('/')
            or re.search(r'[\x00-\x1f\x7f]', value) or any(p in ('.', '..') for p in value.split('/'))):
        raise CheckoutError('path must be absolute without traversal or controls')
    path = Path(value)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise CheckoutError('symlink path components are refused')
        if part.exists() and not part.is_dir():
            raise CheckoutError('path has a non-directory collision')
    if str(path) != value:
        raise CheckoutError('path must have canonical spelling')
    if directory and not path.is_dir():
        raise CheckoutError('configured directory must already exist')
    return path


def git_environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    for key in ('GC_CITY_URL', 'GC_CITY_CONTEXT', 'GC_CITY', 'GC_CITY_PATH', 'GC_CITY_ROOT', 'GC_RIG'):
        env.pop(key, None)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    return env


def git(root: Path | str, *args: str, optional=False) -> str | None:
    try:
        result = subprocess.run(['git', '-C', str(root), *args], env=git_environment(),
                                capture_output=True, text=True, timeout=10)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise CheckoutError(f'Git observation unavailable: {exc}') from exc
    if result.returncode:
        if optional and result.returncode == 128:
            return None
        raise CheckoutError('Git observation failed: ' + result.stderr.strip()[-2000:])
    return result.stdout.rstrip('\n')


def registrations(repo: Path | str) -> list[dict]:
    result = []
    for field in git(repo, 'worktree', 'list', '--porcelain', '-z').split('\0'):
        if field.startswith('worktree '):
            result.append({'path': field[9:]})
        elif field and result:
            key, _, value = field.partition(' ')
            result[-1][key] = value or True
    return result


def diagnostic_directory(value: str) -> Path:
    path = canonical_path(value, directory=True)
    if any((ancestor / '.git').exists() or (ancestor / '.git').is_symlink() for ancestor in (path, *path.parents)):
        raise CheckoutError('evidence directory must be outside all worktrees')
    if git(path, 'rev-parse', '--git-common-dir', optional=True) is not None:
        raise CheckoutError('evidence directory must be outside all worktrees')
    return path


def save_diagnostic(directory: Path, evidence: dict) -> str:
    with tempfile.NamedTemporaryFile(mode='wb', prefix='workspace-blocker-', suffix='.json',
                                     dir=directory, delete=False) as handle:
        handle.write(canonical_bytes(evidence) + b'\n')
        handle.flush()
        os.fsync(handle.fileno())
        name = handle.name
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return name



class WorkspaceCheckout:
    """Component engine. Durable publication is performed by manage_workspace."""
    def __init__(self, run: dict, workspace: dict, *, store_ref: str, evidence_dir: str,
                 parent: str | None = None, allow_external_parent=False, gc='gc',
                 city_root: str | None = None, timeout=15, lock_timeout=2):
        self.run, self.workspace = copy.deepcopy(run), copy.deepcopy(workspace)
        self.gc, self.city_root = gc, city_root
        self.timeout, self.lock_timeout = timeout, lock_timeout
        self.last_native = None
        self.last_observation = None
        # Establish a safe diagnostic sink before parsing mutable source state.
        self.evidence_dir = diagnostic_directory(evidence_dir)
        try:
            validate_record('run', self.run)
            validate_record('workspace', self.workspace)
            self.require(self.run['worktree_lifecycle'] == 'new', 'explicit new rollout selection is required')
            self.require(self.run['workflow_root_id'] == self.workspace['workflow_root_id'], 'workspace belongs to a foreign run')
            self.require(self.workspace['active_member_id'] is not None, 'workspace requires an exact active member')
            if self.workspace['phase'] == 'preparing':
                self.require(self.workspace['input_oid'] == self.workspace['current_oid'] and self.workspace['output_oid'] is None,
                             'preparing workspace has unexplained source state')
            self.require(isinstance(store_ref, str) and re.fullmatch(r'(?:city|rig):[A-Za-z0-9][A-Za-z0-9._-]*', store_ref), 'exact native store identity is required')
            self.store_ref = store_ref
            for field in ('workflow_root_id', 'source_plan_owner_id', 'workspace_owner_id', 'workspace_bead_id', 'writer_step_id', 'writer_attempt_id'):
                self.require(bool(ID.fullmatch(self.workspace[field])) and self.workspace[field] not in ('.', '..'), f'unsafe {field}')
            self.require(type(allow_external_parent) is bool, 'external parent selection must be a boolean')
            self.require(type(lock_timeout) is int and type(timeout) is int and 0 < lock_timeout < timeout <= 120,
                         'native and lock timeouts must be positive bounded integers')
            self.repo = canonical_path(self.run['rig_root'], directory=True)
            self.common = canonical_path(self.run['common_git_dir'], directory=True)
            self.require(git(self.repo, 'rev-parse', '--path-format=absolute', '--git-common-dir') == str(self.common), 'common Git directory identity changed')
            bare = git(self.repo, 'rev-parse', '--is-bare-repository')
            self.require(bare in ('true', 'false'), 'unknown repository layout')
            if bare == 'true':
                self.require(self.common in (self.repo, self.repo / '.git'), 'bare control root identity changed')
            else:
                self.require(git(self.repo, 'rev-parse', '--show-toplevel') == str(self.repo), 'registered rig root identity changed')
            self.path_value = canonical_path(self.workspace['work_dir'])
            default_parent = self.repo / ('workspaces' if self.common == self.repo else 'worktrees')
            self.parent = canonical_path(parent or str(default_parent), directory=parent is not None and Path(parent) != default_parent)
            self.require(self.path_value.parent == self.parent and self.path_value.name not in ('.git', '.gc', '.beads'), 'workspace path must be a safe direct child of the selected parent')
            if self.common == self.repo:
                relative = self.path_value.relative_to(self.repo) if self.path_value.is_relative_to(self.repo) else None
                self.require(relative is None or (relative.parts and relative.parts[0] not in
                             ('objects', 'refs', 'hooks', 'info', 'logs', 'branches', 'worktrees')),
                             'workspace path is inside bare Git administration')
            else:
                self.require(not self.path_value.is_relative_to(self.common), 'workspace path is inside Git administration')
            self.require(self.parent.is_relative_to(self.repo) or allow_external_parent, 'external workspace parent requires explicit permission')
            nested_control = any(Path(r['path']) == self.repo and self.path_value.is_relative_to(self.repo)
                                 for r in registrations(self.repo))
            self.placement = 'within-repo-root' if nested_control else 'outside-worktrees'
            self.require(not self.evidence_dir.is_relative_to(self.repo) and not self.evidence_dir.is_relative_to(self.common)
                         and not self.evidence_dir.is_relative_to(self.path_value), 'evidence directory must be outside managed worktrees and repository administration')
            self._layout()
            provenance = self.workspace['native_provenance']
            self.require((provenance is None) == (self.workspace['native_attempt_id'] is None), 'partial native provenance metadata')
            self.require(provenance is None or isinstance(provenance, dict), 'malformed native provenance')
            self.native_base = provenance.get('base_sha') if provenance else self.workspace['input_oid']
            self.require(isinstance(self.native_base, str) and bool(OID.fullmatch(self.native_base)), 'native base must be the full recorded input OID')
            self.require(git(self.repo, 'cat-file', '-t', self.native_base) == 'commit', 'recorded native input is not a commit')
            self.require(git(self.repo, 'cat-file', '-t', self.workspace['input_oid']) == 'commit', 'recorded member input is not a commit')
            branch = self.workspace['work_branch'] or ''
            self.mode = 'attached' if branch else 'detached'
            if branch:
                self.require(not branch.startswith('-'), 'unsafe work branch')
                git(self.repo, 'check-ref-format', '--branch', branch)
            self.spec = dict(repo=str(self.repo), root=str(self.parent), path=str(self.path_value), branch=branch,
                             mode=self.mode, base=self.native_base, bead=self.workspace['workspace_bead_id'],
                             creator=CREATOR, owner=self.workspace['workspace_owner_id'],
                             generation=str(self.workspace['generation']), lifecycle='active')
            self.spec.update({'base-sha': self.native_base, 'store-ref': store_ref})
            if provenance:
                self._provenance(provenance)
        except (RecordError, OSError, UnicodeError) as exc:
            if isinstance(exc, CheckoutError) and exc.evidence_path:
                raise
            self.fail(str(exc))

    def fail(self, message: str):
        evidence = {'version': 1, 'state': 'blocked', 'reason': message,
                    'workspace': self.workspace, 'git': self.last_observation, 'native': self.last_native}
        name = save_diagnostic(self.evidence_dir, evidence)
        raise CheckoutError(message, name)

    def require(self, condition: Any, message: str):
        if not condition:
            self.fail(message)

    def _layout(self):
        records = registrations(self.repo)
        matches = [r for r in records if r['path'] == str(self.path_value)]
        self.require(len(matches) <= 1, 'ambiguous workspace registration')
        self.require(not matches or not any(k in matches[0] for k in ('prunable', 'bare', 'locked')), 'foreign, locked or prunable registration')
        for registration in records:
            location = Path(registration['path'])
            self.require(not self.evidence_dir.is_relative_to(location), 'evidence directory is inside a registered worktree')
            if location not in (self.repo, self.path_value):
                self.require(not self.path_value.is_relative_to(location), 'workspace is nested in another linked worktree')
        for ancestor in (self.parent, *self.parent.parents):
            if not ancestor.is_dir():
                continue
            common = git(ancestor, 'rev-parse', '--path-format=absolute', '--git-common-dir', optional=True)
            if common is not None:
                self.require(common == str(self.common), 'workspace parent is inside a foreign repository')
                break

    def _command(self, action: str, *, help_only=False) -> dict | str:
        argv = [str(self.gc)]
        if self.city_root is not None:
            argv += ['--city=' + str(canonical_path(self.city_root, directory=True))]
        argv += ['worktree', action]
        if help_only:
            argv += ['--help']
        else:
            argv += ['--' + k + '=' + v for k, v in self.spec.items()]
            if self.placement != 'outside-worktrees':
                argv += ['--placement=' + self.placement]
            if action == 'ensure':
                argv += ['--lock-timeout=' + str(self.lock_timeout) + 's']
            argv += ['--json']
        try:
            response = subprocess.run(argv, cwd=self.repo, env=git_environment(), capture_output=True,
                                      text=True, timeout=self.timeout)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            self.last_native = {'argv': argv, 'outcome': 'unknown', 'error': str(exc)}
            self.fail('native command outcome unknown; reobserve before any retry')
        self.last_native = {'argv': argv, 'returncode': response.returncode,
                            'stdout': response.stdout, 'stderr': response.stderr}
        self.require(response.returncode == 0, 'native worktree ' + action + ' failed')
        if help_only:
            return response.stdout
        try:
            report = parse_record(response.stdout)
        except RecordError as exc:
            self.fail('malformed native worktree report: ' + str(exc))
        self.require(not report.get('planned'), 'native worktree returned a plan instead of observed evidence')
        if action == 'verify':
            self.require(report.get('created') is False and report.get('branch_created') is False, 'native verify reported mutation')
        self.require(report.get('schema_version') == '1' and report.get('ok') is True
                     and report.get('command') == 'worktree ' + action and report.get('action') == action,
                     'unsupported native worktree report')
        self.require(all(report.get(k) == v for k, v in {'path': str(self.path_value), 'branch': self.spec['branch'],
                     'mode': self.mode, 'placement': self.placement}.items()), 'native worktree report identity mismatch')
        self.require(type(report.get('created')) is bool and type(report.get('branch_created')) is bool,
                     'native creation evidence is incomplete')
        self.require(self.mode != 'detached' or report['branch_created'] is False, 'detached provisioning created a branch')
        self.require(isinstance(report.get('head'), str) and bool(OID.fullmatch(report['head'])), 'native report has no full HEAD OID')
        self._provenance(report.get('provenance'))
        stored = self.workspace['native_provenance']
        if stored is not None:
            self.require(report['provenance'] == stored, 'native provisioning attempt or full provenance changed')
        return report

    def _provenance(self, provenance):
        expected = {'schema_version': 2, 'bead_id': self.spec['bead'], 'store_ref': self.store_ref,
                    'repo_identity': str(self.common), 'path': str(self.path_value), 'branch': self.spec['branch'],
                    'mode': self.mode, 'placement': self.placement, 'base_ref': self.native_base,
                    'base_sha': self.native_base, 'creator': CREATOR, 'owner': self.spec['owner'],
                    'generation': self.spec['generation'], 'lifecycle': 'active'}
        self.require(isinstance(provenance, dict) and all(type(provenance.get(k)) is type(v) and provenance[k] == v
                     for k, v in expected.items()), 'native provenance does not match recorded ownership and input')
        self.require(isinstance(provenance.get('attempt_id'), str) and bool(ID.fullmatch(provenance['attempt_id']))
                     and isinstance(provenance.get('created_at'), str) and bool(provenance['created_at']), 'native attempt evidence is incomplete')
        if self.workspace['native_attempt_id'] is not None:
            self.require(provenance['attempt_id'] == self.workspace['native_attempt_id'], 'native provisioning attempt changed')

    def _capabilities(self, action: str):
        help_text = self._command(action, help_only=True)
        flags = set(re.findall(r'--([a-z][a-z-]+)\b', help_text))
        required = set(self.spec) | {'json'}
        if action == 'ensure': required.add('lock-timeout')
        if self.placement != 'outside-worktrees': required.add('placement')
        self.require(required <= flags, 'native contract lacks required flags: ' + ', '.join(sorted(required - flags)))

    def observe(self, *, purpose='checkpoint') -> dict:
        self.require(purpose in ('checkpoint', 'continuation'), 'unknown Git observation purpose')
        self._layout()
        entries = [r for r in registrations(self.repo) if r['path'] == str(self.path_value)]
        self.last_observation = {'path': str(self.path_value), 'registrations': entries}
        if not self.path_value.exists():
            self.require(not entries, 'absent path still has a Git registration')
            return {'state': 'absent', 'head': None, 'git_state': 'absent'}
        self.require(len(entries) == 1, 'existing path lacks exact repository registration')
        self.require(git(self.path_value, 'rev-parse', '--show-toplevel') == str(self.path_value), 'path is not the registered checkout root')
        self.require(git(self.path_value, 'rev-parse', '--path-format=absolute', '--git-common-dir') == str(self.common), 'workspace common Git directory mismatch')
        gitdir = canonical_path(git(self.path_value, 'rev-parse', '--absolute-git-dir'), directory=True)
        head = git(self.path_value, 'rev-parse', '--verify', 'HEAD^{commit}')
        operations = [name for name in OPERATIONS if (gitdir / name).exists() or (gitdir / name).is_symlink()]
        operations += ['common/' + name for name in ('packed-refs.lock', 'config.lock', 'shallow.lock')
                       if (self.common / name).exists() or (self.common / name).is_symlink()]
        dirty = git(self.path_value, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--ignore-submodules=none')
        self.last_observation.update(head=head, operations=operations, status=dirty)
        self.require(not operations, 'active Git operation is preserved: ' + ', '.join(operations))
        if purpose == 'checkpoint':
            self.require(not dirty, 'dirty worktree is preserved')
        self.require(bool(OID.fullmatch(head)), 'workspace has an invalid HEAD')
        symbolic = subprocess.run(['git', '-C', str(self.path_value), 'symbolic-ref', '-q', 'HEAD'],
                                  env=git_environment(), capture_output=True, text=True, timeout=10)
        self.require((self.mode == 'detached' and symbolic.returncode == 1 and not symbolic.stderr)
                     or (self.mode == 'attached' and symbolic.returncode == 0
                         and symbolic.stdout.strip() == 'refs/heads/' + self.spec['branch']), 'workspace HEAD mode or branch changed')
        return {'state': 'registered', 'head': head, 'git_state': 'dirty' if dirty else 'clean',
                'status': dirty}

    def _verified(self, *, purpose='checkpoint') -> dict:
        self._capabilities('verify')
        report = self._command('verify')
        observation = self.observe(purpose=purpose)
        self.require(observation['head'] == report['head'], 'HEAD changed during native verification')
        git(self.path_value, 'merge-base', '--is-ancestor', self.native_base, report['head'])
        return report

    def continuation(self) -> dict:
        """Observe partial work. Native claim admission belongs to the caller."""
        self.require(self.workspace['phase'] in ('entry', 'active'),
                     'continuation requires an unfinished member, before result/checkpoint advancement')
        self.require(self.workspace['native_provenance'] is not None and self.workspace['output_oid'] is None,
                     'continuation lacks its retained native input and attempt')
        report = self._verified(purpose='continuation')
        commits = git(self.path_value, 'rev-list', '--reverse', '--topo-order',
                      self.workspace['current_oid'] + '..' + report['head']).splitlines()
        chain = self.workspace['current_oid']
        for commit in commits:
            self.require(git(self.path_value, 'rev-list', '--parents', '-n', '1', commit).split() == [commit, chain],
                         'partial HEAD is not an owned linear descendant of the recorded checkpoint')
            chain = commit
        self.require(chain == report['head'], 'partial HEAD rewound or differs from the recorded checkpoint')
        git(self.path_value, 'merge-base', '--is-ancestor', self.workspace['input_oid'], report['head'])
        result = self._result(report)
        result.update(state='continuation', git_state='dirty' if self.last_observation['status'] else 'clean',
                      checkpoint_required=True, accepted=False, commit_oids=commits)
        return result

    def _result(self, report: dict, workspace: dict | None = None) -> dict:
        workspace = copy.deepcopy(workspace or self.workspace)
        owner = {key: self.spec[flag] for key, flag in OWNERSHIP.items()}
        owner.update({'gc.worktree_placement': self.placement, 'gc.root_bead_id': workspace['workflow_root_id'],
                      'gc.root_store_ref': self.store_ref})
        reference = dict(version=1, binding_step_id=workspace['writer_step_id'],
                         workflow_root_id=workspace['workflow_root_id'], generation=workspace['generation'],
                         workspace_owner_id=workspace['workspace_owner_id'], workspace_bead_id=workspace['workspace_bead_id'],
                         store_ref=self.store_ref, native_attempt_id=report['provenance']['attempt_id'])
        return {'ok': True, 'evidence_level': 'component', 'path': str(self.path_value), 'head': report['head'],
                'workspace': workspace, 'native_report': report, 'owner_metadata': owner, 'launch_reference': reference}

    def prepare(self) -> dict:
        self.require(self.workspace['phase'] in ('preparing', 'entry'), 'prepare only admits preparing or entry state')
        try:
            self.require(self.workspace['phase'] != 'entry' or self.workspace['native_provenance'] is not None,
                         'entry is missing recorded native metadata')
            observation = self.observe()
            if observation['state'] == 'absent':
                self.require(self.workspace['phase'] == 'preparing' and self.workspace['native_provenance'] is None,
                             'registered workspace unexpectedly disappeared')
                self._capabilities('ensure')
                # Check verify support before provisioning, too.
                self._capabilities('verify')
                report = self._command('ensure')
                self.require(report['head'] == self.workspace['input_oid'], 'first entry must equal recorded input')
                verified = self._verified()
                self.require(verified['provenance'] == report['provenance'], 'provisioning changed before entry')
                report = verified
            else:
                self.require(observation['head'] == self.workspace['input_oid'], 'entry HEAD must equal recorded input')
                report = self._verified()
            self.require(report['head'] == self.workspace['input_oid'] == self.workspace['current_oid'],
                         'entry must equal the exact recorded member input')
            workspace = dict(self.workspace, phase='entry', native_attempt_id=report['provenance']['attempt_id'],
                             native_provenance=report['provenance'])
            validate_record('workspace', workspace)
            return self._result(report, workspace)
        except CheckoutError as exc:
            if exc.evidence_path: raise
            self.fail(str(exc))

    def verify(self) -> dict:
        self.require(self.workspace['phase'] in ('entry', 'active', 'result'), 'workspace phase cannot resume')
        try:
            self.require(self.workspace['native_provenance'] is not None, 'registered workspace is missing native metadata')
            report = self._verified()
            self.require(report['head'] == self.workspace['current_oid'], 'unexplained advanced or unrelated HEAD is preserved')
            if self.workspace['phase'] == 'entry':
                self.require(report['head'] == self.workspace['input_oid'], 'entry differs from exact input')
            if self.workspace['phase'] == 'result':
                self.require(report['head'] == self.workspace['output_oid'], 'result differs from recorded output')
            return self._result(report)
        except CheckoutError as exc:
            if exc.evidence_path: raise
            self.fail(str(exc))

    def path(self) -> str:
        return self.verify()['path']

    def status(self) -> dict:
        try:
            if self.workspace['phase'] == 'preparing':
                observation = self.observe()
                self.require(observation['head'] in (None, self.workspace['input_oid']), 'unexpected preparing HEAD')
                self.require(observation['head'] is not None or self.workspace['native_provenance'] is None,
                             'preparing workspace lost its recorded native attempt')
                if observation['head'] is not None: self._verified()
                return {'ok': True, **observation, 'phase': 'preparing', 'evidence_level': 'component'}
            return self.verify()
        except CheckoutError as exc:
            if exc.evidence_path is None:
                try: self.fail(str(exc))
                except CheckoutError as recorded: exc = recorded
            return {'ok': False, 'state': 'blocked', 'reason': str(exc), 'evidence_path': exc.evidence_path}

    def recover(self, *, member_id: str, result: dict | None = None, result_unrecorded=False,
                writer_step_id: str | None = None) -> dict:
        self.require(member_id == self.workspace['active_member_id'], 'recovery member differs from active member')
        if self.workspace['phase'] in ('preparing', 'entry'):
            self.require(result is None and not result_unrecorded, 'result declaration conflicts with preparation')
            return self.prepare()
        self.require(self.workspace['phase'] in ('active', 'result'), 'unknown workspace phase is preserved')
        if result is None:
            self.require(not result_unrecorded, 'unrecorded result requires an explicit exact declaration')
            return self.verify()
        try:
            validate_record('member-result', result)
            for field in ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id'):
                self.require(result[field] == self.workspace[field], 'result belongs to a foreign workspace')
            self.require(result['member_id'] == member_id and result['input_oid'] == self.workspace['input_oid'], 'result active member or input changed')
            if result_unrecorded or writer_step_id is not None:
                self.require(writer_step_id is not None and result['writer_step_id'] == writer_step_id,
                             'result must name its exact admitted native producer step')
            self.require(self.workspace['native_provenance'] is not None, 'result recovery lacks recorded native provenance')
            report = self._verified()
            self.require(report['head'] == result['output_oid'], 'result output differs from exact HEAD')
            commits = git(self.path_value, 'rev-list', '--reverse', '--topo-order', result['input_oid'] + '..' + report['head']).splitlines()
            self.require(commits == result['commit_oids'], 'result commits differ from the declared linear output')
            chain = result['input_oid']
            for commit in commits:
                parents = git(self.path_value, 'rev-list', '--parents', '-n', '1', commit).split()
                self.require(parents == [commit, chain], 'result is not an owned linear descendant')
                chain = commit
            self.require(chain == report['head'], 'result is unrelated to the recorded input')
            if self.workspace['phase'] == 'result':
                self.require(self.workspace['current_oid'] == self.workspace['output_oid'] == report['head'], 'checkpoint differs from result')
                return self._result(report)
            self.require(self.workspace['current_oid'] == result['input_oid'] and self.workspace['output_oid'] is None,
                         'checkpoint-pending state is inconsistent')
            workspace = dict(self.workspace, phase='result', current_oid=report['head'], output_oid=report['head'])
            output = self._result(report, workspace)
            output['member_result'] = copy.deepcopy(result)
            output['record_result'] = bool(result_unrecorded)
            return output
        except (RecordError, OSError) as exc:
            if isinstance(exc, CheckoutError) and exc.evidence_path: raise
            self.fail(str(exc))


def _record(row: dict, kind: str) -> dict:
    from workspace_records import contracts
    value = row['metadata'].get(contracts()[kind]['metadata_key'])
    if not isinstance(value, str):
        raise CheckoutError(f'missing durable {kind} record')
    return validate_record(kind, parse_record(value))


def _reference(raw: Any, kind: str, bead_id: str, record: dict) -> dict:
    expected = {'kind': kind, 'bead_id': bead_id, 'identity': list(record_identity(kind, record))}
    if not isinstance(raw, str) or parse_record(raw) != expected:
        raise CheckoutError(f'exact {kind} physical record reference changed')
    return expected


def _retain_rows(rows: dict, incoming: dict) -> None:
    """Keep original full snapshots, including revisions and absent metadata."""
    if not isinstance(incoming, dict) or any(not isinstance(row, dict) or row.get('id') != key
                                              for key, row in incoming.items()):
        raise CheckoutError('original native rows must contain exact physical IDs')
    for key, row in incoming.items():
        if key in rows and rows[key] != row:
            raise CheckoutError('native row changed after source selection: ' + key)
        rows.setdefault(key, copy.deepcopy(row))
    if len(rows) > 100:
        raise CheckoutError('complete original native rows exceed the guarded batch bound')


def load_workspace_context(store, *, gc: str, city_root: str, rig_name: str,
                           workflow_root_id: str, input_convoy_id: str,
                           run_record_id: str, plan_record_id: str, workspace_record_id: str,
                           claimed_step_id: str | None = None, extra_ids=(), require_live=True,
                           writer_map=None, writer_rows=None, source_rows=None,
                           record_kind='workspace') -> tuple[dict, dict, dict, dict]:
    """Read only; no initial base selection or missing-record adoption is allowed."""
    from workspace_entry import read_entry, healthy, native_root
    from workspace_source_plan import source_node_ids, validate_source_plan

    if not claimed_step_id:
        raise CheckoutError('recorded entry requires the exact invoking native claimed step')
    ids = list(dict.fromkeys([workflow_root_id, run_record_id, plan_record_id, workspace_record_id,
                              claimed_step_id, *extra_ids]))
    rows = {}
    for original in (writer_rows, source_rows):
        if original is not None:
            _retain_rows(rows, original)
    _retain_rows(rows, store.snapshot(ids))
    workspace = _record(rows[workspace_record_id], 'workspace')
    entry = read_entry(store, gc=gc, city_root=city_root, rig_name=rig_name,
                       workflow_root_id=workflow_root_id, claimed_step_id=claimed_step_id,
                       worktree_lifecycle='new', generation=workspace['generation'],
                       input_convoy_id=input_convoy_id, require_plan=True)
    run, plan = entry['run'], entry['source_plan']
    verify_replay('run', _record(rows[run_record_id], 'run'), run)
    verify_replay('source-plan', _record(rows[plan_record_id], 'source-plan'), plan)
    if (workspace['workflow_root_id'] != workflow_root_id or plan['workflow_root_id'] != workflow_root_id
            or workspace['generation'] != plan['generation']
            or workspace['source_plan_owner_id'] != plan['source_plan_owner_id']
            or workspace['workspace_bead_id'] != workspace_record_id
            or entry['input_convoy_id'] != input_convoy_id or entry['store_ref'] != store.store_ref):
        raise CheckoutError('workspace/plan/run/current convoy logical or physical identity changed')
    needed = list(dict.fromkeys([run['input_convoy_id'], run['source_anchor_id'], input_convoy_id,
                                 plan['source_plan_owner_id'], workspace['workspace_owner_id'], *source_node_ids(plan)]))
    root = rows[workflow_root_id]
    canonical_ref = None
    if workspace['generation'] > 1:
        raw = root['metadata'].get('gc.canonical_ref')
        if not isinstance(raw, str):
            raise CheckoutError('fix generation has no exact canonical reference')
        canonical_ref = parse_record(raw)
        if canonical_ref.get('kind') != 'canonical' or not isinstance(canonical_ref.get('bead_id'), str):
            raise CheckoutError('malformed canonical reference')
        needed.append(canonical_ref['bead_id'])
    missing = [i for i in dict.fromkeys(needed) if i not in rows]
    if missing: _retain_rows(rows, store.snapshot(missing))
    # Revalidate the frozen native rows rather than replacing their revisions
    # with later reads from the entry helper.
    for row in (root, rows[claimed_step_id], rows[run['input_convoy_id']], rows[run['source_anchor_id']], rows[input_convoy_id]):
        healthy(row)
    if (root['metadata'].get('gc.kind') != 'workflow'
            or root['metadata'].get('gc.root_store_ref') != store.store_ref
            or root['metadata'].get('gc.input_convoy_id') != input_convoy_id
            or (require_live and root['status'] == 'closed')):
        raise CheckoutError('frozen workflow root/current convoy is stale or ineligible')
    step = rows[claimed_step_id]
    if (native_root(step) != workflow_root_id or step['metadata'].get('gc.root_store_ref') != store.store_ref
            or step['status'] != 'in_progress' or not step['assignee']):
        raise CheckoutError('frozen invoking step is no longer claimed for this root/store')
    for row in (rows[run['input_convoy_id']], rows[run['source_anchor_id']]):
        if (native_root(row) not in (None, workflow_root_id)
                or any(row['metadata'][k] != store.store_ref for k in ('gc.root_store_ref', 'gc.source_store_ref') if k in row['metadata'])):
            raise CheckoutError('original captured source changed native root/store')
    if (rows[run['input_convoy_id']]['type'] != 'convoy'
            or rows[run['source_anchor_id']]['metadata'].get('gc.synthetic') == 'true'):
        raise CheckoutError('original captured source identity changed')
    convoy = rows[input_convoy_id]
    if (convoy['type'] != 'convoy' or native_root(convoy) != workflow_root_id
            or convoy['metadata'].get('gc.root_store_ref') != store.store_ref
            or convoy['metadata'].get('gc.source_root_id') != workflow_root_id
            or convoy['metadata'].get('gc.source_generation') != str(workspace['generation'])
            or convoy['metadata'].get('gc.source_plan_owner_id') != plan['source_plan_owner_id']):
        raise CheckoutError('current implementation convoy root/store/generation/plan owner changed')
    run_ref = _reference(root['metadata'].get('gc.implementation_run_ref'), 'run', run_record_id, run)
    plan_ref = _reference(rows[plan['source_plan_owner_id']]['metadata'].get('gc.source_plan_ref'), 'source-plan', plan_record_id, plan)
    if entry['run_reference'] != run_ref or entry['source_plan_reference'] != plan_ref:
        raise CheckoutError('entry reader observed a different exact run/plan reference')
    from workspace_run import CHECKS_CONFIG_KEY, CHECKS_POLICY_KEY, capture_check_policy
    policy = capture_check_policy(run, run_record_id, root['metadata'].get(CHECKS_CONFIG_KEY))
    if (entry.get('check_policy') != policy
            or rows[run_record_id]['metadata'].get(CHECKS_POLICY_KEY) != canonical_bytes(policy).decode()):
        raise CheckoutError('frozen required-check policy differs from the initial native run/configuration')
    from workspace_records import record_sha256
    if (entry['run_sha256'] != record_sha256(run) or entry['source_plan_sha256'] != record_sha256(plan)
            or root['metadata'].get('gc.implementation_run_sha256', entry['run_sha256']) != entry['run_sha256']
            or convoy['metadata'].get('gc.source_plan_sha256', entry['source_plan_sha256']) != entry['source_plan_sha256']):
        raise CheckoutError('entry run/plan digest differs from the frozen native binding')
    canonical = _record(rows[canonical_ref['bead_id']], 'canonical') if canonical_ref else None
    if canonical_ref:
        _reference(root['metadata']['gc.canonical_ref'], 'canonical', canonical_ref['bead_id'], canonical)
    validate_source_plan(plan, run, rows, store_ref=store.store_ref, canonical=canonical, stored=plan)
    _reference(rows[workspace['workspace_owner_id']]['metadata'].get('gc.workspace_ref'), 'workspace', workspace_record_id, workspace)
    nodes = [n for n in plan['nodes'] if n['owner_id'] == workspace['workspace_owner_id']]
    if len(nodes) != 1:
        raise CheckoutError('workspace owner is missing or ambiguous in recorded source plan')
    node = nodes[0]
    position = workspace['next_member_position']
    if (node['strategy'] != workspace['strategy'] or position >= len(node['member_ids'])
            or node['member_ids'][position] != workspace['active_member_id']):
        raise CheckoutError('workspace active member/position/strategy differs from recorded source plan')
    if str(store.common_git_dir) != run['common_git_dir']:
        raise CheckoutError('record store lock/common Git directory differs from captured run')
    if writer_map is not None:
        from workspace_store import validate_cooked_writer_map
        access = {'read_only': True} if record_kind is None else {}
        validate_cooked_writer_map(writer_map, rows, store_ref=store.store_ref,
                                  workflow_root_id=workflow_root_id, claimed_step_id=claimed_step_id,
                                  record_kind=record_kind, **access)
        if writer_map.declaration['source_member_id'] != workspace['active_member_id']:
            raise CheckoutError('cooked occurrence belongs to a different active source member')
    return run, plan, workspace, rows


def _publish(store, attempt, *, workspace: dict, authority_id: str, rows: dict,
             writer_map, writer_rows, native_runtime=None,
             projections=(), writes=(), references=(), scope_owner=None, record_kind='workspace') -> dict:
    from workspace_store import GRANT_KEY, GuardRead

    # Freeze every observed metadata value, as well as each row's native revision.
    guards = [GuardRead(i, key, value) for i, row in rows.items() for key, value in row['metadata'].items()]
    publish = store.install_grant if GRANT_KEY not in rows[authority_id]['metadata'] else store.write_records
    prepared = publish(attempt, {'workflow_root_id': workspace['workflow_root_id'],
                                             'generation': workspace['generation'],
                                             'writer_scope_id': scope_owner or workspace['workspace_owner_id'],
                                             'record_kind': record_kind},
                                   authority_id, list(writes), references=list(references), projections=tuple(projections),
                                   writer_map=writer_map, guards=guards, expected_rows=rows)
    receipt = store.execute(prepared)
    resolved = store.resolve(prepared)
    if (resolved.get('outcome') not in ('committed', 'replayed')
            or resolved.get('request_sha256') != prepared.sha256):
        raise CheckoutError('guarded workspace publication is unknown; request_sha256=' + prepared.sha256
                            + '; readback=' + str(resolved.get('outcome')) + '; reobserve without automatic retry')
    # Native grants contain instance tokens; public results contain only the digest/outcome.
    rows.update(resolved['rows'])
    writer_rows.update(copy.deepcopy(rows))
    if native_runtime is not None:
        native_runtime.advance_written_rows(resolved['rows'], prepared=prepared)
    return {'outcome': resolved['outcome'], 'request_sha256': prepared.sha256,
            'write_outcome': receipt.get('outcome')}


def _writer(workspace: dict, attempt) -> dict:
    result = copy.deepcopy(workspace)
    result.update(writer_step_id=attempt.claimed_bead_id, writer_attempt_id=attempt.writer_attempt_id)
    result['claim_binding'].update(writer_step_id=attempt.claimed_bead_id, writer_attempt_id=attempt.writer_attempt_id)
    return validate_record('workspace', result)


def _step_binding(checkout, row, *, require_reference=False):
    workspace = checkout.workspace
    metadata = row['metadata']
    checkout.require(metadata.get('gc.root_bead_id') == workspace['workflow_root_id']
                     and all(metadata[k] == workspace['workflow_root_id'] for k in ('workflow_id', 'molecule_id') if k in metadata)
                     and metadata.get('gc.root_store_ref') == checkout.store_ref
                     and isinstance(metadata.get('gc.step_ref'), str) and bool(metadata['gc.step_ref']),
                     'native step lacks exact root/store/step identity')
    member = workspace['active_member_id']
    pins = [metadata[k] for k in ('gc.drain_member_id', 'gc.source_anchor_id') if k in metadata]
    checkout.require((row['id'] == member or bool(pins)) and all(pin == member for pin in pins),
                     'native step has missing, conflicting or foreign member bindings')
    if 'gc.worktree_ref' in metadata:
        checkout.require(workspace['native_provenance'] is not None, 'native step has an unexplained prior reference')
        expected = checkout._result({'provenance': workspace['native_provenance'], 'head': workspace['current_oid']})['launch_reference']
        raw = metadata['gc.worktree_ref']
        checkout.require(isinstance(raw, str) and parse_record(raw) == dict(expected, binding_step_id=row['id']),
                         'native step reference is malformed, foreign or stale')
    elif require_reference:
        checkout.require(False, 'native producer/consumer is missing its managed workspace reference')


def _continue_workspace(store, attempt, checkout, plan, rows, writer_map, *, authority_id,
                        rig_name, artifact_root, native_runtime):
    from workspace_store import Attempt, GRANT_KEY, GRANT_REFS_KEY
    from workspace_runtime import NativeSourceRuntime

    workspace = checkout.workspace
    checkout.require(rows[workspace['active_member_id']]['status'] != 'closed',
                     'closed source member requires a result/checkpoint decision before continuation')
    _step_binding(checkout, rows[attempt.claimed_bead_id], require_reference=True)
    scope = dict(workflow_root_id=workspace['workflow_root_id'], generation=workspace['generation'],
                 writer_scope_id=workspace['workspace_owner_id'], record_kind='workspace')
    authority = rows[authority_id]
    store._dedicated(authority)
    grant = parse_record(authority['metadata'].get(GRANT_KEY, 'null'))
    store._grant(grant, scope, authority_id)
    previous = Attempt(**grant['attempt'])
    checkout.require(previous.claimed_bead_id == workspace['writer_step_id']
                     and previous.writer_attempt_id == workspace['writer_attempt_id'],
                     'workspace checkpoint differs from its retained writer grant/attempt')
    index = parse_record(rows[workspace['workflow_root_id']]['metadata'].get(GRANT_REFS_KEY, 'null'))
    scope_hash = hashlib.sha256(canonical_bytes(scope)).hexdigest()
    checkout.require(isinstance(index, dict) and index.get('version') == 1
                     and set(index) == {'version', 'scopes'} and type(index['version']) is int
                     and isinstance(index.get('scopes'), dict)
                     and index['scopes'].get(scope_hash) == {'scope': scope, 'authority_id': authority_id},
                     'workspace authority lacks its exact native root reference')
    map_hash = hashlib.sha256(writer_map.declaration_bytes).hexdigest()
    checkout.require(grant['writer_map_sha256'] == map_hash, 'continuation cooked map differs from the recorded writer grant')
    declaration = writer_map.declaration
    writers = [item for item in declaration['steps'] if item['bead_id'] == previous.claimed_bead_id]
    checkout.require(len(writers) == 1 and 'workspace' in writers[0]['record_kinds'],
                     'retained checkpoint writer lacks its exact cooked responsibility')
    occurrence = {key: declaration[key] for key in ('source_member_id', 'expansion_root_id', 'formula_name', 'formula_hash', 'formula_source')}
    occurrence.update({key: writers[0][key] for key in ('step_id', 'step_ref')})
    checkout.require(grant['writer_occurrence'] == occurrence, 'retained writer occurrence differs from the cooked checkpoint')
    if previous == attempt:
        checkout.require(grant['attempt'] == attempt.admission, 'continuation native writer attempt changed')
    else:
        # Read the existing dependency proof. No replacement grant is published.
        store._successor(grant, attempt, scope, None, rows, writer_map.declaration, map_hash)
    if native_runtime is None:
        checkout.require(artifact_root is not None, 'continuation requires the recorded artifact directory for native admission')
        native_runtime = NativeSourceRuntime(store, gc=checkout.gc, city_root=checkout.city_root,
            rig_name=rig_name, run=checkout.run, plan=plan, artifact_root=artifact_root,
            evidence_dir=str(checkout.evidence_dir), claimed_step_id=attempt.claimed_bead_id, native_rows=rows)
    checkout.require(isinstance(native_runtime, NativeSourceRuntime)
                     and native_runtime.store is store and native_runtime.claimed_step_id == attempt.claimed_bead_id,
                     'continuation requires the actual runtime for this exact store/claimed occurrence')
    admission = native_runtime.admit_continuation(workspace, rows, attempt)
    _retain_rows(rows, admission['guard_rows'])
    result = checkout.continuation()
    native_runtime.recheck_continuation()
    _retain_rows(rows, store.snapshot(list(rows)))
    observation = copy.deepcopy(checkout.last_observation)
    checkout.observe(purpose='continuation')
    checkout.require(checkout.last_observation == observation, 'partial Git state changed during continuation admission')
    result.update(evidence_level='native-record-component', identity=admission['identity'],
                  writer_map_sha256=map_hash, check_policy_sha256=native_runtime.check_policy['policy_sha256'],
                  guard_revisions={key: row['revision'] for key, row in rows.items()},
                  session_atomicity='separate_native_readback')
    result['launch_reference']['binding_step_id'] = attempt.claimed_bead_id
    return result


def manage_workspace(store, attempt=None, *, action: str, gc: str, city_root: str, rig_name: str,
                     workflow_root_id: str, input_convoy_id: str, run_record_id: str,
                     plan_record_id: str, workspace_record_id: str, evidence_dir: str,
                     selected_mode: str, claimed_step_id: str | None = None,
                     parent: str | None = None, allow_external_parent=False,
                     authority_id: str | None = None, launch_step_ids=(), result_record_id: str | None = None,
                     declared_result: dict | None = None, result_authority_id: str | None = None,
                     blocker_record_id: str | None = None, blocker_id: str | None = None,
                     writer_map=None, writer_rows=None, source_rows=None,
                     artifact_root: str | None = None, native_runtime=None) -> dict:
    """Native-record caller; current grants must already admit the retained Attempt.

    Initial source selection and preparing-record creation belong to the input
    writer. This caller never derives physical IDs, claims work, replaces grants
    implicitly, or enables a workflow lifecycle.
    """
    from workspace_store import (Attempt, CookedWriterMap, NativeOwnerProjection, NativeWorktreeReference,
                                 RecordWrite, ReferenceWrite, record_reference)

    if selected_mode != 'new' or action not in ('prepare', 'path', 'status', 'verify', 'recover', 'continue'):
        raise CheckoutError('explicit new rollout and a supported workspace action are required')
    changing = action in ('prepare', 'recover')
    if attempt is not None and claimed_step_id not in (None, attempt.claimed_bead_id):
        raise CheckoutError('invoking step conflicts with the retained native Attempt')
    invoking_step = attempt.claimed_bead_id if attempt is not None else claimed_step_id
    if action == 'continue' and (not isinstance(attempt, Attempt) or not authority_id):
        raise CheckoutError('continuation requires the retained native Attempt and exact owner authority')
    if action == 'continue' and any(value is not None for value in (result_record_id, declared_result, result_authority_id,
                                                                 blocker_record_id, blocker_id)):
        raise CheckoutError('read-only continuation cannot publish or consume an advancing result/blocker')
    if changing and (not isinstance(attempt, Attempt) or not authority_id or not launch_step_ids):
        raise CheckoutError('preparation/recovery requires retained Attempt, current owner authority and actual launch steps')
    if len(set(launch_step_ids)) != len(launch_step_ids):
        raise CheckoutError('duplicate launch step binding')
    extra = list(launch_step_ids) + [i for i in (authority_id, result_record_id, result_authority_id, blocker_record_id) if i]
    directory = diagnostic_directory(evidence_dir)
    try:
        if writer_map is None:
            from workspace_cooked import read_cooked_writer_map
            access = {'read_only': True} if action == 'continue' else {}
            writer_map, discovered = read_cooked_writer_map(store, workflow_root_id=workflow_root_id,
                                                           claimed_step_id=invoking_step, **access)
            originals = {} if writer_rows is None else writer_rows
            _retain_rows(originals, discovered)
            writer_rows = originals
        if not isinstance(writer_map, CookedWriterMap) or writer_rows is None:
            raise CheckoutError('typed CookedWriterMap and its original native rows are required')
        if native_runtime is not None:
            from workspace_runtime import NativeSourceRuntime
            if not isinstance(native_runtime, NativeSourceRuntime) or native_runtime.store is not store:
                raise CheckoutError('checkout requires the actual native runtime bound to its exact store')
        run, plan, workspace, rows = load_workspace_context(
            store, gc=gc, city_root=city_root, rig_name=rig_name, workflow_root_id=workflow_root_id,
            input_convoy_id=input_convoy_id, run_record_id=run_record_id, plan_record_id=plan_record_id,
            workspace_record_id=workspace_record_id, claimed_step_id=invoking_step,
            extra_ids=extra, require_live=True, writer_map=writer_map, writer_rows=writer_rows, source_rows=source_rows,
            record_kind=None if action == 'continue' else 'workspace')
    except (RecordError, OSError) as exc:
        path = save_diagnostic(directory, {'version': 1, 'state': 'blocked', 'reason': str(exc),
                               'store_ref': store.store_ref, 'workflow_root_id': workflow_root_id,
                               'workspace_record_id': workspace_record_id})
        raise CheckoutError(str(exc), path) from exc
    checkout = WorkspaceCheckout(run, workspace, store_ref=store.store_ref, evidence_dir=evidence_dir,
                                 parent=parent, allow_external_parent=allow_external_parent, gc=gc, city_root=city_root)
    try:
        owner_keys = set(OWNERSHIP) | {'gc.worktree_placement', 'gc.root_bead_id', 'gc.root_store_ref'}
        owner_metadata = rows[workspace_record_id]['metadata']
        if workspace['native_provenance'] is None:
            checkout.require(not owner_keys.intersection(owner_metadata), 'preparing record has unexplained native projection')
        else:
            expected_owner = checkout._result({'provenance': workspace['native_provenance'], 'head': workspace['current_oid']})['owner_metadata']
            checkout.require(all(owner_metadata.get(k) == v for k, v in expected_owner.items()),
                             'stored native owner projection is incomplete or changed')
        for step_id in launch_step_ids:
            _step_binding(checkout, rows[step_id], require_reference=not changing)
        if action == 'continue':
            return _continue_workspace(store, attempt, checkout, plan, rows, writer_map,
                                       authority_id=authority_id, rig_name=rig_name,
                                       artifact_root=artifact_root, native_runtime=native_runtime)
        if not changing:
            result = checkout.status() if action == 'status' else checkout.verify()
            return result
        # Admission and source read guards are checked natively before provisioning.
        candidate = _writer(workspace, attempt)
        _publish(store, attempt, workspace=candidate, authority_id=authority_id, rows=rows,
                 writer_map=writer_map, writer_rows=writer_rows, native_runtime=native_runtime,
                 writes=[RecordWrite('workspace', workspace_record_id, candidate)])
        checkout.workspace = copy.deepcopy(candidate)
        result_record = None
        if result_record_id:
            raw = rows[result_record_id]['metadata'].get('gc.workspace_result')
            if raw is not None:
                result_record = _record(rows[result_record_id], 'member-result')
                _reference(rows[workspace['active_member_id']]['metadata'].get('gc.workspace_result_ref'),
                           'member-result', result_record_id, result_record)
        if declared_result is not None:
            checkout.require(action == 'recover' and result_record_id is not None, 'unrecorded recovery requires an exact result row')
            if result_record is not None:
                verify_replay('member-result', result_record, declared_result)
            else:
                checkout.require(result_authority_id is not None and declared_result.get('writer_step_id') == attempt.claimed_bead_id,
                                 'unrecorded result requires the retained native producer claim and member-scope authority')
                result_record = declared_result
        if result_record is not None:
            validate_record('member-result', result_record)
            producer_id = result_record['writer_step_id']
            if producer_id not in rows:
                _retain_rows(rows, store.snapshot([producer_id]))
            _step_binding(checkout, rows[producer_id], require_reference=True)
        if action == 'prepare':
            checkout.require(result_record is None and declared_result is None, 'preparation cannot consume a member result')
            result = checkout.prepare()
        else:
            result = checkout.recover(member_id=workspace['active_member_id'], result=result_record,
                                      result_unrecorded=declared_result is not None and rows[result_record_id]['metadata'].get('gc.workspace_result') is None,
                                      writer_step_id=result_record['writer_step_id'] if result_record else None)
        if result.get('record_result'):
            reference = record_reference('member-result', result_record_id, result['member_result'])
            _publish(store, attempt, workspace=candidate, authority_id=result_authority_id, rows=rows,
                     writer_map=writer_map, writer_rows=writer_rows, native_runtime=native_runtime,
                     scope_owner=workspace['active_member_id'], record_kind='member-result',
                     writes=[RecordWrite('member-result', result_record_id, result['member_result'])],
                     references=[ReferenceWrite(workspace['active_member_id'], 'gc.workspace_result_ref', reference)])
        result['workspace'] = _writer(result['workspace'], attempt)
        projections = [NativeOwnerProjection(workspace_record_id, result['owner_metadata'])]
        for step_id in launch_step_ids:
            reference = dict(result['launch_reference'], binding_step_id=step_id)
            projections.append(NativeWorktreeReference(step_id, workspace_record_id, reference))
        result['receipt'] = _publish(store, attempt, workspace=result['workspace'], authority_id=authority_id,
                                     rows=rows, writer_map=writer_map, writer_rows=writer_rows,
                                     native_runtime=native_runtime, projections=projections,
                                     writes=[RecordWrite('workspace', workspace_record_id, result['workspace'])])
        checkout.workspace = result['workspace']
        checkout.verify()
        for step_id in launch_step_ids:
            expected = dict(result['launch_reference'], binding_step_id=step_id)
            checkout.require(rows[step_id]['metadata'].get('gc.worktree_ref') == canonical_bytes(expected).decode(),
                             'native launch reference publication readback changed')
        result['evidence_level'] = 'native-record-component'
        result['launch_step_ids'] = list(launch_step_ids)
        return result
    except (RecordError, OSError, UnicodeError) as exc:
        if not isinstance(exc, CheckoutError) or exc.evidence_path is None:
            try: checkout.fail(str(exc))
            except CheckoutError as recorded: exc = recorded
        # A missing/unknown blocker allocation remains diagnostic evidence, never a fabricated physical ID.
        if changing and blocker_record_id and blocker_id and workspace['phase'] != 'blocked':
            observation = checkout.last_observation or {}
            blocker = dict(version=1, workflow_root_id=workflow_root_id, generation=workspace['generation'],
                           writer_step_id=attempt.claimed_bead_id, source_plan_owner_id=workspace['source_plan_owner_id'],
                           workspace_owner_id=workspace['workspace_owner_id'], blocker_id=blocker_id, status='open',
                           stage=action, member_id=workspace['active_member_id'], blocked_from_phase=workspace['phase'],
                           blocked_member_id=workspace['active_member_id'], blocked_member_position=workspace['next_member_position'],
                           blocked_current_oid=workspace['current_oid'],
                           result_absent=result_record_id is None or rows[result_record_id]['metadata'].get('gc.workspace_result') is None,
                           work_dir=workspace['work_dir'], expected_input_oid=workspace['input_oid'],
                           actual_head_oid=observation.get('head'), git_state=canonical_bytes(observation).decode(), reason=str(exc),
                           evidence_path=exc.evidence_path, recommended_next_action='Inspect preserved evidence and authorize an exact recovery decision.', resolution=None)
            try:
                blocked = _writer(dict(workspace, phase='blocked'), attempt)
                reference = record_reference('blocker', blocker_record_id, blocker)
                _publish(store, attempt, workspace=blocked, authority_id=authority_id, rows=rows,
                         writer_map=writer_map, writer_rows=writer_rows, native_runtime=native_runtime,
                         writes=[RecordWrite('workspace', workspace_record_id, blocked), RecordWrite('blocker', blocker_record_id, blocker)],
                         references=[ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref', reference)])
            except RecordError:
                pass  # The independent diagnostic survives a stale or unavailable store grant.
        raise exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('action', choices=('prepare', 'path', 'status', 'verify', 'recover', 'continue'))
    for flag in ('store-ref', 'city-root', 'rig-name', 'workflow-root-id', 'input-convoy-id',
                 'run-record-id', 'plan-record-id', 'workspace-record-id', 'evidence-dir'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--worktree-lifecycle', choices=('new',), required=True)
    parser.add_argument('--parent')
    parser.add_argument('--allow-external-parent', action='store_true')
    parser.add_argument('--claimed-step-id')
    parser.add_argument('--authority-id')
    parser.add_argument('--artifact-root')
    parser.add_argument('--launch-step-id', action='append', default=[])
    parser.add_argument('--result-record-id')
    parser.add_argument('--result-authority-id')
    parser.add_argument('--declared-result', type=Path)
    parser.add_argument('--blocker-record-id')
    parser.add_argument('--blocker-id')
    parser.add_argument('--gc', default='gc')
    args = parser.parse_args(argv)
    try:
        from workspace_store import Attempt, WorkspaceStore
        from workspace_run import registered_rig, repository_identity
        city_root = str(canonical_path(args.city_root, directory=True))
        rig_root = registered_rig(args.gc, city_root, args.rig_name, args.store_ref)
        _, common = repository_identity(rig_root)
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=city_root, common_git_dir=common)
        claimed_step = args.claimed_step_id or os.environ.get('GC_BEAD_ID')
        attempt = Attempt.from_env(claimed_step) if claimed_step and args.action in ('prepare', 'recover', 'continue') else None
        declaration = parse_record(args.declared_result.read_text()) if args.declared_result else None
        result = manage_workspace(store, attempt, action=args.action, gc=args.gc, city_root=city_root, rig_name=args.rig_name,
                                  workflow_root_id=args.workflow_root_id, input_convoy_id=args.input_convoy_id,
                                  run_record_id=args.run_record_id, plan_record_id=args.plan_record_id,
                                  workspace_record_id=args.workspace_record_id, evidence_dir=args.evidence_dir,
                                  selected_mode=args.worktree_lifecycle, claimed_step_id=claimed_step, parent=args.parent, allow_external_parent=args.allow_external_parent,
                                  authority_id=args.authority_id, launch_step_ids=args.launch_step_id,
                                  result_record_id=args.result_record_id, declared_result=declaration,
                                  result_authority_id=args.result_authority_id,
                                  blocker_record_id=args.blocker_record_id, blocker_id=args.blocker_id,
                                  artifact_root=args.artifact_root)
        if args.action in ('path', 'continue') and result.get('ok'):
            print(result['path'])
        else:
            print(json.dumps(result, sort_keys=True))
        return 0 if result.get('ok') else 1
    except (RecordError, OSError, UnicodeError, ImportError) as exc:
        error = {'ok': False, 'reason': str(exc), 'evidence_path': getattr(exc, 'evidence_path', None)}
        print(json.dumps(error, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
