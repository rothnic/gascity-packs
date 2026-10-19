For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
Only `new` is supported. Preserve older or unclassified state and follow explicit migration guidance.

Retain `{{worktree_lifecycle}}` from the captured run. Unknown or conflicting
selection blocks with the original state preserved for explicit migration.

For an admitted managed run, read exact run/source-plan/workspace references through
`workspace_outputs.referenced_record` and the recorded input prepared by
`workspace_checkout.py`. Use its authoritative path and native provenance. Missing
or conflicting references block; do not fall back to a launcher or recapture base.

After implementation, freeze actual full HEAD. Construct
`workspace_outputs.result_binding(run, plan, workspace, store_ref=...,
member_id=..., output_oid=...)`. Run `workspace_outputs.execute_checks` in that
checkout with frozen ordered requirement IDs/argv and actual native producer
step/session/attempt. Preserve actual receipts, including failed/skipped/unrun/
setup_failure. Core/pack source checks do not replace project behavior checks.
Include summary and frozen requirement artifacts with their actual hashes.
This step emits test evidence; only `record-result` may publish acceptance after
`independent-acceptance` completes. A summary schema pass supplies no acceptance.

Use `{{summary_path}}` when supplied as the absolute per-item summary path.
When it is empty, select a distinct item summary under the artifact root.
Record the selected path as `gc.implementation.summary_path` on this item's
workflow root before project checks, independent acceptance and result
publication. Those stages must qualify that same path and its exact bytes.
Do not move or rewrite an accepted summary to satisfy a different later option.

Write or update the unaccepted task summary with these schema-required body sections,
using the exact `##` headings below in this order:

- `## Summary`
- `## Intended Behavior`
- `## Changed Files`
- `## Verification`
- `## Remaining Risks`

The `## Verification` section must include both the first verification command
and the final proof command, with the observed pass/fail result.

Write the summary as a `gc.build.implementation-summary.v1` artifact and record
its absolute path on the workflow root bead as `gc.implementation.summary_path`
before closing.
Include a Markdown coverage table. The validator only recognizes a table with
an `ID` column and a `Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.implementation-summary.v1`
- `workflow: {id: <workflow-root-id>, formula: <root-workflow-formula>}`
- `methodology: {pack: gascity, name: build-basic}`
- `producer: {formula: do-work, stage: implement, attempt: <positive integer>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- For the source anchor bead, use `path: beads/<source-anchor-id>` and
  `hash: bead:<source-anchor-id>`. For changed files or upstream build
  artifacts, use repo-relative paths and scheme-qualified hashes such as
  `sha256:<digest>` or `git:<revision>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Artifact validation: this step is gated by the pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. Before closing this step, verify the registered rig through native identity readback and run the validator with that explicit `GC_RIG_ROOT`. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig. Run `GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`; fix every reported validation error before setting `gc.outcome=pass`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
