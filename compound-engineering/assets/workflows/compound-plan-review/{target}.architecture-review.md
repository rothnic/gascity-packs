Review the plan with the installed Compound Engineering architecture strategist
persona.

Check layering, contracts, migration shape, dependency direction, and fit with existing architecture. Record any required design changes before decomposition.

Read the current native-recorded plan and upstream files, not only their
context copy. In this lane's report record the native workflow root id,
absolute paths, and SHA-256 hashes of the reviewed plan and every upstream
file. If those bytes change before completion, use `iterate` and retain the
finding instead of approving a different subject.

Read the review context from workflow root metadata
`gc.build.plan_review_context_path`. Write this lane's report to
`<artifact_root>/plan-review/architecture-review.md` and close with
`gc.outcome=pass`, `design_review.architecture_verdict=approve|iterate`, and
`design_review.architecture_report_path=<artifact path>`.

Do not invoke provider-native subagents. You are the Gas City lane for this persona.
