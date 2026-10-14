Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply only
to explicit `legacy`; the managed instructions govern an admitted `new` run.
Unknown modes and failed managed reads never authorize legacy fallback.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` review/continuation, consume the recorded
canonical generation, owner-output and accepted terminal member-result through
`workspace_outputs.referenced_record`. Pass the retained mode and exact subject
into the existing methodology review expansion. Do not reconstruct source from
summary paths, a launcher HEAD or a current default branch. The concrete setup,
review/fix and terminal approval lanes own commit-bound review. Report mode
keeps source read-only and supplies no publication authority.

Prepare for gstack code review.

Current review_mode is {{review_mode}}. Interactive review may apply fixes
through the graph fix lane. Report mode must produce findings and evidence
without changing code.

The review fanout maps upstream gstack review, qa evidence, cso security, and
gap analysis into Gas City lanes. Ensure implementation summaries, changed
files, test proof, and remaining risks are available in the review context.

Close this stage with `gc.outcome=pass` after context is ready.

Do not invoke provider-native subagents. The Gas City review fanout is the
delegation mechanism.

The terminal code-review step writes the review report to the resolved review
report path and records that path on the workflow root bead as
`gc.build.review_report_path` before closing. Use
`gc bd update "<workflow-root-id>" --set-metadata "gc.build.review_report_path=<absolute path>"`.

Artifact validation: this stage is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the artifact recorded at `gc.build.review_report_path` against schema `gc.build.review.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
