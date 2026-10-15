Apply gstack plan-review findings.

Read the synthesis and update the plan artifact in place when required fixes
remain. Keep optional ambition clearly separated from accepted scope. In
interactive mode, only add new scope after explicit approval is recorded; in
autonomous mode, preserve optional scope as deferred follow-up.

Read the synthesis from `gc.build.plan_review_report_path` and write the apply
summary to `gc.build.plan_review_apply_summary_path`. Respect `review_mode`:
report-only work does not edit; agent or interactive work applies only
authorized repairs. Any plan or upstream change, including setting the plan
status to `approved`, requires `design_review.verdict=iterate` so the four
lanes review the new bytes. Do not replace the prior review subject or write
a passing synthesis for this lane's own edits.

Set `design_review.verdict=done` only for a no-op when founder, design,
engineering, and developer-experience lanes approve and the imported
`validate_plan_review.py native-check` succeeds with the current claim and
durable rig root. It must accept the structured report for the exact current
native-recorded plan and upstream files. Required fixes, missing evidence, or
a stale subject require `design_review.verdict=iterate`; merely recording
remaining required fixes never permits `done`.

Close with `gc.outcome=pass`,
`design_review.verdict=done|iterate`,
`design_review.report_path=<plan review summary path>`, and
`gstack.plan_review.output_path=<plan review summary path>`.

Keep edited build artifacts schema-valid. Stage checks and the build gate's final artifact check validate these
Markdown build artifacts, so any edit you make to one must leave it valid:

- The plan artifact at workflow root metadata `gc.build.plan_path`, schema `gc.build.plan.v1`:
  front-matter `status` must be one of `draft`, `questions`, `approved`, `changes_required`, `blocked`, or `superseded`.

When you edit one of them:

- Edit it in place and preserve its YAML front matter: keep `schema`,
  `workflow`, `methodology`, `producer`, and `trace` intact, and keep
  `trace.coverage` and the Markdown `ID`/`Status` coverage table in sync.
- Use only the allowed `status` values listed above. Do not invent statuses
  such as `reviewed`; record review progress in the apply summary and bead
  metadata, not in the artifact's front matter.
- Before closing with `gc.outcome=pass`, from `$GC_RIG_ROOT`, re-run the
  validator on every build artifact you edited and fix every reported error:
  `python3 .gc/scripts/validate_build_artifact.py --schema gc.build.plan.v1 --path "<plan path>"`.
- On a repeated attempt (`gc.attempt` greater than 1), first read the validator
  errors from `gc.attempt_log` on the loop control bead and repair the
  artifact in place.

Do not invoke provider-native subagents. This Gas City graph lane is the plan
fix delegation mechanism.
