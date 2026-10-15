This is the `build-from-decompose-base` decompose handoff step.

Concrete rule: concrete methodology packs extend this base rather than copying the suffix graph.

Validate the prerequisite inputs before any side effects:

- artifact_root: {{artifact_root}}
- context_path: {{context_path}}
- requirements_path: {{requirements_path}}
- plan_path: {{plan_path}}
- plan_review_path: {{plan_review_path}}
- decomposition_path: {{decomposition_path}}
- decomposition_formula: {{decomposition_formula}}
- drain_policy: {{drain_policy}}
- interaction_mode: {{interaction_mode}}
- review_mode: {{review_mode}}

Do not rerun requirements, plan, or plan-review. This continuation is valid
only when the supplied requirements, implementation plan, and plan-review
artifacts exist and the plan-review artifact records approval or an equivalent
pass verdict.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" --entrypoint decompose
```

In new mode, an initial decomposition suffix captures one run from its real
native task or convoy before allocation. A recorded suffix reuses its original
run through the entry contract's native source relationship. Approved artifacts
supplement that proof; they do not establish its root, store, generation or base.

Record `gc.build.continuation_entrypoint=decompose` when this suffix is
launched directly. Close only after the decompose stage can create or reuse the
decomposition artifact and implementation convoy.
