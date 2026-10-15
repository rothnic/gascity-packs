Run the gstack founder scope review lane.

Use the plan-ceo-review posture: challenge the premise, compare minimal viable
and ideal architecture approaches, check whether the plan solves the real
outcome, and name any 10-star product opportunity that is simple enough to be
worth surfacing.

Write findings under the artifact root. Distinguish required plan fixes from
optional ambition and deferred ideas.

Read `gc.build.plan_review_context_path` and the current native-recorded plan
and upstream files. Record the native workflow root id, absolute paths, and
SHA-256 hashes of every reviewed file in this lane's report. If the bytes
change, use `iterate`; a stale report cannot approve the new plan.

Close with `gc.outcome=pass`,
`gstack.plan_review.founder_verdict=approve|iterate`, and
`gstack.plan_review.output_path=<founder review report path>`.

Do not invoke provider-native subagents. You are the founder review lane.
