Run the BMAD architecture handoff review and close pass only after the plan is
ready for epics and stories.

Use the imported Gas City [plan-review acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Read the original native request, current PRD, and native-recorded architecture
plan. Record an absolute report path at `gc.build.plan_review_report_path`,
normally `{{artifact_root}}/plan-review.md` under the durable rig root. Write
`gc.verdict-report.v1`, kind `review`, bound by `subject` to this workflow's
exact approved `gc.build.plan.v1` plan and current upstream files, including
the PRD. Capture the subject with the imported `validate_plan_review.py subject`
only after reviewing those bytes.

Passing requires `verdict: pass`, `severity: none`, `findings: []`, and a
successful `validate_plan_review.py native-check`. Preserve unresolved findings
in a failing report and close `gc.outcome=fail` with the concrete reason.
Respect `review_mode`; permitted repairs require review of their changed
bytes, and report-only review grants no editing authority. The native
`plan-review-approved.py` check permits three attempts and records errors on
its control's `gc.attempt_log`. This is architecture handoff approval, not
BMAD's later implementation-readiness check after story decomposition.
