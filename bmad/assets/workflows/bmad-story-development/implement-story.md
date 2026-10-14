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

The story loop retains its BMAD PRD, architecture, story and readiness
requirements. Self-check and acceptance-audit reports bind the current attempt
and actual story commit. Source repairs return `iterate` for another check.
`apply-story-findings` supplies the final tested producer output; inherited
independent-acceptance and record-result qualify it before closure.

Implement the BMAD story with the installed `bmad-quick-dev` and
`bmad-dev-story` skills.

Treat BMAD's "hand to a sub-agent/task" instruction as this Gas City lane.

Resolve the source anchor as the workflow root's stamped `gc.source_anchor_id`;
only when the root has none, use the same rules as the do-work `prepare-worktree`
step (for a shared-drain item, the drain member in `gc.drain_member_id`), read
`work_dir` from the source anchor, validate that it is an absolute existing git
worktree, set `WORKTREE` to that path, and `cd "$WORKTREE"` before reading or
editing source files. If `work_dir` is missing, invalid, or points at the
launcher checkout, fail before editing.
`gc.work_dir` is the launcher rig root, not the implementation worktree; do not
edit, test, or commit in the launcher checkout.

Implement the story, run focused tests from inside the worktree, update task
completion evidence, then make a focused commit in the worktree (`git add` the
changed files and `git commit`). Do-work's `close-source-anchor` step fails
closed when the worktree has no implementation commit, so uncommitted edits are
a failed implementation, not a pass. Commit only when `git status --porcelain`
shows changes, and never use `git commit --allow-empty`. This step re-runs on
every story loop iteration: if the story is already committed and nothing
changed, do not commit again; record the existing `HEAD` commit hash instead.
Write an implementation summary to
`{{artifact_root}}/task-<source-anchor-id>-summary.md` after resolving the
source anchor. Record the summary path, focused commit hash, changed files, and
verification result on the story-development step before closing it. Leave the
source anchor open; later workflow steps close it.

Close with `gc.outcome=pass` only after the story is implemented, verified, and
committed.

Do not invoke provider-native subagents. You are the implementation lane.
