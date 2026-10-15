Apply required Superpowers plan-review feedback.

Read the plan-review context from workflow root metadata
`gc.build.plan_review_context_path` and the plan-review report from
`gc.build.plan_review_report_path`. Write the apply summary to workflow root
metadata path `gc.build.plan_review_apply_summary_path`, which should be
`<artifact_root>/plan-review-apply-summary.md`.

Update only the requirements or plan artifacts needed to resolve required
findings. Preserve traceability and avoid adding unrequested scope. If a
finding cannot be resolved safely, record the blocker in the apply summary.

Respect `review_mode`: report-only work does not edit the plan; agent or
interactive work applies only authorized repairs. Any plan or upstream change,
including changing the plan status to `approved`, requires
`design_review.verdict=iterate` so the reviewer inspects those new bytes.
Preserve the prior report; this feedback lane must not rewrite its subject or
create a passing review for its own edits.

Set `design_review.verdict=done` only for a no-op after the reviewer approves
and the imported `validate_plan_review.py native-check` succeeds with the
current claim and durable rig root. The structured report must pass for the
exact native-recorded plan and upstream files. Then update workflow root
metadata with `gc.build.plan_status=approved`. Otherwise preserve the findings,
set `gc.build.plan_status=draft`, and use `design_review.verdict=iterate`.

Always close with `gc.outcome=pass`, `design_review.verdict=done|iterate`, and
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
  `python3 .gc/scripts/validate_build_artifact.py --schema gc.build.requirements.v1 --path "<requirements path>"`.
  `python3 .gc/scripts/validate_build_artifact.py --schema gc.build.plan.v1 --path "<plan path>"`.
- On a repeated attempt (`gc.attempt` greater than 1), first read the validator
  errors from `gc.attempt_log` on the loop control bead and repair the
  artifact in place.

Do not invoke provider-native subagents. This Gas City lane owns the fix pass.
