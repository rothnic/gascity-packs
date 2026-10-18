"""Resolve standalone suffixes from native input relationships, never artifacts."""
from __future__ import annotations

import hashlib

from workspace_records import canonical_bytes, contracts, parse_record, record_identity, record_sha256, validate_record


FIELDS = {'version', 'workflow_root_id', 'store_ref', 'generation', 'child_root_id',
          'unit_convoy_id', 'implementation_convoy_id', 'drain_control_id', 'member_id',
          'run_ref', 'source_plan_ref', 'run_sha256', 'source_plan_sha256', 'check_policy_sha256',
          'suffix_root_id', 'suffix_input_convoy_id', 'source_anchor_id', 'run_input_convoy_id',
          'source_plan_owner_route', 'canonical_ref', 'canonical_sha256',
          'suffix_input_plan_ref', 'suffix_input_plan_sha256'}
CURRENT_PLAN = {'generation', 'implementation_convoy_id', 'source_plan_ref', 'source_plan_sha256',
                'source_plan_owner_route', 'canonical_ref', 'canonical_sha256'}


def reference_bytes(binding):
    # The root joins the immutable source/run route once. Each writer map also
    # binds the exact current plan, including a later explicit fix generation.
    return canonical_bytes({key: value for key, value in binding.items() if key not in CURRENT_PLAN})


def row_ids(binding):
    values = [binding[key] for key in ('workflow_root_id', 'child_root_id', 'suffix_root_id',
        'unit_convoy_id', 'suffix_input_convoy_id', 'implementation_convoy_id', 'drain_control_id',
        'member_id', 'source_anchor_id', 'run_input_convoy_id') if binding[key] is not None]
    values.append(binding['run_ref']['bead_id'])
    if binding['source_plan_ref'] is not None:
        values.extend((binding['source_plan_ref']['bead_id'], binding['source_plan_ref']['identity'][2]))
    route = binding['source_plan_owner_route']
    if route is not None:
        values.extend(route[key] for key in ('child_root_id', 'suffix_root_id', 'unit_convoy_id',
            'suffix_input_convoy_id', 'drain_control_id', 'member_id', 'source_anchor_id', 'run_input_convoy_id')
            if route[key] is not None)
    if binding['canonical_ref'] is not None:
        values.append(binding['canonical_ref']['bead_id'])
    for proof in (binding, route):
        if proof is not None and proof['suffix_input_plan_ref'] is not None:
            values.extend((proof['suffix_input_plan_ref']['bead_id'], proof['suffix_input_plan_ref']['identity'][2]))
    return tuple(dict.fromkeys(values))


def source_owner_context(plan, rows, *, store_ref, continuation=None):
    """Prove a plan owner's physical root without changing its native identity."""
    from workspace_entry import native_root, reference
    from workspace_store import CONTINUATION_KEY, NativeRunContinuation, require
    owner = rows[plan['source_plan_owner_id']]
    physical_id = native_root(owner)
    if physical_id == plan['workflow_root_id']:
        return None
    require(plan['source_plan_owner_id'] == plan['writer_step_id'],
            'suffix source-plan owner is not its exact native writer')
    if continuation is not None:
        require(continuation.binding['version'] == 2
                and continuation.binding['child_root_id'] == physical_id,
                'source-plan owner differs from the invoking suffix')
        validate(continuation, rows, store_ref=store_ref, workflow_root_id=plan['workflow_root_id'],
                 claimed_step_id=plan['writer_step_id'])
        return continuation
    require(physical_id in rows and CONTINUATION_KEY in rows[physical_id]['metadata'],
            'source-plan owner has no exact published suffix route')
    root = rows[plan['workflow_root_id']]
    route = parse_record(rows[physical_id]['metadata'][CONTINUATION_KEY])
    require(set(route) == FIELDS - CURRENT_PLAN and route['child_root_id'] == physical_id,
            'source-plan owner has no exact published suffix route')
    plan_ref = reference(owner['metadata'].get('gc.source_plan_ref'), 'source-plan')
    require(plan_ref['identity'] == list(record_identity('source-plan', plan)),
            'source-plan owner reference changed')
    canonical_ref = None; canonical_sha = None
    if root['metadata'].get('gc.canonical_ref'):
        canonical_ref = reference(root['metadata']['gc.canonical_ref'], 'canonical')
        canonical = _payload(rows[canonical_ref['bead_id']], 'canonical')
        canonical_sha = record_sha256(canonical)
    binding = dict(route, generation=plan['generation'],
        implementation_convoy_id=root['metadata']['gc.input_convoy_id'], source_plan_ref=plan_ref,
        source_plan_sha256=record_sha256(plan), source_plan_owner_route=None,
        canonical_ref=canonical_ref, canonical_sha256=canonical_sha)
    context = NativeRunContinuation(canonical_bytes(binding))
    validate(context, rows, store_ref=store_ref, workflow_root_id=plan['workflow_root_id'],
             require_reference=True, _owner_checked=True)
    return context


