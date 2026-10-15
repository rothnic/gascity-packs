Prepare the gstack plan-review context.

Collect requirements, plan, acceptance criteria, test commands, release risks,
and unresolved decisions into one review context under the artifact root.
Record the context path on the workflow root so every Gas City fanout lane
reviews the same material.

Use `<artifact_root>/plan-review/context.md`, `report.md`, and
`apply-summary.md` for the shared handoff. Record their absolute paths as
`gc.build.plan_review_context_path`, `gc.build.plan_review_report_path`, and
`gc.build.plan_review_apply_summary_path` on the native workflow root.
Include its id and the current native-recorded plan and requirements paths in
the context. Each reviewer must read those actual files and record their
SHA-256 hashes; a context copy is not authority for changed artifacts.

Current interaction_mode is {{interaction_mode}}. The adapted upstream skills
are plan-ceo-review, plan-design-review, plan-eng-review, and plan-devex-review.

Close with `gc.outcome=pass`.

Do not invoke provider-native subagents. Gas City graph lanes are the
delegation mechanism.
