This is the `implementation-base` methodology contract source-anchor close step.
Concrete methodology packs may override the artifact checks while preserving
the native closure contract below.

Close the original source member through the [native runtime recipe](../workspace-runtime.md).

Only the recorded `new` lifecycle is supported. Resolve the current native
run, source plan, workspace and grant references. Run
`gc gc workspace flow close-source` with the exact member ID after
`record-result` has committed or replayed its accepted result and checkpoint.
The last member also requires its qualified owner-output.

If `{{summary_path}}` is set, verify that the accepted result retains that exact
summary path and hash. Preserve the accepted bytes. A changed summary requires
new checks and independent acceptance before closure.

The helper validates the current generation, clean output OID, captured project
checks, independent review and artifact hashes. Closure supplies no additional
acceptance. Missing, stale, foreign or unknown evidence leaves the member open.
An already closed member requires the same accepted readback on replay.

Close this physical workflow step only after successful readback. Never close
a wrapper convoy, parent workflow or another member. Preserve older or
unclassified runs and checkouts for explicit migration.
