For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
The legacy instructions below retain their existing behavior.

Implement this Compound Engineering shared-drain item with {{implementation_target}}.

Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native shared-workspace helpers and captured policy.
For an admitted `new` run, use the imported Gas City
`workspace_checkout.load_workspace_context` and
`workspace_checkout.manage_workspace(action="path", ...)` APIs with exact run,
source-plan, workspace, city/rig/store and claimed-step identities. Require the
current native claim and admitted member/owner grant. The active member must
equal `gc.drain_member_id` at the recorded position and generation. The input
must be the preceding accepted checkpoint, or the owner's frozen first input.
Preserve unexpected dirty state, a changed owner or an advanced HEAD as a
blocker. Do not infer a new base or advance another member's workspace.

Make a focused commit for this member's actual changes. For `no_change`, keep
the exact `input_oid` and do not create an empty commit. Freeze `output_oid`,
then call `workspace_outputs.result_binding(run, plan, workspace,
store_ref=..., member_id=..., output_oid=...)` and
`workspace_outputs.execute_checks` with frozen requirement IDs/argv and the
actual native producer identity. Hash the summary under {{artifact_root}}.
The shared `independent-acceptance` and `record-result` stages must use that
exact implement-item commit, checks and independent reviewer. Only a committed
or replayed `workspace_outputs.prepare_member_result` receipt and readback may
checkpoint this member. The final member also needs a qualified `owner-output`.
Leave source closure and pointer advancement to the admitted shared lifecycle.
If those stages or native capabilities are absent, preserve the evidence and
block. Do not close the member from this source-writing step.

Use the existing shared-drain procedure below only for explicit `legacy`.
Unknown mode or failed managed reads never select legacy.

For the legacy shared drain, read the current native root's
`gc.drain_member_id` and compare the item index and assigned member. A synthetic
drain-unit convoy must resolve to that original member. Do not close a wrapper,
parent convoy or workflow root as this item. Preserve a conflicting stamp or
unexpected owner instead of guessing from dependency or step IDs.

Run inside the existing shared worktree lifecycle. Resolve the assigned drain
member from metadata, validate ownership and context path {{context_path}} when
set, apply the smallest implementation changes for this item, run focused
verification, write an item summary to
`{{artifact_root}}/task-<source-anchor-id>-summary.md`, and close only the
source anchor on success. Record the summary path, changed files, and
verification result on the source anchor before closing it.

Do not invoke provider-native subagents. This Gas City lane is the work
delegation mechanism for ce-work.

Artifact validation: this step is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
