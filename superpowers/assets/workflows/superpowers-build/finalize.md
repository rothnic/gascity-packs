Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Use the native managed source contract below. Only `new` is supported.
Legacy or unclassified state requires explicit migration; preserve its checkout
and original run. Never infer source authority from paths or artifacts.
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

Use the assigned Superpowers branch-finalization skill materialized for this agent.

Run `gc gc workspace flow verify` using
[the native runtime arguments](../../../../gascity/assets/workflows/workspace-runtime.md), then require
`workspace_review.validate_approval` on the current canonical generation and
unchanged accepted artifacts before recording pass.

Read the accepted `gc.build.implementation-summary.v1` summary at its original
absolute path and verify its recorded hash. Preserve its original workflow,
methodology, producer and trace, including when it belongs to a member run.
The reporting key `gc.build.implementation_summary_path` must identify that
accepted path; it cannot select or qualify a replacement. Missing or changed
accepted bytes block finalization. Do not synthesize, copy, restamp or rewrite
the accepted summary.

Write a separate final report that links the accepted artifacts. Confirm their
paths, test evidence, review state, residual risks and publish readiness.
Record the final report path as `gc.build.final_report_path` and the build-base
finalize outcome on the workflow root bead. Keep the accepted summary unchanged.

Do not invoke provider-native subagents or upstream plugin runtime commands.

Artifact validation: this stage is gated by the imported pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.final_report_path` against schema `gc.build.final-report.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
