# Workspace source inputs

Workspace preparation resolves inputs from the declared [source plan](source-plans.md).
Each dependent task receives the exact accepted predecessor output.
An integration task receives the commit produced by the ordered predecessor merges.

## Prepare a task

For `worktree_lifecycle = "new"`, the preparation step calls `workspace_dependency.py`.
The helper reads the recorded run, source plan, required project checks and actual native workflow roles.
Use the IDs returned by native expansion; do not derive task or record IDs from names.

```sh
python3 <pack-root>/assets/scripts/workspace_dependency.py \
  --worktree-lifecycle new --gc gc \
  --city-root /path/to/city --rig-name project --store-ref rig:project \
  --workflow-root-id ROOT_ID --input-convoy-id IMPLEMENTATION_CONVOY_ID \
  --generation 1 --workspace-owner-id OWNER_ID --member-id MEMBER_ID \
  --claimed-step-id PREPARATION_STEP_ID \
  --artifact-root /path/to/artifacts --evidence-dir /path/to/diagnostics
```

Both artifact directories must already exist outside the repository and its worktrees.
The invoking step must retain its current native session and claim.

Optional settings control placement and native record reuse:

| Option | Behavior |
| --- | --- |
| `--launch-step-id` | Bind each actual cooked consumer to the checkout. Repeat for multiple consumers; omission selects the declared consumers. |
| `--parent` | Use a canonical absolute workspace parent. |
| `--allow-external-parent` | Permit an explicitly configured parent outside the normal rig layout. |
| `--work-branch` | Create an attached worktree on this branch. Omission uses a detached worktree. |
| `--workspace-record-id`, `--authority-id` | Reuse exact known native allocations after validating their state. First entry can allocate these automatically. |
| `--resume-decision` | Resume the recorded integration blocker using an explicit decision file. |

First preparation qualifies accepted sources before allocating native records or creating the worktree.
The guarded write publishes the initial workspace and owner authority together.
Each launch consumer receives a native reference to that exact workspace.

For an active, unfinished member, another call observes continuation without rewriting records or transferring authority.
Owned partial edits and linear descendant commits remain in place.
The original input stays fixed; `accepted=false` and `checkpoint_required=true` identify unfinished work.
Completing the member still requires project checks, independent review and its recorded result.

## Resolve an accepted input

The workflow supplies three forms of context:

- **Records:** the exact owner-output and final member-result references.
- **Native evidence:** the selected store, workflow root, workspace owner and retained native attempts.
- **Acceptance policy:** the fixed required checks and the producer's exact checkout.

The source helper checks the output against the final member result.
The accepted result must retain:

- **Commit:** the exact output OID at a clean checkout, or an earlier accepted shared checkpoint retained in the current native history.
- **Checks:** every required project check completed successfully at that commit.
- **Review:** an independent producer/reviewer session pair and a passed report for the same commit and required scope.
- **Artifacts:** the complete retained files with their original byte hashes.
- **Authority:** the native producer, reviewer and record writer identities match the accepted evidence.

Pending, rejected, skipped, unrun and setup-failure results refuse dependent preparation.
A changed artifact or source commit also refuses preparation.
The workflow fences the consumed record references before workspace effects.

For a shared chain, the first member receives the base or predecessor output.
Each later member receives the preceding member's accepted output.
The stable workspace owner retains its original provisioning identity throughout the chain.
An earlier accepted checkpoint keeps its own checks, review, artifacts and input-to-output commit history.
The native runtime separately verifies the current shared checkout and its ancestry.

## Integrate independent outputs

The workflow first provisions the integration owner's native workspace at the plan base.
The workflow holds the exclusive workspace lock throughout the merges.

The integration helper:

1. Verifies each accepted predecessor commit exists in the repository and descends from the plan base.
2. Checks the native owner, retained attempt and exact HEAD before each merge.
3. Merges predecessors in their declared order.
4. Checks the final native ownership and clean checkout.
5. Returns the merged input commit and ordered predecessor record hashes.

The integration member starts from the merged input commit.
Any member changes produce a separate output commit.
Project checks and independent review qualify the final member output.

The merge receipt binds the plan base, merged input and ordered predecessor hashes.
Dependent preparation checks the receipt against the retained predecessor output records.

## Recover a failed integration

A merge conflict retains the files, index and Git merge state.
The workflow records an integration blocker alongside the unchanged workspace checkpoint.
Ordinary preparation refuses this blocked workspace.

Under the same admitted native ownership:

1. Inspect the retained blocker and accepted source order.
2. Resolve the conflict and complete the Git merge. Leave the checkout clean.
3. Save an explicit decision outside the repository, under the configured artifact root:

   ```json
   {
     "workflow_root_id": "ROOT_ID",
     "generation": 1,
     "source_plan_owner_id": "PLAN_OWNER_ID",
     "workspace_owner_id": "OWNER_ID",
     "store_ref": "rig:project",
     "blocker_id": "RECORDED_BLOCKER_ID",
     "expected_head_oid": "FULL_RESOLVED_COMMIT_OID"
   }
   ```

4. Repeat the preparation command with `--resume-decision /path/to/artifacts/decision.json`.

Recovery verifies the exact decision, original native owner and ordered merge parents.
Unrelated commits, changed accepted sources, unfinished Git operations or a different blocker refuse recovery.
The guarded write resolves the blocker and restores its paused checkpoint before publishing the merged input.
The decision file and merge receipt retain their original byte hashes.
Recovery neither resets the worktree nor accepts the integration member's result.

Preparation refuses a dirty checkout, changed HEAD or unfinished prior Git operation.
An ownership change between merges retains any completed merge.
The failed operation returns no accepted input.

## Helper interfaces

Pack authors can call the helpers from the workflow's admitted preparation step:

```python
bundle = resolve_member_input(
    plan, owner_id, member_id,
    load_owner_output=load_owner_output,
    load_member_result=load_member_result,
    qualify_native=qualify_native,
    acceptance_context=acceptance_context,
    store_ref=store_ref,
    artifact_root=artifact_root,
)
```

`acceptance_context(result, native_evidence)` returns the binding, required checks and exact producer checkout.
Derive the context from the immutable run, fixed project policy and native workspace record.
The helper reuses the accepted-result consumer validator with the independently resolved native binding.

For an integration member, call `materialize_integration(work_dir, bundle, verify_native=verify_native)` under the retained workspace lock.
The verifier checks current native ownership before each mutation and after the final merge.
The helper preserves conflicts for explicit recovery.
`inspect_integrated_history` checks completed ordered merge parents without changing Git state.
Native admission and a recorded recovery decision remain separate requirements.
