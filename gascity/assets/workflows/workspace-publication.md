For `new`, use the [native runtime arguments](workspace-runtime.md). Resolve
`REVIEW_OWNER_ID="$ROOT_ID"` from the root's exact native review reference.
The referenced review payload retains the physical `review-result` writer.
`PUBLICATION_DECISION` must name the existing authorized destination, frozen lease,
canonical hash and approval hash. The command also requires positive publication
authority on the native launch root.

```bash
gc gc workspace flow publish "${WORKSPACE_ARGS[@]}" \
  --review-owner-id "$REVIEW_OWNER_ID" --decision "$PUBLICATION_DECISION" \
  --title-file "$SANITIZED_TITLE_FILE" --body-file "$SANITIZED_BODY_FILE"
```

Git pushes use the exact approved OID and a create-if-absent or explicit lease.
Native uncertainty is persisted before the effect. PR creation uses the existing
GitHub adapter, authenticated actor, exact repository/base/mode and one durable
marker reservation. Lost responses reconcile the same intent through actual
provider readback. An uncertain effect is never retried automatically.

When publication is disabled, retain the local approved result. A no-op cannot
convert a blocked review or incomplete checkpoint into success. Older or
unclassified state requires explicit migration before publication.
