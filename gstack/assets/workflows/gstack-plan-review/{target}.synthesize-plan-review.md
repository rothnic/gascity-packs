Synthesize the gstack plan review.

Read the founder, design, engineering, and developer-experience reports.
Deduplicate findings, preserve lane attribution, and classify each item as
required fix, optional expansion, deferred follow-up, or residual risk.

Write one synthesis under the artifact root with the final recommendation and
the exact plan edits needed before implementation.

Write it to the absolute `gc.build.plan_review_report_path` recorded on the
native workflow root, and preserve `gstack.plan_review.synthesis_path` as the
same report path. Follow the imported Gas City
[plan-review acceptance contract](../../../../gascity/docs/plan-review-acceptance.md).
Read the current native-recorded plan and upstream files. All four lane reports
must review this workflow and the same plan/upstream paths and SHA-256 hashes.
A missing or stale lane report requires another review.

The synthesis must be `gc.verdict-report.v1`, kind `review`. Every unresolved
required fix stays in a failing report's structured findings, with lane
attribution and a concrete repair. Recording a required fix is not approval.

Use only the validator's severity values:

- Finding severity: `minor`, `major`, or `blocker`
- Report severity: `none`, `minor`, `major`, or `blocker`

The report severity must equal the highest finding severity. A passing report
uses `severity: none` and `findings: []`. A failing report keeps every required
finding and uses a non-`none` severity.

Only when all four lanes approve the current approved plan and required
findings are resolved may it use `verdict: pass`, `severity: none`, and
`findings: []`.

Capture `subject` with the imported `validate_plan_review.py subject` command
after reviewing the current bytes. Copy its JSON object verbatim. Do not derive
or prefix the native workflow root ID. If the helper refuses, preserve that
reason as a finding and do not invent a subject. If the plan still needs an
approved status, record that change for the apply lane and review the resulting
bytes on the next iteration. Do not modify the plan or turn deferred optional
ambition into accepted scope while synthesizing.

Before closing, validate the written report with the imported
`validate_verdict_report.py` from the same Gas City scripts directory:

```sh
python3 <pack-scripts>/validate_verdict_report.py <report-path> --kind review
```

Resolve `<pack-scripts>` from the imported pack assets, not the worker's current
directory. Fix report-format errors without dropping or weakening findings.

Close with `gc.outcome=pass`,
`gstack.plan_review.synthesis_path=<plan review synthesis path>`, and
`gstack.plan_review.output_path=<plan review synthesis path>`.

Do not invoke provider-native subagents. Synthesis happens in this Gas City
fan-in lane.