def _payload(row, kind):
    payload = parse_record(row['metadata'][contracts()[kind]['metadata_key']])
    validate_record(kind, payload)
    return payload


def retain_source_owner(store, plan, rows):
    """Read the exact published owner route and its complete native proof."""
    from workspace_entry import native_root, reference
    from workspace_store import CONTINUATION_KEY, require
    owner = rows[plan['source_plan_owner_id']]
    physical_id = native_root(owner)
    if physical_id == plan['workflow_root_id']:
        return rows
    result = dict(rows)
    def retain(ids):
        observed = store.snapshot(list(dict.fromkeys(ids)))
        require(all(key not in result or result[key] == row for key, row in observed.items()),
                'source-plan owner changed after its original snapshot')
        result.update(observed)
    retain([physical_id, plan['workflow_root_id']])
    route = parse_record(result[physical_id]['metadata'][CONTINUATION_KEY])
    require(set(route) == FIELDS - CURRENT_PLAN, 'source-plan owner route is malformed')
    ids = [route[key] for key in ('workflow_root_id', 'child_root_id', 'suffix_root_id', 'unit_convoy_id',
        'suffix_input_convoy_id', 'drain_control_id', 'member_id', 'source_anchor_id', 'run_input_convoy_id')
        if route[key] is not None]
    root = result[plan['workflow_root_id']]
    ids.extend((route['run_ref']['bead_id'], root['metadata']['gc.input_convoy_id'],
                reference(owner['metadata'].get('gc.source_plan_ref'), 'source-plan')['bead_id']))
    if root['metadata'].get('gc.canonical_ref'):
        ids.append(reference(root['metadata']['gc.canonical_ref'], 'canonical')['bead_id'])
    if route['suffix_input_plan_ref'] is not None:
        ids.extend((route['suffix_input_plan_ref']['bead_id'], route['suffix_input_plan_ref']['identity'][2]))
    retain(ids)
    source_owner_context(plan, result, store_ref=store.store_ref)
    return result


