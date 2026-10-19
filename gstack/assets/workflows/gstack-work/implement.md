For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
Only `new` is supported. Preserve older or unclassified state and follow explicit migration guidance.

Implement the assigned gstack work bead.

Use `{{summary_path}}` when supplied as the absolute per-item summary path.
When it is empty, select a distinct item summary under the artifact root.
Record the selected path as `gc.implementation.summary_path` on this item's
workflow root before project checks, independent acceptance and result
publication. Those stages must qualify that same path and its exact bytes.
Do not move or rewrite an accepted summary to satisfy a different later option.

Retain `worktree_lifecycle` {{worktree_lifecycle}}. `new` requires the composed native helpers and captured policy. For an admitted managed run,
read exact run/source-plan/workspace identities through the imported Gas City
`workspace_checkout.load_workspace_context` API and obtain the verified path
with `workspace_checkout.manage_workspace(action="path", ...)`. Require the
current native producer claim and admitted member/owner grant before edits.
First entry matches `input_oid`. Preserve unexpected dirty state, advanced
HEAD or conflicting ownership as a blocker outside all worktrees. A managed
read failure cannot select raw `work_dir` or recapture the default branch.

Commit owned changes in that workspace, then freeze the full `output_oid`.
For `no_change`, retain `input_oid` without an empty commit. Construct
`workspace_outputs.result_binding(run, plan, workspace, store_ref=...,
member_id=..., output_oid=...)` and run `workspace_outputs.execute_checks`
after the commit for frozen requirement IDs/argv and actual native producer
step/session/attempt. Hash the summary under {{artifact_root}}. The inherited
`independent-acceptance` and `record-result` stages qualify this exact commit
through independent review and admitted `prepare_member_result` recording.
Leave source closure to the inherited close stage after accepted readback.
Neither self-review nor a summary schema pass supplies independent acceptance.

Gas City owns the worktree, bead, and convoy plumbing. Read the assigned
implementation bead, the approved plan, and any context bundle before editing.
Use the gstack discipline: ship the narrowest complete slice, test it, review
your own diff, and record proof.

Your summary must include intended behavior, first verification command,
changed files, the focused commit hash, proof command, remaining risks, and any
release consideration.

Close with `gc.outcome=pass` only after the work is implemented, verified, and
committed.

Do not invoke provider-native subagents. You are the implementation lane.

Artifact validation: this step is gated by the imported pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
