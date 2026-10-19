Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Source access requires the recorded `new` lifecycle.
Legacy or unclassified work stops for explicit migration; preserve its original
run and checkout. Do not infer source authority from artifacts or old paths.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` review, load exact run/source-plan/workspace,
canonical, terminal member-result and owner-output references through
`workspace_outputs.referenced_record`. Validate current native qualification
and the accepted requirement scope before source access. Call
`workspace_review.begin_canonical_review` with the exact binding, required
checks, artifact root, recorded work_dir, actual native reviewer identity and
selected review_mode. Preserve its canonical/result hashes and before snapshot
in the review context. Every lane must inspect that same full output OID.
Use the recorded run base or canonical fix parent for the diff, never a current
default branch. Reports name the generation, owner, member, OID and hashes.
Keep report-only review read-only. Missing or conflicting evidence blocks.

Prepare the Superpowers code-review context.

Resolve the implementation summary, changed files, diff base, requirements,
plan, decomposition output, and artifact root from workflow root metadata and
the completed drain manifest. Use these exact handoff paths:

- code-review context: `<artifact_root>/code-review-context.md`
- implementation review report: `<artifact_root>/implementation-review-report.md`
- gap-analysis report: `<artifact_root>/gap-analysis-report.md`
- review fix summary: `<artifact_root>/review-fix-summary.md`

`<artifact_root>` is relative to the rig repository root. Create and write
these files there, and record the same rig-relative paths in root metadata. Do
not use a per-bead worktree as the artifact root: that worktree is disposable
and inaccessible to later review and finalization lanes.

Write the compact context file to the code-review context path. The context
file must include the workflow root id, source bead id, implementation convoy
id, implemented member bead ids, task summary paths, commit hashes, changed
files, requirements path, plan path, decomposition path, and the exact report
paths above.

For a direct, standalone review (no implementation convoy, drain manifest,
requirements, plan, or decomposition is available), write the literal context
field `implementation_convoy_id: not provided` and mark each unavailable
upstream path `not provided`. Do not invent an external convoy or infer a full
build workflow from the review subject alone. Those markers distinguish
standalone review scope from a build-derived review whose required artifacts are
missing.

Update workflow root metadata before closing:

- `gc.build.code_review_context_path=<context path>`
- `gc.build.code_review_report_path=<implementation review report path>`
- `gc.build.gap_analysis_report_path=<gap-analysis report path>`
- `gc.build.review_fix_summary_path=<review fix summary path>`
- `gc.build.code_review_status=ready`

The context file must state the loop contract:

- request-code-review writes `code_review.review_verdict=approve|iterate` and
  `code_review.review_report_path=<implementation review report path>`.
- gap-analysis-review writes `code_review.gap_verdict=approve|iterate` and
  `code_review.gap_report_path=<gap-analysis report path>`.
- process-code-review owns the approval-check fields
  `code_review.verdict=done|iterate` and
  `code_review.report_path=<review fix summary path>`.

Close this setup bead with `gc.outcome=pass` and
`code_review.output_path=<context path>`.

Do not invoke provider-native subagents or upstream plugin runtime commands.
This graph stage is the delegation mechanism.
