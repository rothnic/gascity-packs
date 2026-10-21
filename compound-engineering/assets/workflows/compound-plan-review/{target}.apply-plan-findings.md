Resolve `VALIDATOR_PATH` from the same imported Gas City pack as the native
loop's `gc.check_path`: its absolute path is `<check-directory>/../validate_build_artifact.py`.
Require that resolved validator and its pack schemas to exist; never copy a
validator into the rig or select one from a source checkout.

Apply required Compound Engineering plan-review findings.

Update only the requirements or plan artifacts needed to resolve required findings. Preserve Compound Engineering identifiers and traceability. If findings cannot be resolved safely, record the blocker in the review artifact instead of inventing scope.

Read the synthesized report from `gc.build.plan_review_report_path`. Write the
apply summary to `gc.build.plan_review_apply_summary_path`, which should be
`<artifact_root>/plan-review/apply-summary.md`.

Treat plan author readiness and independent review status as separate state:
the plan artifact's front-matter status and `gc.build.plan_status` describe
whether the author considers the current plan ready, while
`gc.build.plan_review_status` and `design_review.verdict` describe whether the
current bytes have passed independent review. Resolve the build workflow root
from the current native claim's `gc.root_bead_id`; write both `gc.build.*`
status fields to that root bead, not to this claimed apply child. Keep this
child's `design_review.*` verdict and output fields on the child.

Respect `review_mode`: report-only work records findings without editing;
agent or interactive work applies only authorized repairs. If a permitted
repair resolves the required findings, set the plan artifact's front-matter
`status: approved` and `gc.build.plan_status=approved` before returning the
changed bytes to the four review lanes. Keep
`gc.build.plan_review_status=draft` and close with
`design_review.verdict=iterate`, because the reviewers must inspect those new
bytes. Preserve the report that caused the repair; do not replace its subject
or manufacture a passing report in this apply lane. Do not reset an approved,
unchanged plan to `draft` solely because a fresh independent review is pending.

If report-only mode or missing repair authority prevents an edit, preserve the
plan bytes and their current `gc.build.plan_status`; keep
`gc.build.plan_review_status=draft` and record the unresolved finding in the
apply summary. In agent or interactive mode, when an authorized repair leaves
required substantive findings unresolved, keep the plan artifact's front-matter
status and `gc.build.plan_status` at `draft`, keep
`gc.build.plan_review_status=draft`, and close with
`design_review.verdict=iterate`. Do not mark an unresolved plan approved to
satisfy the native gate or edit outside the existing repair authority.

Set `design_review.verdict=done` only for a no-op after all four lanes approve,
the structured report has no unresolved findings, and the imported
`validate_plan_review.py native-check` succeeds with the current claim and
durable rig root. The check revalidates the exact native-recorded plan,
report, workflow, and upstream files. Only then set
`gc.build.plan_review_status=approved`; leave the already-approved
`gc.build.plan_status` aligned with the plan's approved front matter.
If the plan changed, its subject is stale, or a required finding remains,
return it through review with `design_review.verdict=iterate`.

Always close with `gc.outcome=pass`,
`design_review.report_path=<apply summary path>`, and
`design_review.output_path=<apply summary path>`.

Keep edited build artifacts schema-valid. Stage checks and the build gate's final artifact check validate these
Markdown build artifacts, so any edit you make to one must leave it valid:

- The requirements artifact at workflow root metadata `gc.build.requirements_path`, schema `gc.build.requirements.v1`:
  front-matter `status` must be one of `draft`, `questions`, `approved`, `changes_required`, `blocked`, or `superseded`.
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
  `python3 "$VALIDATOR_PATH" --schema gc.build.requirements.v1 --path "<requirements path>"`.
  `python3 "$VALIDATOR_PATH" --schema gc.build.plan.v1 --path "<plan path>"`.
- On a repeated attempt (`gc.attempt` greater than 1), first read the validator
  errors from `gc.attempt_log` on the loop control bead and repair the
  artifact in place.

Do not invoke provider-native subagents. This Gas City lane owns the fix pass.
