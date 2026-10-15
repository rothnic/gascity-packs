This is the independent `plan-review-verdict` child of the native `plan-review` check.
The preceding `author-repair` child owns permitted plan changes; do not edit
the plan, requirements or author summary from this reviewer session. Read
the actual current request/context, plan, upstream files and any author
repair summary, then review those bytes independently. The logical check
still allows only three total attempts and alone gates decomposition.

Use the built-in Gas City `design-review` flow on the current implementation
plan. Read the original native request and current requirements before review.
Required changes block decomposition; recording them in a summary is not approval.

Check implementation readiness, requirements traceability, task boundaries,
exact test commands, risky files/interfaces, and rollback. Follow the
[default plan-review acceptance contract](../../../docs/plan-review-acceptance.md).
An earlier report is prior feedback. After an author repair, independently
review the current plan and upstream bytes again. Preserve genuine findings
and earlier reports. Complete this report handoff in order:

1. Obtain the exact current `subject` with the acceptance helper. Write a new
   `gc.verdict-report.v1` report for this claimed review with that subject and
   your actual verdict and findings.
2. Read back the new report from its absolute path before validation.
3. Run `validate_plan_review.py check` with the current native plan, workflow
   root and artifact root, and `--report` set to that same absolute path.
   Checking an earlier failing report does not review the repaired plan.
4. Record that same existing path on the workflow root as
   `gc.build.plan_review_report_path`, even when the new report remains blocked.

Do not write or overwrite
`gc.build.review_report_path`; that key belongs to the later implementation review.

The native `plan-review-approved.py` gate requires an approved
`gc.build.plan.v1`, `verdict: pass`, `severity: none`, empty findings, and exact
plan/upstream hashes. It allows three attempts. Read the native control's `gc.attempt_log` and
review the changed subject after the authored repair child. Preserve blocked
findings when approval is unavailable.

Set `gc.outcome=pass` only after that validation succeeds. Otherwise set
`gc.outcome=fail` and record the blocker before closing. Use
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=<pass-or-fail>"`,
then `gc bd close "<claimed-step-id>" --reason "<concise reason>"`.
Do not pass metadata flags to `gc bd close`, or create tasks for a blocked plan.
