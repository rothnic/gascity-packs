Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply
only to explicit `legacy`; the managed instructions govern an admitted `new`
run. Unknown modes or failed reads never authorize legacy fallback.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` run, finish the exact context opened by this
review's setup with `workspace_review.finish_canonical_review`. Supply the
actual report and immutable evidence path after every required methodology
lane completes. The report-only path preserves findings without authorizing
source changes or publication. The approval path must bind the independently
reviewed clean canonical OID, required checks and artifact hashes; a loop
`done` or a schema-valid report alone does not approve a commit.
Publish with `workspace_review.prepare_review_record`, an admitted current
recorder claim, exact owner grant and current native qualification. Execute and
resolve the same prepared `WorkspaceStore` request; require committed/replayed
readback. Drift, unknown writes, missing evidence or a changed generation block.
Do not rewrite accepted summary artifacts during report publication.

Finalize the Compound Engineering code-review expansion.

Verify the latest loop verdict from the apply-review-findings lane.

Report-only path:

- If workflow root metadata `gc.var.review_mode=report`, do not require the
  apply-review-findings lane and do not apply fixes.
- Confirm the synthesized review report exists at workflow root metadata
  `gc.build.code_review_report_path`.
- Preserve the report's own verdict (`approved`, `changes_required`, or
  `blocked`). In report mode, producing the validated report is the successful
  deliverable even when findings require changes.
- Publish the synthesized report as the stage review report (see "Review report
  path" below).
- Update workflow root metadata:
  - `gc.build.code_review_status=reported`
  - `gc.build.code_review_report_path=<synthesized report path>`
- Close this expansion target with `gc.outcome=pass`,
  `code_review.verdict=reported`, and
  `code_review.report_path=<synthesized report path>`.

Approval path for `agent` and `interactive` modes:

- Confirm `code_review.verdict=done` on the apply-review-findings lane.
- Confirm the synthesized review report exists at workflow root metadata
  `gc.build.code_review_report_path`.
- Confirm the review fix summary exists at workflow root metadata
  `gc.build.review_fix_summary_path`.
- Publish the synthesized report as the stage review report (see "Review report
  path" below).
- Update workflow root metadata:
  - `gc.build.code_review_status=approved`
  - `gc.build.code_review_approved_at=<UTC timestamp>`
- Close this expansion target with `gc.outcome=pass`,
  `code_review.verdict=done`, and
  `code_review.report_path=<review fix summary path>`.

Review report path (both passing paths):

The terminal artifact check on this step and the build gate validate the file
recorded at workflow root metadata `gc.build.review_report_path` against
`gc.build.review.v1`. The build prepare stage pre-declares that key as
`<artifact_root>/review-report.md`, which this expansion does not otherwise
write, so publish the review report explicitly before closing:

- Resolve the review report path: use workflow root metadata
  `gc.build.review_report_path` when it is set; otherwise use the synthesized report
  path from `gc.build.code_review_report_path`.
- If the resolved review report path is relative, resolve it against
  `$GC_RIG_ROOT` before copying and recording it.
- If the review report path differs from the synthesized report path, copy the
  synthesized report to it with `mkdir -p "$(dirname "<review report path>")"`
  and `cp -f "<synthesized report path>" "<review report path>"`.
- Record the absolute review report path on the workflow root bead, not on the
  claimed step bead:
  `gc bd update "<workflow-root-id>" --set-metadata "gc.build.review_report_path=<absolute path>"`.
  Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts
  a JSON object.
- From `$GC_RIG_ROOT`, run the artifact validator with the claimed bead id and
  fix any error before setting `gc.outcome=pass`:
  `GC_BEAD_ID=<claimed-step-id> .gc/scripts/checks/build-artifact-valid.sh`.
- On repair attempts (`gc.attempt` greater than 1), first read the validator
  errors from `gc.attempt_log` on the validation loop control bead (the
  dependent of this step bead) and fix every listed error in place.

Failure path:

- If unresolved required findings remain, do not approve the expansion.
- Update workflow root metadata with `gc.build.code_review_status=failed`.
- Close with `gc.outcome=fail`, `code_review.report_path=<review fix summary
  path>`, and a concise `gc.failure_reason` that points at the blocking
  finding.
