Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` decomposition, first validate the captured run
with `workspace_entry.read_entry`. Keep original run input/source anchor
separate from the new implementation convoy. Translate this methodology's
approved source work into the shared tasks.md contract and use the imported
`create_beads_from_tasks.py` managed route with explicit --worktree-lifecycle
new, --city, --store-ref, --workflow-root, --claimed-step, --generation and
native --source-plan-record-id/--authority-id values. Preserve its actual
native IDs, ownership and scheduling dependencies. Source predecessor order
is declared separately in the source-plan; do not infer it from a `needs` edge.

The common `workspace_source_plan.declare_plan` / `publish_plan` APIs publish
one exact source-plan and implementation-convoy binding under an admitted
claim/grant. Require committed/replayed receipt and readback before drain.
Reuse exact records on continuation; artifact text or a closed bead cannot
substitute for accepted output. Unknown creation/publication outcomes require
inspection of the original native request, never duplicate expansion or raw
lifecycle metadata patches. Preserve all methodology approvals/readiness gates.

Translate `{{plan_path}}` and optional context `{{context_path}}` into a
Superpowers implementation convoy. Record `{{decomposition_path}}` if the
caller provided a decomposition artifact path.

Artifact validation: this stage is gated by the imported pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.decomposition_path` (fallback `gc.var.decomposition_path`) against schema `gc.build.decomposition.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
