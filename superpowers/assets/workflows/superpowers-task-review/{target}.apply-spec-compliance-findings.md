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

Apply Superpowers spec-compliance findings.

Use implementation target {{implementation_target}} for code changes. Read the
spec compliance report from `code_review.spec_report_path`. If it approves,
write a no-op apply summary. If it requires changes, make the smallest code or
test updates needed to satisfy the approved task scope and rerun focused
verification.

Write the spec-fix summary under the task artifact directory with resolved
finding ids, changed files, tests run, and any blocker. Close with
`gc.outcome=pass` and `code_review.spec_apply_path=<spec-fix summary path>`.

Do not set `code_review.verdict` or `code_review.report_path`; code quality
still has to run after this lane.

Do not invoke provider-native subagents. This Gas City fanout lane is the
delegation mechanism.

