Source work requires the recorded `new` lifecycle. Use the existing
[entry contract](../workspace-entry.md) and verified native run, source plan and
workspace references. Continue the original base and captured check policy;
artifact paths, closed tasks, old `work_dir` fields and the current checkout
cannot select source. Legacy or unclassified work stops for explicit migration
with the original records and checkout preserved.

This is the `build-from-plan-base` plan-review stage.

Review the implementation plan before decomposition. The verdict must map to
approved, questions, changes_required, or blocked, and it must honor
interaction_mode {{interaction_mode}}.

Write the plan-review artifact to `{{plan_review_path}}` when supplied;
otherwise write it under `{{artifact_root}}`. Close only after an approved or
equivalent pass verdict is recorded, or after a blocked/changes-required verdict
is recorded with a concrete reason.