def validate_binding(data, raw):
    from workspace_store import STORE_REF, _id, _reference, require
    import re
    require(set(data) == FIELDS and type(data['version']) is int and data['version'] == 2
            and type(data['generation']) is int and data['generation'] > 0
            and isinstance(data['store_ref'], str) and STORE_REF.fullmatch(data['store_ref'])
            and canonical_bytes(data) == raw, 'suffix binding is malformed')
    for key in ('workflow_root_id', 'child_root_id', 'suffix_root_id', 'unit_convoy_id',
                'suffix_input_convoy_id', 'implementation_convoy_id', 'member_id',
                'source_anchor_id', 'run_input_convoy_id'):
        _id(data[key], 'suffix physical ID')
    require(data['workflow_root_id'] not in (data['suffix_root_id'], data['child_root_id']),
            'suffix must preserve a different physical workflow root')
    if data['drain_control_id'] is None:
        require(data['child_root_id'] == data['suffix_root_id']
                and data['unit_convoy_id'] == data['suffix_input_convoy_id']
                and data['member_id'] == data['workflow_root_id'], 'suffix invents a drain relationship')
    else:
        _id(data['drain_control_id'], 'suffix drain control')
        require(len({data[key] for key in ('workflow_root_id', 'suffix_root_id', 'child_root_id',
                'unit_convoy_id', 'drain_control_id', 'member_id')}) == 6, 'suffix drain roles overlap')
    ref = _reference(data['run_ref'])
    require(ref['kind'] == 'run' and ref['identity'][0] == data['workflow_root_id'],
            'suffix run belongs to another root')
    if data['source_plan_ref'] is None:
        require(data['source_plan_sha256'] is None and data['generation'] == 1
                and data['drain_control_id'] is None, 'suffix lacks its declared source plan')
    else:
        ref = _reference(data['source_plan_ref'])
        require(ref['kind'] == 'source-plan' and ref['identity'][:2] == [data['workflow_root_id'], data['generation']],
                'suffix plan belongs to another root or generation')
    route = data['source_plan_owner_route']
    require(route is None or isinstance(route, dict) and set(route) == FIELDS - CURRENT_PLAN
            and route['version'] == 2 and route['workflow_root_id'] == data['workflow_root_id'],
            'suffix plan owner has a malformed native route')
    if data['canonical_ref'] is not None:
        ref = _reference(data['canonical_ref'])
        require(ref['kind'] == 'canonical' and ref['identity'][0] == data['workflow_root_id'],
                'suffix canonical subject belongs to another root')
    if data['suffix_input_plan_ref'] is not None:
        ref = _reference(data['suffix_input_plan_ref'])
        require(ref['kind'] == 'source-plan' and ref['identity'][0] == data['workflow_root_id']
                and ref['identity'][1] <= data['generation'], 'suffix input plan belongs to another root or generation')
    for key in ('run_sha256', 'check_policy_sha256', 'source_plan_sha256', 'canonical_sha256', 'suffix_input_plan_sha256'):
        require((key in ('source_plan_sha256', 'canonical_sha256', 'suffix_input_plan_sha256') and data[key] is None)
                or isinstance(data[key], str) and re.fullmatch('[0-9a-f]{64}', data[key]),
                'suffix authority fingerprint is malformed')
    require((data['canonical_ref'] is None) == (data['canonical_sha256'] is None), 'suffix canonical authority is partial')
    require((data['suffix_input_plan_ref'] is None) == (data['suffix_input_plan_sha256'] is None), 'suffix input plan authority is partial')
    return data


