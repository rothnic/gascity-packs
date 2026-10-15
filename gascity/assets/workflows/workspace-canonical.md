For `new`, use the [native runtime arguments](workspace-runtime.md). Resolve
`TERMINAL_SUMMARY` from the terminal member's already accepted artifacts.

```bash
gc gc workspace flow canonical "${WORKSPACE_ARGS[@]}" --summary "$TERMINAL_SUMMARY"
```

The command reads the current plan, terminal owner output and member result from
their native references. The canonical record retains the accepted summary hash.
An aggregate report may link that summary. Rewriting the summary requires new
checks and independent review.

Missing, stale or partial native records stop finalization. Preserve older
runs for explicit migration without recapturing source.
