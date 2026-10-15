
Read the current step bead metadata, get `gc.root_bead_id`, then read workflow
root metadata with `gc bd show <root-bead-id> --json`. Required workflow root
metadata keys are `gc.github.source_bead_id`, `gc.github.repo`,
`gc.github.number`, `gc.github.url`, `gc.github.head_sha`,
`gc.github.snapshot_path`, and `gc.github.review_dir`.

If workflow root metadata has `gc.github.reused_current_output=true`, do not
launch the generic `review` formula. Instead validate the reused
`gc.github.review_report_path` with
`{{pack_root}}/assets/scripts/github_reports.py review-outcome`, verify it
lives under `gc.github.review_dir`, refresh `gc.github.review_outcome` from the
validator result, close this step with `gc.outcome=pass`, and leave the reused
artifacts untouched. This is the no-op path that makes current-head reuse
effective even though the formula graph still schedules this step.

Create the deterministic generic-review handoff artifacts for this head SHA:

- `SUBJECT_PATH=<gc.github.review_dir>/subject.md`
- `REPORT_PATH=<gc.github.review_dir>/review-report.md`

Write `SUBJECT_PATH` as a Markdown review subject that includes the PR URL
{{github_pr_url}}, repo, PR number, head SHA, snapshot JSON path, and explicit
instructions to review the PR diff/head for correctness, tests, security,
maintainability, and release risk. Keep large payloads in artifact files; the
subject may point to the snapshot instead of embedding it.

Launch the selected targetless code-review methodology formula with explicit
paths. The default is `review`; toolkit adapters may override
`code_review_formula` without changing GitHub snapshot, comment, or finalize
behavior. Compatibility with the requested modes was validated at the snapshot
gate. Pass review_mode {{review_mode}} and interaction_mode
{{interaction_mode}} through when the selected formula accepts them; the PR
adapter itself never mutates code regardless of review mode.

This report-only review consumes the explicit snapshot, PR diff and recorded
`gc.github.head_sha`. Keep those immutable inputs. Artifact paths grant no
workspace or source-write authority. A reviewer that needs a source checkout
must receive an existing native run and verified workspace; never manufacture
one or infer a base from the current directory.

Launch with explicit report inputs. Omit an interaction or review variable only
when the selected formula does not declare that variable:

```sh
gc sling gc.run-operator {{code_review_formula}} --formula \
  --var context_path="{{context_path}}" \
  --var subject_path="$SUBJECT_PATH" \
  --var report_path="$REPORT_PATH" \
  --var interaction_mode="{{interaction_mode}}" \
  --var review_mode="{{review_mode}}"
```

Keep this adapter read-only. `agent` may produce a structured fix handoff but
cannot apply it. An interactive source change requires a separately admitted
managed workflow and verified workspace; this snapshot grants no such authority.

Do not close this step until `REPORT_PATH` exists and validates through
`{{pack_root}}/assets/scripts/github_reports.py review-outcome "$REPORT_PATH"`.
Persist the review handoff and result on workflow root metadata:
`gc bd update <root-bead-id> --set-metadata gc.github.review_subject_path="$SUBJECT_PATH" --set-metadata gc.github.review_report_path="$REPORT_PATH" --set-metadata gc.github.review_outcome=<approve|comment|request_changes|block>`.

The adapter does not check out a mutation worktree, push commits, amend
contributor branches, submit formal GitHub review events, or create follow-up
PRs.
