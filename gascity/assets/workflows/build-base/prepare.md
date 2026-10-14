This is the `build-base` prepare stage. Treat it as a virtual contract that
concrete formulas may override. Users normally launch a concrete implementation
such as `build-basic`; this fallback exists so inherited steps still have a
well-defined contract.

Launch inputs:

- artifact_root: {{artifact_root}}
- context_path: {{context_path}}
- requirements_path: {{requirements_path}}
- plan_path: {{plan_path}}
- decomposition_path: {{decomposition_path}}
- drain_policy: {{drain_policy}}
- worktree_lifecycle: {{worktree_lifecycle}}
- interaction_mode: {{interaction_mode}}
- review_mode: {{review_mode}}
- implementation_target: {{implementation_target}}
- planning_formula: {{planning_formula}}
- decomposition_formula: {{decomposition_formula}}
- implementation_formula: {{implementation_formula}}
- implementation_item_formula: {{implementation_item_formula}}
- code_review_formula: {{code_review_formula}}
- review_fix_formula: {{review_fix_formula}}
- max_iterations: {{max_iterations}}
- push: {{push}}
- open_pr: {{open_pr}}

Validate the target, artifact root, and optional context inputs. Record the normalized artifact paths on the workflow root bead so later stages can reuse them without inventing new locations.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
python3 "{{pack_root}}/assets/scripts/workspace_entry.py" gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" \
  --entrypoint build --worktree-lifecycle "{{worktree_lifecycle}}" --allow-pending-source
```

An `awaiting-source` result permits planning only. Keep implementation blocked
until the original workflow has a valid native source and recorded run.

Validate mode inputs against the methodology vocabulary before any stage runs:
`interaction_mode` must be `interactive`, `autonomous`, or `headless`;
`review_mode` must be `report`, `agent`, or `interactive`; `drain_policy` must
be `separate` or `same-session`. The running formula's
`[metadata.gc.methodology]` declares which of those values it supports. If a
requested value is outside the vocabulary or unsupported by the formula's
declared metadata, stop this workflow as blocked instead of starting work:
record `gc.build.status=blocked` and a machine-readable
`gc.blocked_reason` (for example `unsupported-interaction-mode:headless`) on
the workflow root, then close this step with `gc.outcome=fail` and
`gc.failure_class=methodology_incompatible`. In `headless` interaction mode,
never ask questions; treat missing required input as the same blocked outcome.

To read the running formula's methodology metadata, identify the claimed step
bead from `CLAIMED_BEAD_ID` in the startup claim output, or `$GC_BEAD_ID` if the
claim output did not expose one. For that fallback, assign
`CLAIMED_BEAD_ID="$GC_BEAD_ID"` before the read. Stop as blocked if neither value
is present.
Read `gc bd show "$CLAIMED_BEAD_ID" --json` and take `gc.root_bead_id` from its
metadata as `ROOT_ID`. Read `gc bd show "$ROOT_ID" --json` and take the root's
exact `gc.formula_name` as `RUNNING_FORMULA`. If either metadata value is missing,
malformed or ambiguous, stop as blocked and do not run formula show.
Run `gc formula show "$RUNNING_FORMULA" --json` and inspect
`metadata.gc.methodology` in that output. Never infer the formula name from
`gc.step_ref`; checked attempts can have `gc.step_ref=prepare.iteration.1`.
Do not inspect pack source directories, repository files, `.beads/config.yaml`,
session logs, or runtime state to discover methodology metadata.

Record the selected methodology formulas as adapter inputs, not as behavior in
this virtual contract. Entrypoint adapters may launch those formulas explicitly;
concrete build formulas may instead override stage steps while preserving the
same artifact names and close semantics.

Persist the normalized values on the workflow root bead using `gc.var.<name>` for each launch input and `gc.build.<artifact>_path` for resolved artifact paths. If an optional path input is blank, derive it under the resolved artifact root and record the derived absolute path.

Build artifacts are Markdown files with YAML front matter, not JSON. When a
path input is blank, derive these canonical filenames under the artifact root:

- `requirements.md` for `gc.build.requirements_path`
- `implementation-plan.md` for `gc.build.plan_path`
- `decomposition.md` for `gc.build.decomposition_path`
- `implementation-summary.md` for `gc.build.implementation_summary_path`
- `review-report.md` for `gc.build.review_report_path`
- `factory-run.md` for `gc.build.final_report_path`

Resolved artifact path keys recorded on the workflow root are
`gc.build.requirements_path`, `gc.build.plan_path`,
`gc.build.decomposition_path`, `gc.build.implementation_summary_path`,
`gc.build.review_report_path`, and `gc.build.final_report_path`. Producer-stage
validation gates read these keys, so record every derived path even when the
matching launch input was blank.

When updating metadata, store plain scalar strings without embedded quote
characters. Prefer a single JSON-object update with `gc bd update <root> --metadata
'{"gc.var.push":"false","gc.var.open_pr":"false","gc.var.max_iterations":"10"}'`
or individually quoted `--set-metadata 'key=value'` arguments. Do not write
values like `"false"` or `"10"` that include literal double quotes.

Close commands do not accept metadata flags. Before closing this step, set the
step outcome with `gc bd update <claimed-step-id> --set-metadata 'gc.outcome=pass'`
and then close with `gc bd close <claimed-step-id> --reason '<concise reason>'`.
Do not pass `--set-metadata` or `--metadata` to `gc bd close`, and do not use
`gc.outcome=success`; successful workflow stages use `gc.outcome=pass`.

Do not edit source files. Close this step only after the required paths and input assumptions are explicit.
