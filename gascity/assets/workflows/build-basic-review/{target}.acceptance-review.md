Run the starter factory acceptance review lane.

Review the implementation against the requirements, acceptance criteria,
implementation plan, decomposition, and task summaries. Focus on correctness:
did the factory build the requested behavior, and did it avoid out-of-scope
changes?

Resolve the exact run, source plan, workspace, terminal accepted result, owner
output and canonical record through the imported `workspace_outputs` helpers.
Validate native qualification and the captured check policy before source access.
Use `workspace_review.begin_canonical_review` with the current native reviewer,
recorded workspace and exact binding; retain its canonical/result hashes and
source snapshot. Every lane reviews that same full canonical output OID.
Artifact paths and old `work_dir` fields do not establish source authority.
Missing or conflicting records stop review for explicit recovery or migration.

Read `gc.build.code_review_context_path` for requirements and methodology
evidence. Resolve source paths and proof commands against the verified canonical
workspace, then verify its exact OID and clean state. Keep review read-only. An
unchanged launcher checkout is irrelevant to the accepted canonical result.

Write findings under the build artifact root. Required findings must include
the relevant requirement or task reference plus the file, command, or artifact
that proves the issue.

Close with `gc.outcome=pass`,
`code_review.acceptance_verdict=approve|iterate`, and
`code_review.output_path=<acceptance review report path>`.

Use explicit close metadata so the review loop can detect the lane result:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.acceptance_verdict=approve' \
  --set-metadata 'code_review.output_path=<acceptance review report path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Build-basic acceptance review approved.'
```

If you find required fixes, set
`code_review.acceptance_verdict=iterate` instead of `approve` and explain the
smallest required fix in the report and close reason.

Do not set `code_review.verdict` or `code_review.report_path`; synthesis and
fix application own the final review verdict.

Do not invoke provider-native subagents. You are the starter factory acceptance
review lane.
