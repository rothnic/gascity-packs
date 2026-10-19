Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` QA pass, read the canonical and terminal accepted
result through `workspace_outputs.referenced_record`. Validate the subject with
`workspace_review.canonical_subject` and preserve exact run/generation/owner,
output OID, required check scope and artifact hashes. Recheck the same subject
before and after browser/regression inspection. Record actual tested application
revision; a launcher build or unrelated deployment earns no credit. Bind QA
summary and lane reports to that OID. `done` requires unchanged source and all
required behavior/proof; missing evidence or a changed canonical returns
`iterate` or a preserved blocker. Report mode remains read-only.

Prepare the gstack QA context.

Gather staging URLs, local run commands, test commands, acceptance criteria,
and implementation summaries. If a browser surface exists, identify the flows
to exercise. If not, identify the closest command or API workflow.

Current interaction_mode is {{interaction_mode}}. Ask for credentials or a
staging URL only when the flow cannot be tested otherwise.

Close with `gc.outcome=pass`.

Do not invoke provider-native subagents. Gas City graph lanes are the
delegation mechanism.
