Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` drain or continuation, call
`workspace_entry.read_entry` with the exact original workflow root, registered
city/rig/store, current claimed step, retained generation/mode and native input
convoy, with `require_plan=True`. Read back the immutable run and source-plan
references and hashes before delegation. The existing native drain owns
routing; this control stage does not implement source or launch extra workers.
Each leaf must use the declared workspace owner and accepted member input.
A shared drain advances only after committed/replayed member-result readback;
its final member also requires an accepted owner-output. Missing shared result
stages or unknown native state block with original evidence preserved.

A same-root continuation reconstructs these exact records and admitted claims.
An artifact-only or cross-root handoff cannot recapture a default base, infer
accepted output from closed beads, or overwrite a retained lifecycle mode.
Use explicit migration for such legacy input and preserve the original run.

Drain gstack work in one shared session.

Route assigned implementation beads to {{implementation_target}} using
`gstack-work-item`. Keep the item lane single-lane and stop on item failure.

Do not invoke provider-native subagents.
