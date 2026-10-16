This is the independent `plan-review-verdict` child of the native `plan-review` check.
The preceding `author-repair` child owns permitted plan changes; do not edit
the plan, requirements or author summary from this reviewer session. Read
the actual current request/context, plan, upstream files and any author
repair summary, then review those bytes independently. The logical check
still allows only three total attempts and alone gates decomposition.

This is the `build-from-plan-base` plan-review stage.

Review the implementation plan before decomposition. The verdict must map to
approved, questions, changes_required, or blocked, and it must honor
interaction_mode {{interaction_mode}}.

Write the plan-review artifact to `{{plan_review_path}}` when supplied;
otherwise write it under `{{artifact_root}}`. Record its absolute path on the
current workflow root as `gc.build.plan_review_report_path`.

Follow the [default plan-review acceptance contract](../../../docs/plan-review-acceptance.md).
The `gc.verdict-report.v1` report must bind its `subject` to this native
workflow's current approved plan and current upstream bytes. Only a validated
`verdict: pass`, `severity: none`, and empty findings permits
`gc.outcome=pass`. A blocked/changes_required verdict is `gc.outcome=fail`,
even after its concrete reason is recorded. Do not allocate tasks in that state.

For every blocked review, capture `repair_subject` with `native-repair-subject`
while this reviewer is claimed. If a malformed trace prevents a complete
`subject`, record that diagnostic and the repair identity in a failing report
as the contract directs. The next author may repair only after the native
repair preflight; approval still requires a new complete subject and review.

The native `plan-review-approved.py` check allows three attempts. Use
`gc.attempt_log` from its control for an official repair, preserve the original
findings, and review every authorized plan change again. Set the exact outcome
with `gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=<pass-or-fail>"`
before `gc bd close "<claimed-step-id>" --reason "<concise reason>"`.
