Prepare the Superpowers brainstorming context.

Resolve the build target, artifact root, design candidate path, requirements
artifact path, optional context bundle, and brainstorming approval mode. Use
workflow root metadata `gc.var.brainstorming_approval_mode` when present;
otherwise default to `autonomous`.

Create the brainstorming artifact directory under the build artifact root.
Apply the imported Gas City [workspace entry contract](../../../../gascity/assets/workflows/workspace-entry.md)
with the `requirements` entrypoint through `gc gc workspace entry gate`, keeping
the exact native city, store, rig, workflow root, and claimed step explicit.

Locate this workflow's design-approval validation control and read its recorded
absolute `gc.check_path`. Confirm that check is executable; the imported formula
layer owns its path and any supported override.

Write a compact context note for the design-approval loop and written-spec
loop, including the native check path.

Do not invoke provider-native subagents or upstream plugin runtime commands.
This Gas City graph stage is the delegation mechanism.
