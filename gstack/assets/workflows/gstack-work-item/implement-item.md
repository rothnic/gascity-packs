For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
The legacy instructions below retain their existing behavior.

Implement the assigned gstack shared-drain item.

Retain `worktree_lifecycle` {{worktree_lifecycle}}. `new` remains disabled
until composed shared-workspace acceptance qualifies. In an admitted managed
run, use the imported Gas City `workspace_checkout.load_workspace_context`
and `workspace_checkout.manage_workspace(action="path", ...)` APIs with exact
run/source-plan/workspace and native city/rig/store identities. Require the
current native claim, admitted owner grant, active `gc.drain_member_id`,
position and generation. Start from the preceding accepted checkpoint, or the
frozen owner input for its first member. Preserve unexpected dirty state,
HEAD drift or ownership conflicts. Never substitute a launcher or default ref.

Commit owned source changes. A verified `no_change` retains `input_oid`
without an empty commit. Freeze `output_oid`, construct
`workspace_outputs.result_binding(run, plan, workspace, store_ref=...,
member_id=..., output_oid=...)`, and run `workspace_outputs.execute_checks`
for frozen requirement IDs/argv with actual native producer identities after
the commit. Hash the summary under {{artifact_root}}. The inherited shared
`independent-acceptance` and `record-result` stages must consume this exact
implement-item commit. Require independent review and admitted
`workspace_outputs.prepare_member_result` readback before checkpointing.
The final member also requires a qualified owner-output. Missing shared stages
or native admission block. Leave closure and advancement to that lifecycle.

The existing shared procedure below applies only to explicit `legacy`.
Unknown mode or failed managed reads never select legacy.

Gas City owns the shared drain and source-anchor lifecycle. Read only the
assigned item scope, implement the smallest complete change, run focused proof,
and record intended behavior, first verification command, changed files, proof
command, and remaining risks.

Close with `gc.outcome=pass` only after verification.

Do not invoke provider-native subagents. You are the single item lane.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
