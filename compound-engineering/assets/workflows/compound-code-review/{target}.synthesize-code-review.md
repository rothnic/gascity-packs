Retain `worktree_lifecycle` {{worktree_lifecycle}} from the captured run.
`new` requires the composed native workspace helpers and captured check policy.
Keep the methodology below. Source access requires the recorded `new` lifecycle.
Legacy or unclassified work stops for explicit migration; preserve its original
run and checkout. Do not infer source authority from artifacts or old paths.
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

Synthesize the Compound Engineering code-review lanes.

Merge correctness, testing, maintainability, standards, CE always-on agent
outputs, selected conditional reviewer outputs, skipped conditional no-op
artifacts, deployment-verification notes, and gap-analysis findings into one
implementation-review report. Count skipped conditional artifacts as coverage
records, not reviewer failures. Deduplicate overlaps, suppress non-actionable
noise, classify required fixes, and write the approval verdict used by
the imported pack-owned `implementation-review-approved.sh` check. Required fixes must be
specific enough for the single apply step to resolve them directly.

Read the review context from `gc.build.code_review_context_path` and all lane
artifacts from `{{artifact_root}}/code-review/`. Write the synthesized report to
`gc.build.code_review_report_path`, which should be
`{{artifact_root}}/code-review/review-report.md`.

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
  formula: compound-review
methodology:
  pack: compound-engineering
  name: compound-review
producer:
  formula: compound-code-review
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
`code_review.review_verdict=approve|iterate`, and
`code_review.review_report_path=<synthesized report path>`. Do not set
`code_review.verdict` or `code_review.report_path`; the apply-review-findings
lane owns the final loop verdict consumed by the approval check.

Do not invoke provider-native subagents. Synthesis happens in this Gas City lane.
