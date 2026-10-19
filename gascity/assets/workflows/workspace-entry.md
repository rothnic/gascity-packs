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

Run the imported pack's helpers through `gc gc workspace entry` (and
`dependency`, `checkout`, `runtime`, or `flow` for the other helpers). The first
`gc` is the CLI and the second is the import binding. Its existing command
dispatcher keeps helpers beside their pack schemas. An explicit invocation
must use the canonical imported `gc` pack's `assets/scripts` path, resolved from
native formula provenance, rather than a rig-local copy. Workspace helpers
load `schemas/workspace/records.v1.json` relative to that pack layout.

For another helper, resolve the canonical scripts directory through that same
native binding. In each new worker session, run the path lookup and helper in
one shell; a variable from an earlier stage is not available:

```sh
PACK_SCRIPTS=$(gc --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace scripts-path) || exit "$?"
python3 "$PACK_SCRIPTS/formula_methodology.py" --help
```

Keep this imported path even when a higher layer overrides a prompt. Do not
guess it from the worker directory, a checkout parent, or an absent `pack_root`.

Formula validators use the native validation control's absolute `gc.check_path`.
Keep that control's actual bead identity when self-running its check, rather
than the claimed child step id. For direct schema validation, use
`assets/scripts/validate_build_artifact.py` in the canonical imported `gc` pack,
beside that pack's schemas. A higher-layer check override does not relocate
this helper. A rig does not need a
`.gc/scripts` copy of the pack helpers or validators.

Run `workspace_entry.py gate` before creating implementation work or handing
off to another suffix. Pass the entrypoint named in the stage instructions.
The helper requires `gc.var.worktree_lifecycle=new` and an explicit
`gc.var.worktree_base_ref` on the native root before first capture. The formula
default `@default` is an explicit selection of the verified registered repository.
Capture records its exact commit immediately without fetching. Missing, empty or
invalid selectors refuse capture; continuation always uses the retained commit.

New lifecycle also requires `gc.var.worktree_checks` on that same native root.
Use canonical JSON with explicit project check IDs and command arguments:

```json
{"required_checks":[{"argv":["python3","-m","unittest"],"id":"unit"}]}
```

Run capture freezes these commands with the exact initial base in
`gc.workspace_required_checks.v1` on the run record. Later acceptance consumes
that policy. Missing, empty, malformed or changed configuration refuses capture
or replay; a result artifact cannot select easier checks.

- **Legacy or unclassified:** refuse source access and preserve the original
  state for [explicit migration](../../docs/worktree-dependencies.md#migrate-existing-work).
  Changing a selector cannot convert an existing run.
- **Recorded:** the native run retains its original input, base commit and
  lifecycle. Changing the implementation convoy or default branch does not
  select another base. Successful exact readback permits requirements, planning
  and decomposition before a source plan exists. Initial capture also requires
  a `committed` or `replayed` receipt. Implementation requires the later source
  plan and workspace admission; recorded preparation does not waive those gates.
- **Awaiting source:** `--allow-pending-source` permits planning when source
  capture is not yet possible. It does not enable a targetless native launch.
  Implementation requires a valid source convoy and recorded run.
- **Refused:** missing records, a different root/store/generation, changed
  lifecycle, or artifact-only input require repair or explicit migration.
  A nonzero exit or unknown capture receipt blocks handoff; reconcile the
  original operation rather than treating missing evidence as success.

Initial `requirements`, `plan` and `decompose` entries may capture generation 1
from their real native input before a run exists. Capture records the registered
repository, exact base and required checks once. Approved artifacts remain
required for the selected stage. A `convoy` or `review` entry requires the
already declared source plan; it cannot bootstrap a run from evidence paths.

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

For a separately launched recorded suffix, sling the recorded implementation
convoy, or the original native source task/convoy. If the original input does
not itself point to its run, supply `--var worktree_run_root=<original-root>`
at launch. The helper also accepts `--recorded-root <original-root>` on `gate`,
`read` and `prepare`. This selector only locates a candidate. The helper verifies
the actual native input, original source anchor, run, current plan, generation,
captured checks and layout before allowing work. It never adopts an artifact's
root or base.

The physical suffix root must be active. A completed original root may be used
only with its exact accepted canonical subject and source plan, with no failed,
held or canceled native state. Review, fix and publication retain that subject
and the existing generation rules. Changed input, policy, layout or hashes
refuse; an outstanding original intent still requires resolution.

A separate suffix keeps its physical root and claimed step. Its first allowed
source-plan, workspace, canonical, review or publication write joins the
inherited run reference atomically with that payload, guarding the original and
physical roots and every actual drain relationship. Read-only entry never
stamps a root. Existing native drain children retain their original binding.

Record and grant IDs are allocated by the native create command as closed,
unassigned, empty tasks. Lifecycle payloads and references are published
together through the guarded store adapter. If allocation or publication has
an uncertain outcome, inspect and resolve the original operation before
continuing. Never create another record merely because an acknowledgement
was lost.
