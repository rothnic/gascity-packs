#!/usr/bin/env python3
"""Prepare native workspaces from declared, accepted source dependencies."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys

from workspace_records import (RecordError, canonical_bytes, contracts, parse_record,
                               record_identity, record_sha256, validate_record)
from workspace_store import (GRANT_KEY, GRANT_REFS_KEY, MISSING, TRANSITION_NONCE_KEY,
                             GuardRead, RecordWrite, ReferenceWrite, SuccessorRelation,
                             record_reference, transition_locks)


class DependencyError(RecordError):
    def __init__(self, message, evidence_path=None):
        super().__init__(message)
        self.evidence_path = evidence_path


def require(condition, message):
    if not condition:
        raise DependencyError(message)


class FrozenRecords:
    """Retain original physical rows, references and revisions through a write."""
    def __init__(self, store, rows=None):
        self.store, self.rows, self.read_keys = store, {}, set()
        self.merge(rows or {})

    def merge(self, rows):
        require(isinstance(rows, dict), 'native guard rows must be an exact-ID object')
        require(len(set(self.rows) | set(rows)) <= 100, 'complete guarded scope exceeds 100 rows; chunking is forbidden')
        for bead_id, row in rows.items():
            require(isinstance(row, dict) and row.get('id') == bead_id, 'native guard row physical identity differs')
            require(bead_id not in self.rows or canonical_bytes(self.rows[bead_id]) == canonical_bytes(row),
                    'native source changed after its original snapshot; do not refresh the proof')
        self.rows.update(copy.deepcopy(rows))

    def ensure(self, ids):
        ids = list(dict.fromkeys(ids))
        require(len(set(ids) | set(self.rows)) <= 100, 'complete guarded scope exceeds 100 rows; chunking is forbidden')
        missing = [bead_id for bead_id in ids if bead_id not in self.rows]
        if missing:
            self.merge(self.store.snapshot(missing))
        return self.rows

    def metadata(self, bead_id, key):
        self.ensure([bead_id])
        self.read_keys.add((bead_id, key))
        return self.rows[bead_id]['metadata'].get(key, MISSING)

    def payload(self, kind, bead_id):
        raw = self.metadata(bead_id, contracts()[kind]['metadata_key'])
        require(isinstance(raw, str), f'missing durable {kind} payload')
        payload = validate_record(kind, parse_record(raw))
        row = self.rows[bead_id]
        require(row['status'] == 'closed' and not row['assignee'] and row['type'] == 'task' and not row.get('labels'),
                f'{kind} payload requires a dedicated closed, unassigned native record')
        return payload

    def read(self, kind, holder_id, key, *, required=True):
        raw = self.metadata(holder_id, key)
        if raw is MISSING and not required:
            return None
        require(isinstance(raw, str), f'missing exact {kind} physical reference')
        ref = parse_record(raw)
        require(set(ref) == {'kind', 'identity', 'bead_id'} and ref['kind'] == kind
                and isinstance(ref['identity'], list) and isinstance(ref['bead_id'], str) and bool(ref['bead_id']),
                f'malformed exact {kind} physical reference')
        payload = self.payload(kind, ref['bead_id'])
        require(ref == record_reference(kind, ref['bead_id'], payload), f'{kind} reference identity differs from its payload')
        return payload

    @property
    def guards(self):
        # Every row participates even when its metadata is empty. Original
        # revisions also fence additions to keys that were never read.
        keys = self.read_keys | {(bead_id, key) for bead_id, row in self.rows.items() for key in row['metadata']}
        keys |= {(bead_id, TRANSITION_NONCE_KEY) for bead_id in self.rows}
        return [GuardRead(bead_id, key, self.rows[bead_id]['metadata'].get(key, MISSING))
                for bead_id, key in sorted(keys)]

    def acknowledge(self, prepared, resolved):
        require(resolved.get('request_sha256') == prepared.sha256 and resolved.get('outcome') in ('committed', 'replayed'),
                'guarded publication is unknown; request_sha256=' + prepared.sha256
                + '; resolve the original request without another submission')
        # This update acknowledges only the exact after-state of our own frozen
        # request. It never replaces a stale precondition with an arbitrary read.
        after = parse_record(prepared.after_bytes.decode())
        actual = resolved.get('rows')
        require(isinstance(actual, dict) and set(actual) == set(after), 'exact guarded readback is incomplete')
        for bead_id, expected in after.items():
            require(all(actual[bead_id][key] == expected[key] for key in ('metadata', 'status', 'assignee', 'type', 'labels')),
                    'guarded publication readback differs from its frozen intention')
        self.rows.update(copy.deepcopy(actual))


def writer_checkpoint(workspace, attempt):
    binding = {key: workspace[key] for key in ('workflow_root_id', 'generation', 'workspace_owner_id')}
    binding.update(writer_step_id=attempt.claimed_bead_id, writer_attempt_id=attempt.writer_attempt_id)
    return dict(workspace, writer_step_id=attempt.claimed_bead_id,
                writer_attempt_id=attempt.writer_attempt_id, claim_binding=binding)


def integration_inputs(bundle):
    return [{key: source[key] for key in ('owner_id', 'output_oid', 'workspace_output_sha256')}
            for source in bundle['predecessors']]


def initial_workspace(bundle, attempt, *, workspace_record_id, work_dir, work_branch):
    source = bundle['input_oid'] or bundle['base_oid']
    workspace = dict(version=1, workflow_root_id=bundle['workflow_root_id'], generation=bundle['generation'],
        source_plan_owner_id=bundle['source_plan_owner_id'], workspace_owner_id=bundle['workspace_owner_id'],
        workspace_bead_id=workspace_record_id, strategy=bundle['strategy'], work_dir=work_dir, work_branch=work_branch,
        phase='preparing', input_oid=source, current_oid=source, active_member_id=bundle['member_id'],
        next_member_position=bundle['member_position'], output_oid=None,
        integration_inputs=integration_inputs(bundle) if bundle['strategy'] == 'integration' else None,
        native_attempt_id=None, native_provenance=None)
    return validate_record('workspace', writer_checkpoint(workspace, attempt))


def select_checkpoint(workspace, bundle, attempt):
    validate_record('workspace', workspace)
    for key in ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id', 'strategy'):
        require(workspace[key] == bundle[key], 'workspace checkpoint belongs to another source scope')
    require(workspace['phase'] != 'blocked', 'workspace is blocked; authorize its exact recovery decision first')
    if workspace['active_member_id'] == bundle['member_id']:
        require(workspace['next_member_position'] == bundle['member_position'], 'workspace member position differs')
        if bundle['strategy'] == 'integration':
            require(workspace['integration_inputs'] == integration_inputs(bundle), 'ordered integration inputs changed')
            if workspace['phase'] in ('preparing', 'entry'):
                require(workspace['input_oid'] == bundle['base_oid'], 'uncompleted integration moved its starting commit')
        else:
            require(workspace['input_oid'] == bundle['input_oid'], 'workspace input differs from its accepted source')
        require(workspace['phase'] in ('preparing', 'entry', 'active'), 'completed member needs a declared successor')
        return writer_checkpoint(workspace, attempt)
    require(workspace['strategy'] == 'shared-chain' and workspace['phase'] == 'result'
            and workspace['next_member_position'] + 1 == bundle['member_position']
            and workspace['current_oid'] == workspace['output_oid'] == bundle['input_oid'],
            'shared-chain advance requires the immediate accepted predecessor checkpoint')
    return writer_checkpoint(dict(workspace, phase='entry', input_oid=bundle['input_oid'], current_oid=bundle['input_oid'],
        active_member_id=bundle['member_id'], next_member_position=bundle['member_position'], output_oid=None), attempt)


def _authority(frozen, scope):
    raw = frozen.metadata(scope['workflow_root_id'], GRANT_REFS_KEY)
    if raw is MISSING:
        return None
    index = parse_record(raw) if isinstance(raw, str) else None
    require(isinstance(index, dict) and set(index) == {'version', 'scopes'} and index['version'] == 1
            and isinstance(index['scopes'], dict), 'malformed native root authority references')
    entry = index['scopes'].get(record_sha256(scope))
    if entry is None:
        return None
    require(isinstance(entry, dict) and set(entry) == {'scope', 'authority_id'} and entry['scope'] == scope
            and isinstance(entry['authority_id'], str) and bool(entry['authority_id']), 'exact workspace authority scope changed')
    return entry['authority_id']


def publish_checkpoint(frozen, attempt, workspace, *, authority_id, writer_map, plan_record_id,
                       extra_writes=(), extra_references=(), native_runtime=None):
    store = frozen.store
    scope = dict(workflow_root_id=workspace['workflow_root_id'], generation=workspace['generation'],
                 writer_scope_id=workspace['workspace_owner_id'], record_kind='workspace')
    raw = frozen.metadata(authority_id, GRANT_KEY)
    writes = [RecordWrite('workspace', workspace['workspace_bead_id'], workspace), *extra_writes]
    references = [ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_ref',
                                 record_reference('workspace', workspace['workspace_bead_id'], workspace)), *extra_references]
    arguments = dict(writer_map=writer_map, guards=frozen.guards, expected_rows=frozen.rows)
    if raw is MISSING:
        prepared = store.install_grant(attempt, scope, authority_id, writes, references, **arguments)
    else:
        require(isinstance(raw, str), 'native workspace grant is malformed')
        grant = parse_record(raw)
        if grant.get('attempt') == attempt.admission:
            prepared = store.write_records(attempt, scope, authority_id, writes, references, **arguments)
        else:
            previous = grant.get('attempt', {}).get('claimed_bead_id')
            expansion = grant.get('writer_occurrence', {}).get('expansion_root_id')
            require(isinstance(previous, str) and isinstance(expansion, str), 'predecessor grant lacks its native occurrence')
            frozen.ensure([previous, expansion])
            arguments.update(guards=frozen.guards, expected_rows=frozen.rows, expected_grant=grant,
                successor_relation=SuccessorRelation(plan_record_id, workspace['source_plan_owner_id']))
            prepared = store.accept_replacement(attempt, scope, authority_id, writes, references, **arguments)
    submitted = store.execute(prepared)
    resolved = store.resolve(prepared)
    frozen.acknowledge(prepared, resolved)
    if native_runtime is not None:
        native_runtime.advance_written_rows(resolved['rows'], prepared=prepared)
    return dict(outcome=resolved['outcome'], request_sha256=prepared.sha256,
                submission_outcome=submitted.get('outcome'), retry_allowed=False)


def integration_receipt_path(artifact_root, bundle):
    identity = {key: bundle[key] for key in ('workflow_root_id', 'generation', 'source_plan_owner_id',
                                            'workspace_owner_id', 'member_id', 'base_oid')}
    identity['integration_inputs'] = integration_inputs(bundle)
    return Path(artifact_root) / ('source-integration-' + record_sha256(identity) + '.json')


def _integration_receipt(path, bundle, workspace):
    from workspace_outputs import artifact, read_artifact
    reference = artifact(path, path.parent)
    receipt = read_artifact(reference, path.parent)
    require(receipt.get('base_oid') == bundle['base_oid']
            and receipt.get('integration_inputs') == integration_inputs(bundle)
            and receipt.get('output_oid') == workspace['input_oid'], 'integration evidence differs from the recorded input')
    return receipt, reference


def _resume_integration(frozen, attempt, workspace, bundle, *, decision_path, artifact_root,
        run, gc, city_root, evidence_dir, parent, allow_external_parent, authority_id,
        writer_map, plan_record_id, native_runtime, launch_step_ids, blocker_record_id=None, blocker_id=None):
    from workspace_checkout import WorkspaceCheckout, _step_binding
    from workspace_inputs import inspect_integrated_history
    from workspace_outputs import artifact, immutable_json, read_artifact

    require(workspace['strategy'] == bundle['strategy'] == 'integration'
            and workspace['phase'] in ('blocked', 'entry')
            and workspace['input_oid'] == bundle['base_oid']
            and workspace['integration_inputs'] == integration_inputs(bundle)
            and workspace['active_member_id'] == bundle['member_id']
            and workspace['next_member_position'] == bundle['member_position'],
            'recovery requires the exact unfinished integration checkpoint')
    blocker = frozen.read('blocker', workspace['workspace_owner_id'], 'gc.workspace_blocker_ref')
    raw_ref = frozen.metadata(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref')
    exact_record_id = parse_record(raw_ref)['bead_id']
    require(blocker_record_id in (None, exact_record_id) and blocker_id in (None, blocker['blocker_id']),
            'recovery names another recorded blocker')
    expected = {key: workspace[key] for key in ('workflow_root_id', 'generation', 'source_plan_owner_id',
                                                'workspace_owner_id', 'work_dir')}
    expected.update(stage='integrate-inputs', blocked_from_phase='entry',
        blocked_member_id=workspace['active_member_id'], blocked_member_position=workspace['next_member_position'],
        expected_input_oid=bundle['base_oid'], result_absent=True)
    require(all(blocker[key] == value for key, value in expected.items()),
            'recorded blocker differs from the integration source checkpoint')
    if workspace['phase'] == 'blocked':
        require(blocker['status'] == 'open' and blocker['blocked_current_oid'] == workspace['current_oid'],
                'blocked workspace differs from its open blocker')
    else:
        require(blocker['status'] == 'resolved' and blocker['resolution'] is not None,
                'partial integration recovery requires its resolved blocker')
    reference = artifact(decision_path, artifact_root)
    decision = read_artifact(reference, artifact_root)
    exact = {key: workspace[key] for key in ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id')}
    exact.update(store_ref=frozen.store.store_ref, blocker_id=blocker['blocker_id'])
    require(set(decision) == set(exact) | {'expected_head_oid'}
            and all(type(decision[key]) is type(value) and decision[key] == value for key, value in exact.items())
            and isinstance(decision['expected_head_oid'], str)
            and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', decision['expected_head_oid']),
            'recovery decision belongs to another exact source, blocker or commit')
    head = decision['expected_head_oid']
    resolution = dict(decision_path=reference['path'], decision_sha256=reference['sha256'], expected_head_oid=head)
    if blocker['status'] == 'resolved':
        require(blocker['resolution'] == resolution and workspace['current_oid'] == head,
                'partial recovery changed its recorded decision or HEAD')
    native_runtime.admit_continuation(workspace, frozen.rows, attempt)
    frozen.merge(native_runtime.guard_rows)
    # Verify the resolved source without mutating the blocked native record. The
    # expected HEAD comes from the explicit, hash-bound decision, not a recapture.
    expected_workspace = dict(workspace, phase='active', current_oid=head)
    checkout = WorkspaceCheckout(run, expected_workspace, store_ref=frozen.store.store_ref,
        evidence_dir=str(evidence_dir), parent=parent, allow_external_parent=allow_external_parent,
        gc=gc, city_root=city_root)
    observed = checkout.verify()
    owner_row = frozen.rows[workspace['workspace_bead_id']]['metadata']
    require(all(owner_row.get(key) == value for key, value in observed['owner_metadata'].items()),
            'recovery changed the retained native owner projection')
    for step_id in launch_step_ids:
        _step_binding(checkout, frozen.rows[step_id], require_reference=True)
    merged = inspect_integrated_history(Path(workspace['work_dir']), bundle, head)
    native_runtime.recheck_continuation()
    read_artifact(reference, artifact_root)
    path = integration_receipt_path(artifact_root, bundle)
    integration_evidence = immutable_json(path, merged)
    receipts = []
    if workspace['phase'] == 'blocked':
        resolved = dict(blocker, writer_step_id=attempt.claimed_bead_id, status='resolved', resolution=resolution)
        workspace = writer_checkpoint(dict(workspace, phase='entry', current_oid=head), attempt)
        receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
            writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=native_runtime,
            extra_writes=[RecordWrite('blocker', exact_record_id, resolved)],
            extra_references=[ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref',
                record_reference('blocker', exact_record_id, resolved))]))
    native_runtime.bind_workspace(workspace, frozen.rows)
    native_runtime.verify_integration(Path(workspace['work_dir']), bundle, head)
    workspace = writer_checkpoint(dict(workspace, phase='active', input_oid=head, current_oid=head), attempt)
    receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
        writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=native_runtime))
    native_runtime.bind_workspace(workspace, frozen.rows)
    WorkspaceCheckout(run, workspace, store_ref=frozen.store.store_ref, evidence_dir=str(evidence_dir),
        parent=parent, allow_external_parent=allow_external_parent, gc=gc, city_root=city_root).verify()
    native_runtime.recheck_continuation()
    read_artifact(reference, artifact_root)
    return workspace, integration_evidence, receipts


def _block_integration(frozen, attempt, workspace, exc, *, authority_id, writer_map, plan_record_id,
                       blocker_record_id, blocker_id, evidence_dir, native_runtime):
    from workspace_checkout import git, save_diagnostic
    head = git(workspace['work_dir'], 'rev-parse', 'HEAD', optional=True)
    state = git(workspace['work_dir'], 'status', '--porcelain=v1', '--untracked-files=all')
    evidence = save_diagnostic(Path(evidence_dir), dict(version=1, state='blocked', reason=str(exc),
        workspace=workspace, actual_head_oid=head, git_state=state,
        recommended_next_action='Inspect the preserved merge state and authorize an exact recovery decision.'))
    blocker = dict(version=1, workflow_root_id=workspace['workflow_root_id'], generation=workspace['generation'],
        writer_step_id=attempt.claimed_bead_id, source_plan_owner_id=workspace['source_plan_owner_id'],
        workspace_owner_id=workspace['workspace_owner_id'], blocker_id=blocker_id, status='open', stage='integrate-inputs',
        member_id=workspace['active_member_id'], blocked_from_phase=workspace['phase'],
        blocked_member_id=workspace['active_member_id'], blocked_member_position=workspace['next_member_position'],
        blocked_current_oid=workspace['current_oid'], result_absent=True, work_dir=workspace['work_dir'],
        expected_input_oid=workspace['input_oid'], actual_head_oid=head, git_state=state or 'clean', reason=str(exc),
        evidence_path=evidence, recommended_next_action='Inspect preserved inputs and conflicts; authorize a recovery decision.',
        resolution=None)
    validate_record('blocker', blocker)
    try:
        publish_checkpoint(frozen, attempt, writer_checkpoint(dict(workspace, phase='blocked'), attempt),
            authority_id=authority_id, writer_map=writer_map, plan_record_id=plan_record_id,
            extra_writes=[RecordWrite('blocker', blocker_record_id, blocker)],
            extra_references=[ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref',
                record_reference('blocker', blocker_record_id, blocker))], native_runtime=native_runtime)
    except (RecordError, OSError) as publication:
        raise DependencyError('integration state was preserved; blocker publication is unknown: ' + str(publication), evidence) from exc
    raise DependencyError('integration is blocked; conflict state and source checkpoint were preserved', evidence) from exc


def prepare_dependency_workspace(store, attempt, *, gc, city_root, rig_name, workflow_root_id,
        input_convoy_id, generation, workspace_owner_id, member_id, artifact_root, evidence_dir,
        workspace_record_id=None, authority_id=None, launch_step_ids=(), parent=None,
        allow_external_parent=False, work_branch=None, blocker_record_id=None, blocker_id=None,
        resume_decision=None):
    """Use actual run/plan/role/policy records to prepare one dependency input.

    Native allocations happen only after source qualification. Every mutation
    carries retained original rows and actual cooked writer admission. Git
    integration retains conflicts; it never grants result acceptance.
    """
    from workspace_checkout import WorkspaceCheckout, diagnostic_directory, manage_workspace
    from workspace_cooked import read_cooked_writer_map
    from workspace_entry import allocate_placeholder, healthy, read_entry
    from workspace_inputs import materialize_integration, resolve_member_input
    from workspace_outputs import immutable_json
    from workspace_runtime import NativeSourceRuntime
    from workspace_source_plan import source_node_ids, validate_source_plan

    directory = diagnostic_directory(str(evidence_dir))
    artifacts = diagnostic_directory(str(artifact_root))
    require(type(generation) is int and generation > 0, 'generation must be a positive integer')
    require(attempt.claimed_bead_id, 'dependency preparation requires the retained native claim')
    writer_map, map_rows = read_cooked_writer_map(store, workflow_root_id=workflow_root_id,
                                                claimed_step_id=attempt.claimed_bead_id)
    frozen = FrozenRecords(store, map_rows)
    entry = read_entry(store, gc=gc, city_root=city_root, rig_name=rig_name,
        workflow_root_id=workflow_root_id, claimed_step_id=attempt.claimed_bead_id,
        worktree_lifecycle='new', generation=generation, input_convoy_id=input_convoy_id, require_plan=True)
    run, plan = entry['run'], entry['source_plan']
    # Entry independently validates the registered rig and replays its captured
    # repository identity. The CLI starts without a caller-supplied lock path.
    if store.common_git_dir is None:
        store.common_git_dir = run['common_git_dir']
    require(writer_map.declaration['source_member_id'] == member_id, 'claimed cooked workflow belongs to another source member')
    nodes = [node for node in plan['nodes'] if node['owner_id'] == workspace_owner_id and member_id in node['member_ids']]
    require(len(nodes) == 1, 'requested member/owner is absent from the recorded source plan')
    run_record_id, plan_record_id = entry['run_reference']['bead_id'], entry['source_plan_reference']['bead_id']
    frozen.ensure([workflow_root_id, input_convoy_id, run['input_convoy_id'], run['source_anchor_id'],
                   plan['source_plan_owner_id'], *source_node_ids(plan)])
    require(frozen.read('run', workflow_root_id, 'gc.implementation_run_ref') == run, 'original run reference changed')
    require(frozen.read('source-plan', plan['source_plan_owner_id'], 'gc.source_plan_ref') == plan, 'original source plan changed')
    root, convoy = frozen.rows[workflow_root_id], frozen.rows[input_convoy_id]
    healthy(root)
    require(root['status'] != 'closed' and root['metadata'].get('gc.input_convoy_id') == input_convoy_id
            and convoy['metadata'].get('gc.source_plan_owner_id') == plan['source_plan_owner_id']
            and convoy['metadata'].get('gc.source_plan_sha256') == record_sha256(plan), 'current native plan/convoy selection is stale')
    validate_source_plan(plan, run, frozen.rows, store_ref=store.store_ref, stored=plan)
    runtime = NativeSourceRuntime(store, gc=gc, city_root=city_root, rig_name=rig_name, run=run, plan=plan,
        artifact_root=artifacts, evidence_dir=directory, claimed_step_id=attempt.claimed_bead_id)
    frozen.merge(runtime.guard_rows)
    bundle = resolve_member_input(plan, workspace_owner_id, member_id,
        load_owner_output=lambda owner: frozen.read('owner-output', owner, 'gc.workspace_output_ref', required=False),
        load_member_result=lambda member: frozen.read('member-result', member, 'gc.workspace_result_ref', required=False),
        qualify_native=runtime.qualify_native, acceptance_context=runtime.acceptance_context,
        store_ref=store.store_ref, artifact_root=artifacts)
    frozen.merge(runtime.guard_rows)
    existing = frozen.read('workspace', workspace_owner_id, 'gc.workspace_ref', required=False)
    scope = dict(workflow_root_id=workflow_root_id, generation=generation, writer_scope_id=workspace_owner_id,
                 record_kind='workspace')
    recorded_authority = _authority(frozen, scope)
    require(authority_id is None or recorded_authority is None or authority_id == recorded_authority,
            'supplied authority conflicts with the exact native root reference')
    if existing is not None and existing['generation'] != generation:
        require(existing['workflow_root_id'] == workflow_root_id and existing['generation'] + 1 == generation,
                'workspace reference belongs to another root or skipped generation')
        existing = None
    declaration = writer_map.declaration
    map_steps = {step['bead_id']: step for step in declaration['steps']}
    if not launch_step_ids:
        launch_step_ids = tuple(step['bead_id'] for step in declaration['steps'] if step['record_kinds'])
    require(launch_step_ids and len(set(launch_step_ids)) == len(launch_step_ids)
            and all(step in map_steps for step in launch_step_ids), 'launch steps must be exact actual cooked occurrences')
    frozen.ensure(launch_step_ids)
    repo = Path(run['rig_root'])
    default_parent = repo / ('workspaces' if Path(run['common_git_dir']) == repo else 'worktrees')
    selected_parent = Path(parent) if parent is not None else default_parent
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', workspace_owner_id), 'workspace owner has an unsafe path spelling')
    # Validate layout before allocating native records. Existing ownership has
    # priority over any optional creation arguments.
    if existing is not None:
        require(workspace_record_id in (None, existing['workspace_bead_id']), 'physical workspace argument conflicts with its exact reference')
        require(recorded_authority is not None, 'existing workspace has no native owner authority')
        workspace_record_id, authority_id = existing['workspace_bead_id'], recorded_authority
        if resume_decision is not None:
            require(all(existing[key] == bundle[key] for key in
                        ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id', 'strategy')),
                    'integration recovery belongs to another source scope')
            workspace = existing
        else:
            workspace = select_checkpoint(existing, bundle, attempt)
        require(work_branch is None or work_branch == workspace['work_branch'], 'existing workspace branch selection changed')
        WorkspaceCheckout(run, workspace, store_ref=store.store_ref, evidence_dir=str(directory), parent=parent,
                          allow_external_parent=allow_external_parent, gc=gc, city_root=city_root)
    else:
        require(resume_decision is None, 'recovery requires its existing recorded workspace and blocker')
        require(recorded_authority is None, 'owner authority exists without its published workspace; resolve its original intent')
        # Physical IDs always come from native allocation/readback. The selected
        # path is a stable owner/generation name, independent of control IDs.
        work_dir = str(selected_parent / (workspace_owner_id + '-g' + str(generation)))
        # A lexical preview validates the real layout without inventing a native
        # physical ID or publishing a placeholder payload.
        require(selected_parent.is_absolute() and str(selected_parent) == str(selected_parent.resolve()),
                'workspace parent must use canonical absolute spelling')
        require(not artifacts.is_relative_to(repo) and not directory.is_relative_to(repo), 'evidence must be outside the repository')
        workspace_record_id = allocate_placeholder(store, title='Managed workspace record', existing_id=workspace_record_id)
        authority_id = allocate_placeholder(store, title='Managed workspace authority', existing_id=authority_id)
        workspace = initial_workspace(bundle, attempt, workspace_record_id=workspace_record_id, work_dir=work_dir,
                                      work_branch=work_branch)
        WorkspaceCheckout(run, workspace, store_ref=store.store_ref, evidence_dir=str(directory), parent=parent,
                          allow_external_parent=allow_external_parent, gc=gc, city_root=city_root)
    frozen.ensure([workspace_record_id, authority_id])
    if existing is not None and existing['phase'] == 'active' and resume_decision is None:
        with transition_locks(store.common_git_dir, scope, store.timeout):
            continued = manage_workspace(store, attempt, action='continue', gc=gc, city_root=city_root, rig_name=rig_name,
                workflow_root_id=workflow_root_id, input_convoy_id=input_convoy_id, run_record_id=run_record_id,
                plan_record_id=plan_record_id, workspace_record_id=workspace_record_id, evidence_dir=str(directory),
                selected_mode='new', parent=parent, allow_external_parent=allow_external_parent,
                authority_id=authority_id, launch_step_ids=launch_step_ids, writer_map=writer_map,
                writer_rows=frozen.rows, artifact_root=str(artifacts), native_runtime=runtime)
            integration_evidence = None
            if bundle['strategy'] == 'integration':
                _, integration_evidence = _integration_receipt(integration_receipt_path(artifacts, bundle), bundle, existing)
            return dict(continued, ok=True, input_oid=existing['input_oid'], authority_id=authority_id,
                workspace_record_id=workspace_record_id, launch_step_ids=list(launch_step_ids),
                integration_evidence=integration_evidence, receipts=[])
    if resume_decision is not None:
        with transition_locks(store.common_git_dir, scope, store.timeout):
            workspace, integration_evidence, receipts = _resume_integration(frozen, attempt, workspace, bundle,
                decision_path=resume_decision, artifact_root=artifacts, run=run, gc=gc, city_root=city_root,
                evidence_dir=directory, parent=parent, allow_external_parent=allow_external_parent,
                authority_id=authority_id, writer_map=writer_map, plan_record_id=plan_record_id,
                native_runtime=runtime, launch_step_ids=launch_step_ids,
                blocker_record_id=blocker_record_id, blocker_id=blocker_id)
            return dict(ok=True, state='prepared', evidence_level='native-record-component', workspace=workspace,
                input_oid=workspace['input_oid'], path=workspace['work_dir'], authority_id=authority_id,
                workspace_record_id=workspace_record_id, launch_step_ids=list(launch_step_ids),
                integration_evidence=integration_evidence, receipts=receipts, accepted=False)
    if bundle['strategy'] == 'integration' and workspace['phase'] != 'active':
        blocker_record_id = allocate_placeholder(store, title='Integration blocker record', existing_id=blocker_record_id)
        blocker_id = blocker_id or blocker_record_id
        frozen.ensure([blocker_record_id])
    receipts = []
    with transition_locks(store.common_git_dir, scope, store.timeout):
        try:
            receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
                                              writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=runtime))
        except (RecordError, OSError) as exc:
            from workspace_checkout import save_diagnostic
            evidence = save_diagnostic(directory, dict(version=1, state='unknown', reason=str(exc),
                workflow_root_id=workflow_root_id, generation=generation, workspace_owner_id=workspace_owner_id,
                workspace_record_id=workspace_record_id, authority_id=authority_id, blocker_record_id=blocker_record_id,
                retry_allowed=False, next_action='Inspect the original request and these exact native allocations.'))
            raise DependencyError(str(exc), evidence) from exc
        prepared = manage_workspace(store, attempt, action='prepare', gc=gc, city_root=city_root, rig_name=rig_name,
            workflow_root_id=workflow_root_id, input_convoy_id=input_convoy_id, run_record_id=run_record_id,
            plan_record_id=plan_record_id, workspace_record_id=workspace_record_id, evidence_dir=str(directory),
            selected_mode='new', parent=parent, allow_external_parent=allow_external_parent, authority_id=authority_id,
            launch_step_ids=launch_step_ids, blocker_record_id=blocker_record_id, blocker_id=blocker_id,
            writer_map=writer_map, writer_rows=frozen.rows, native_runtime=runtime)
        workspace = prepared['workspace']
        runtime.bind_workspace(workspace, frozen.rows)
        integration_evidence = None
        if bundle['strategy'] == 'integration':
            path = integration_receipt_path(artifacts, bundle)
            if workspace['phase'] == 'active':
                _, integration_evidence = _integration_receipt(path, bundle, workspace)
            else:
                try:
                    require(not path.exists(), 'partial integration evidence requires explicit recovery; do not merge again')
                    merged = materialize_integration(Path(workspace['work_dir']), bundle,
                                                     verify_native=runtime.verify_integration)
                    integration_evidence = immutable_json(path, merged)
                    workspace = writer_checkpoint(dict(workspace, phase='active', input_oid=merged['output_oid'],
                                                        current_oid=merged['output_oid']), attempt)
                    receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
                                                      writer_map=writer_map, plan_record_id=plan_record_id,
                                                      native_runtime=runtime))
                except (RecordError, OSError) as exc:
                    _block_integration(frozen, attempt, prepared['workspace'], exc, authority_id=authority_id,
                        writer_map=writer_map, plan_record_id=plan_record_id, blocker_record_id=blocker_record_id,
                        blocker_id=blocker_id, evidence_dir=directory, native_runtime=runtime)
        elif workspace['phase'] == 'entry':
            workspace = writer_checkpoint(dict(workspace, phase='active'), attempt)
            receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
                                              writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=runtime))
        runtime.bind_workspace(workspace, frozen.rows)
        # Verification at the final prepared input is independent of result
        # acceptance. Existing same-member work is checked by the checkout engine.
        final = WorkspaceCheckout(run, workspace, store_ref=store.store_ref, evidence_dir=str(directory), parent=parent,
                                  allow_external_parent=allow_external_parent, gc=gc, city_root=city_root)
        final.verify()
        return dict(ok=True, state='prepared', evidence_level='native-record-component', workspace=workspace,
            input_oid=workspace['input_oid'], path=workspace['work_dir'], authority_id=authority_id,
            workspace_record_id=workspace_record_id, launch_step_ids=list(launch_step_ids),
            integration_evidence=integration_evidence, receipts=receipts)


def main(argv=None):
    from workspace_store import Attempt, WorkspaceStore
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store-ref', 'city-root', 'rig-name', 'workflow-root-id', 'input-convoy-id',
                 'workspace-owner-id', 'member-id', 'claimed-step-id', 'artifact-root', 'evidence-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--worktree-lifecycle', required=True, choices=['new'])
    parser.add_argument('--generation', required=True, type=int)
    parser.add_argument('--gc', default='gc')
    for name in ('workspace-record-id', 'authority-id', 'parent', 'work-branch', 'blocker-record-id', 'blocker-id', 'resume-decision'):
        parser.add_argument('--' + name)
    parser.add_argument('--launch-step-id', action='append', default=[])
    parser.add_argument('--allow-external-parent', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city_root)
        result = prepare_dependency_workspace(store, Attempt.from_env(args.claimed_step_id), gc=args.gc,
            city_root=args.city_root, rig_name=args.rig_name, workflow_root_id=args.workflow_root_id,
            input_convoy_id=args.input_convoy_id, generation=args.generation, workspace_owner_id=args.workspace_owner_id,
            member_id=args.member_id, artifact_root=args.artifact_root, evidence_dir=args.evidence_dir,
            workspace_record_id=args.workspace_record_id, authority_id=args.authority_id,
            launch_step_ids=args.launch_step_id, parent=args.parent, allow_external_parent=args.allow_external_parent,
            work_branch=args.work_branch, blocker_record_id=args.blocker_record_id, blocker_id=args.blocker_id,
            resume_decision=args.resume_decision)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RecordError, OSError, KeyError, ValueError, TypeError) as exc:
        print(json.dumps(dict(ok=False, state='blocked', reason=str(exc),
                              evidence_path=getattr(exc, 'evidence_path', None)), sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
