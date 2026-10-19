Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` documentation pass, inspect the exact canonical
source. Record proposed updates in the lane artifact. Report mode cannot edit
source. Required repository edits use `workspace_review.fix_plan` with the
exact canonical parent and an admitted generation/workspace. Run the common
result, canonical, test and independent review path for the resulting commit.
Return `iterate` and require new code review, QA and release readiness for that
OID. Do not mutate the accepted canonical checkout or preserve an old approval
over documentation changes. Missing fix routing or native admission blocks.

Run the gstack document-release lane.

Check README, architecture docs, usage docs, changelog, and contributor docs
that are affected by the change. Write exact documentation updates or state why
no docs need to change.

Write findings under the artifact root.

Close with `gc.outcome=pass`,
`gstack.release.docs_verdict=approve|iterate`, and
`gstack.release.output_path=<document-release report path>`.

Do not invoke provider-native subagents. You are the docs lane.
