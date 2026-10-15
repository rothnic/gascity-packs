Use the assigned BMAD architecture skill materialized for this agent.

Review the PRD and architecture handoff before epic/story decomposition. Confirm
that the architecture output is complete enough for `bmad-create-epics-and-stories`
to preserve requirement traceability and produce implementable stories.

Do not run `bmad-check-implementation-readiness` here; that BMAD skill runs
after epics and stories exist.

Follow the imported Gas City [plan-review acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Read the original native request, current PRD, and architecture plan from the
workflow root's recorded paths. Write a `gc.verdict-report.v1`, kind `review`,
report under `{{artifact_root}}/plan-review.md` (or its already-recorded path),
and record its absolute path as `gc.build.plan_review_report_path` on that root.

The architecture must validate as `gc.build.plan.v1`, belong to this workflow,
and have `status: approved`. Its upstream trace must bind the current PRD and
all other declared upstream bytes. Only after reviewing those exact files,
capture `subject` with the imported `validate_plan_review.py subject` and
write `verdict: pass`, `severity: none`, and `findings: []` if no required
finding remains. Report-only review does not edit the architecture; authorized
repairs must be reviewed again before capturing their new subject. Preserve
unresolved findings in a structured failing report instead of inventing
approval.

The native `plan-review-approved.py` executable gate allows three attempts and
validates the current subject before decomposition. Run the imported
`validate_plan_review.py native-check` with the current claim and durable rig
root before setting `gc.outcome=pass`. Otherwise close with `gc.outcome=fail`
and a concrete `gc.failure_reason`. On an official repair attempt read the
native control's `gc.attempt_log`. This architecture handoff does not replace
BMAD's later implementation-readiness review of the actual epics and stories.

Do not invoke provider-native subagents or upstream BMAD runtime commands.
