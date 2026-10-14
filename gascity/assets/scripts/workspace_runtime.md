# Native workspace acceptance

`workspace_runtime.py` connects the workspace record writers to native workflow,
session and checkout readback. We use the compiled physical producer, independent
reviewer and recorder occurrences. The adapter runs the captured project checks
and preserves the original work-store rows for the next guarded write.

The run writer captures `gc.var.worktree_checks` once with the initial run:

```json
{"required_checks":[{"argv":["python3","-B","tests.py"],"id":"project-tests"}]}
```

The immutable `gc.workspace_required_checks.v1` sidecar stays on the physical run
record. The adapter rejects missing checks, duplicate IDs, changed commands,
changed run/base bindings and changed native configuration. Check and review
receipts retain the policy hash, physical run ID, run/base and source-plan hashes.

## Callable interface

```python
runtime = NativeSourceRuntime(
    store, gc=gc, city_root=city_root, rig_name=rig_name,
    run=entry["run"], plan=entry["source_plan"],
    artifact_root=artifact_root, evidence_dir=evidence_dir,
    claimed_step_id=claimed_step_id, native_rows=original_rows,
)
```

`store` is the actual `WorkspaceStore` with its captured common Git directory.
`entry` comes from `workspace_entry.read_entry`. The invoking shell retains the
native session and instance environment. `native_rows` is optional.

| Call | Result |
| --- | --- |
| `execute_checks(owner_id, member_id, output_oid)` | Actual command receipts with native producer identity and frozen policy. |
| `begin_review(owner_id, member_id, output_oid, checks, artifacts)` | Context bound to the current independent reviewer. |
| `complete_review(context, report, status, evidence_path)` | Immutable review receipt after source and authority rechecks. |
| `make_member_result(owner_id, member_id, output_oid, checks, review, artifacts)` | Result with actual Git commits and recorder identity. |
| `qualify_native(result)` | Native acceptance evidence, independent binding and original `guard_rows`. |
| `acceptance_context(result, native)` | Frozen `binding`, `required_checks` and actual `work_dir`. |
| `bind_workspace(workspace, native_rows)` | Exact provisioned integration workspace binding. |
| `verify_integration(work_dir, bundle, head_oid)` | Current owner/attempt, accepted predecessor and clean Git verification. |
| `admit_continuation(workspace, original_rows, attempt)` | Current and retained prior writer identity. Checkout owns dependency, dirty-state and grant checks. |
| `recheck_continuation()` | Recheck original work rows, policy, retained sessions and discovered formula bytes. |

`attempt` and `writer_map` expose the admitted native `Attempt` and typed
`CookedWriterMap`. `check_policy`, `required_checks`, `guards` and `guard_rows`
expose the frozen authority and same-store read guards. Result, canonical,
review and publication writers receive `qualify_native=runtime.qualify_native`.

After an exact successful native write, call
`advance_written_rows(resolved["rows"], prepared=prepared)`. The adapter resolves
the original `PreparedWrite` again and checks its original rows and immutable
authority before it acknowledges the written rows. Arbitrary newer snapshots
cannot replace the qualification basis.

## CLI

Every action requires `--city-root`, `--store-ref`, `--rig-name`,
`--workflow-root-id`, `--claimed-step-id`, `--generation`, `--artifact-root`
and `--evidence-dir`. Use `--gc` to select the native executable.

| Action | Additional arguments |
| --- | --- |
| `context`, `checks` | `--owner-id`, `--member-id`, `--output-oid` |
| `begin-review` | Owner/member/output arguments, `--checks` JSON array, `--artifacts` JSON array |
| `complete-review` | `--context` JSON object, `--report`, `--review-evidence`, `--status` |
| `make-result` | Owner/member/output arguments, `--checks`, `--review` JSON object, `--artifacts` |
| `qualify` | `--result` JSON object |
| `record-result` | `--result`, native `--record-id`, native `--authority-id`, optional `--initial-write`, `--operation-nonce` |

CLI output is JSON. `qualify` emits original revision summaries and opaque
attempt IDs. Allocate physical record/grant placeholders through
`workspace_entry.allocate_placeholder`, or use existing exact native references.

## Evidence limits

For an earlier shared checkpoint, `historical_checkpoint` is true and
`current_head_oid` identifies the current checkout. `head_oid` identifies the
accepted retained commit. Consumers validate the historical artifact and commit
proof with `work_dir=None` after native qualification. The terminal member still
requires its exact current HEAD.

Session beads retain the instance authority that the session list omits.
The adapter hashes that authority with the same `Attempt.writer_attempt_id`
derivation used by the writers. A completed role can use its native
`gc.session_attempt_id` claim stamp after the current pool token rotates.
Without that native stamp, the retained session instance must still match.
The opaque stamp requires the matching native core implementation.
Session-store revocation can race a work-store
transaction. Separate readback does not make both stores atomic.

The full guarded row set is bounded to 100 physical rows. Component tests use
a native command port and real Git. Native workflow acceptance remains separate.
