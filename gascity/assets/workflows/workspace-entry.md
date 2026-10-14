Use the recorded workspace lifecycle at each build entry and continuation.

Launch the workflow with a real task or convoy in the selected store. The native
graph invocation requires that input; a requirements or plan artifact does not
replace it. A task launch uses the native singleton input convoy and its recorded
source task. A convoy launch uses the convoy itself as its source.

Read the claimed step and workflow root from the native claim output. Keep the
selected city, root store and registered rig explicit:

- `CITY_ROOT`: the selected city's absolute path.
- `ROOT_STORE_REF`: the root's exact `gc.root_store_ref`.
- `RIG_NAME`: the registered rig selected for this workflow.
- `ROOT_ID`: the claimed step's native workflow root.
- `CLAIMED_BEAD_ID`: the currently claimed physical step.

Verify these values against native claim, root and `gc rig list --json`
readbacks. Do not infer them from the current directory, artifacts or
`gc.work_dir`. Use the same explicit city and store for every command.

Run `workspace_entry.py gate` before creating implementation work or handing
off to another suffix. Pass the entrypoint named in the stage instructions.
The helper reads `gc.var.worktree_lifecycle` and the optional
`gc.var.worktree_base_ref` from the root. An omitted base uses the registered
repository's `HEAD`; an explicitly empty or invalid base is rejected.

New lifecycle also requires `gc.var.worktree_checks` on that same native root.
Use canonical JSON with explicit project check IDs and command arguments:

```json
{"required_checks":[{"argv":["python3","-m","unittest"],"id":"unit"}]}
```

Run capture freezes these commands with the exact initial base in
`gc.workspace_required_checks.v1` on the run record. Later acceptance consumes
that policy. Missing, empty, malformed or changed configuration refuses capture
or replay; a result artifact cannot select easier checks.

- **Legacy:** the existing workflow continues with its legacy lifecycle. A run
  already captured in new mode cannot switch to legacy mode.
- **Recorded:** the native run retains its original input, base commit and
  lifecycle. Changing the implementation convoy or default branch does not
  select another base.
- **Awaiting source:** `--allow-pending-source` permits planning when source
  capture is not yet possible. It does not enable a targetless native launch.
  Implementation requires a valid source convoy and recorded run.
- **Refused:** missing records, a different root/store/generation, changed
  lifecycle, or artifact-only input require repair or explicit migration.

Attached continuations consume the original workflow's run. Native drain items
retain their own workflow roots and physical steps. The helper follows the
item's unit convoy and drain control to the original workflow, then verifies its
run, source plan, member and captured checks. It keeps the original base even if
the repository's default branch has advanced.

The first workspace publication records that inherited relationship in the
same guarded operation as its workspace record and references. Native worktree
ownership names the item's actual workflow root; the run and source-plan records
continue to name the original workflow. Do not rewrite either identity to make a
continuation pass.

A standalone suffix without a proven native relationship must not recapture the
base or adopt a run from an artifact. For implementation-convoy handoff, pass
`--require-plan` so that the current convoy's exact source-plan reference and
generation are verified as well.

Record and grant IDs are allocated by the native create command as closed,
unassigned, empty tasks. Lifecycle payloads and references are published
together through the guarded store adapter. If allocation or publication has
an uncertain outcome, inspect and resolve the original operation before
continuing. Never create another record merely because an acknowledgement
was lost.
