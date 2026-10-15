Prepare the Compound Engineering plan-review context.

Resolve the requirements artifact, plan artifact, artifact root, and optional context bundle. Write a compact review context file that includes those paths, the build target, and any known prior review findings.

Include the native workflow root id and current native-recorded artifact paths.
Every persona must read the actual plan and upstream files and record their
SHA-256 hashes in its report. A context copy or a report for older bytes cannot
approve the current plan. Use the imported Gas City
[acceptance contract](../../../../gascity/docs/plan-review-acceptance.md) for the
synthesized subject-bound report; keep persona findings and the apply summary
as separate evidence.

Use these exact artifact paths under the workflow root's artifact root:

- `plan-review/context.md`
- `plan-review/coherence-review.md`
- `plan-review/feasibility-review.md`
- `plan-review/scope-review.md`
- `plan-review/architecture-review.md`
- `plan-review/report.md`
- `plan-review/apply-summary.md`

After writing the context file, update the workflow root bead with:

- `gc.build.plan_review_context_path=<artifact_root>/plan-review/context.md`
- `gc.build.plan_review_report_path=<artifact_root>/plan-review/report.md`
- `gc.build.plan_review_apply_summary_path=<artifact_root>/plan-review/apply-summary.md`
- `gc.build.plan_review_status=ready`

Do not invoke provider-native subagents or upstream plugin runtime commands.
This graph stage is the delegation mechanism.
