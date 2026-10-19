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

Synthesize the gstack QA result.

Read the browser QA, regression evidence, and QA fix artifacts. Set
`code_review.verdict=done` only when QA behavior and regression evidence are
approved. Set `code_review.verdict=iterate` when defects or missing evidence
remain.

Write one QA summary under the artifact root.

Close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<QA summary path>`, and
`gstack.qa.summary_path=<QA summary path>`.

Do not invoke provider-native subagents. Synthesis happens in this Gas City
fan-in lane.
