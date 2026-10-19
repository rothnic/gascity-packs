For `worktree_lifecycle=new`, use the imported Gas City
[managed runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).
Before source access, run `gc gc workspace checkout continue` with actual native
run/plan/workspace/grant references. After the final focused commit and summary,
run `gc gc workspace runtime checks`; the captured native policy selects required
commands. Preserve the exact output OID and actual receipts for independent-acceptance.
Leave source closure to the guarded result/checkpoint and close stages.
Only `new` is supported. Preserve older or unclassified state and follow explicit migration guidance.

Record the Superpowers task result.

For a separate-item formula exposing `summary_path`, read its supplied value
from the native root's `gc.var.summary_path` and use that exact absolute path.
When it is empty, or this shared-member formula exposes no such option,
select a distinct item summary under the artifact root.
Record the selected path as `gc.implementation.summary_path` on this item's
workflow root before project checks, independent acceptance and result
publication. Those stages must qualify that same path and its exact bytes.
Do not move or rewrite an accepted summary to satisfy a different later option.

Retain `worktree_lifecycle` {{worktree_lifecycle}}. `new` requires the composed native helpers and captured policy. For an admitted managed run,
reload the exact run/source-plan/workspace through the imported Gas City
`workspace_checkout.load_workspace_context` API. Require the active
`gc.drain_member_id`, current native producer claim and admitted owner grant.
Use only its verified workspace path. Preserve unexpected index, HEAD or owner
state as a blocker. Never recover through raw `work_dir` or a new default ref.

This is the task's final commit owner. Require the TDD red/green evidence and
the completed spec-compliance then code-quality review before the commit.
Commit only owned changes. For a verified `no_change`, retain `input_oid`
without an empty commit. Freeze the actual full `output_oid`, then construct
`workspace_outputs.result_binding(run, plan, workspace, store_ref=...,
member_id=..., output_oid=...)`. Run `workspace_outputs.execute_checks` after
the commit for the frozen requirement IDs/argv with this producer's actual
native step/session/attempt. Hash the task summary under {{artifact_root}}.

Pass that exact commit and test evidence to `independent-acceptance`, followed
by `record-result`. The latter uses `workspace_outputs.make_member_result` and
`prepare_member_result` with an admitted recorder and an independent review of
the committed source. Task review before the commit does not replace that
acceptance. A final shared member also requires the qualified owner-output.
Do not publish an accepted result, advance the shared member or close the
source anchor here. A failed TDD, spec, quality or managed acceptance gate
leaves the source anchor open.

Update the per-item summary with changed files, test commands, command output
locations, commits to make, blockers, and traceability back to the plan task.
If the task could not be completed, record the blocker and leave the source
anchor open with a failing outcome instead of hiding the failure.

Create a focused commit for this task when the verification evidence is clean
and the repository state is ready. Use the approved plan's commit guidance when
it gives an exact message; otherwise use a concise message scoped to the task.

Do not invoke provider-native subagents or upstream plugin runtime commands.
