Source work requires the recorded `new` lifecycle. Use the existing
[entry contract](../workspace-entry.md) and verified native run, source plan and
workspace references. Continue the original base and captured check policy;
artifact paths, closed tasks, old `work_dir` fields and the current checkout
cannot select source. Legacy or unclassified work stops for explicit migration
with the original records and checkout preserved.

Use the built-in Gas City starter factory post-implementation review loop.

The `build-basic-review` expansion has already created three review lanes:
acceptance/correctness, test evidence, and simplicity/maintainability. Record
that this starter factory review fanout is active, then let the expansion own
review synthesis, required fixes, and the final `code_review.verdict`.

Record the synthesized review report path and pass/fail outcome on the workflow
root bead. Use
`gc bd update "<workflow-root-id>" --set-metadata "gc.build.review_report_path=<absolute path>"`.
Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts a JSON
object.
Before closing this step, set the claimed step outcome with
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, then close
with `gc bd close "<claimed-step-id>" --reason "<concise reason>"`. Do not pass
`--metadata` or `--set-metadata` to `gc bd close`.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.review_report_path` against schema `gc.build.review.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
