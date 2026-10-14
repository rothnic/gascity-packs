For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
The legacy instructions below retain their existing behavior.

Implement this Compound Engineering item with {{implementation_target}}.

Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
For an admitted `new` run, load the run, source-plan and workspace through the
imported Gas City `workspace_checkout.load_workspace_context` API. Resolve the
path with `workspace_checkout.manage_workspace(action="path", ...)` using the
same physical record IDs, registered city/rig/store and claimed step. Require
the current native producer claim and admitted owner grant before any edit.
First entry must match `input_oid`. Resume only recognized recorded state.
Preserve an unexpected dirty index, advanced HEAD or conflicting owner as a
blocker outside all worktrees. Never read raw `work_dir` as a managed fallback.

Implement and commit only owned changes in that verified workspace. Freeze the
actual full `output_oid` after the commit. For a genuine `no_change`, retain
`input_oid` without an empty commit. Build the exact subject with
`workspace_outputs.result_binding(run, plan, workspace, store_ref=...,
member_id=..., output_oid=...)`. Run `workspace_outputs.execute_checks` for the
frozen requirement IDs/argv after the commit, with actual producer step,
session and attempt identities. Hash the summary under {{artifact_root}} and
retain test receipts for `independent-acceptance` and `record-result`.
The inherited `record-result` publishes this implement commit through
`workspace_outputs.make_member_result` and `prepare_member_result`, using an
admitted recorder and an independent review of the same commit. Do not close
the source anchor or publish accepted metadata here. Failed or missing checks,
review, records or claims block. A summary schema pass supplies no acceptance.

Use the source-anchor procedure below only for explicit `legacy`. An unknown
mode or failed managed read must never select legacy.

For legacy work, read the claimed step's `gc.root_bead_id` and that root's
stamped `gc.source_anchor_id`. Use the exact stamp from inherited preparation.
For a native drain, it must equal `gc.drain_member_id`; the synthetic
`gc.synthetic_kind=drain-unit-convoy` is a wrapper, never the source anchor.
If the stamp is absent or conflicts, stop with source preserved. The inherited
close-source-anchor resolves and closes that same original member.

Read `work_dir` from the source anchor, validate that it is an absolute existing
git worktree, set `WORKTREE` to that path, and `cd "$WORKTREE"` before reading
or editing source files. If `work_dir` is missing, invalid, or points at the
launcher checkout, fail before editing. `gc.work_dir` is the launcher rig root,
not the implementation worktree; do not edit, test, or commit in the launcher
checkout.

Use the installed ce-work guidance as the implementation prompt for this Gas
City lane. Implement only the owned source anchor boundary, run focused
verification from inside the worktree, then make a focused commit in the
worktree (`git add` the changed files and `git commit`). The inherited
`close-source-anchor` step fails closed when the worktree has no implementation
commit, so uncommitted edits are a failed implementation, not a pass. Write an
implementation summary to `{{artifact_root}}/task-<source-anchor-id>-summary.md`
after resolving the source anchor. Record the summary path, focused commit
hash, changed files, and verification result on this implement step and on the
source anchor before closing this step.

Close with `gc.outcome=pass` only after the work is implemented, verified, and
committed.

Do not invoke provider-native subagents. Leave the source anchor open for the
close-source-anchor step.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
