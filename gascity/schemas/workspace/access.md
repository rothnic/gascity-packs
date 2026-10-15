# Workspace record access

Workflow helpers use the [writer adapter](../../assets/scripts/workspace_store.py)
to publish workspace records through Gas City's native
`beads guarded-metadata-batch` command.
One transaction joins the writer grant, claimed step, payloads and references.
The [record contracts](README.md#identity-and-writers) define the nine payloads.

## Select the city and store

Construct `WorkspaceStore` with explicit local context:

- **`cwd`:** the canonical absolute city directory.
- **`store_ref`:** the configured `city:<name>` or `rig:<name>` store.
- **`common_git_dir`:** the canonical common Git directory for the recorded run.
- **`gc`:** the native binary that supports guarded metadata batches.
- **`timeout`:** the command and lock timeout, in seconds. The default is 30.

The adapter removes inherited city, rig and remote routing variables from native
commands. Physical record IDs come from native Beads creation. Every transaction
uses one selected store and at most 100 distinct physical rows. Unsupported
capabilities and larger transactions refuse without a fallback or split batch.

## Bind the writer

Retain the session, instance token and exact step ID from the successful native
claim. Construct `Attempt` from those values. `Attempt.from_env(claimed_step_id)`
reads the retained session and token. The native command checks the current claim.
An assignee name or trigger bead alone does not authorize a write.

Each grant has four scope fields:

| Field | Meaning |
| --- | --- |
| `workflow_root_id` | Exact native workflow root |
| `generation` | Positive source generation |
| `record_kind` | One of the nine record kinds |
| `writer_scope_id` | The designated owner below |

| Record kind | `writer_scope_id` |
| --- | --- |
| `run` | Workflow root |
| `source-plan`, `canonical` | Source-plan owner |
| `workspace`, `blocker`, `owner-output` | Workspace owner |
| `member-result` | Source member |
| `review` | Review owner |
| `publish` | Publication owner |

Kinds have separate grants even when owner IDs match. A workspace transition may
include a blocker for the same workspace owner. The adapter rejects multiple
physical payloads for one logical record in a batch.

Every operation requires a `CookedWriterMap` through the `writer_map` keyword.
The entry helper constructs
the map from the actual native formula, source hash and physical steps. The
adapter checks each step's root, store, source member, reference and declared
dependencies. Fixed pack responsibilities determine which record kinds the
claimed step can write. Physical steps match the compiled formula's explicit
`gc.step_ref`, or its full step ID when that reference is absent. Dependency
edges still resolve through full compiled IDs. Duplicate or malformed references
are refused.

A native retry or Ralph control and its attempts may share a semantic step ID.
Later controller attachments must join the original compiled seed, exact native
control and frozen source-specification bead. The adapter verifies the complete
contiguous attempt history, native counters and maximum, attachment idempotency,
root, store, source membership, designations and dependencies. Scoped iteration
bodies and their checks retain their exact compiled roles. Reference suffixes
alone never authorize an occurrence.

The frozen specification is read through native `gc bd show --json`; its opaque
revision and exact description are checked against the compiled source and a
second read. The cooked map retains this source binding and opaque revision.
Only the validated native CAS response to that map's own exact request can
advance its observed spec revision. Fresh snapshots and resolve-only readback
cannot advance it. This observation token is separate from the map's semantic
identity, so repeated acknowledged publications retain the same grant identity.
Earlier occurrences must be closed and remain read-only history; only the latest in-progress claimed
writer can publish records. Its control and specification join the atomic guard
set. An explicitly admitted replacement can advance only to the immediate native
attempt with the same source member, expansion and record responsibility.
Logical controls and scope checks cannot write records.

A native scope check may share its body's semantic step ID when it names that
exact body reference. Both occurrences must match the compiled source's scope,
roles, Ralph step, attempt and failure policy, and retain the same dependencies.
The paired scope check has the control role and has no record responsibilities;
the body retains the member role and its declared record responsibilities.

A scoped retry or Ralph control can retain the native setup or member role.
Its scope check targets the logical control, which blocks on the current attempt.
Admission compares these physical `blocks` edges from native `gc bd show` with the
compiled source and the proven attempt history. Both native reads must retain the
original row identities, revisions and metadata. The logical control and scope
check remain read-only. Only that map's validated own CAS can advance the observed
revisions without changing the map identity. The row guards do not provide an
atomic predicate against unrelated dependency-edge edits.

Graph discovery retains at most 4096 original native rows, including the expansion
and source context. Read-only snapshots use batches of at most 100 rows. A listing
that reaches the extra sentinel row is refused rather than accepted as complete.
This read limit is separate from the 100-row atomic transaction limit.

The runtime retains those original context rows separately from its write guards.
Checkpoint, allocation and result helpers use that complete context when validating
the cooked map. Acknowledging an exact committed request advances only its own
affected rows; another read cannot replace an original row with a newer revision.

Native formula previews leave metadata templates unresolved. Writer admission
substitutes the expansion's recorded variables, with formula defaults for absent
variables, before comparing designations. An unresolved variable or a different
physical designation refuses admission.

## Publish a record

Allocate record and grant placeholders as closed, unassigned native beads with
empty metadata. Verify their actual IDs and state. Allocation does not publish
accepted records or references. An uncertain allocation outcome needs readback.

Use the operation that matches the recorded authority:

- **`install_grant`:** atomically installs the first grant and its first payload.
- **`write_records`:** writes or replays under the exact retained writer grant.
- **`accept_replacement`:** explicitly transfers a grant after native admission
  and a proven successor relationship.

Supply `RecordWrite` for each payload and `ReferenceWrite` for each reference.
References contain the kind, full ordered identity and native physical ID. A
reference joins its validated payload in the same batch. Native reference targets
must belong to the same workflow and store.

`expected_rows` retains the complete original snapshot, including the cooked
graph and the operation's grant, claimed step, root, payloads and references.
`GuardRead` compares metadata against the original snapshot. Use `MISSING` for an absent key and `None` for
JSON null. The transaction selects the authority, claim, source and expansion
bindings, records, references, explicit read guards and typed projection targets.
Grant replacement also selects its previous writer and the closed predecessor
path used to authorize the successor, including paired control and attempt rows.
Unrelated graph branches remain read-only context.

Every selected row receives a changing transaction nonce so parent and input
guards participate in native commit ordering. More than 100 required transaction
rows still refuse; mutations are never split into batches. Original context rows
cannot be replaced with newer revisions or different typed metadata.

The prepared request fixes its city, store, common Git directory and original
revisions. `execute` submits that request once. A timeout or malformed response
returns `unknown`. Call `resolve` for exact readback of the original intent.
Readback may report `committed`, `replayed`, `not_committed` or `unknown`. Readback
never writes. An unknown outcome must not trigger another mutation.

## Publish native bindings

Typed projections join their records in the same guarded transaction:

- **`NativeOwnerProjection`:** publishes the matching workspace's native owner
  metadata from complete schema 2 provisioning evidence.
- **`NativeWorktreeReference`:** binds an actual workflow step to that exact
  workspace, store and provisioning attempt.
- **`SourceMembershipProjection`:** declares source membership for an existing
  native node in the published plan. Conflicting membership refuses.
- **`SourcePlanConvoyBinding`:** binds the native implementation convoy to the
  published plan and updates the root's input references together.
- **`RunCheckPolicyProjection`:** captures the configured required checks with
  the initial run record, base commit and native configuration snapshot.

Source projections require the existing native root and store to match. Convoy
binding also requires the original input-convoy guard and recorded run.

New-mode runs require a nonempty `gc.var.worktree_checks` configuration:

```json
{"required_checks":[{"argv":["go","test","./..."],"id":"unit"}]}
```

Check IDs must be unique. Each check supplies an explicit argument list. The
projection stores the canonical policy and its hash in
`gc.workspace_required_checks.v1` on the run record. Later writers consume this
captured policy. A result manifest cannot supply or replace the required checks.
Replay retains the exact policy bytes. Replay cannot add a policy to an existing
run.

## Resume and recover

Immutable records require exact payload replay. Replay retains the first writer's
payload fields and checks the current grant. Workspace phase transitions retain
stable owner, path and native provisioning identity. Publication transitions
retain their original intent and authorization. A blocker resolution retains
the original observation and adds an explicit decision.

When a workspace blocks, its transaction publishes the matching open blocker and
retains the checkpoint.
Resume requires the guarded blocker reference, a resolved decision and its exact
paused phase and member. The resumed HEAD must match the recorded decision.

Another failure can create a new dedicated blocker after the previous blocker was resolved.
The transaction guards the resolved record and publishes the new open blocker with its blocked workspace.
Previous blocker observations and decisions remain unchanged.

Grants retain the cooked map hash and the original physical writer occurrence.
Grant replacement supports these cases:

- **Same step:** a newly admitted native incarnation retains the same map.
- **Same member:** the original writer has closed. The next designated writer
  follows a declared dependency path whose exact preceding steps have closed.
- **Next shared member:** the source plan names the immediate successor in the
  same single-lane shared chain. The original native writer has closed.

The adapter rejects altered membership, sibling expansions and role assertions.

`transition_locks(common_git_dir, scope)` holds the owner lock before the root
lock. Hold the context around Git work and the guarded record publication.
Nested calls for the same owner reuse the held lock. Lock contention fails at
the configured timeout. Lock files remain in the common
Git directory so Git maintenance does not remove their inodes.

## Runtime boundaries

The adapter admits supported local Linux filesystems for process locks. Native
transactions provide store write ordering. Process locks do not protect another
host, clone, arbitrary direct writer or remote publication effect.

Workflow helpers validate Git state, source-plan relationships, artifact bytes
and acceptance evidence before record publication. Workflow entry requires the
native commands and every writer needed by the selected lifecycle.
