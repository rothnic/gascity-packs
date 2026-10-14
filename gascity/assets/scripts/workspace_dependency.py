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
                             GuardRead, InheritedRunReference, NativeOwnerProjection,
                             NativeRunContinuation, NativeWorktreeReference,
                             RecordWrite, ReferenceWrite, SuccessorRelation,
                             record_reference, transition_locks)


class DependencyError(RecordError):
    def __init__(self, message, evidence_path=None, request_path=None):
        super().__init__(message)
        self.evidence_path = evidence_path
        self.request_path = request_path


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


def initial_workspace(bundle, attempt, *, workspace_record_id, work_dir, work_branch, layout=None):
    source = bundle['input_oid'] or bundle['base_oid']
    workspace = dict(version=1, workflow_root_id=bundle['workflow_root_id'], generation=bundle['generation'],
        source_plan_owner_id=bundle['source_plan_owner_id'], workspace_owner_id=bundle['workspace_owner_id'],
        workspace_bead_id=workspace_record_id, strategy=bundle['strategy'], work_dir=work_dir, work_branch=work_branch,
        phase='preparing', input_oid=source, current_oid=source, active_member_id=bundle['member_id'],
        next_member_position=bundle['member_position'], output_oid=None,
        integration_inputs=integration_inputs(bundle) if bundle['strategy'] == 'integration' else None,
        native_attempt_id=None, native_provenance=None)
    if layout is not None:
        workspace['layout'] = copy.deepcopy(layout)
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


def checkout_context(writer_map, rows):
    context = writer_map.continuation
    return dict(continuation=context, native_rows=rows) if context is not None else {}


def publish_checkpoint(frozen, attempt, workspace, *, authority_id, writer_map, plan_record_id,
                       extra_writes=(), extra_references=(), native_runtime=None, launch_step_ids=()):
    from workspace_requests import retain_request
    from workspace_runtime import NativeSourceRuntime
    store = frozen.store
    require(isinstance(native_runtime, NativeSourceRuntime) and native_runtime.store is store,
            'checkpoint publication requires its actual runtime and durable request directory')
    scope = dict(workflow_root_id=workspace['workflow_root_id'], generation=workspace['generation'],
                 writer_scope_id=workspace['workspace_owner_id'], record_kind='workspace')
    raw = frozen.metadata(authority_id, GRANT_KEY)
    writes = [RecordWrite('workspace', workspace['workspace_bead_id'], workspace), *extra_writes]
    references = [ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_ref',
                                 record_reference('workspace', workspace['workspace_bead_id'], workspace)), *extra_references]
    projections = []
    context = writer_map.continuation
    if context is not None:
        projections.append(InheritedRunReference(context))
        physical_root = context.binding['child_root_id']
        owner_root = frozen.metadata(workspace['workspace_bead_id'], 'gc.root_bead_id')
        if workspace['native_provenance'] is not None and owner_root != physical_root:
            from workspace_checkout import WorkspaceCheckout
            from workspace_runtime import NativeSourceRuntime
            require(isinstance(native_runtime, NativeSourceRuntime) and native_runtime.store is store
                    and launch_step_ids, 'inherited successor needs its actual runtime and launch occurrences')
            # The saved Git provenance is unchanged. Only this proven child
            # obtains the active native owner and per-occurrence references.
            retained = frozen.payload('workspace', workspace['workspace_bead_id'])
            old_context = native_runtime.retained_workspace_continuation(retained)
            frozen.merge(native_runtime.guard_rows)
            checkout = WorkspaceCheckout(native_runtime.run, retained, store_ref=store.store_ref,
                evidence_dir=native_runtime.evidence_dir, parent=str(Path(retained['work_dir']).parent),
                allow_external_parent=retained.get('layout', {}).get('allow_external_parent', True),
                gc=native_runtime.gc, city_root=native_runtime.city_root,
                **(dict(continuation=old_context, native_rows=frozen.rows) if old_context is not None else {}))
            native = checkout.successor_projection(workspace, continuation=context,
                native_rows=frozen.rows, writer_map=writer_map)
            projections.append(NativeOwnerProjection(workspace['workspace_bead_id'], native['owner_metadata']))
            admitted_steps = {step['bead_id'] for step in writer_map.declaration['steps']}
            for step_id in launch_step_ids:
                require(step_id in admitted_steps, 'successor launch step is outside its actual cooked map')
                projections.append(NativeWorktreeReference(step_id, workspace['workspace_bead_id'],
                    dict(native['launch_reference'], binding_step_id=step_id)))
    arguments = dict(writer_map=writer_map, guards=frozen.guards, expected_rows=frozen.rows,
                     projections=projections)
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
    request_path, pending = retain_request(store, prepared)
    try:
        submitted = store.execute(prepared)
        resolved = store.resolve(prepared)
        frozen.acknowledge(prepared, resolved)
        native_runtime.advance_written_rows(resolved['rows'], prepared=prepared)
    except (RecordError, OSError) as exc:
        raise DependencyError(str(exc) + '; resolve the original retained request: ' + str(request_path),
                              request_path=str(request_path)) from exc
    require(pending.read_text() == str(request_path), 'pending request reference changed after acknowledgement')
    pending.unlink()
    return dict(outcome=resolved['outcome'], request_sha256=prepared.sha256,
                submission_outcome=submitted.get('outcome'), retry_allowed=False, request_path=str(request_path))


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