def validate(continuation, rows, *, store_ref, workflow_root_id, claimed_step_id=None, require_reference=False,
             _owner_checked=False):
    from workspace_entry import healthy, native_root, reference
    from workspace_store import CONTINUATION_KEY, MISSING, WorkspaceStore, _exact_root, _metadata_record, require
    data = continuation.binding
    require(data['workflow_root_id'] == workflow_root_id and data['store_ref'] == store_ref,
            'suffix belongs to another logical root/store')
    require(all(key in rows and rows[key]['id'] == key for key in continuation.row_ids),
            'suffix native row union is incomplete')
    root, physical, suffix, intake, convoy, anchor = (rows[data[key]] for key in
        ('workflow_root_id', 'child_root_id', 'suffix_root_id', 'suffix_input_convoy_id',
         'implementation_convoy_id', 'source_anchor_id'))
    for row in (root, physical, suffix, intake, convoy, anchor):
        healthy(row)
        require(all(row['metadata'][key] == store_ref for key in ('gc.root_store_ref', 'gc.source_store_ref')
                    if key in row['metadata']), 'suffix relationship changed native store')
    for row in (root, physical, suffix):
        require(row['metadata'].get('gc.kind') == 'workflow'
                and row['metadata'].get('gc.root_store_ref') == store_ref
                and all(row['metadata'][key] == row['id'] for key in ('workflow_id', 'molecule_id', 'gc.root_bead_id')
                        if key in row['metadata']), 'suffix relationship is not an exact native workflow root')
    if claimed_step_id is not None:
        require(physical['status'] != 'closed' and suffix['status'] != 'closed', 'physical suffix workflow is no longer active')
    require(suffix['metadata'].get('gc.input_convoy_id') == data['suffix_input_convoy_id']
            and physical['metadata'].get('gc.input_convoy_id') == data['unit_convoy_id']
            and root['metadata'].get('gc.input_convoy_id') == data['implementation_convoy_id']
            and intake['type'] == convoy['type'] == 'convoy', 'suffix native input relationship changed')
    for row in (suffix, physical, intake):
        hint = row['metadata'].get('gc.var.worktree_run_root')
        require(hint in (None, '', workflow_root_id), 'suffix selector conflicts with the native source root')
    for row in (suffix, physical):
        for key, default in (('worktree_parent', ''), ('worktree_name_prefix', ''),
                             ('worktree_allow_external_parent', 'false')):
            configured = 'gc.var.' + key
            require(row['metadata'].get(configured, root['metadata'].get(configured, default))
                    == root['metadata'].get(configured, default), 'suffix changed the recorded workspace layout')
    run_ref = reference(root['metadata'].get('gc.implementation_run_ref'), 'run')
    run_row = rows[data['run_ref']['bead_id']]
    WorkspaceStore._dedicated(run_row)
    run = _metadata_record(run_row, contracts()['run']['metadata_key'])
    validate_record('run', run)
    require(run_ref == data['run_ref'] and list(record_identity('run', run)) == run_ref['identity']
            and record_sha256(run) == data['run_sha256'] and run['worktree_lifecycle'] == 'new'
            and run['source_anchor_id'] == data['source_anchor_id']
            and run['input_convoy_id'] == data['run_input_convoy_id'], 'suffix recorded run changed')
    require(anchor['metadata'].get('gc.synthetic') != 'true'
            and native_root(anchor) in (None, workflow_root_id), 'suffix source anchor changed')
    input_ref = data['suffix_input_plan_ref']
    if input_ref is not None:
        input_row = rows[input_ref['bead_id']]
        WorkspaceStore._dedicated(input_row)
        input_plan = _payload(input_row, 'source-plan')
        input_owner = rows[input_plan['source_plan_owner_id']]
        require(list(record_identity('source-plan', input_plan)) == input_ref['identity']
                and record_sha256(input_plan) == data['suffix_input_plan_sha256']
                and _metadata_record(input_owner, 'gc.source_plan_ref') == input_ref
                and intake['metadata'].get('gc.source_plan_owner_id') == input_owner['id']
                and intake['metadata'].get('gc.source_plan_sha256') == data['suffix_input_plan_sha256']
                and _exact_root(intake, workflow_root_id)
                and intake['metadata'].get('gc.root_store_ref') == store_ref
                and intake['metadata'].get('gc.source_root_id') == workflow_root_id
                and intake['metadata'].get('gc.source_generation') == str(input_plan['generation']),
                'suffix native input plan changed')
        if input_ref != data['source_plan_ref']:
            require(physical['metadata'].get(CONTINUATION_KEY) == reference_bytes(data).decode()
                    and input_plan['generation'] < data['generation'],
                    'fresh suffix input is not the currently selected source generation')
    else:
        require(not intake['metadata'].get('gc.source_plan_owner_id'), 'suffix omitted its native input plan')
    direct = intake['id'] in (run['input_convoy_id'], data['implementation_convoy_id']) or input_ref is not None
    if not direct:
        require(intake['metadata'].get('gc.synthetic') == 'true'
                and intake['metadata'].get('gc.source_bead_id') == run['source_anchor_id']
                and suffix['metadata'].get('gc.source_bead_id') == run['source_anchor_id'],
                'suffix selector does not match the actual native source task/convoy')
    if data['source_plan_ref'] is None:
        require(convoy['id'] == run['input_convoy_id'] and not convoy['metadata'].get('gc.source_plan_owner_id'),
                'suffix omitted a declared source plan')
    else:
        plan_ref = data['source_plan_ref']; plan_row = rows[plan_ref['bead_id']]
        WorkspaceStore._dedicated(plan_row)
        plan = _metadata_record(plan_row, contracts()['source-plan']['metadata_key'])
        validate_record('source-plan', plan)
        owner = rows[plan['source_plan_owner_id']]
        require(list(record_identity('source-plan', plan)) == plan_ref['identity']
                and record_sha256(plan) == data['source_plan_sha256']
                and _metadata_record(owner, 'gc.source_plan_ref') == plan_ref
                and convoy['metadata'].get('gc.source_plan_owner_id') == owner['id']
                and convoy['metadata'].get('gc.source_plan_sha256') == data['source_plan_sha256']
                and root['metadata'].get('gc.build.implementation_convoy_id') == convoy['id'],
                'suffix source-plan reference or payload changed')
        for row in (owner, convoy):
            native_owner = (row is owner and _owner_checked and _exact_root(owner, physical['id']))
            if row is owner and not _exact_root(row, workflow_root_id) and not _owner_checked:
                route = data['source_plan_owner_route']
                require(route is not None and route['child_root_id'] == native_root(owner), 'suffix plan owner route is missing')
                from workspace_store import NativeRunContinuation
                owner_data = dict(route, **{key: data[key] for key in CURRENT_PLAN})
                owner_data['source_plan_owner_route'] = None
                validate(NativeRunContinuation(canonical_bytes(owner_data)), rows, store_ref=store_ref,
                         workflow_root_id=workflow_root_id, require_reference=True, _owner_checked=True)
                native_owner = True
            require((_exact_root(row, workflow_root_id) or native_owner) and row['metadata'].get('gc.root_store_ref') == store_ref
                    and row['metadata'].get('gc.source_root_id') == workflow_root_id
                    and row['metadata'].get('gc.source_generation') == str(data['generation']),
                    'suffix plan belongs to another native root/store/generation')
    policy = _metadata_record(run_row, 'gc.workspace_required_checks.v1')
    from workspace_run import capture_check_policy
    expected = capture_check_policy(run, run_ref['bead_id'], canonical_bytes({'required_checks': policy['required_checks']}).decode())
    require(policy == expected, 'suffix captured check policy identity, base or digest changed')
    for row in (suffix, physical):
        requested = row['metadata'].get('gc.var.worktree_checks')
        require(requested in (None, '') or capture_check_policy(run, run_ref['bead_id'], requested) == policy,
                'suffix requested a different captured check policy')
    configured = root['metadata'].get('gc.var.worktree_checks')
    require(configured is None or capture_check_policy(run, run_ref['bead_id'], configured) == policy,
            'suffix configured check policy differs from its captured policy')
    require(hashlib.sha256(canonical_bytes(policy)).hexdigest() == data['check_policy_sha256'],
            'suffix captured check policy changed')
    if data['canonical_ref'] is not None:
        canonical_ref = reference(root['metadata'].get('gc.canonical_ref'), 'canonical')
        canonical = _metadata_record(rows[canonical_ref['bead_id']], contracts()['canonical']['metadata_key'])
        validate_record('canonical', canonical)
        require(canonical_ref == data['canonical_ref'] and record_sha256(canonical) == data['canonical_sha256']
                and list(record_identity('canonical', canonical)) == canonical_ref['identity'], 'suffix canonical subject changed')
    if root['status'] == 'closed':
        require(root['metadata'].get('gc.outcome') == 'pass' and data['source_plan_ref'] is not None
                and data['canonical_ref'] is not None,
                'completed logical workflow has no accepted recorded subject')
        require(canonical['workflow_root_id'] == workflow_root_id
                and canonical['generation'] in (data['generation'], data['generation'] - 1),
                'completed logical workflow subject changed')
        if canonical['generation'] == plan['generation']:
            require(canonical['source_plan_owner_id'] == plan['source_plan_owner_id']
                    and canonical['workspace_owner_id'] == plan['terminal_owner_id'],
                    'completed logical workflow has a different accepted terminal subject')
        else:
            require(plan['parent_canonical_generation'] == canonical['generation']
                    and plan['base_oid'] == plan['parent_canonical_oid'] == canonical['output_oid'],
                    'completed logical workflow lost its exact fix parent')
    if data['drain_control_id'] is not None:
        control, unit, member = (rows[data[key]] for key in ('drain_control_id', 'unit_convoy_id', 'member_id'))
        for row in (control, unit, member): healthy(row)
        require(control['metadata'].get('gc.kind') == 'drain' and _exact_root(control, suffix['id'])
                and control['metadata'].get('gc.root_store_ref') == store_ref
                and unit['type'] == 'convoy' and unit['metadata'].get('gc.synthetic_kind') == 'drain-unit-convoy'
                and unit['metadata'].get('gc.parent_convoy_id') == intake['id']
                and all(row['metadata'].get('gc.drain_control_id') == control['id']
                        and row['metadata'].get('gc.drain_member_id') == member['id'] for row in (physical, unit))
                and _exact_root(member, workflow_root_id) and member['metadata'].get('gc.root_store_ref') == store_ref
                and member['metadata'].get('gc.source_root_id') == workflow_root_id
                and member['metadata'].get('gc.source_generation') == str(data['generation'])
                and sum(member['id'] in node['member_ids'] for node in plan['nodes']) == 1,
                'suffix actual drain control/unit/member relationship changed')
    native_ref = physical['metadata'].get('gc.implementation_run_ref', MISSING)
    context = physical['metadata'].get(CONTINUATION_KEY, MISSING)
    if native_ref is MISSING and context is MISSING:
        require(not require_reference, 'suffix inherited reference has not been published')
    else:
        require(native_ref == canonical_bytes(data['run_ref']).decode()
                and context == reference_bytes(data).decode(), 'suffix inherited reference is partial or changed')
    if claimed_step_id is not None:
        claim = rows[claimed_step_id]
        require(_exact_root(claim, physical['id']) and claim['metadata'].get('gc.root_store_ref') == store_ref,
                'claimed occurrence is outside the proven physical suffix root/store')
    return data


