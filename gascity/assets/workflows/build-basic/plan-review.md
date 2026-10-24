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

1. Obtain the exact current `subject` with the acceptance helper. If it cannot
   be read, retain the diagnostic as a blocking finding; never invent an
   approval subject. For every blocked review, capture `repair_subject` with
   `native-repair-subject` while this reviewer is claimed, even when the plan
   and its `subject` are valid. Write a new `gc.verdict-report.v1` report for
   this claimed review with the actual verdict and findings. A failing report
   must include that repair identity; it does not approve the plan. Preserve
   earlier reports rather than retrofitting their identities.
   If `native-repair-subject` itself fails because the plan front matter,
   schema, workflow identity, or required native input is unavailable, do not
   fabricate an identity or publish the diagnostic as an author-repair report.
   Set `gc.outcome=fail` and `gc.failure_reason` on this claimed reviewer with
   the exact helper diagnostic, then close it. Do not record a report path or
   continue to step 2; this failure cannot authorize author repair.
2. Read back the new report from its absolute path before validation.
3. Hash the report bytes you just read, then run
   `validate_plan_review.py native-review-report-check --report <absolute-path>
   --report-sha256 <sha256>`. This checks the report against the current
   claimed reviewer, workflow root, plan and requirements before publication.
   It accepts a complete failing handoff as complete but still failing; it
   does not grant approval. A missing or stale repair identity must be fixed
   in this current report and checked again. Checking an earlier report does
   not review repaired plan bytes.
4. Record that same checked path on the workflow root as
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
