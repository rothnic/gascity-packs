Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply only
to explicit `legacy`; the managed instructions govern an admitted `new` run.
Unknown modes and failed managed reads never authorize legacy fallback.
Resolve shared helpers through the imported Gas City `assets/scripts` layer.

For an admitted `new` finalization, load the exact canonical,
owner-output, terminal member-result and review through
`workspace_outputs.referenced_record`. Validate accepted checks, independent
review, current native qualification and artifact hashes against clean recorded
HEAD. Preserve the canonical summary's bytes and full output OID. Produce the
final report from those accepted records; never reconstruct accepted source
from closed beads, a summary path, default ref or launcher HEAD. Missing,
partial or drifted evidence blocks. Finalization supplies no publication
approval and cannot reopen source work or rewrite accepted receipts.

Finalize the gstack sprint.

Write a concise sprint report under the build artifact root. Include the
methodology, interaction_mode, review_mode, requirements path, plan path,
decomposition path, implementation summary, review report, QA report, release
readiness report, tests run, changed files, residual risks, and next human
action.

The report should explain that garrytan/gstack role behavior was adapted into
Gas City fanouts and persistent beads. Keep it useful for someone using
automated factories for the first time.

Close with `gc.outcome=pass` and the sprint report path.

Do not invoke provider-native subagents.

Artifact validation: this stage is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the artifact recorded at `gc.build.final_report_path` against schema `gc.build.final-report.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
