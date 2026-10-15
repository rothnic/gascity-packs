Finalize the gstack plan review.

Require all four reviewer lanes to approve and the apply lane to report
`design_review.verdict=done`. Unresolved required findings, a missing report,
or an exhausted loop must close with `gc.outcome=fail` and a concrete
`gc.failure_reason`. Recording remaining required fixes is not approval.

Before closing pass, run the imported
`validate_plan_review.py native-check` with the current claim and durable rig
root. Record `gc.build.plan_review_status=approved`, the current absolute
`gc.build.plan_review_report_path`, and `gc.build.plan_review_approved_at` only
after it succeeds. A failed or unknown check must record
`gc.build.plan_review_status=failed` and close `gc.outcome=fail`.

Do not invoke provider-native subagents.

The native `plan-review-approved.py` gate permits three attempts. It validates
`gc.build.plan.v1`, approved status, and a passing `gc.verdict-report.v1`
subject bound to this workflow's exact current plan and upstream bytes. Follow
the shared [acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Do not edit the plan, upstream files, or review subject in this finalizer;
changed bytes need the native review/fix loop. On an official check attempt,
read the native control's `gc.attempt_log` and preserve any unresolved failure.
