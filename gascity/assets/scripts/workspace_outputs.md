# Qualified source outputs, review and publication

An accepted workspace result binds required project behavior checks and an
independent native review to one exact commit, input, repository, store, workflow
root, source generation, owner, member and artifact set. Closing a work item or
containing its ancestors does not establish acceptance.

The `workspace_flow.py` callable and installed `gc gc workspace flow` command
connect these helpers to `NativeSourceRuntime`. Required policy and physical
identities come from native records. Legacy remains the default. Native workflow
acceptance at matched core/pack/project revisions remains separate from component
fixtures and source validation.

## Producer completion

`workspace_outputs.result_binding(run, plan, workspace, *, store_ref, member_id,
output_oid)` validates the recorded scope and retained native workspace provenance.
Construct this binding from independently read records, never from a result's
claimed evidence. Native ownership/attempt verification remains required.

The producer sequence is:

1. `execute_checks(binding, work_dir, required_checks, producer, evidence_dir)`
   executes ordered `{id, argv}` requirements without a shell. Each receipt retains
   actual status, exit, stdout/stderr, clean before/after HEAD, scope and producer
   identity. Freeze the required policy before execution. Pack/core source checks
   cannot replace the project's requirement assertions.
2. An independent native reviewer calls `begin_review(...)`, inspects the source,
   behavior, actual checks and artifacts, and writes a report. `complete_review(...)`
   rereads source/hashes and writes immutable evidence. Report/agent modes do not
   change source. Interactive edits require replacement output checks and review.
3. `make_member_result(binding, *, writer_step_id, commit_oids, checks, review,
   artifacts, required_checks, artifact_root, work_dir)` emits acceptance only after
   all required checks actually pass and independent review completes. The admitted
   recorder can differ from the actual producer and reviewer. Changed results name
   every actual input-to-output commit; no-change results retain input/output equality
   and an empty commit list. Squash/cherry-pick delivery uses its canonical OID.

Identity objects contain exactly `step_id`, `session_id`, and `attempt_id` from
actual native state. Instance tokens do not enter result artifacts. Execution and
review manifests preserve `passed`, `failed`, `skipped`, `unrun`, `setup_failure`.
The existing v1 review record maps skipped/setup_failure to pending; the hashed
manifest retains the precise status. Only passed execution/review supplies credit.

`validate_accepted_result(result, *, plan, store_ref, repo_dir, artifact_root,
required_checks, native_evidence)` is the consumer API. The native qualifier supplies
an independently resolved `result_binding`, current scope/HEAD/clean/native attempt,
recorder identity, and actual producer/reviewer step/session/attempt identities.
The helper compares them to the hashed manifests and frozen policy. The producer
API instead supplies `binding` and optionally `work_dir` directly; callers must
not use that component-only route to omit native qualification at consumption.

`make_owner_output(plan, results, *, artifact_root, qualifications,
integration_inputs=None, integration_evidence=None)` verifies every member using
`qualifications[member_id] = {binding, required_checks}`. Shared checkpoints must
be contiguous. Integration keeps the declared predecessor order and hashes; the
integration receipt names the merged **input**, while C's output may include its
own further changes. Its output needs fresh checks/review.

## Canonical state and fixes

`canonical_payload(...)` selects the plan's single terminal owner, validates its
qualified final result, and binds the accepted terminal summary hash. An aggregate
human summary may point to this evidence; it cannot replace the accepted summary
with unreviewed bytes. Multiple unintegrated terminals, missing results, changed
hashes and conflicting pointers refuse. Each canonical generation is immutable.

`begin_canonical_review` and `finish_canonical_review` bind the exact canonical
record hash. Existing producer review can be reused at identical OID, required
scope and artifact bindings, preserving its original reviewer identity. A different
reviewer must complete a report. Dirty/wrong-OID/changed-artifact approval refuses.

`workspace_review.fix_plan` records the next plan at the current canonical OID with
explicit parent generation/OID. `validate_fix_parent` and canonical publication
must see that parent still current. X approval cannot approve Y. Y requires actual
project checks and independent review; iteration exhaustion remains a blocker.

## Guarded native records

