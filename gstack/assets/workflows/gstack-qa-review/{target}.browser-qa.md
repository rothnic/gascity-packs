Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply only
to explicit `legacy`; the managed instructions govern an admitted `new` run.
Unknown modes and failed managed reads never authorize legacy fallback.
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

Run the gstack browser QA lane.

Exercise the most important user workflows with the available browser or
command-line testing surface. Capture screenshots, logs, command output, or
other evidence. If browser testing is unavailable, record the fallback proof
used and what remains untested.

Write findings under the artifact root.

Close with `gc.outcome=pass`,
`gstack.qa.browser_verdict=approve|iterate`, and
`gstack.qa.output_path=<browser QA report path>`.

Do not invoke provider-native subagents. You are the QA lane.