def read(store, *, claimed_step_id, requested_root_id=None, recorded_root_id=None, observed_rows=None):
    from workspace_entry import healthy, native_root, reference
    from workspace_store import CONTINUATION_KEY, NativeRunContinuation, require
    require(observed_rows is None or isinstance(observed_rows, dict) and not observed_rows,
            'suffix observations must start empty')
    rows = {} if observed_rows is None else observed_rows
    def get(bead_id):
        require(isinstance(bead_id, str) and bead_id and bead_id == bead_id.strip(), 'suffix has no exact native relationship ID')
        if bead_id not in rows: rows.update(store.snapshot([bead_id]))
        healthy(rows[bead_id]); return rows[bead_id]
    claim = get(claimed_step_id); physical = get(native_root(claim)); suffix = physical
    control_id = physical['metadata'].get('gc.drain_control_id')
    unit = get(physical['metadata'].get('gc.input_convoy_id'))
    if control_id:
        control = get(control_id); suffix = get(native_root(control))
        if 'gc.implementation_run_ref' in suffix['metadata'] and CONTINUATION_KEY not in suffix['metadata']:
            return None
    intake = get(suffix['metadata'].get('gc.input_convoy_id'))
    published = parse_record(suffix['metadata'][CONTINUATION_KEY]) if CONTINUATION_KEY in suffix['metadata'] else {}
    candidates = [recorded_root_id, intake['metadata'].get('gc.source_root_id'),
                  suffix['metadata'].get('gc.var.worktree_run_root'), published.get('workflow_root_id')]
    if requested_root_id not in (None, physical['id'], suffix['id']): candidates.append(requested_root_id)
    candidates = set(value for value in candidates if value)
    if not candidates: return None
    require(len(candidates) == 1, 'suffix selectors conflict with the native source root')
    root_id = candidates.pop()
    if root_id in (physical['id'], suffix['id']): return None
    root = get(root_id)
    require(requested_root_id in (None, root_id, physical['id'], suffix['id']), 'suffix continues another requested workflow')
    run_ref = reference(root['metadata'].get('gc.implementation_run_ref'), 'run')
    run_row = get(run_ref['bead_id']); run = parse_record(run_row['metadata'][contracts()['run']['metadata_key']])
    validate_record('run', run)
    get(run['source_anchor_id']); get(run['input_convoy_id'])
    convoy = get(root['metadata'].get('gc.input_convoy_id'))
    plan_ref = None; plan = None; owner_route = None
    if convoy['metadata'].get('gc.source_plan_owner_id'):
        owner = get(convoy['metadata']['gc.source_plan_owner_id'])
        plan_ref = reference(owner['metadata'].get('gc.source_plan_ref'), 'source-plan')
        plan = parse_record(get(plan_ref['bead_id'])['metadata'][contracts()['source-plan']['metadata_key']])
        validate_record('source-plan', plan)
        if native_root(owner) != root_id:
            owner_root = get(native_root(owner))
            require(CONTINUATION_KEY in owner_root['metadata'], 'source plan owner has no published native suffix route')
            owner_route = parse_record(owner_root['metadata'][CONTINUATION_KEY])
            require(set(owner_route) == FIELDS - CURRENT_PLAN, 'source plan owner route is malformed')
            for key in ('child_root_id', 'suffix_root_id', 'unit_convoy_id', 'suffix_input_convoy_id',
                        'drain_control_id', 'member_id', 'source_anchor_id', 'run_input_convoy_id'):
                if owner_route[key] is not None: get(owner_route[key])
            if owner_route['suffix_input_plan_ref'] is not None:
                get(owner_route['suffix_input_plan_ref']['bead_id'])
                get(owner_route['suffix_input_plan_ref']['identity'][2])
    canonical_ref = None; canonical_sha256 = None
    if root['metadata'].get('gc.canonical_ref'):
        canonical_ref = reference(root['metadata']['gc.canonical_ref'], 'canonical')
        canonical = parse_record(get(canonical_ref['bead_id'])['metadata'][contracts()['canonical']['metadata_key']])
        validate_record('canonical', canonical); canonical_sha256 = record_sha256(canonical)
    input_plan_ref = None; input_plan_sha256 = None
    if intake['metadata'].get('gc.source_plan_owner_id'):
        input_owner = get(intake['metadata']['gc.source_plan_owner_id'])
        input_plan_ref = reference(input_owner['metadata'].get('gc.source_plan_ref'), 'source-plan')
        input_plan = _payload(get(input_plan_ref['bead_id']), 'source-plan')
        input_plan_sha256 = record_sha256(input_plan)
    member_id = physical['metadata'].get('gc.drain_member_id') if control_id else root_id
    get(member_id)
    policy = parse_record(run_row['metadata']['gc.workspace_required_checks.v1'])
    binding = dict(version=2, workflow_root_id=root_id, store_ref=store.store_ref,
        generation=plan['generation'] if plan else 1, child_root_id=physical['id'],
        suffix_root_id=suffix['id'], suffix_input_convoy_id=intake['id'], unit_convoy_id=unit['id'],
        implementation_convoy_id=convoy['id'], drain_control_id=control_id, member_id=member_id,
        source_anchor_id=run['source_anchor_id'], run_input_convoy_id=run['input_convoy_id'],
        run_ref=run_ref, source_plan_ref=plan_ref, run_sha256=record_sha256(run),
        source_plan_sha256=record_sha256(plan) if plan else None,
        source_plan_owner_route=owner_route, canonical_ref=canonical_ref, canonical_sha256=canonical_sha256,
        suffix_input_plan_ref=input_plan_ref, suffix_input_plan_sha256=input_plan_sha256,
        check_policy_sha256=hashlib.sha256(canonical_bytes(policy)).hexdigest())
    continuation = NativeRunContinuation(canonical_bytes(binding))
    validate(continuation, rows, store_ref=store.store_ref, workflow_root_id=root_id, claimed_step_id=claimed_step_id)
    return continuation, rows
