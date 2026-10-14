This is the `fix-loop-base` methodology contract fix-application step.

Concrete methodology packs override this step to run fixes through
`{{implementation_formula}}` with implementation target
`{{implementation_target}}`. Keep the fix work scoped to the findings artifact.

For managed source, implement only in the declared fix generation at its exact
canonical parent. Recheck `workspace_review.validate_fix_parent` before effects.
Complete ordinary producer project checks and independent review at replacement Y.
Publish immutable result/output records, then advance canonical only through
`workspace_outputs.prepare_canonical` with the guarded still-current X parent.
Any newer generation blocks this writer. Advancing to Y invalidates X approval;
retain X evidence for inspection rather than editing its immutable record.
