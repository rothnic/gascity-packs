Run the gstack developer-experience plan review lane.

Use the plan-devex-review posture when the work affects APIs, CLIs, SDKs,
docs, onboarding, install paths, or operational workflows. Check time to first
happy path, error messages, docs coverage, upgrade path, and the user's magical
moment. For product-only work, mark the lane not applicable.

Write findings under the artifact root.

Read `gc.build.plan_review_context_path` and the current native-recorded plan
and upstream files. Record the native workflow root id, absolute paths, and
SHA-256 hashes of every reviewed file in this lane's report. If the bytes
change, use `iterate`; a stale report cannot approve the new plan. A justified
not-applicable developer-experience verdict still names the exact subject.

Close with `gc.outcome=pass`,
`gstack.plan_review.devex_verdict=approve|iterate`, and
`gstack.plan_review.output_path=<devex review report path>`.

Do not invoke provider-native subagents. You are the developer-experience lane.
