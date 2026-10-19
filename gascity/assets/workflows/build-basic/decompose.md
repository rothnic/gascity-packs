Use the built-in Gas City `create-beads` decomposition flow.

Create task beads or a decomposition artifact from the approved requirements
and implementation plan. Preserve traceability from each work item back to the
relevant acceptance criteria and plan section, and record the implementation convoy
that the `implement` formula will drain.

Create the decomposition artifact at the path recorded on the workflow root
bead as `gc.build.decomposition_path` (fallback
`gc.var.decomposition_path`). The artifact must be Markdown with YAML front
matter, not JSON. Its front matter must declare
`schema: gc.build.decomposition.v1`, the workflow id/formula, the methodology
pack/name, the producer formula/stage/attempt, `status`, and `trace` with
upstream and coverage entries. Include a Markdown coverage table whose
ID/status pairs exactly match `trace.coverage`.
The validator only recognizes a Markdown table with an `ID` column and a
`Status` column. Use this shape:

| ID | Status |
| --- | --- |
| REQ-001 | covered |

Use mapping objects for front matter; do not use scalar shortcuts such as
`workflow: build-basic`. The top-level YAML shape must be:

- `schema: gc.build.decomposition.v1`
- `workflow: {id: <workflow-root-id>, formula: build-basic}`
- `methodology: {pack: gascity, name: build-basic}`
- `producer: {formula: build-basic, stage: decompose, attempt: <positive integer>}`
- `status: approved` or another schema-allowed status
- `trace: {upstream: [...], coverage: [...]}`

Trace front matter must use the validator shape exactly:

- `trace.upstream[]` entries must include `path` and `hash`; do not use
  `id`/`title`/`type` entries as the upstream shape.
- For the requirements and plan artifacts, use their recorded paths and
  scheme-qualified hashes such as `sha256:<digest>` or `git:<revision>`.
- If an upstream entry lists `ids`, every listed id must appear exactly once in
  `trace.coverage` and in the Markdown coverage table with the same status.
- Coverage statuses are not artifact statuses. Use `covered` for satisfied
  requirements; do not use `approved` in `trace.coverage[].status` or the
  Markdown coverage table.

Include the required schema sections:

- Summary
- Selected Downstream Formulas
- Implementation Convoy
- Work Items

The native helper creates work-item beads first, then a new implementation
convoy for those work units. Do not reuse the source or launch convoy from
`gc.var.convoy_id`.

Use the [workspace entry contract](../workspace-entry.md)
and the pack's native expansion helper. Declare code sources separately from
ordinary scheduling dependencies in the `tasks.md` creation payload:

Read the entry helper's recorded `run.source_anchor_id` with the same native
city/store routing, and read that original request alongside the approved plan.
The request and approved plan define each source strategy and the ordered
predecessors. An example is syntax guidance; it does not replace that graph.
If the original request and approved plan conflict, record the blocker before
allocation. Resolve linked files relative to this actual description file or
the rendered `pack_root`, rather than the worker's current directory. An
initial path error requires checking the rendered path; do not declare a helper
unavailable without looking up and executing its actual command.

Set `TASKS_PATH` to that creation file's absolute path. Keep it separate from
the approved decomposition artifact: native creation records its recovery
status and returned IDs in `tasks.md`.

Use the complete creation envelope below under the exact Markdown heading
`## Bead Creation Payload`. Replace `my-project` with the registered rig.
Derive the owners, members, strategies and ordered predecessors from the
approved request and implementation plan. The YAML illustrates syntax. Before
creation, compare its source graph with the approved plan. After creation,
verify the same graph in the native readback.
Replace the example names and edges with the approved task graph.

```yaml
target_rig: my-project
convoys:
  - key: implementation
    title: Implementation
    description: Implement the approved plan.
    beads:
      - key: a
        title: First independent change
        type: task
        description: Implement the first approved change.
        acceptance_criteria: [Required checks and independent review pass.]
      - key: b
        title: Second independent change
        type: task
        description: Implement the second approved change.
        acceptance_criteria: [Required checks and independent review pass.]
      - key: m
        title: Integrate both changes
        type: task
        description: Integrate the accepted outputs in their declared order.
        acceptance_criteria: [Both changes work together and required checks pass.]
sources:
  nodes:
    - owner: a
      strategy: isolated
      members: [a]
      predecessors: []
    - owner: b
      strategy: isolated
      members: [b]
      predecessors: []
    - owner: m
      strategy: integration
      members: [m]
      predecessors: [a, b]
  terminal: m
```

Each owner/member key must name a work item or convoy in that same payload.
Use one terminal output. Ordered predecessors describe which accepted code
feeds a task; scheduling dependencies alone transfer no source code.
An explicit `integration` owner consumes its listed predecessors directly.
Declaring `dependent` with multiple predecessors instead creates an additional
`<owner>-inputs` integration work item before that dependent owner. These are
different graphs; preserve the requested strategy and order. A shared-chain
owner uses ordered members and `single_lane: true`. Before invoking the helper,
compare every declared owner, strategy, member and ordered predecessor with the
approved graph. Afterward verify the exact returned source plan; do not repair
a mismatch by manually editing native records.

```sh
python3 "{{pack_root}}/assets/scripts/create_beads_from_tasks.py" "$TASKS_PATH" \
  --city "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --workflow-root "$ROOT_ID" \
  --claimed-step "$CLAIMED_BEAD_ID" --worktree-lifecycle new --generation 1 \
  --evidence-dir '<existing-evidence-directory-outside-worktrees>'
```

The helper creates native members and their implementation convoy, then
publishes the source plan and both root convoy bindings, `gc.input_convoy_id`
and `gc.build.implementation_convoy_id`, in one guarded batch.
Planning A/B inputs does not require their outputs to exist yet. The
integration workspace refuses missing or unaccepted outputs at consumption.
Verify the exact plan/reference readback before closing decomposition or
starting any drain. If the command reports an uncertain operation, resolve
that operation; do not rerun creation blindly. For a fix generation, pass its
actual generation and exact current canonical parent instead of `1`.

Do not create or extend a convoy manually after this command. Do not recreate
members or repeat creation to recover an uncertain response. Reconcile the
original operation and require the same source plan and both convoy references.

Record the decomposition output on the workflow root bead with
`gc bd update "<workflow-root-id>" --set-metadata "gc.build.decomposition_path=<absolute path>"`.
Do not use `gc bd update --metadata 'key=value'`; `--metadata` only accepts a JSON
object.

Before closing this step, set the claimed step outcome with
`gc bd update "<claimed-step-id>" --set-metadata "gc.outcome=pass"`, then close
with `gc bd close "<claimed-step-id>" --reason "<concise reason>"`. Do not pass
`--metadata` or `--set-metadata` to `gc bd close`.

Artifact validation: this stage is gated by the pack-owned `build-artifact-valid.sh` check, which validates the artifact recorded at `gc.build.decomposition_path` (fallback `gc.var.decomposition_path`) against schema `gc.build.decomposition.v1`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
