This is the `build-from-requirements-base` handoff into the inherited plan suffix.

Validate that the requirements artifact now exists and is approved or otherwise
valid for planning. Do not write the implementation plan from this step.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" --entrypoint plan
```

In new mode, reuse the original run; an approved artifact alone cannot provide
the missing native source identity.

Close only after the inherited `build-from-plan-base` suffix can consume the
requirements artifact without rerunning requirements.
