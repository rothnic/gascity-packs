Use the built-in Gas City `design-review` flow on the current implementation
plan. Read the original native request and current requirements before review.
Required changes block decomposition; recording them in a summary is not approval.

Check implementation readiness, requirements traceability, task boundaries,
exact test commands, risky files/interfaces, and rollback. Follow the
[default plan-review acceptance contract](../../../docs/plan-review-acceptance.md).
Write a `gc.verdict-report.v1` review with the exact current `subject`, and
record its absolute path on the workflow root as
`gc.build.plan_review_report_path`. Do not write or overwrite
`gc.build.review_report_path`; that key belongs to the later implementation review.

The native `plan-review-approved.py` gate requires an approved
`gc.build.plan.v1`, `verdict: pass`, `severity: none`, empty findings, and exact
plan/upstream hashes. It allows three attempts. On repair, read the native
control's `gc.attempt_log`; apply only authorized fixes and review the changed
subject again. Preserve blocked findings when approval is unavailable.

Set `gc.outcome=pass` only after that validation succeeds. Otherwise set
`gc.outcome=fail` and record the blocker before closing. Use
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=<pass-or-fail>"`,
then `gc bd close "<claimed-step-id>" --reason "<concise reason>"`.
Do not pass metadata flags to `gc bd close`, or create tasks for a blocked plan.
