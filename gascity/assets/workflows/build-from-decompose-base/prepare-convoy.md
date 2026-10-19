This is the `build-from-decompose-base` handoff into the inherited convoy suffix.

Validate that decomposition created or adopted an implementation convoy and
recorded it as `gc.input_convoy_id` and `gc.build.implementation_convoy_id`.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace entry gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" --entrypoint convoy --require-plan
```

Do not implement work from this handoff step. Close only after the inherited
`build-from-convoy-base` suffix can drain the implementation convoy without
rerunning decomposition.
