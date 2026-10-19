Resolve `VALIDATOR_PATH` from the same imported Gas City pack as the native
loop's `gc.check_path`: its absolute path is `<check-directory>/../validate_build_artifact.py`.
Require that resolved validator and its pack schemas to exist; never copy a
validator into the rig or select one from a source checkout.

Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Source access requires the recorded `new` lifecycle.
Legacy or unclassified work stops for explicit migration; preserve its original
run and checkout. Do not infer source authority from artifacts or old paths.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` fix, read the current canonical and commit-bound
findings through `workspace_outputs.referenced_record`. Report mode cannot
apply fixes. A no-op retains the exact canonical OID and matching approval.
Source or test changes require `workspace_review.fix_plan(canonical, findings,
previous_plan, writer_step_id=..., source_plan_owner_id=..., nodes=...,
terminal_owner_id=..., max_iterations=...)`. Use native IDs and the configured
bounded retry policy. Publish the declared source-plan using
`workspace_source_plan.declare_plan` and `publish_plan` under the current
admitted claim/owner grant. Retain the exact parent generation/OID; do not edit
the accepted canonical checkout in place or replace a newer parent.

Run the selected methodology's native implementation/fix lanes against that
recorded generation. Use the common checkout, result and canonical APIs for
its tested commit and independent review. A changed pass returns `iterate`;
only a later independent review of the new canonical commit can approve.
Preserve artifacts for both generations. Do not rewrite the old accepted
summary, review or receipt. Any missing native route, grant or helper blocks
with original state retained. Artifact paths grant no source-write authority.

Apply gstack code-review findings.

Use implementation target {{implementation_target}} for any code changes. Read
the review synthesis from workflow root `gc.build.code_review_report_path`. If
all required review lanes approve, write a no-op review-fix artifact. If
required fixes or missing evidence remain, make the smallest focused changes
and run proof commands. Write the review-fix artifact under the artifact root
and record it on the workflow root as `gc.build.review_fix_summary_path`.

Set `code_review.verdict=done` only when staff, QA evidence, security, and gap
analysis approve, and update workflow root metadata with
`gc.build.code_review_status=approved`. Set `code_review.verdict=iterate` when
required fixes remain, and update workflow root metadata with
`gc.build.code_review_status=draft`.

Always close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<review-fix artifact path>`, and
`code_review.output_path=<review-fix artifact path>`.

Keep this attempt's unaccepted draft artifacts schema-valid. The paths at
`gc.build.implementation_summary_path` and `gc.build.code_review_report_path`
identify accepted input artifacts; read them without modifying their bytes,
paths, hashes or producer fields.

An artifact change belongs to the replacement generation declared above. Write
its new summary and review to distinct generation-specific paths before checks,
independent review, result publication and canonical qualification. Schema
validation alone cannot approve a replacement or refresh an accepted hash.

For an unaccepted draft owned by this attempt:

- Preserve the YAML mapping shape for `schema`, `workflow`, `methodology`,
  `producer` and `trace`. Keep `trace.coverage` and the Markdown `ID`/`Status`
  coverage table in sync.
- Implementation-summary status is `draft`, `approved`, `blocked` or
  `superseded`; review status is `draft`, `questions`, `approved`,
  `changes_required`, `blocked` or `superseded`. A status is not acceptance.
- Before closing, validate each new draft with the imported validator:
  `python3 "$VALIDATOR_PATH" --schema gc.build.implementation-summary.v1 --path "<new summary path>"`.
  `python3 "$VALIDATOR_PATH" --schema gc.build.review.v1 --path "<new review path>"`.
- On a repeated attempt, read `gc.attempt_log` on the loop control. Repair only
  this attempt's unaccepted draft in place. An accepted artifact remains
  immutable even when a later validator reports an error; block and qualify a
  replacement generation instead.

Do not invoke provider-native subagents. This Gas City graph lane is the delegation
mechanism for fixes.
