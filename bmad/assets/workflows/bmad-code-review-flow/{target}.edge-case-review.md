Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply
only to explicit `legacy`; the managed instructions govern an admitted `new`
run. Unknown modes or failed reads never authorize legacy fallback.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` review, use the exact canonical binding and
canonical/result hashes from this expansion's setup context. Validate the
subject with `workspace_review.canonical_subject` before inspecting source.
Use `workspace_outputs.snapshot` before and after the lane to confirm the
recorded workspace, clean index and full output OID. Review and synthesis are
read-only source work. Record this lane's finding/report hash against that
subject; never choose a default ref, launcher or newer commit. Conditional
skips retain the same subject and the required skip artifact. A missing,
stale or changed context blocks instead of producing approval.

Run the BMAD edge case hunter review lane.

Use the BMAD code-review workflow and quick-dev acceptance standard as source guidance. Focus on boundary values, error paths, missing tests, concurrency, lifecycle, and integration edge cases.

Read `gc.build.code_review_context_path` from the workflow root. Write this lane
artifact to `{{artifact_root}}/code-review/edge-case.md`. Close with
`gc.outcome=pass`, `code_review.review_verdict=approve|iterate`, and
`code_review.lane_report_path=<lane artifact path>`. Do not set
`code_review.verdict` or `code_review.report_path`; the apply-bmad-review-findings
lane owns the final loop verdict consumed by the approval check.

Do not invoke provider-native subagents. You are the edge case hunter lane.
