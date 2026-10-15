Apply build-basic starter review findings.

Use implementation target {{implementation_target}} for any code changes. Read
the starter review synthesis. If all three review lanes approve, write a no-op
review summary. If required fixes or missing evidence remain, make the smallest
focused changes, run the relevant proof commands, and write the review-fix
summary under the build artifact root.

For required fixes, read the current canonical and commit-bound
findings through `workspace_outputs.referenced_record`. Report mode cannot
apply fixes. A no-op retains the exact canonical OID and matching approval.
Source or test changes require `workspace_review.fix_plan(canonical, findings,
previous_plan, writer_step_id=..., source_plan_owner_id=..., nodes=...,
terminal_owner_id=..., max_iterations=...)`. Use native IDs and the configured
bounded retry policy. Publish the declared source-plan using
`workspace_source_plan.declare_plan` and `publish_plan` under the current
admitted claim/owner grant. Retain the exact parent generation/OID; do not edit
the accepted canonical checkout in place or replace a newer parent.

Run the selected methodology's native implementation/fix lanes against that
recorded generation. Use the common checkout, result and canonical APIs for
its tested commit and independent review. A changed pass returns `iterate`;
only a later independent review of the new canonical commit can approve.
Preserve artifacts for both generations. Do not rewrite the old accepted
summary, review or receipt. Any missing native route, grant or helper blocks
with original state retained. Artifact paths grant no source-write authority.

The review context supplies findings and traceability, not writable authority.
Any source change must run through the declared replacement generation and its
verified workspace. Do not edit the accepted canonical checkout in place.
Preserve accepted summaries and reports; write replacement artifacts for the
new generation. A no-op keeps the exact existing canonical OID and approval.

Set `code_review.verdict=done` only when acceptance, test evidence, and
simplicity all approve after this pass. Set `code_review.verdict=iterate` when
required fixes remain.

Always close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<starter review summary path>`, and
`code_review.output_path=<starter review summary path>`.

Use the exact claimed bead id when updating metadata. Do not pass freeform notes
or additional positional arguments to `gc bd update`; unquoted words can resolve to
unrelated beads. Use this command shape:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.verdict=done' \
  --set-metadata 'code_review.report_path=<starter review summary path>' \
  --set-metadata 'code_review.output_path=<starter review summary path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Build-basic starter review approved.'
```

Do not invoke provider-native subagents. This starter factory graph lane is the
fix delegation mechanism.
