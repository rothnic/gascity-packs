Synthesize the Compound Engineering plan-review lanes.

Merge coherence, feasibility, scope, and architecture findings into one plan-review report. Deduplicate overlapping findings, classify each as required change or residual risk, and write the approval verdict used by `.gc/scripts/checks/design-review-approved.sh`.

Read the review context from `gc.build.plan_review_context_path` and write the
synthesized report to `gc.build.plan_review_report_path`, which should be
`<artifact_root>/plan-review/report.md`.

Use the imported Gas City [plan-review acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Review the current native-recorded plan and requirements, not just the context
copy. Require all four lane reports to name this workflow and the same plan
and upstream paths and SHA-256 hashes. Missing, stale, or required findings
mean `iterate`; preserve each finding and its lane attribution.

Write `gc.verdict-report.v1`, kind `review`, to the recorded report path.
Only an approved current plan with no unresolved findings may receive
`verdict: pass`, `severity: none`, and `findings: []`. After reviewing those
bytes, capture its exact `subject` with the imported
`validate_plan_review.py subject` command from the shared contract. Do not
rewrite the plan while synthesizing. If its status still needs approval,
record that required change for the apply lane; the changed bytes need another
review. A report or recommendation alone does not authorize decomposition.

Close with `gc.outcome=pass`,
`design_review.review_verdict=approve|iterate`, and
`design_review.review_report_path=<synthesized report path>`. Do not set
`design_review.verdict`; the apply-plan-findings lane owns the final loop
verdict consumed by the approval check.

Do not invoke provider-native subagents. Synthesis happens in this Gas City lane.
