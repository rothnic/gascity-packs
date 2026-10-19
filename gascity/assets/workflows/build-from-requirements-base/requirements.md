Planning requires the recorded `new` lifecycle. Follow the existing
[entry contract](../workspace-entry.md) and verify the native run, captured base
commit and check policy. Inspect that exact commit read-only while authoring or
reviewing artifacts. Source-plan and workspace admission is required before
implementation or source edits. Artifact paths, closed tasks, old `work_dir`
fields and the current checkout cannot select source. Legacy or unclassified
work stops for explicit migration with the original records and checkout preserved.

This is the `build-from-requirements-base` requirements stage.

Produce or reuse the requirements artifact at `{{requirements_path}}` when
provided; otherwise write the default requirements artifact under
`{{artifact_root}}`.

The requirements artifact must use the base requirements contract, stable IDs,
example mapping, acceptance criteria, open questions, out-of-scope notes, and
approval state. Close only after the requirements path and content hash are
recorded for the inherited plan suffix.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.requirements_path` (fallback `gc.var.requirements_path`) against schema `gc.build.requirements.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