The store-facing functions are `prepare_member_result`, `prepare_owner_output`,
`prepare_canonical`, `prepare_review_record` and `prepare_publication_record`.
They resolve exact native record references, validate domain evidence and return
a frozen `WorkspaceStore` request. Physical record IDs and separate grants must
already be allocated by the existing native workflow. An explicitly authorized
`initial_write=True` installs the first grant and first validated payload together
in one guarded batch. It refuses existing authority/payload adoption. Later writes
use the retained admitted grant; replacement authority belongs to the native writer.
No helper invents IDs, claims work, installs a replacement grant or writes raw metadata.

Writer scope contains `workflow_root_id`, `generation`, `writer_scope_id` and
explicit `record_kind`. Every store-facing prepare function also requires the
actual `CookedWriterMap` from `workspace_cooked.read_cooked_writer_map` via
`writer_map`. Its expansion, source member and every physical step are included
in the guarded rows. The adapter checks fixed writer responsibility and native
dependency/closed-predecessor facts; no guessed role map is accepted. The actual
native qualifier also retains `guard_rows`:
original full root/producer/reviewer/recorder/workspace snapshots. The qualifier's
`current_generation` must come from the root's actually selected current source
plan/convoy, with that original row fenced too. An old generation cannot rebind a
temporarily missing current pointer after a newer plan is selected. The request keeps
their revision, status, assignee and metadata, plus guarded run/plan/input/result/
canonical pointers and payloads. Keep these snapshots in memory; they may contain
private grant metadata and must not become public artifacts.

Execute through `WorkspaceStore.execute`, then classify the same frozen intent
with `resolve`. Only exact committed/replayed readback permits progress. Unknown
outcomes do not retry. Result-written/output-pointer-missing and immutable
canonical-written/current-pointer-missing partials reuse the same physical identity
and bytes. A stale writer cannot refresh its guards to overwrite newer state.

## Publication

`workspace_publish.publication_intent(...)` consumes exact canonical approval and
a hashed existing authority decision. The decision schema is
`gc.workspace.publication-authority.v1` with `binding`, `canonical_sha256`,
`review_sha256`, `remote`, `remote_url`, full branch `ref`, frozen
`expected_remote_oid` (null means create-if-absent), and boolean `push`/`open_pr`.
PR authority additionally supplies `pr_spec = {repo, base, actor, mode, marker}`.
Existing protected-target, credential-scope and sanitized-content policy still
applies in the owning adapter. The helper never creates that authority.

`push_publication(..., persist, current)` rereads approval/source/authority, persists
uncertainty before an explicit `OID:ref` lease-safe push, and compares actual remote
readback. `persist` must return `{outcome: committed|replayed, record_sha256}` from
the native write/readback. `current` reads the actual canonical pointer. Unknown
remote state blocks before effects; lost command responses reconcile the same
intent. An uncertain intent only reads back and never pushes again. Immutable
blocker/readback artifacts preserve unresolved outcomes and prohibit retries.

Provider queries and PR creation remain outside the helper. After exact Git
readback, `reserve_pr_attempt` checks current approval/authority and atomically
reserves one creation marker. Only its first successful reservation permits the
adapter's single effect. Later calls reconcile provider state with
`reconcile_publication`: exact marker/repo/base/actor/mode/head OID and one URL are
required. Missing, foreign or ambiguous readbacks remain uncertain. Observed PR
record publication additionally requires an actual provider readback callback.

## Checks

The read-only component validator requires explicit files and the exact checkout:

```sh
python3 assets/scripts/workspace_outputs.py \
  --result /private/result.json --binding /private/binding.json \
  --required-checks /private/check-policy.json \
  --artifact-root /private/evidence --work-dir /owned/project-worktree
```

The policy file contains `required_checks: [{id, argv}]`. This command validates
supplied evidence; it neither writes native records nor enables a workflow.

```sh
python3 -m unittest discover -s gascity/tests -p test_workspace_results.py -v
```

Fixtures use real Git repositories/local bare remotes, executed Python requirements,
an explicit native batch protocol double and a deterministic provider fixture.
They do not run a controller/database, authenticated model workers, installation,
external publication or full worker workflow acceptance.
