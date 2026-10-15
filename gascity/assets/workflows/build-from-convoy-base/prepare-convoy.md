This is the `build-from-convoy-base` convoy handoff step.

Validate the implementation convoy before implementation drains run. Accept the
convoy from `{{implementation_convoy_id}}` when supplied; otherwise read the
convoy ID recorded on the workflow root as `gc.input_convoy_id`.

The convoy must contain only runnable implementation work items for this build
continuation. Reject planning, review, workflow-control, or original request
convoys. Apply the [workspace entry contract](../workspace-entry.md):

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" \
  --entrypoint convoy --require-plan
```

In new mode, consume the original run and the current convoy's declared source
plan. The helper validates their existing native binding; this handoff must
not replace `gc.input_convoy_id`, recapture a base, or adopt artifact-only
state. Older or unclassified input requires explicit migration. The native
source plan owns both convoy bindings.

Close only after the convoy identity, drain policy {{drain_policy}}, selected
implementation target {{implementation_target}}, and source artifact paths are
validated and recorded.