def _recovery_decision(frozen, workspace, blocker, decision_path, artifact_root):
    from workspace_outputs import artifact, read_artifact
    reference = artifact(decision_path, artifact_root)
    decision = read_artifact(reference, artifact_root)
    exact = {key: workspace[key] for key in ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id')}
    exact.update(store_ref=frozen.store.store_ref, blocker_id=blocker['blocker_id'])
    require(set(decision) == set(exact) | {'expected_head_oid'}
            and all(type(decision[key]) is type(value) and decision[key] == value for key, value in exact.items())
            and isinstance(decision['expected_head_oid'], str)
            and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', decision['expected_head_oid']),
            'recovery decision belongs to another exact source, blocker or commit')
    resolution = dict(decision_path=reference['path'], decision_sha256=reference['sha256'],
                      expected_head_oid=decision['expected_head_oid'])
    if blocker['status'] == 'resolved':
        require(blocker['resolution'] == resolution and workspace['current_oid'] == resolution['expected_head_oid'],
                'partial recovery changed its recorded decision or HEAD')
    return reference, resolution


def _allocate_preparation_retry_blocker(frozen, workspace, scope, native_runtime):
    from workspace_allocation import allocate_roles
    from workspace_entry import allocate_placeholder
    from workspace_run import native_json
    reference = parse_record(frozen.metadata(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref'))
    blocker = frozen.read('blocker', workspace['workspace_owner_id'], 'gc.workspace_blocker_ref')
    require(blocker['status'] == 'resolved', 'preparation retry requires its resolved blocker')
    packet = dict(store=parse_record(frozen.store._binding().decode()), scope=scope,
                  blocker_reference=reference, resolution=blocker['resolution'], input_oid=workspace['input_oid'])
    ids, rows = allocate_roles(frozen.store, packet, prefix='prepare-retry-' + record_sha256(packet),
        roles=(('blocker', 'Preparation retry blocker record', None),),
        allocate=allocate_placeholder, native_read=native_json, admit=native_runtime.recheck_continuation)
    frozen.merge(rows)
    return ids['blocker']


def _resume_preparation(frozen, attempt, workspace, bundle, *, decision_path, artifact_root,
        run, gc, city_root, evidence_dir, parent, allow_external_parent, authority_id,
        writer_map, plan_record_id, native_runtime, launch_step_ids, blocker_record_id=None, blocker_id=None):
    from workspace_checkout import OWNERSHIP, WorkspaceCheckout, _step_binding
    from workspace_outputs import read_artifact
    require(workspace['phase'] in ('blocked', 'preparing') and workspace['native_provenance'] is None
            and workspace['native_attempt_id'] is None and workspace['output_oid'] is None
            and workspace['input_oid'] == workspace['current_oid'] == (bundle['input_oid'] or bundle['base_oid'])
            and workspace['active_member_id'] == bundle['member_id']
            and workspace['next_member_position'] == bundle['member_position']
            and workspace['integration_inputs'] == (integration_inputs(bundle) if bundle['strategy'] == 'integration' else None),
            'recovery requires the exact unfinished first preparation')
    blocker = frozen.read('blocker', workspace['workspace_owner_id'], 'gc.workspace_blocker_ref')
    record_id = parse_record(frozen.metadata(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref'))['bead_id']
    require(blocker_record_id in (None, record_id) and blocker_id in (None, blocker['blocker_id']),
            'recovery names another recorded blocker')
    expected = {key: workspace[key] for key in ('workflow_root_id', 'generation', 'source_plan_owner_id',
                                                'workspace_owner_id', 'work_dir')}
    expected.update(stage='prepare', blocked_from_phase='preparing', member_id=workspace['active_member_id'],
        blocked_member_id=workspace['active_member_id'], blocked_member_position=workspace['next_member_position'],
        blocked_current_oid=workspace['current_oid'], expected_input_oid=workspace['input_oid'], result_absent=True)
    require(all(blocker[key] == value for key, value in expected.items())
            and blocker['status'] == ('open' if workspace['phase'] == 'blocked' else 'resolved'),
            'recorded blocker differs from the first preparation checkpoint')
    reference, resolution = _recovery_decision(frozen, workspace, blocker, decision_path, artifact_root)
    require(resolution['expected_head_oid'] == workspace['input_oid'], 'preparation recovery cannot change its recorded input')
    native_runtime.admit_continuation(workspace, frozen.rows, attempt)
    frozen.merge(native_runtime.guard_rows)
    candidate = writer_checkpoint(dict(workspace, phase='preparing'), attempt)
    checkout = WorkspaceCheckout(run, candidate, store_ref=frozen.store.store_ref, evidence_dir=str(evidence_dir),
        parent=parent, allow_external_parent=allow_external_parent, gc=gc, city_root=city_root,
        **checkout_context(writer_map, frozen.rows))
    owner_keys = set(OWNERSHIP) | {'gc.worktree_placement', 'gc.root_bead_id', 'gc.root_store_ref'}
    require(not owner_keys.intersection(frozen.rows[workspace['workspace_bead_id']]['metadata']),
            'first preparation has an unexplained native owner projection')
    observation = checkout.observe()
    require(observation['head'] in (None, workspace['input_oid']), 'preparation recovery must preserve its exact input')
    if observation['state'] == 'registered':
        checkout._verified()
    for step_id in launch_step_ids:
        _step_binding(checkout, frozen.rows[step_id], require_reference=False)
    native_runtime.recheck_continuation()
    read_artifact(reference, artifact_root)
    if workspace['phase'] == 'preparing':
        return candidate, None
    resolved = dict(blocker, writer_step_id=attempt.claimed_bead_id, status='resolved', resolution=resolution)
    receipt = publish_checkpoint(frozen, attempt, candidate, authority_id=authority_id,
        writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=native_runtime,
        extra_writes=[RecordWrite('blocker', record_id, resolved)],
        extra_references=[ReferenceWrite(workspace['workspace_owner_id'], 'gc.workspace_blocker_ref',
            record_reference('blocker', record_id, resolved))])
    return candidate, receipt


def _resume_integration(frozen, attempt, workspace, bundle, *, decision_path, artifact_root,
        run, gc, city_root, evidence_dir, parent, allow_external_parent, authority_id,
        writer_map, plan_record_id, native_runtime, launch_step_ids, blocker_record_id=None, blocker_id=None):
    from workspace_checkout import WorkspaceCheckout, _step_binding
    from workspace_inputs import inspect_integrated_history
    from workspace_outputs import immutable_json, read_artifact

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
    reference, resolution = _recovery_decision(frozen, workspace, blocker, decision_path, artifact_root)
    head = resolution['expected_head_oid']
    native_runtime.admit_continuation(workspace, frozen.rows, attempt)
    frozen.merge(native_runtime.guard_rows)
    # Verify the resolved source without mutating the blocked native record. The
    # expected HEAD comes from the explicit, hash-bound decision, not a recapture.
    expected_workspace = dict(workspace, phase='active', current_oid=head)
    checkout = WorkspaceCheckout(run, expected_workspace, store_ref=frozen.store.store_ref,
        evidence_dir=str(evidence_dir), parent=parent, allow_external_parent=allow_external_parent,
        gc=gc, city_root=city_root, **checkout_context(writer_map, frozen.rows))
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
        parent=parent, allow_external_parent=allow_external_parent, gc=gc, city_root=city_root,
        **checkout_context(writer_map, frozen.rows)).verify()
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
        allow_external_parent=None, name_prefix=None, work_branch=None, blocker_record_id=None, blocker_id=None,
        resume_decision=None):
    """Use actual run/plan/role/policy records to prepare one dependency input.

    Native allocations happen only after source qualification. Every mutation
    carries retained original rows and actual cooked writer admission. Git
    integration retains conflicts; it never grants result acceptance.
    """
    from workspace_checkout import WorkspaceCheckout, diagnostic_directory, manage_workspace, select_workspace_layout
    from workspace_cooked import read_cooked_writer_map
    from workspace_entry import allocate_placeholder, healthy, read_entry
    from workspace_inputs import materialize_integration, resolve_member_input
    from workspace_outputs import immutable_json
    from workspace_runtime import NativeSourceRuntime, _ReadFence
    from workspace_source_plan import source_node_ids, validate_source_plan

    directory = diagnostic_directory(str(evidence_dir))
    artifacts = diagnostic_directory(str(artifact_root))
    require(type(generation) is int and generation > 0, 'generation must be a positive integer')
    require(attempt.claimed_bead_id, 'dependency preparation requires the retained native claim')
    entry_reads = _ReadFence(store)
    entry = read_entry(entry_reads, gc=gc, city_root=city_root, rig_name=rig_name,
        workflow_root_id=workflow_root_id, claimed_step_id=attempt.claimed_bead_id,
        worktree_lifecycle='new', generation=generation, input_convoy_id=input_convoy_id, require_plan=True)
    run, plan = entry['run'], entry['source_plan']
    # A native child keeps its physical claim while inheriting the original
    # lifecycle tuple. Its drain unit is not a new source-plan convoy.
    workflow_root_id, input_convoy_id = run['workflow_root_id'], entry['input_convoy_id']
    context = (NativeRunContinuation(canonical_bytes(entry['native_continuation']))
               if entry.get('native_continuation') is not None else None)
    writer_map, map_rows = read_cooked_writer_map(entry_reads, workflow_root_id=workflow_root_id,
        claimed_step_id=attempt.claimed_bead_id, continuation=context,
        continuation_rows=entry_reads.rows if context is not None else None)
    frozen = FrozenRecords(store, entry_reads.rows)
    frozen.merge(map_rows)
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
        artifact_root=artifacts, evidence_dir=directory, claimed_step_id=attempt.claimed_bead_id,
        native_rows=frozen.rows)
    frozen.merge(runtime.guard_rows)
    bundle = resolve_member_input(plan, workspace_owner_id, member_id,
        load_owner_output=lambda owner: frozen.read('owner-output', owner, 'gc.workspace_output_ref', required=False),
        load_member_result=lambda member: frozen.read('member-result', member, 'gc.workspace_result_ref', required=False),
        qualify_native=runtime.qualify_native, acceptance_context=runtime.acceptance_context,
        store_ref=store.store_ref, artifact_root=artifacts)
    frozen.merge(runtime.guard_rows)
    existing = frozen.read('workspace', workspace_owner_id, 'gc.workspace_ref', required=False)
    if existing is not None and existing['generation'] == generation:
        # Before a successor commits, the saved workspace still belongs to its
        # previous writer's published child, independently of the invoking one.
        retained_context = runtime.retained_workspace_continuation(existing)
        frozen.merge(runtime.guard_rows)
        ref = parse_record(frozen.metadata(workspace_owner_id, 'gc.workspace_ref'))
        original_ids = [ref['bead_id'], *(retained_context.row_ids if retained_context is not None else ())]
        frozen.merge(store.snapshot(list(dict.fromkeys(original_ids))))
        observed = store.read_record('workspace', ref['bead_id'], ref['identity'], continuation=retained_context)
        require(observed == existing, 'retained native workspace differs from its frozen reference')
        frozen.merge(store.snapshot(list(dict.fromkeys(original_ids))))
    scope = dict(workflow_root_id=workflow_root_id, generation=generation, writer_scope_id=workspace_owner_id,
                 record_kind='workspace')
    from workspace_requests import require_resolved_scope
    try:
        require_resolved_scope(store, scope)
    except RecordError as exc:
        raise DependencyError(str(exc)) from exc
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
    layout = None
    if existing is None or 'layout' in existing:
        layout, work_dir = select_workspace_layout(run, workspace_owner_id, generation, root['metadata'],
            workspace=existing, parent=parent, name_prefix=name_prefix,
            allow_external_parent=allow_external_parent, evidence_dir=directory)
        parent, allow_external_parent = layout['parent'], layout['allow_external_parent']
    else:
        # Old records retain their original path/provenance. Missing historical
        # prefix or external permission is not inferred from new formula defaults.
        require(name_prefix in (None, '') and root['metadata'].get('gc.var.worktree_name_prefix', '') == '',
                'historical workspace has no recorded name prefix; resume its original layout')
        configured_parent = root['metadata'].get('gc.var.worktree_parent', '')
        require(not configured_parent or configured_parent == str(Path(existing['work_dir']).parent),
                'historical workspace parent conflicts with its recorded path')
        if configured_parent:
            require(parent is None or parent == configured_parent, 'historical workspace parent override changed')
            parent = configured_parent
    # Validate layout before allocating native records. Existing ownership has
    # priority over any optional creation arguments.
    if existing is not None:
        require(workspace_record_id in (None, existing['workspace_bead_id']), 'physical workspace argument conflicts with its exact reference')
        require(recorded_authority is not None, 'existing workspace has no native owner authority')
        workspace_record_id, authority_id = existing['workspace_bead_id'], recorded_authority
        if resume_decision is not None:
            require(all(existing[key] == bundle[key] for key in
                        ('workflow_root_id', 'generation', 'source_plan_owner_id', 'workspace_owner_id', 'strategy')),
                    'workspace recovery belongs to another source scope')
            workspace = existing
        else:
            workspace = select_checkpoint(existing, bundle, attempt)
        require(work_branch is None or work_branch == workspace['work_branch'], 'existing workspace branch selection changed')
        # Layout preflight inspects the retained workspace under its published
        # writer. The successor's physical child is admitted atomically below.
        WorkspaceCheckout(run, existing, store_ref=store.store_ref, evidence_dir=str(directory), parent=parent,
                          allow_external_parent=allow_external_parent, gc=gc, city_root=city_root,
                          **(dict(continuation=retained_context, native_rows=frozen.rows)
                             if retained_context is not None else {}))
    else:
        require(resume_decision is None, 'recovery requires its existing recorded workspace and blocker')
        require(recorded_authority is None, 'owner authority exists without its published workspace; resolve its original intent')
        # Physical IDs always come from native allocation/readback. The selected
        # path is a stable owner/generation name, independent of control IDs.
        require(not artifacts.is_relative_to(repo) and not directory.is_relative_to(repo), 'evidence must be outside the repository')
        workspace_record_id = allocate_placeholder(store, title='Managed workspace record', existing_id=workspace_record_id)
        authority_id = allocate_placeholder(store, title='Managed workspace authority', existing_id=authority_id)
        workspace = initial_workspace(bundle, attempt, workspace_record_id=workspace_record_id, work_dir=work_dir,
                                      work_branch=work_branch, layout=layout)
        WorkspaceCheckout(run, workspace, store_ref=store.store_ref, evidence_dir=str(directory), parent=parent,
                          allow_external_parent=allow_external_parent, gc=gc, city_root=city_root,
                          **checkout_context(writer_map, frozen.rows))
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
    receipts = []
    if resume_decision is not None and workspace['native_provenance'] is None:
        with transition_locks(store.common_git_dir, scope, store.timeout):
            workspace, receipt = _resume_preparation(frozen, attempt, workspace, bundle,
                decision_path=resume_decision, artifact_root=artifacts, run=run, gc=gc, city_root=city_root,
                evidence_dir=directory, parent=parent, allow_external_parent=allow_external_parent,
                authority_id=authority_id, writer_map=writer_map, plan_record_id=plan_record_id,
                native_runtime=runtime, launch_step_ids=launch_step_ids,
                blocker_record_id=blocker_record_id, blocker_id=blocker_id)
            if receipt is not None:
                receipts.append(receipt)
            # A second failure retains the resolved blocker and its exact allocation intent.
            blocker_record_id = _allocate_preparation_retry_blocker(frozen, workspace, scope, runtime)
        blocker_id = blocker_record_id
    elif resume_decision is not None:
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
    with transition_locks(store.common_git_dir, scope, store.timeout):
        try:
            receipts.append(publish_checkpoint(frozen, attempt, workspace, authority_id=authority_id,
                writer_map=writer_map, plan_record_id=plan_record_id, native_runtime=runtime,
                launch_step_ids=launch_step_ids))
        except (RecordError, OSError) as exc:
            from workspace_checkout import save_diagnostic
            evidence = save_diagnostic(directory, dict(version=1, state='unknown', reason=str(exc),
                workflow_root_id=workflow_root_id, generation=generation, workspace_owner_id=workspace_owner_id,
                workspace_record_id=workspace_record_id, authority_id=authority_id, blocker_record_id=blocker_record_id,
                request_path=getattr(exc, 'request_path', None), retry_allowed=False,
                next_action='Resolve the original retained request without submitting another write.'))
            raise DependencyError(str(exc), evidence, request_path=getattr(exc, 'request_path', None)) from exc
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
            allow_external_parent=allow_external_parent, gc=gc, city_root=city_root,
            **checkout_context(writer_map, frozen.rows))
        final.verify()
        return dict(ok=True, state='prepared', evidence_level='native-record-component', workspace=workspace,
            input_oid=workspace['input_oid'], path=workspace['work_dir'], authority_id=authority_id,
            workspace_record_id=workspace_record_id, launch_step_ids=list(launch_step_ids),
            integration_evidence=integration_evidence, receipts=receipts)


def main(argv=None):
    from workspace_store import Attempt, WorkspaceStore
    argv = sys.argv[1:] if argv is None else argv
    resolving = any(value == '--resolve-request' or value.startswith('--resolve-request=') for value in argv)
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('store-ref', 'city-root'):
        parser.add_argument('--' + name, required=True)
    for name in ('rig-name', 'workflow-root-id', 'input-convoy-id',
                 'workspace-owner-id', 'member-id', 'claimed-step-id', 'artifact-root', 'evidence-dir'):
        parser.add_argument('--' + name, required=not resolving)
    parser.add_argument('--worktree-lifecycle', required=not resolving, choices=['new'])
    parser.add_argument('--generation', required=not resolving, type=int)
    parser.add_argument('--resolve-request')
    parser.add_argument('--gc', default='gc')
    for name in ('workspace-record-id', 'authority-id', 'parent', 'name-prefix', 'work-branch', 'blocker-record-id', 'blocker-id', 'resume-decision'):
        parser.add_argument('--' + name)
    parser.add_argument('--launch-step-id', action='append', default=[])
    parser.add_argument('--allow-external-parent', action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args(argv)
    try:
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city_root)
        if args.resolve_request:
            from workspace_requests import resolve_request
            result = resolve_request(store, args.resolve_request)
            print(json.dumps(result, sort_keys=True))
            return 0 if result.get('outcome') in ('committed', 'replayed') else 1
        result = prepare_dependency_workspace(store, Attempt.from_env(args.claimed_step_id), gc=args.gc,
            city_root=args.city_root, rig_name=args.rig_name, workflow_root_id=args.workflow_root_id,
            input_convoy_id=args.input_convoy_id, generation=args.generation, workspace_owner_id=args.workspace_owner_id,
            member_id=args.member_id, artifact_root=args.artifact_root, evidence_dir=args.evidence_dir,
            workspace_record_id=args.workspace_record_id, authority_id=args.authority_id,
            launch_step_ids=args.launch_step_id, parent=args.parent, name_prefix=args.name_prefix,
            allow_external_parent=args.allow_external_parent,
            work_branch=args.work_branch, blocker_record_id=args.blocker_record_id, blocker_id=args.blocker_id,
            resume_decision=args.resume_decision)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RecordError, OSError, KeyError, ValueError, TypeError) as exc:
        print(json.dumps(dict(ok=False, state='blocked', reason=str(exc),
            evidence_path=getattr(exc, 'evidence_path', None), request_path=getattr(exc, 'request_path', None)),
            sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
