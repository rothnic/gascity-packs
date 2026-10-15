Finalize the Compound Engineering plan-review expansion.

Verify the latest synthesized verdict is approved, record the review report path on the parent build step, and close this expansion target. If the loop exhausted attempts or has unresolved required findings, record a failing review outcome with the report path.

Use workflow root metadata `gc.build.plan_review_report_path` and
`gc.build.plan_review_apply_summary_path`. On success, update the workflow root
only after the exact current-subject check below succeeds, with
`gc.build.plan_review_status=approved` and
`gc.build.plan_review_approved_at=<UTC timestamp>`, then close with
`gc.outcome=pass`.

The native `plan-review-approved.py` check resolves from the imported Gas City
assets and allows three attempts. It validates the `gc.build.plan.v1` schema,
approved status, and a passing `gc.verdict-report.v1` report bound to this
workflow's exact current plan and upstream bytes. Follow the shared
[acceptance contract](../../../../gascity/docs/plan-review-acceptance.md) and run
the imported `validate_plan_review.py native-check` before closing pass.

Do not edit the reviewed plan, upstream files, or report subject in this
finalizer. A changed or missing subject requires another authorized review,
not a refreshed approval. On an official check attempt, read the native
control's `gc.attempt_log`. If the loop exhausted attempts, any required finding
remains, or the exact check refuses, set `gc.build.plan_review_status=failed`
and close with `gc.outcome=fail` and the concrete `gc.failure_reason`.
