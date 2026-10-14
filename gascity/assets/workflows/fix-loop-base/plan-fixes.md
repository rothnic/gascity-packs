This is the `fix-loop-base` methodology contract fix-planning step.

Concrete methodology packs override this step to convert `{{findings_path}}`
into their native fix plan with optional context from `{{context_path}}`. The
adapter remains responsible for external publication and lifecycle state.

For managed source, resolve current canonical and exact findings. Use
`workspace_review.fix_plan` to declare the next plan at the reviewed OID with an
explicit parent generation/OID and existing iteration limit. Publish through the
guarded source-plan writer. `validate_fix_parent` must match before fix work.
Preserve exhaustion as a blocker; do not reset attempts or overwrite a newer
generation. New activation still requires composed native acceptance.

For new mode, create the fix task/convoy graph through the existing native
creation workflow first. Keep its exact native owner/member IDs in `FIX_NODES`.
Then declare the parent-bound generation with the actual shared command:

```bash
gc gc workspace flow fix-plan "${WORKSPACE_ARGS[@]}" \
  --nodes "$FIX_NODES" --plan-owner-id "$FIX_PLAN_OWNER_ID" \
  --terminal-owner-id "$FIX_TERMINAL_OWNER_ID" \
  --implementation-convoy-id "$FIX_CONVOY_ID" --max-iterations "{{max_iterations}}"
```

The native source-plan writer validates every physical node and convoy membership
and publishes their source binding with the next generation. Only committed or
replayed readback permits the fix implementation handoff. Use fresh runtime
context for the newly selected generation. Preserve the original run/base/policy.
