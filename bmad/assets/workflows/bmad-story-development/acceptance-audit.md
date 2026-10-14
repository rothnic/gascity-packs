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

This lane is read-only source review. Refuse stale reports or a changed
worktree/commit. A missing artifact or command cannot earn a finding-free pass.

Audit BMAD story acceptance.

Compare the implementation against the PRD, architecture, epics/stories, and Given/When/Then acceptance criteria. Check test evidence and flag missing, extra, or misunderstood behavior.

Write the acceptance-audit report under `{{artifact_root}}/bmad-story-development/`
and close with `gc.outcome=pass`,
`bmad_story.acceptance_audit_report_path=<report path>`, and
`bmad_story.acceptance_required_findings=<count>`. If the story cannot be
audited because required artifacts or the worktree are missing, close with
`gc.outcome=fail` instead of inventing a result.

Do not invoke provider-native subagents. You are the acceptance audit lane.
