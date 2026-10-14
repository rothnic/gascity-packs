Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Its legacy source/path/state operations apply
only to explicit `legacy`; the managed instructions govern an admitted `new`
run. Unknown modes or failed reads never authorize legacy fallback.
Resolve helper modules through the imported Gas City `assets/scripts` layer;
keep that resolved directory on Python's import path for sibling modules.

For an admitted `new` review, use the exact canonical binding and
canonical/result hashes from this expansion's setup context. Validate the
subject with `workspace_review.canonical_subject` before inspecting source.
Use `workspace_outputs.snapshot` before and after the lane to confirm the
recorded workspace, clean index and full output OID. Review and synthesis are
read-only source work. Record this lane's finding/report hash against that
subject; never choose a default ref, launcher or newer commit. Conditional
skips retain the same subject and the required skip artifact. A missing,
stale or changed context blocks instead of producing approval.

Synthesize the gstack code review.

Read the staff, QA evidence, security, and gap-analysis reports. Deduplicate
findings and produce one ordered list of required fixes, missing evidence, and
residual risks. Preserve the source lane for each finding.

Write the synthesized report to `gc.build.code_review_report_path`, which
should be `{{artifact_root}}/code-review/review-report.md`.

The synthesized report must be valid for `gc.build.review.v1`: start with YAML
front matter containing `schema: gc.build.review.v1`, `workflow`,
`methodology`, `producer`, `status`, and `trace`; include a Markdown coverage
table; and include `## Verdict`, `## Findings`, and `## Verification`
sections. Use `status: changes_required` when required fixes remain, and use
schema-allowed coverage statuses only (`covered`, `blocked`, `deferred`,
`not_applicable`, `out_of_scope`, `superseded`). Do not use `violated`,
`resolved`, `approved`, or `changes_required` as coverage row statuses. Include
`rationale: <why this id is not covered>` on every non-`covered` coverage row.

Use this front matter shape exactly. Do not use dotted YAML keys such as
`workflow.id`, and do not make `trace` a list:

```yaml
---
schema: gc.build.review.v1
workflow:
  id: <workflow-root-id>
  formula: gstack-review
methodology:
  pack: gstack
  name: gstack-review
producer:
  formula: gstack-code-review
  stage: synthesize-code-review
  attempt: 1
status: changes_required
trace:
  upstream:
    - path: <relative input artifact path>
      hash: sha256:<input artifact digest>
      ids: [<finding-or-lane-id>]
  coverage:
    - id: <finding-or-lane-id>
      status: covered
---
```

The Markdown coverage table must have `ID` and `Status` columns, and its rows
must exactly match `trace.coverage`.

Close with `gc.outcome=pass`,
`code_review.review_verdict=approve|iterate`,
`code_review.review_report_path=<synthesized report path>`, and
`code_review.output_path=<synthesized report path>`.

Do not invoke provider-native subagents. Synthesis happens in this Gas City
fan-in lane.
