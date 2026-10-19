Source work requires the recorded `new` lifecycle. Use the existing
[entry contract](../workspace-entry.md) and verified native run, source plan and
workspace references. Continue the original base and captured check policy;
artifact paths, closed tasks, old `work_dir` fields and the current checkout
cannot select source. Legacy or unclassified work stops for explicit migration
with the original records and checkout preserved.

This is the `build-from-convoy-base` same-session implementation drain.

Implement the work in the implementation convoy recorded as `gc.input_convoy_id`.
Use drain policy `same-session`, route work to {{implementation_target}}, and
process exactly one item at a time in the shared lane so context is preserved
without losing item traceability.

Do not modify requirements, plan, plan-review, or decomposition artifacts from
this step. Keep implementation work isolated from the launcher checkout, run
focused tests as work progresses, and record item evidence so the inherited
review suffix can map changes back to the approved artifacts.

If one item fails, skip remaining shared-lane work and record the failure
reason. Close this step only after the lane is complete, skipped because of a
prior item failure, or blocked with explicit evidence.
