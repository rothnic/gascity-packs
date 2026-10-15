Close the original source member through the [native runtime recipe](../../../../gascity/assets/workflows/workspace-runtime.md).

Only recorded `worktree_lifecycle=new` is supported. Resolve the current native
run, source plan, workspace and grant references. Run
`gc gc workspace flow close-source` with the exact member ID after
`record-result` has committed or replayed its accepted result and checkpoint.
The last member also requires its qualified owner-output.

For a separate-item formula exposing `summary_path`, read the supplied value
from the native root's `gc.var.summary_path`. If set, verify that the accepted
result retains that exact absolute path and its original hash. A mismatch blocks
closure; do not copy or rewrite accepted bytes to satisfy the option after
acceptance. Shared members retain their own distinct accepted paths.

The helper validates the current generation, clean output OID, captured project
checks, independent review and artifact hashes. Closure supplies no additional
acceptance. Missing, stale, foreign or unknown evidence leaves the member open.
An already closed member requires the same accepted readback on replay.

Close this physical workflow step only after successful readback. Never close
a wrapper convoy, parent workflow or another member. Preserve older or
unclassified runs and checkouts for explicit migration.

Keep the Superpowers TDD, spec-compliance and code-quality evidence bound to
the final task commit. Do not invoke provider-native subagents or plugin commands.
