Prepare the Superpowers brainstorming context.

Resolve the build target, artifact root, design candidate path, requirements
artifact path, optional context bundle, and brainstorming approval mode. Use
workflow root metadata `gc.var.brainstorming_approval_mode` when present;
otherwise default to `autonomous`.

Create the brainstorming artifact directory under the build artifact root.
Read the native loop control's `gc.check_path` and verify it resolves the imported
Gas City pack's executable `design-review-approved.sh`. Do not copy or refresh
rig-local scripts. A missing resolved helper stops setup.

Write a compact context note for the design-approval and written-spec loops.

Do not invoke provider-native subagents or upstream plugin runtime commands.
This Gas City graph stage is the delegation mechanism.
