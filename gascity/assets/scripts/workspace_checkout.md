# Managed checkout preparation and recovery

`workspace_checkout.py` consumes a captured `new` run and a durable workspace
record. It provisions through native `gc worktree ensure` and verifies through
`gc worktree verify`. It never resolves a default branch, fetches source, creates
physical record IDs, claims work, replaces a writer grant or removes a checkout.

The helper is an opt-in source component. Existing workflow preflights still
classify their source paths as `legacy` and reject `new`. Enabling a workflow
requires the composed core/pack checks, source-inventory admission and actual
native launch/resume acceptance. A passing command-double test supplies component
evidence only.

## Callable API

`WorkspaceCheckout(run, workspace, *, store_ref, evidence_dir, parent=None,
allow_external_parent=False, gc="gc", city_root=None, timeout=15, lock_timeout=2)`
provides the Git/native component operations:

- `prepare()` admits preparing/absent or registered/exact-input state and returns
  an `entry` workspace candidate, full native report, owner projection and launch
  reference. It does not publish lifecycle records.
- `verify()` requires recorded provenance, the same native attempt, a clean
  checkout, no Git operation and HEAD equal to the recorded checkpoint.
- `path()` returns the verified absolute implementation directory.
- `continuation()` observes unfinished partial work under native provisioning,
  linear checkpoint ancestry and active-operation checks. Use the managed caller
  below for native claim and cooked occurrence admission.
- `status()` returns the observation or an explicit blocked result with evidence.
- `recover(member_id=..., result=None, result_unrecorded=False, writer_step_id=None)`
  replays a known partial. An exact member result can complete its pending workspace checkpoint.
  `result_unrecorded=True` requires an explicit result declaration; it does not
  infer a result or acceptance from HEAD. An unrecorded result requires the exact
  native producer `writer_step_id`, distinct from the logical member when routed.

`load_workspace_context(store, ...)` reads the exact run, plan and workspace
references, original source identity and declared active member. It reuses
`workspace_entry.read_entry` to distinguish the immutable original run from the
current implementation convoy after decomposition. It fences the exact original
source, current convoy, source plan and optional canonical rows without recapturing
a base. It revalidates that frozen snapshot through `workspace_source_plan`.
The optional `writer_map`, `writer_rows` and `source_rows` arguments carry the
actual `CookedWriterMap` and full original snapshots. Conflicting later reads
refuse. The reader also compares the captured required-check sidecar with the
original run and native configuration.

`manage_workspace(store, attempt=None, *, action, gc, city_root, rig_name,
workflow_root_id, input_convoy_id, run_record_id, plan_record_id,
workspace_record_id, evidence_dir, selected_mode, claimed_step_id=None, parent=None,
allow_external_parent=False, authority_id=None, launch_step_ids=(),
result_record_id=None, declared_result=None, result_authority_id=None,
blocker_record_id=None, blocker_id=None, writer_map=None, writer_rows=None,
source_rows=None, artifact_root=None, native_runtime=None)` is the durable caller. The `store` is a
`workspace_store.WorkspaceStore`; `attempt` is its retained native `Attempt`.

[`workspace_dependency.py`](workspace_dependency.py) supplies the production
front door. It selects actual accepted inputs, creates the first `preparing`
payload/reference/grant atomically, calls this helper and records declared
integration. The preparation prompt calls that bridge directly.
Preparation first checks admission and all original source rows in a guarded transaction. It then
provisions/verifies the fixed input and atomically publishes the workspace record,
`NativeOwnerProjection` and `NativeWorktreeReference` for each actual launch step.
It reads the transaction back and verifies Git again before returning the path.
Read-only actions make no record writes.

Every publication uses the actual typed writer map and original rows. When the
map is omitted, `workspace_cooked.read_cooked_writer_map` discovers it from the
native formula and physical occurrences. `writer_rows` advances in place only
from an exact successful acknowledgement of this caller's guarded transaction.
An actual `NativeSourceRuntime` supplied by the bridge receives that same
`PreparedWrite` through `advance_written_rows`. A new result authority joins its
first payload and reference through `install_grant`. An empty grant cannot adopt
an existing workspace.

`action="continue"` returns a read-only path for the exact current same-member
occurrence, including `write-failing-test` and `implement-story`. It requires a
retained native `Attempt`, exact current owner authority and `artifact_root`, or
the bridge's actual `native_runtime`. The cooked map, dependency path, closed
prior writer, native sessions, owner projection, consumer reference, attempt,
generation and policy must agree. Read-only map admission grants no write role.

Continuation permits dirty edits and linear commits after the checkpoint. It
returns `accepted=false` and `checkpoint_required=true`. The recorded member,
input, current OID and writer remain unchanged. Results and checkpoints still
precede logical advancement. Native claim/source/session and Git state are
rechecked before the path returns.

Active merge/rebase/bisect/cherry-pick state and nonlinear or rewound HEAD refuse
with preserved evidence. Completed integration uses its recorded input checkpoint.
A reset to that same exact checkpoint remains read-only partial state, subject to
the same native claim/owner/policy checks. It earns no result acceptance.

