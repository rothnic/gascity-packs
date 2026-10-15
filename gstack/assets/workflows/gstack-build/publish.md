Optionally publish the gstack sprint.

Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Legacy or unclassified work requires explicit migration. Unknown or failed
native reads never authorize publication.

For an admitted `new` publication, require the exact canonical, accepted
terminal result, owner-output and commit-bound review through the imported
Gas City `workspace_outputs.referenced_record` APIs. Verify full `output_oid`,
clean recorded workspace, current native qualification, required project
checks and hashed artifacts. QA, release-readiness and final sprint reports
must all bind that same canonical generation/OID. A later documentation fix
invalidates the old readiness and approval; re-test and re-review its new
canonical output before publication. Missing or stale evidence blocks.

Respect push {{push}} and open_pr {{open_pr}} independently. If both are false,
record the explicit no-op on root and publish stage with the existing publish
artifact contract. A no-op grants no remote authority. With positive existing
authority, call `workspace_publish.publication_intent` for the exact canonical
OID, review hash, configured remote, full ref and hashed authorization decision.
Record the frozen expected remote OID and PR repository/base/actor/mode/marker.
Publish the intent through `workspace_publish.prepare_publication_record`
under the current admitted claim/owner grant; execute and resolve the same
`WorkspaceStore` request and require committed/replayed readback before effects.

Use `workspace_publish.push_publication` for the explicit approved OID:ref
push and lease. PR creation remains in the existing provider adapter: first
use `workspace_publish.reserve_pr_attempt`, then consume exact provider
readback through `workspace_publish.reconcile_publication`. Preserve uncertain
responses and reconcile the same intent; do not retry creation, switch to a
branch tip, reset the worktree or invent publication success. Only observed
Git/provider state permits the final admitted publication record and pass.
The publisher alone owns effects. QA, ship and release lanes cannot push,
open PRs, merge or deploy. Report-only review cannot authorize publication.

Respect push {{push}} and open_pr {{open_pr}}. If neither is enabled, record a
no-op publish result. If publishing is enabled, verify the sprint report,
release readiness report, test evidence, and review approval are present before
any push or PR action.

Close with `gc.outcome=pass` and publish metadata.

Do not invoke provider-native subagents.
