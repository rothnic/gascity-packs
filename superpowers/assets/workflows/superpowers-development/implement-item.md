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

This is an inspect-only step. Preserve the approved design, written
spec and plan gates. It writes task context, never a commit or accepted
checkpoint. `record-item-result` owns the final task commit after TDD and
spec-compliance then code-quality review.

Inspect the Superpowers shared-drain implementation task.

Resolve `gc.drain_member_id`, `gc.drain_item_index`, the existing shared
worktree, the approved requirements, approved plan, decomposition artifact, and
this task bead. The task bead describes the work unit only; the drained
Superpowers implementation workflow supplies the execution procedure.

Use the installed `executing-plans`, `test-driven-development`, and
`using-git-worktrees` skills as guidance for this task. Confirm the task can run
in the shared-drain lane, identify the first test behavior to drive, and write a
compact task context note for the following implementation steps.

Do not edit source files in the launcher checkout. Do not invoke
provider-native subagents or upstream plugin runtime commands.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
