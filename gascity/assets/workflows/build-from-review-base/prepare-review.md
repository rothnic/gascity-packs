This is the `build-from-review-base` review handoff step.

Apply the [workspace entry contract](../workspace-entry.md) before consuming
review evidence:

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" \
  --entrypoint review --require-plan
```

For a separately launched suffix, its native input must identify the recorded
implementation convoy or original source. An optional `worktree_run_root`
selector locates that run; it cannot authorize unrelated input. Keep the
captured base, layout, policy and exact source generation.

Recorded root selector: `{{worktree_run_root}}` (empty uses native relationships).
This value locates a candidate; the native task or convoy must prove its run.

For retained `new` mode, restore exact run/plan/canonical/result references from the
native adapter and verify the accepted canonical subject through `workspace_review`.
If the immutable canonical exists without its current pointer, use
`workspace_outputs.prepare_canonical` to replay that same physical record and bytes
with the original parent guard. Missing/conflicting pointers block; do not recapture
base, switch roots or infer a canonical commit from ancestry/closure.

Validate that implementation evidence exists before review runs:

- artifact_root: {{artifact_root}}
- context_path: {{context_path}}
- requirements_path: {{requirements_path}}
- plan_path: {{plan_path}}
- plan_review_path: {{plan_review_path}}
- decomposition_path: {{decomposition_path}}
- implementation_summary_path: {{implementation_summary_path}}
- code_review_formula: {{code_review_formula}}
- review_fix_formula: {{review_fix_formula}}
- implementation_formula: {{implementation_formula}}
- implementation_item_formula: {{implementation_item_formula}}
- implementation_target: {{implementation_target}}
- worktree_lifecycle: {{worktree_lifecycle}}
- review_mode: {{review_mode}}
- interaction_mode: {{interaction_mode}}
- max_iterations: {{max_iterations}}

If this suffix is launched directly, require explicit implementation evidence
or a root metadata pointer to it. If this step is reached from
`build-from-convoy-base`, consume the implementation summary recorded by the
implementation suffix. Do not run implementation work from this step.

Close only after the review subject, evidence paths, selected review/fix
formulas, modes, and max iteration limit are recorded on the workflow root.
