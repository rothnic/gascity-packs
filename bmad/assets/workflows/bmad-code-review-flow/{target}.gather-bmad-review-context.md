Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply
only to explicit `legacy`; the managed instructions govern an admitted `new`
run. Unknown modes or failed reads never authorize legacy fallback.
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

Gather BMAD code-review context.

Use the installed `bmad-code-review` skill as guidance. Resolve the
implementation summary, changed files, diff base, PRD, architecture,
epics/stories, test evidence, and artifact root.

Create `{{artifact_root}}/code-review/` if needed. Write:

- Review context: `{{artifact_root}}/code-review/context.md`
- Synthesized report path: `{{artifact_root}}/code-review/review-report.md`
- Review-fix summary path: `{{artifact_root}}/code-review/apply-summary.md`

Record those paths on the workflow root as:

- `gc.build.code_review_context_path`
- `gc.build.code_review_report_path`
- `gc.build.review_fix_summary_path`
- `gc.build.code_review_status=ready`

Close this setup lane with `gc.outcome=pass` only after the context file exists
and the root metadata points at all three paths.

Do not invoke provider-native subagents. This graph lane is the delegation mechanism.
