Execute `gc gc workspace flow canonical` through
[the canonical recording recipe](../workspace-canonical.md) after the accepted
terminal owner output.

Record the accepted canonical build implementation summary.

For the captured `new` run, read the exact source plan's terminal owner-output and
qualified final member result through the native adapter. Bind its already accepted
terminal summary with `workspace_outputs.prepare_canonical`, then execute/read back
the frozen request before review. An aggregate human summary may reference that
accepted artifact; it cannot replace its hash with newly written unreviewed bytes.
No missing terminal result, multiple unintegrated outputs or stale parent generation
may proceed. Never infer acceptance from closed anchors. The reporting contract
below must preserve the accepted terminal summary's path, bytes and hash.

This build-base stage may be inherited by concrete build methodology packs.
Concrete build methodology packs may override this stage, but any override must
preserve the root implementation-summary artifact contract.

The implementation drain may write one or more per-item summaries from source
worktrees. Resolve the accepted terminal summary through the exact native result.
Record its path as `gc.build.implementation_summary_path`. The conventional name
`implementation-summary.md` does not select another artifact or permit a copy
to replace the qualified summary.

Resolve the workflow root through native readback. Set
`gc.build.implementation_summary_path` to the exact absolute path in the
committed or replayed canonical binding, even when an earlier unqualified
placeholder suggested `implementation-summary.md`. This reporting key cannot
select or replace an artifact. A conflicting current qualified canonical
binding, missing accepted artifact or changed bytes/hash blocks finalization:

`gc bd update "<workflow-root-id>" --set-metadata "gc.build.implementation_summary_path=<absolute path>"`

Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts a JSON
object.

Use source anchor ids, drain child workflows and per-item summary paths as
reporting context. Their raw metadata cannot replace the native accepted result.
The accepted summary must cover all accepted requirement IDs. Missing coverage
requires a qualified replacement result with new checks and independent review.
An optional aggregate human report must use a separate explicit artifact path.
It cannot change the accepted summary or supply missing acceptance.

Validate the accepted artifact as Markdown with YAML front matter, not JSON. Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.implementation-summary.v1`
- `workflow: {id: <accepted-workflow-id>, formula: <accepted-workflow-formula>}`
- `methodology: {pack: <accepted-pack>, name: <accepted-methodology>}`
- `producer: {formula: <accepted-producer-formula>, stage: <accepted-producer-stage>, attempt: <accepted-attempt>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Preserve the accepted member's original workflow, methodology, producer and trace
fields. Do not restamp them as this aggregate stage or repair accepted bytes to
fit an aggregate template. A separate optional report may name this stage as its
own producer; it supplies no acceptance for the retained summary.

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- For upstream build artifacts or implementation summaries, use their recorded
  paths and scheme-qualified hashes such as `sha256:<digest>`. For convoy or
  bead inputs, use `path: beads/<bead-id>` and `hash: bead:<bead-id>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Include a Markdown coverage table whose ID/status pairs exactly match
`trace.coverage`. The validator only recognizes a Markdown table with an `ID`
column and a `Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

The body must include these schema-required sections:

- Summary
- Intended Behavior
- Changed Files
- Verification
- Remaining Risks

Verify that those sections cover the implementation convoy id, source anchor ids,
per-item summary paths, changed files, first verification commands, final proof
commands, observed pass/fail results, and remaining risks. Missing accepted
requirement IDs block finalization.

Before closing this step, verify the registered rig through native identity readback and run the validator with that explicit `GC_RIG_ROOT`. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig:

`GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`

fix every reported validation error before setting `gc.outcome=pass`. A repair
to accepted bytes requires a qualified replacement result. Then set
the claimed step outcome with
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, and close
with `gc bd close "<claimed-step-id>" --reason "<concise reason>"`. Do not pass
`--metadata` or `--set-metadata` to `gc bd close`.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.implementation_summary_path` against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead). Preserve accepted bytes until a qualified replacement result is available. Two bounded repair attempts follow the first failure. Exhaustion closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode. Record unresolved ambiguity in a separate diagnostic report.
