Run the starter factory simplicity review lane.

Review the implementation for maintainability, readable boundaries,
unnecessary abstractions, accidental broad changes, and obvious future
maintenance risk. Keep this lane beginner-friendly: flag only concrete issues
that a new factory user can understand and act on.

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

Write findings under the build artifact root. Required findings must be tied to
specific changed files or artifacts and must explain the smallest useful fix.

Close with `gc.outcome=pass`,
`code_review.simplicity_verdict=approve|iterate`, and
`code_review.output_path=<simplicity review report path>`.

Use explicit close metadata so the review loop can detect the lane result:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.simplicity_verdict=approve' \
  --set-metadata 'code_review.output_path=<simplicity review report path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Build-basic simplicity review approved.'
```

If you find required fixes, set
`code_review.simplicity_verdict=iterate` instead of `approve` and explain the
smallest required fix in the report and close reason.

Do not set `code_review.verdict` or `code_review.report_path`; synthesis and
fix application own the final review verdict.

Do not invoke provider-native subagents. You are the starter factory simplicity
review lane.
