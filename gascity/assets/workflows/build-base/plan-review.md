This is the `build-base` plan-review stage. Concrete methodology formulas may
override it with their own native review and repair contract.

Review the current plan for requirements traceability, feasibility, edge cases,
task boundaries, exact verification commands, and implementation readiness.
Read the original native request and current upstream artifacts. Record every
unresolved finding; writing a report does not make the plan approved.

Follow the [default plan-review acceptance contract](../../../docs/plan-review-acceptance.md).
The report must be `gc.verdict-report.v1`, kind `review`, with its `subject`
bound to the current native workflow, exact plan bytes, and current upstream
bytes. Record its absolute path on the workflow root as
`gc.build.plan_review_report_path`. The pack-owned `plan-review-approved.py`
gate validates that subject and the approved plan; it allows three attempts.

Set `gc.outcome=pass` only for `verdict: pass`, `severity: none`, and empty
findings after the exact subject validates. Otherwise preserve a failing report,
set `gc.outcome=fail` with the concrete blocking reason, and close the claimed
step. Authorized repairs must produce a newly reviewed subject; report-only or
headless work must retain unresolved findings rather than invent approval.

Use `gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=<pass-or-fail>"`
before `gc bd close "<claimed-step-id>" --reason "<concise reason>"`.
On an official repair attempt, read `gc.attempt_log` on its native control.
Do not allocate implementation tasks until the current review is accepted.
