Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply only
to explicit `legacy`; the managed instructions govern an admitted `new` run.
Unknown modes and failed managed reads never authorize legacy fallback.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` release pass, use the exact canonical source and
accepted terminal result through `workspace_outputs.referenced_record` and
`workspace_review.canonical_subject`. QA and code-review reports must bind the
same generation/OID and hashes. Keep source read-only. Readiness summaries name
that subject and required reports. A later fix invalidates these checks until
the new tested/reviewed canonical OID completes QA and release readiness.
Do not push, open PRs, merge or deploy from readiness lanes. Report mode grants
no publishing authority. Missing or changed evidence preserves a blocker.

Run the gstack ship readiness lane.

Check branch cleanliness, test commands, coverage deltas, review approval,
QA approval, release notes, and whether publish flags permit push or PR work.
Do not push or open PRs from this lane.

Write findings under the artifact root.

Close with `gc.outcome=pass`,
`gstack.release.ship_verdict=approve|iterate`, and
`gstack.release.output_path=<ship readiness report path>`.

Do not invoke provider-native subagents. You are the release-engineering lane.
