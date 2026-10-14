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

Select the Compound Engineering conditional code-review lanes.

Read the review context from workflow root metadata
`gc.build.code_review_context_path`. Preserve the stock CE reviewer-selection
intent by selecting conditional lanes with model judgment over the context
bundle, diff, changed files, PR metadata, and prior comments. Do not use simple
keyword matching.

Always keep these Gas City lanes active: correctness, testing,
maintainability, project standards, agent-native parity, learnings research,
and gap analysis.

For each conditional lane, record whether it is selected or skipped:

- security
- performance
- API contract
- data migration
- reliability
- adversarial
- previous comments
- Julik frontend races
- Swift iOS
- deployment verification

Write the reviewer manifest to
`{{artifact_root}}/code-review/reviewer-selection.json`. Update workflow root
metadata with:

- `gc.build.reviewer_selection_path=<manifest path>`
- `gc.build.selected_reviewers=<comma-separated always-on plus selected conditional keys>`
- `gc.build.skipped_reviewers=<comma-separated skipped conditional keys>`
- `gc.build.reviewer_selection_status=ready`

Close with `gc.outcome=pass` only after the manifest exists and all conditional
keys appear exactly once as selected or skipped.

Do not invoke provider-native subagents. This Gas City lane performs the CE
reviewer-selection step.
