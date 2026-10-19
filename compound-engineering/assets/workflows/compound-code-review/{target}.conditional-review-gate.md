Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Source access requires the recorded `new` lifecycle.
Legacy or unclassified work stops for explicit migration; preserve its original
run and checkout. Do not infer source authority from artifacts or old paths.
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

Gate one Compound Engineering conditional code-review lane.

Read the claimed bead metadata `ce.review_key`, `ce.review_step_suffix`, and
`ce.review_artifact_name`. Read the reviewer manifest from workflow root
metadata `gc.build.reviewer_selection_path`.

If the manifest selects `ce.review_key`, close only this gate bead with
`gc.outcome=pass`, `code_review.gate_decision=selected`, and
`code_review.review_key=<ce.review_key>`. The paired reviewer bead becomes
ready after this gate closes.

If the manifest skips `ce.review_key`, find the paired reviewer bead with
`gc bd list --all --metadata-field "gc.root_bead_id=$CLAIMED_ROOT_BEAD_ID"
--metadata-field "gc.step_ref=<paired step ref>" --json --limit 0`, where the
paired step ref is this gate's `gc.step_ref` without the trailing `-gate`. If
the current bead does not expose `gc.step_ref`, derive the paired step ref from
`ce.review_step_suffix` and verify the candidate title and route before updating
it. Write a no-op lane artifact to
`{{artifact_root}}/code-review/<ce.review_artifact_name>`, update the paired
reviewer bead with `gc.outcome=pass`,
`code_review.review_verdict=approve`,
`code_review.lane_report_path=<no-op artifact path>`,
`code_review.gate_decision=skipped`, `code_review.review_key=<ce.review_key>`,
and `code_review.skip_reason=<manifest reason>`, then close that paired
reviewer bead. After that, close this gate bead with `gc.outcome=pass`,
`code_review.gate_decision=skipped`, `code_review.review_key=<ce.review_key>`,
and `code_review.skip_reason=<manifest reason>`.

Use exact bead ids from filtered `gc bd list --json` results. Do not update a
template name, do not fuzzy-match, and do not close a bead without reading it
back afterward.

Do not invoke provider-native subagents. This Gas City gate prevents skipped CE
conditional reviewers from being routed to real reviewer sessions.
