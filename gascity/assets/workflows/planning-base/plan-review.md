This is the independent `plan-review-verdict` child of the native `plan-review` check.
The preceding `author-repair` child owns permitted plan changes; do not edit
the plan, requirements or author summary from this reviewer session. Read
the actual current request/context, plan, upstream files and any author
repair summary, then review those bytes independently. The logical check
still allows only three total attempts and alone gates decomposition.

This is the `planning-base` methodology contract plan-review step.

Concrete methodology packs override this step to approve, revise, or reject the
plan artifact. Close pass only after the plan artifact is approved and ready for
the decomposition contract.

The requested review authority is `{{review_mode}}`: in `report` mode, record
findings and a verdict without mutating the plan; in `agent` mode, also produce
a structured fix handoff for the native author-repair child; in `interactive`
mode, only that author child may apply permitted plan fixes with every change
and reason recorded. The interaction posture is `{{interaction_mode}}`; in `headless`
mode, never ask questions and stop blocked with a machine-readable
`gc.blocked_reason` when approval input is missing.

Follow the [default plan-review acceptance contract](../../../docs/plan-review-acceptance.md).
Write a `gc.verdict-report.v1` review with the current native workflow's exact
plan/upstream `subject`, and record its absolute path as
`gc.build.plan_review_report_path` on the root. The native
`plan-review-approved.py` gate allows three attempts and requires an approved
plan, passing report, and no findings. A blocked report must retain
`gc.outcome=fail`; it must not close pass merely because findings are recorded.
For an authorized repair, read the control's `gc.attempt_log` and review the
changed subject again. Preserve report-only and headless authority limits.

For every blocked review, capture `repair_subject` with `native-repair-subject`
while this reviewer is claimed. A malformed trace may prevent a complete
`subject`; retain the actual diagnostic and use the repair identity only in a
failing report. Follow the contract's repair preflight and new-report handoff.
Only a newly validated complete subject can authorize decomposition.
