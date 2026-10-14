Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the task/story procedure below in either mode. Legacy source/path
resolution applies only to explicit `legacy`; managed source operations use
the recorded workspace. Unknown modes or failed reads never select legacy.

For an admitted `new` item, reload the exact run/source-plan/workspace
through the imported Gas City `workspace_checkout.load_workspace_context`
API with the same native city/rig/store and physical record IDs. At clean
first entry use `workspace_checkout.manage_workspace(action="path", ...)`.
Later TDD/story steps retain that exact recorded path and require recognized
same-member continuation evidence for the current dirty state or committed
HEAD. The clean `path` verifier is not a dirty/advanced-HEAD resume API. If the
composed native continuation contract is absent, block without resetting or
adopting the state. Match active
`gc.drain_member_id`, position, generation and native workspace provenance.
Before a write, require this step's current native claim and admitted member/
owner grant. A different session must reconstruct the same recorded workspace.
Preserve unexpected dirty state, advanced HEAD, ownership changes or stale
attempts as blockers outside all worktrees. Never use raw `work_dir`, the
launcher or a newly selected base. Retain the exact member input across
continuation and recognized partials; do not advance its checkpoint here.

Task review uses the recorded task workspace and this attempt's exact
source/diff snapshot before record-item-result commits. It is not canonical
output acceptance. Preserve spec-compliance -> apply-spec-findings ->
code-quality -> apply-quality-findings order. A source change requires a new
review pass and `iterate`; this lane cannot self-approve its own fixes.

Apply Superpowers code-quality findings.

Use implementation target {{implementation_target}} for any code changes. Read
the spec compliance report, spec-fix summary, and code quality report. If both
review lanes approve, write a no-op final task-review summary. If required
quality fixes remain, make the smallest focused updates, rerun the relevant
verification, and write the fix summary.

Set `code_review.verdict=done` only when spec compliance and code quality both
approve after this pass. Set `code_review.verdict=iterate` when required
findings remain or when quality was deferred because spec compliance still
needed another pass.

Always close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<task review summary path>`, and
`code_review.output_path=<task review summary path>`.

Use the exact claimed bead id when updating metadata. Do not pass freeform notes
or additional positional arguments to `gc bd update`; unquoted words can resolve to
unrelated beads. Use this command shape:

```bash
gc bd update "$CLAIMED_BEAD_ID" \
  --set-metadata 'gc.outcome=pass' \
  --set-metadata 'code_review.verdict=done' \
  --set-metadata 'code_review.report_path=<task review summary path>' \
  --set-metadata 'code_review.output_path=<task review summary path>'
gc bd close "$CLAIMED_BEAD_ID" --reason 'Superpowers task review approved.'
```

Do not invoke provider-native subagents. This Gas City fanout lane is the
delegation mechanism.

