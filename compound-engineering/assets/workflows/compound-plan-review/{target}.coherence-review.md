Review the plan with the installed Compound Engineering coherence reviewer
persona.

Check for internal contradictions, unresolved references, terminology drift, and ambiguity that would make implementers diverge. Return findings in the build review artifact format consumed by synthesis.

Read the current native-recorded plan and upstream files, not only their
context copy. In this lane's report record the native workflow root id,
absolute paths, and SHA-256 hashes of the reviewed plan and every upstream
file. If those bytes change before completion, use `iterate` and retain the
finding instead of approving a different subject.

The canonical review subject is the workflow root plus the current plan and
exact `plan.trace.upstream` paths and hashes. Cite additional valid/current
files as supplementary support; those citations are not part of the canonical
subject and need not match across personas. Missing, stale, or changed
canonical inputs still require `iterate`.

Read the review context from workflow root metadata
`gc.build.plan_review_context_path`. Write this lane's report to
`<artifact_root>/plan-review/coherence-review.md` and close with
`gc.outcome=pass`, `design_review.coherence_verdict=approve|iterate`, and
`design_review.coherence_report_path=<artifact path>`.

Do not invoke provider-native subagents. You are the Gas City lane for this persona.
