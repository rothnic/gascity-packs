This is the `build-from-plan-base` handoff into the inherited decompose suffix.

Validate that the plan and plan-review artifacts now exist, that the
plan-review verdict approves decomposition, and that downstream decompose
selectors are present.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace entry gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" --entrypoint decompose
```

Do not create implementation beads in this handoff step. Close only after the
inherited `build-from-decompose-base` suffix has the approved plan inputs it
requires.
