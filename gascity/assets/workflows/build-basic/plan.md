Use the built-in Gas City design authoring flow.

Create the implementation plan at the path recorded on the workflow root bead
as `gc.build.plan_path` (fallback `gc.var.plan_path`). The artifact must be
Markdown with YAML front matter, not JSON. Its front matter must declare
`schema: gc.build.plan.v1`, the workflow id/formula, the methodology pack/name,
the producer formula/stage/attempt, `status`, and `trace` with upstream and
coverage entries. Include a Markdown coverage table whose ID/status pairs
exactly match `trace.coverage`.
The validator only recognizes a Markdown table with an `ID` column and a
`Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.plan.v1`
- `workflow: {id: <workflow-root-id>, formula: build-basic}`
- `methodology: {pack: gascity, name: build-basic}`
- `producer: {formula: build-basic, stage: plan, attempt: <positive integer>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- Every upstream entry must name a current readable file with a scheme-qualified hash. Include the
  requirements artifact at its recorded path. Use `sha256:<64-hex-digest>`
  for the exact current file bytes, or `git:<full-immutable-commit-id>` only
  when the current file bytes match that file at the named commit. Short Git
  revisions and moving refs are not accepted.
- Do not put bead IDs, `beads/<id>` pseudo-paths, or `bead:` hashes in plan
  upstream entries. Keep request bead references in the narrative context;
  they do not replace the file inputs reviewed with this plan.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Read the original request, current requirements, repository instructions and
selected native recipes before authoring. Resolve the source repository and
input revision from that request and native source context. Before task
allocation, inspect the relevant source and tests at the captured full OID with
read-only access such as `git -C "<repository>" show "<input-oid>:<path>"`.
Record the files, interfaces and observed behavior used for the plan. If a
required source or procedure cannot be read, record the failed read and blocker.
Keep the plan and any later repair within the original request's authority.

Cover these readiness details within the required sections below:

- **Source and implementation:** Describe the current inputs, outputs and
  interfaces, the files to change, task boundaries and implementation order.
  Identify risky files or interactions and a concrete rollback procedure.
- **Verification:** Name the exact commands, their owning native stages and
  execution directories, expected behavior and required evidence. Preserve any
  requested post-close observation for its designated observer and stage.
- **Independent review:** Name the configured `build-basic-review` expansion's
  acceptance/correctness, test evidence and simplicity/maintainability lanes,
  followed by synthesis, required fixes and the final report/verdict handoff.
  Read the [implementation review recipe](review.md) before describing it.
- **Source completion:** Read the selected `do-work` or `do-work-item` recipes.
  For legacy `do-work`, describe [worktree preparation](../do-work/prepare-worktree.md),
  the focused [implementation commit and summary](../do-work/implement.md), then
  [source-anchor closure and readback](../do-work/close-source-anchor.md).
  For legacy shared work, follow [the item recipe](../do-work-item/implement-item.md)
  that owns its source closure. Bind legacy evidence to the recorded source
  `work_dir` and committed output OID. For `new`, retain the selected managed
  checks, independent acceptance, result/checkpoint and source-close procedure.
- **Final handoff:** Describe the canonical implementation summary and review
  report consumed by [finalization](finalize.md), the final report path and the
  selected [publish policy](publish.md). Include any required legacy stamp and
  deprecation-warning evidence. Mark later allocated identities, output OIDs
  and closure evidence as pending until their owning stages produce them.

Use these required level-two headings verbatim, in this order; a single `#`
heading does not satisfy the artifact check:

```markdown
## Summary
## Current System
## Proposed Implementation
## Non-Goals
## Verification
```

Record the implementation plan path on the workflow root bead before closing.
Use `gc bd update "<workflow-root-id>" --set-metadata "gc.build.plan_path=<absolute path>"`.
Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts a JSON
object.
Before closing this step, set the claimed step outcome with
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, then close
with `gc bd close "<claimed-step-id>" --reason "<concise reason>"`. Do not pass
`--metadata` or `--set-metadata` to `gc bd close`.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.plan_path` (fallback `gc.var.plan_path`) against schema `gc.build.plan.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
