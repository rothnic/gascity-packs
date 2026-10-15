This is the `planning-base` methodology contract plan-review step.

Concrete methodology packs override this step to approve, revise, or reject the
plan artifact. Close pass only after the plan artifact is approved and ready for
the decomposition contract.

The requested review authority is `{{review_mode}}`: in `report` mode, record
findings and a verdict without mutating the plan; in `agent` mode, also produce
a structured fix handoff for the planning author to apply; in `interactive`
mode, safe plan fixes may be applied directly with every change and reason
recorded. The interaction posture is `{{interaction_mode}}`; in `headless`
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
