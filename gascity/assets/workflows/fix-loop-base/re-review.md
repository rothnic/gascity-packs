This is the `fix-loop-base` methodology contract re-review step.

Concrete methodology packs override this step to call `{{code_review_formula}}`
after fixes. Continue only while the iteration count is below
`{{max_iterations}}`. Record the follow-up review report path on workflow root
metadata as `gc.build.review_report_path` before closing.

For managed source, review the newly bound canonical Y through `workspace_review`,
with actual required project tests and independent verdict at Y. X approval cannot
approve Y even when X is an ancestor. Use a fresh immutable review record and
`prepare_review_record`; verify readback before finalization. Exhaustion, failed
tests, findings, skipped/unrun/setup_failure and stale parents remain visible
blockers. Do not manufacture a pass from a closed fix convoy or schema-valid report.

Artifact validation: this step is gated by the pack-owned `build-artifact-valid.sh` check, which validates the report recorded at `gc.build.review_report_path` against schema `gc.build.review.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the report in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the report.
