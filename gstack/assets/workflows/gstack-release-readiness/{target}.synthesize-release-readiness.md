Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` release pass, use the exact canonical source and
accepted terminal result through `workspace_outputs.referenced_record` and
`workspace_review.canonical_subject`. QA and code-review reports must bind the
same generation/OID and hashes. Keep source read-only. Readiness summaries name
that subject and required reports. A later fix invalidates these checks until
the new tested/reviewed canonical OID completes QA and release readiness.
Do not push, open PRs, merge or deploy from readiness lanes. Report mode grants
no publishing authority. Missing or changed evidence preserves a blocker.

Synthesize the gstack release readiness result.

Read the document-release, ship-readiness, and deployment-readiness reports.
Set `code_review.verdict=done` only when release readiness is approved or every
remaining concern is explicitly non-blocking. Set `code_review.verdict=iterate`
when release-blocking issues remain.

Write one release readiness summary under the artifact root.

Close with `gc.outcome=pass`,
`code_review.verdict=done|iterate`,
`code_review.report_path=<release readiness summary path>`, and
`gstack.release.summary_path=<release readiness summary path>`.

Do not invoke provider-native subagents. Synthesis happens in this Gas City
fan-in lane.
