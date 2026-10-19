Execute `gc gc workspace flow canonical` through
[the canonical recording recipe](../workspace-canonical.md) after the accepted
terminal owner output.

For the captured `new` run, select the source plan's single terminal owner-output,
read its qualified final member result and accepted summary, and bind through
`workspace_outputs.prepare_canonical` with guarded exact readback. Reuse identical
producer review through `workspace_review` for terminal approval where its OID,
required scope and artifacts match. Aggregate reporting cannot mint acceptance or
replace the accepted terminal summary hash. Missing, partial or stale results
block. The reporting contract below supplies no additional acceptance.

If an aggregate report is needed, include selected anchors, drain
policy, item result classes, report paths, commit refs when available, and any
operator recovery instructions at a separate explicit artifact path. Direct implement does not run gap-analysis or
review loops. Publish settings are push {{push}} and open_pr {{open_pr}}.

The accepted terminal summary must already use summary_path {{summary_path}}
when that option is set. Otherwise use its exact accepted native artifact path.
Preserve those bytes and their hash. Put any additional aggregate report at a
separate explicit artifact path, without replacing the accepted summary.
Update workflow root metadata
with `gc.implementation.summary_path=<absolute path>` so the optional publish
step has the exact accepted report path to consume. Validate the retained summary
as a `gc.build.implementation-summary.v1` artifact.
The summary body must contain these exact schema-required `##` headings in this
order:

- `## Summary`
- `## Intended Behavior`
- `## Changed Files`
- `## Verification`
- `## Remaining Risks`

Include a Markdown coverage table. The validator only recognizes a table with
an `ID` column and a `Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: implement`. The top-level YAML shape must be:

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
- For source anchor beads, use `path: beads/<bead-id>` and `hash: bead:<bead-id>`.
  For changed files, item summaries, or upstream build artifacts, use
  repo-relative paths and scheme-qualified hashes such as `sha256:<digest>` or
  `git:<revision>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Artifact validation: this step is gated by the pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallback `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. Before closing this step, verify the registered rig through native identity readback and run the validator with that explicit `GC_RIG_ROOT`. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig. Run `GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`; fix every reported validation error before setting `gc.outcome=pass`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and require a qualified replacement result before any change to accepted bytes. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
