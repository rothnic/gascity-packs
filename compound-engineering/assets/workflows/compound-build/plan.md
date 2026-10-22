Use the assigned Compound Engineering planning skill materialized for this agent.

Create a plan artifact from the requirements output. Preserve Compound Engineering traceability identifiers and include the stage handoff details needed by the build-base plan, plan-review, and decompose stages.

The shared `gc.build.plan.v1` artifact contract applies to this Compound plan.
Write Markdown with YAML front matter, not JSON. Its top-level mapping must
include:

- `schema: gc.build.plan.v1`
- `workflow: {id: <workflow-root-id>, formula: compound-build}`
- `methodology: {pack: compound-engineering, name: plan}`
- `producer: {formula: compound-build, stage: plan, attempt: <positive integer>}`
- `status`: one of `draft`, `questions`, `approved`, `changes_required`,
  `blocked`, or `superseded`
- `trace: {upstream: [...], coverage: [...]}`

Use this front-matter shape, replacing the placeholder values with the current
workflow and artifact data:

```yaml
---
schema: gc.build.plan.v1
workflow:
  id: "<workflow-root-id>"
  formula: compound-build
methodology:
  pack: compound-engineering
  name: plan
producer:
  formula: compound-build
  stage: plan
  attempt: 1
status: draft
trace:
  upstream:
    - path: "<requirements-artifact-recorded-path>"
      hash: "sha256:<64-hex-digest>"
      ids: [R1]
  coverage:
    - id: R1
      status: covered
---
```

Each `trace.upstream` entry must be a mapping with `path` and `hash`. Use
current readable file inputs. Include the requirements artifact at its recorded
path and use `sha256:<64-hex-digest>` for current file bytes. The digest in the
example is a placeholder; compute the hash from each current file. Do not put
bead IDs, `beads/<id>` pseudo-paths, or `bead:` hashes in plan upstream entries.
If an upstream entry lists `ids`, every listed ID must appear exactly once in
`trace.coverage` and in the Markdown coverage table with the same status. The
ID/status pairs in the Markdown table must match `trace.coverage`.
Each `trace.coverage` entry must be a mapping with `id` and `status`.
Use coverage statuses allowed by the schema (`covered`, `not_applicable`,
`deferred`, `blocked`, `out_of_scope`, or `superseded`); `approved` is a plan
status, not a coverage status. The table must have `ID` and `Status` columns.
Use this table shape, adding rows for the exact coverage entries:

| ID | Status |
| --- | --- |
| R1 | covered |

Use these required level-two headings verbatim, in this order:

```markdown
## Summary
## Current System
## Proposed Implementation
## Non-Goals
## Verification
```

Do not replace or omit these headings with Compound-specific section names.
Preserve the Compound plan's requirements, KTDs, implementation-unit IDs,
risks, acceptance examples, coverage, and stage handoff within these sections;
use nested headings where they help organize that material.

Read the requirements artifact from workflow root metadata
`gc.build.requirements_path` and write the plan artifact to
`gc.build.plan_path`. After writing the artifact, update the workflow root bead
with:

- `gc.build.plan_path=<plan artifact path>`
- `gc.build.plan_status=approved|draft|failed`
- `gc.build.plan_summary=<one-sentence summary>`

Close this step only after the workflow root metadata and this step metadata
record the same plan outcome.

Do not invoke provider-native subagents or upstream plugin runtime commands. If
upstream methodology would require document-review or research subagents, record
the needed graph lanes as required follow-up.

Artifact validation: this stage is gated by `.gc/scripts/checks/build-artifact-valid.sh`, which validates the artifact recorded at `gc.build.plan_path` (fallback `gc.var.plan_path`) against schema `gc.build.plan.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
