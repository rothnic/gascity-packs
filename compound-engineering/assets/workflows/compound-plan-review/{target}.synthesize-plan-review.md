Synthesize the Compound Engineering plan-review lanes.

Merge coherence, feasibility, scope, and architecture findings into one plan-review report. Deduplicate overlapping findings, classify each as required change or residual risk, and write the approval verdict used by `.gc/scripts/checks/design-review-approved.sh`.

Read the review context from `gc.build.plan_review_context_path` and write the
synthesized report to `gc.build.plan_review_report_path`, which should be
`<artifact_root>/plan-review/report.md`.

Use the imported Gas City [plan-review acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Review the current native-recorded plan and requirements, not just the context
copy. Require all four lane reports to agree on the canonical subject returned
by the imported `validate_plan_review.py subject` command: this workflow root,
the exact current plan path and hash, and exactly the current
`plan.trace.upstream` paths and hashes. Additional valid/current references
in a lane's rationale are supplementary evidence, not canonical subject
members; those citations may differ across lanes. A missing, conflicting, or
stale canonical subject or required finding means `iterate`; preserve each
finding and its lane attribution.

Write `gc.verdict-report.v1`, kind `review`, to the recorded report path.
Treat the plan front matter and `gc.build.plan_status` as author readiness. If
either is not `approved`, record the required change for the apply lane; those
bytes cannot receive a passing review. The native workflow root's
`gc.build.plan_review_status=draft` is expected until the finalizer validates a
passing report and records independent review approval. Do not treat that
draft review-status field alone as an unresolved plan finding.

For an author-approved plan with no unresolved findings, write
`verdict: pass`, `severity: none`, and `findings: []`. Capture its exact
`subject` with the imported
`validate_plan_review.py subject` command from the shared contract. Do not
rewrite the plan while synthesizing. A report or recommendation alone does not
authorize decomposition.

Use finding severities `minor`, `major`, or `blocker`. Use report severities
`none`, `minor`, `major`, or `blocker`. The report severity must equal the
highest finding severity. Before closing, validate the report with the imported
`validate_verdict_report.py` from the same Gas City scripts directory:

```sh
python3 <pack-scripts>/validate_verdict_report.py <report-path> --kind review
```

Resolve `<pack-scripts>` from the imported pack assets, not the worker's current
directory. Fix report-format errors without dropping or weakening findings.

Close with `gc.outcome=pass`,
`design_review.review_verdict=approve|iterate`, and
`design_review.review_report_path=<synthesized report path>`. Do not set
`design_review.verdict`; the apply-plan-findings lane owns the final loop
verdict consumed by the approval check.

Do not invoke provider-native subagents. Synthesis happens in this Gas City lane.
