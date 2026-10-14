Review the exact recorded canonical generation after the methodology review and
required fixes. Use the [native runtime arguments](workspace-runtime.md).

```bash
gc gc workspace flow begin-canonical-review "${WORKSPACE_ARGS[@]}" \
  > "$ARTIFACT_ROOT/canonical-review-context.json"
```

Inspect the canonical source, captured project checks, accepted summary and
methodology findings. Write `CANONICAL_REVIEW_REPORT` with concrete findings.
Complete the review under this actual native reviewer occurrence:

```bash
gc gc workspace flow complete-canonical-review "${WORKSPACE_ARGS[@]}" \
  --context "$ARTIFACT_ROOT/canonical-review-context.json" \
  --report "$CANONICAL_REVIEW_REPORT" \
  --review-evidence "$ARTIFACT_ROOT/canonical-review-evidence.json" \
  --status "$CANONICAL_REVIEW_STATUS"
```

Only `passed` approves the exact canonical record and OID. Required changes stop
finalization. Route fixes through the native fix/decomposition workflow with the
current canonical generation and OID as its explicit parent. A replacement output
requires fresh project checks and independent review. Approval of an earlier OID
cannot approve its descendant. Exhaustion preserves the blocker and findings.
