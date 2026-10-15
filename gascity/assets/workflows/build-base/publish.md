Execute `gc gc workspace flow publish` through
[the native publication recipe](../workspace-publication.md). Keep the same
recorded publish intent for push/PR readback; never create another effect after
an uncertain response. Preserve older or unclassified work for explicit migration.

This is the `build-base` publish stage. Treat it as a virtual contract that concrete formulas may override.

For the captured `new` run, use the exact canonical/approval/authority contract in
`workspace_publish.py` and the owning `publish` preflight/push/open-pr step files.
Persist and read back intent before effects; reconcile the same immutable OID and
PR marker after uncertainty without duplication. Missing approval/guards or changed
source blocks, and no-op preserves any earlier failure.

If `push` or `open_pr` is enabled, publish the finalized build result according to the workflow metadata. If publishing is disabled, record the exact reason and leave the artifacts ready for a later publisher.

Write a publish result artifact under the workflow artifact root when one is
available. Record the same publish outcome on the workflow root bead and this
publish step before closing.

Required workflow root metadata:

- `gc.build.publish_status=published|noop|failed`
- `gc.build.publish_action=push|pr|push_pr|noop|failed`
- `gc.build.publish_recorded_at=<UTC timestamp>`
- `gc.build.publish_artifact_path=<publish result artifact path>`
- `gc.build.publish_reason=<short machine-readable reason>`

For disabled publishing, use `gc.build.publish_status=noop`,
`gc.build.publish_action=noop`, and a reason such as
`push=false_open_pr=false`. Also record whether remotes were present with
`gc.build.publish_remote_status`.

Close this step only after the publish action or explicit no-op is recorded on
both the workflow root and the publish step.
