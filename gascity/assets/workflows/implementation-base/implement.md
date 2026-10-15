This is the `implementation-base` methodology contract implementation step.

Concrete methodology packs override this step to apply their native
implementation discipline. Work only inside the prepared worktree and preserve
the source anchor for the close step.

Use the [native runtime recipe](../workspace-runtime.md) with the exact recorded
run, source plan, workspace and current owner grant. Recover the same member
through `gc gc workspace checkout continue` before source access. Use only the
returned path. A missing or failed read blocks with the source preserved;
artifact context and raw metadata cannot identify another checkout.

Use `{{summary_path}}` when supplied as the absolute per-item summary path.
Write the summary before project checks, independent acceptance and result
publication. Those stages must qualify that same path and its exact bytes.

Write the per-item implementation summary as a `gc.build.implementation-summary.v1`
artifact and record its absolute path on the workflow root bead as
`gc.implementation.summary_path` before closing.

The summary body must contain these exact schema-required `##` headings in this
order:

- `## Summary`
- `## Intended Behavior`
- `## Changed Files`
- `## Verification`
- `## Remaining Risks`

Artifact validation: this step is gated by the pack-owned `build-artifact-valid.sh` check, which validates the summary recorded at `gc.implementation.summary_path` (fallbacks `gc.build.implementation_summary_path`, then `gc.var.summary_path`) against schema `gc.build.implementation-summary.v1`. Before closing this step, verify the registered rig through native identity readback and run the validator with that explicit `GC_RIG_ROOT`. The validator is the script recorded as `gc.check_path` on the validation loop control bead (the dependent of this step bead whose `gc.kind` is `ralph`); Gas City resolves it to this pack's own `build-artifact-valid.sh` asset, so nothing has to be copied into the rig. Run `GC_BEAD_ID=<claimed-step-id> GC_RIG_ROOT=<launcher-rig-root> "<gc.check_path>"`; fix every reported validation error before setting `gc.outcome=pass`. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the summary in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the summary.
