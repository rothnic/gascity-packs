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

Resolve and read the original input before deciding that required build input
is missing:

1. Read the claimed step and its exact workflow root as described below. Keep
   the native claim, selected city, root store, and registered rig explicit.
2. Read the root’s `gc.input_convoy_id` in that same native store. Resolve the
   original task or convoy under the existing [workspace entry
   contract](../workspace-entry.md); its native reader remains authoritative
   for source identity and immutable source/store-pin compatibility, including
   supported preserved root and claimed-step pins. For a task launch, read the
   original task recorded by the native singleton input; for a genuine convoy
   launch, read the convoy itself. Retain the validated original identity; do
   not restamp or select another source. A `tracks` edge may corroborate that
   source, but it neither selects the source nor adds a required edge.
3. Read the complete original task or convoy description. Read the supplied
   `context_path` bundle in full and each declared request and behavior input.
   Resolve relative `items[].path` values from the directory containing
   `context_path`, not from the worker's current directory. Validate the bundle
   with the imported `validate_context_bundle.py` helper, then open each exact
   resolved path. A failed lookup from the worker directory does not show that
   a declared input is missing.
   Compare a materialized request with its original native source; do not guess
   input paths from the working directory or an earlier workflow.
4. Blank `requirements_path`, `plan_path`, and `decomposition_path` are valid
   before their producer stages. Derive their output paths under `artifact_root`
   as specified below. Neither those blank outputs nor the attached workflow
   root's generic description proves that the original request is missing.

These are input reads for the already claimed step, not work discovery or
permission to claim, update, or close the source task, input convoy, or another
step. They do not replace the mandatory workspace entry and selected-mode
checks below. If a required input is actually missing, unreadable, foreign,
ambiguous, or inconsistent, retain the failing read or helper diagnostic and
use the blocked outcome below; never manufacture input or infer success.

When `context_path` is set, use the selected city and registered rig verified
from the native claim and workflow root to find the imported pack's validator
before opening bundle items:

```sh
PACK_SCRIPTS=$(gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace scripts-path) || exit "$?"
python3 "$PACK_SCRIPTS/validate_context_bundle.py" "{{context_path}}" || exit "$?"
```

If validation fails, retain its exact diagnostic and use the blocked outcome
above.

Validate the target, artifact root, and optional context inputs. Record the normalized artifact paths on the workflow root bead so later stages can reuse them without inventing new locations.

Apply the [workspace entry contract](../workspace-entry.md) before handoff:

```sh
gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace entry gate \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig "$RIG_NAME" \
  --workflow-root "$ROOT_ID" --claimed-step "$CLAIMED_BEAD_ID" \
  --entrypoint build --worktree-lifecycle "{{worktree_lifecycle}}" --allow-pending-source
```

A successful `recorded` result allows requirements, planning and decomposition.
Initial capture must have a `committed` or `replayed` receipt; an existing run
must pass exact native readback. A source plan is not required at this stage.
An `awaiting-source` result permits planning only. Implementation still requires
the original recorded run, source plan and admitted workspace. A nonzero exit,
unknown receipt or refused read blocks handoff; preserve the original request.

Validate mode inputs with the compact native reader below before any stage runs:
`interaction_mode` must be `interactive`, `autonomous`, or `headless`;
`review_mode` must be `report`, `agent`, or `interactive`; `drain_policy` must
be `separate` or `same-session`. The running formula's
`[metadata.gc.methodology]` declares which of those values it supports. If a
requested value is outside the vocabulary or unsupported by the formula's
declared metadata, stop this workflow as blocked instead of starting work:
record `gc.build.status=blocked` and the reader's machine-readable
`selection.blocked_reason` as `gc.blocked_reason` on
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
Read the compact native declaration before evaluating supported modes:

```sh
PACK_SCRIPTS=$(gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace scripts-path) || exit "$?"
python3 "$PACK_SCRIPTS/formula_methodology.py" --formula "$RUNNING_FORMULA" \
  --city-root "$CITY_ROOT" --rig "$RIG_NAME" \
  --interaction-mode "{{interaction_mode}}" --review-mode "{{review_mode}}" \
  --drain-policy "{{drain_policy}}"
```

Run this selected-mode command; do not substitute a raw `gc formula show` call.
The helper parses the complete native JSON and validates all three requested
values before printing the compact declaration and `selection`. Continue only
when it exits zero with `declared: true` and `selection.supported: true`.
Exit 2 with `selection.supported: false` means the selected modes are invalid or
unsupported; record its exact `selection.blocked_reason` and the failing outcome
above. Do not reinterpret a supported selection as incompatible.
An `UNREADABLE` result or another failed read blocks with
`gc.blocked_reason=unreadable-methodology:<formula-name>` and the failing
outcome above. Never infer unsupported modes from missing or truncated output.
Never infer the formula name from
`gc.step_ref`; checked attempts can have `gc.step_ref=prepare.iteration.1`.
Do not inspect pack source directories, repository files, `.beads/config.yaml`,
session logs, or runtime state to discover methodology metadata.

Record the selected methodology formulas as adapter inputs, not as behavior in
this virtual contract. Entrypoint adapters may launch those formulas explicitly;
concrete build formulas may instead override stage steps while preserving the
same artifact names and close semantics.

Persist the normalized values on the workflow root bead using `gc.var.<name>`
for each launch input and `gc.build.<artifact>_path` for resolved artifact paths.
Derive blank optional paths under the resolved artifact root, except for the
implementation summary: its accepted path is not known during preparation.

Build artifacts are Markdown files with YAML front matter, not JSON. When a
path input is blank, derive these canonical filenames under the artifact root:

- `requirements.md` for `gc.build.requirements_path`
- `implementation-plan.md` for `gc.build.plan_path`
- `decomposition.md` for `gc.build.decomposition_path`
- `review-report.md` for `gc.build.review_report_path`
- `factory-run.md` for `gc.build.final_report_path`

Resolved artifact path keys recorded on the workflow root are
`gc.build.requirements_path`, `gc.build.plan_path`,
`gc.build.decomposition_path`, `gc.build.review_report_path`, and
`gc.build.final_report_path`. Producer-stage validation gates read these keys,
so record every derived path even when the matching launch input was blank.
Leave `gc.build.implementation_summary_path` unresolved until the canonical
stage reads the exact accepted terminal summary. Do not prepopulate a reporting
placeholder as though it were an accepted artifact.

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
