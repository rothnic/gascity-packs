Run the starter factory test evidence review lane.

Check that each accepted task recorded an intended behavior, first verification
command, proof command, changed files, and remaining risks. Verify that the
commands actually cover the acceptance criteria claimed by the requirements and
plan.

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

Write concrete findings under the build artifact root. Distinguish missing
proof from real product defects so the fix lane can either run the missing
command or change code.

Close with `gc.outcome=pass`,
`code_review.test_evidence_verdict=approve|iterate`, and
`code_review.output_path=<test evidence report path>`.

Use explicit close metadata so the review loop can detect the lane result:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.test_evidence_verdict=approve' \
  --set-metadata 'code_review.output_path=<test evidence report path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Build-basic test evidence review approved.'
```

If proof is missing or insufficient, set
`code_review.test_evidence_verdict=iterate` instead of `approve` and explain
whether the fix lane should run missing proof commands or change code.

Do not set `code_review.verdict` or `code_review.report_path`; synthesis and
fix application own the final review verdict.

Do not invoke provider-native subagents. You are the starter factory test
evidence review lane.
