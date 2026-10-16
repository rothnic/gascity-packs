This is the independent `plan-review-verdict` child of the native `plan-review` check.
The preceding `author-repair` child owns permitted plan changes; do not edit
the plan, requirements or author summary from this reviewer session. Read
the actual current request/context, plan, upstream files and any author
repair summary, then review those bytes independently. The logical check
still allows only three total attempts and alone gates decomposition.

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

For every blocked review, capture `repair_subject` with `native-repair-subject`
while this reviewer is claimed. If a malformed trace prevents a complete
`subject`, record that diagnostic and the repair identity in a failing report
as the contract directs. A repair identity cannot approve decomposition.

Set `gc.outcome=pass` only for `verdict: pass`, `severity: none`, and empty
findings after the exact subject validates. Otherwise preserve a failing report,
set `gc.outcome=fail` with the concrete blocking reason, and close the claimed
step. Authorized repairs must produce a newly reviewed subject; report-only or
headless work must retain unresolved findings rather than invent approval.

Use `gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=<pass-or-fail>"`
before `gc bd close "<claimed-step-id>" --reason "<concise reason>"`.
On an official repair attempt, read `gc.attempt_log` on its native control.
Do not allocate implementation tasks until the current review is accepted.