Use actual physical launch-step IDs. Each consumer must retain exact native root,
store and step identity, and bind the declared active member directly or through
its source/drain-member metadata. A workspace record, owner name or successful
helper invocation alone does not establish an actual launch consumer.

Unrecorded result recovery additionally requires the retained native producer
claim, bound to the active member, an allocated result row and an already-admitted
member-scope authority. The producer must retain its exact managed workspace
reference. Result publication precedes the owner checkpoint. If interrupted between them, the
recorded result completes that exact pending checkpoint on replay. A result's
acceptance stays as declared; recovery never awards project or review acceptance.

Provide both blocker IDs to write a dedicated open blocker and mark the workspace
blocked under the current owner grant. The physical blocker row must already
exist as a dedicated nondispatch allocation. A stale/unavailable grant cannot
write a blocker, so private diagnostic evidence also survives independently.
Blocked or unsupported phases require an explicit recovery decision outside this
helper; they cannot silently resume.

## CLI

All actions take these recorded read identities and the exact currently claimed
invoking step (`--claimed-step-id` or native `GC_BEAD_ID`). `path`, `status` and
`verify` need no session token. `continue` reads the retained native session.
These four actions do not mutate records:

```sh
python3 assets/scripts/workspace_checkout.py verify \
  --worktree-lifecycle new --city-root '/registered/city' \
  --rig-name 'project' --store-ref 'rig:project' \
  --workflow-root-id 'workflow-root' --input-convoy-id 'current-implementation-convoy' \
  --claimed-step-id 'actual-invoking-step' \
  --run-record-id 'run-record' --plan-record-id 'plan-record' \
  --workspace-record-id 'workspace-record' \
  --evidence-dir '/private/evidence-outside-checkouts'
```

Use `path` to print only the verified absolute path, `status` for an observation,
or `verify` for the complete evidence envelope. `continue` prints the admitted
partial-work path and requires `--authority-id` plus `--artifact-root` and the
retained native session environment. `prepare` and `recover` also
require `--claimed-step-id`, `--authority-id` and one or more `--launch-step-id`
values. Session ID and incarnation token come from the native environment.
`--parent` retains a nondefault parent; `--allow-external-parent` explicitly admits
an external parent. `--blocker-record-id` and `--blocker-id` enable blocker-record
publication.

For a recorded result awaiting its checkpoint, pass `recover --result-record-id`.
For an explicitly declared unrecorded result, additionally pass
`--declared-result /private/exact-result.json --result-authority-id <authority>`.
The existing result, if present, must replay byte-equivalently under canonical
record encoding. These flags do not establish a new claim or authorize a stale
writer.

The immutable `gc.workspace_required_checks.v1` sidecar must already have joined
initial run capture. Its scope comes from canonical native
`gc.var.worktree_checks={"required_checks":[{"id":"...","argv":["..."]}]}`.
Result manifests cannot redefine that policy. Missing or changed policy blocks
all managed path/publication operations.

## Safety and topology

The ordinary and bare-control-root default parent is `<rig>/worktrees`. A bare
repository whose common Git directory equals the rig root uses
`<rig>/workspaces`, because `<bare>/worktrees` holds Git administration. Direct
children and custom parents are supported by the adapter. Nondefault parents
must already exist. External parents require explicit permission.

Paths must have absolute canonical spelling, no traversal or symlink components,
and one safe child below the selected parent. Registration, common Git directory,
HEAD mode/branch, input and full native provenance must agree. Foreign, locked,
prunable, nested-linked and admin-directory placements refuse without repair.
The helper strips ambient Git routing/configuration variables for both native
commands and direct Git observations.

Native help must advertise the required flags before provisioning. Detached mode
requires `--mode`; ensure requires `--lock-timeout`. Placement beneath a registered rig checkout or bare root requires
concrete native `--placement` support. Placement selection uses observed
Git registrations for all topologies. Verify is lock-free and receives no lock
flag. The detached and bounded-lock candidates require composition with the
placement/owner-reference extensions; unavailable capabilities refuse rather
than falling back to raw Git or another mode.

First entry equals the recorded member input. Native provisioning base and attempt
remain fixed for that physical workspace; later recorded member checkpoints can
be descendants. A recoverable changed result must name every commit in an exact
clean linear chain from its member input to HEAD. Merges, unrelated or unexplained
advanced HEAD, dirty work and merge/rebase/cherry-pick/revert/bisect/sequencer or Git lock state
remain intact and blocked.

Diagnostics are exclusive, mode-600, fsynced JSON files in an existing directory
outside every worktree and the selected repository administration. They retain
expected workspace, observed Git state and exact native argv/stdout/stderr.
Unknown native command completion is never success or an automatic retry.

## Checks

From the repository root:

```sh
python3 -m unittest discover -s gascity/tests -p test_workspace_checkout.py -v
```

The tests use real ordinary/bare/control-root Git fixtures and a narrow native
CLI double. Store caller tests use a separate protocol double. They prove helper
behavior and publication ordering, not actual Beads transaction semantics,
controller launch/wake behavior, authenticated workers or installed rollout.
Final acceptance must bind the composed core, pack and fixture revisions.
