This is the `build-from-requirements-base` requirements handoff step.

Validate artifact_root {{artifact_root}}, context_path {{context_path}},
requirements_path {{requirements_path}}, interaction_mode {{interaction_mode}},
and the selected planning formula {{planning_formula}} before requirements work
starts.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" \
  --entrypoint requirements --allow-pending-source
```

An awaiting-source result permits requirements work, not implementation.

Record `gc.build.continuation_entrypoint=requirements` when this suffix is
launched directly. Close only after the requirements stage can write or reuse
the selected requirements artifact.
