For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
Only `new` is supported. Preserve older or unclassified state and follow explicit migration guidance.

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

Use the installed ce-work guidance as the implementation prompt for this Gas
City lane. Implement only the owned member boundary, run focused
verification from inside the worktree, then make a focused commit in the
worktree (`git add` the changed files and `git commit`). A changed result requires a committed output. A verified no-change result
retains the accepted input OID. Write an
implementation summary at `{{summary_path}}` when supplied as the absolute
per-item summary path. When it is empty, use
`{{artifact_root}}/task-<source-anchor-id>-summary.md` after resolving the source
anchor. Record the selected path as `gc.implementation.summary_path` on this
item's workflow root before project checks, independent acceptance and result
publication. Those stages must qualify that same path and its exact bytes.
Do not move or rewrite an accepted summary to satisfy a different later option.
Record the summary path, exact output OID, changed files and verification
result on this implement step. Accepted records belong to the admitted recorder.

Close with `gc.outcome=pass` only after the work is implemented, verified, and
committed.

Do not invoke provider-native subagents. Leave the source anchor open for the
close-source-anchor step.

Artifact validation: this step is gated by the imported pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
