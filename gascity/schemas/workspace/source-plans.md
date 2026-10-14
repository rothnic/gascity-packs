# Source plans

A source plan declares which accepted task outputs supply each workspace's input.
Use a source plan for a run with `worktree_lifecycle = "new"`.
The [run record](README.md#identity-and-writers) supplies the run's fixed repository and base commit.

## Choose a strategy

| Strategy | Members | Source predecessors | Input |
| --- | --- | --- | --- |
| `isolated` | One | None | The plan's base commit |
| `dependent` | One | One | The predecessor's accepted output |
| `shared-chain` | Ordered members | Zero or one | The base or predecessor output, then the preceding member's accepted output |
| `integration` | One | At least two, in declared order | A merge of all accepted predecessor outputs |

Use `shared-chain` when tasks must advance one workspace in a fixed sequence.
Set `single_lane` to `true` for the shared owner.
The shared owner retains its original native workspace identity as members advance.

Use `integration` when one task needs outputs from independent workspaces.
Create a real native integration task before the source plan declaration.
The [input helper](source-inputs.md) merges predecessors in the declared order.

Scheduling dependencies determine when a task may run.
Source predecessors determine which commits supply the task's input.
Declare each relationship explicitly.

## Declare a native graph

Native task creation must precede source plan publication.
Every owner and member must belong to the same native workflow root and store.
Each native row carries the source root and generation alongside its native workflow metadata.
Native allocation supplies the source fields for each new owner and member.
For an existing plan owner, the guarded declaration can add absent source fields in the same batch.
The existing plan owner must already belong to the exact native root and store.
Conflicting source fields refuse publication.

The plan validator requires:

- **Unique identities:** each owner appears once. Each member belongs to one owner.
- **Valid edges:** predecessors exist in the plan. Duplicate edges and self references fail.
- **Acyclic flow:** source edges contain no cycles.
- **One terminal:** every producer reaches the declared terminal owner.
- **Native membership:** all owners, members and the plan owner already exist in the selected native store.
- **Frozen order:** source predecessors and shared members retain their declared order on replay.

An owner may also be its own member.
An owner cannot be another owner's member.
Predecessor outputs may remain pending when the plan is declared.
Workspace preparation requires accepted outputs when the dependent member starts.

## Validate supplied snapshots

From the repository root:

```sh
python3 gascity/assets/scripts/workspace_source_plan.py validate \
  --plan /path/to/source-plan.json \
  --run /path/to/run.json \
  --native-nodes /path/to/native-nodes.json \
  --store-ref rig:project
```

The native snapshot file maps exact bead IDs to rows with `id` and `metadata`.
The command checks the supplied graph and membership.
The command returns the source order and record digest.
Live publication requires the guarded native writer.

## Publish a plan

The workflow supplies the native IDs for the run record, plan record and writer authority.
Record placeholders must be closed and unassigned.
The current claimed step supplies the admitted native session and instance token.
The publisher reads the current cooked formula and its physical step occurrences.
Only the native decomposition step designated for source plans may publish the record.

```sh
python3 gascity/assets/scripts/workspace_source_plan.py declare \
  --plan /path/to/source-plan.json \
  --store-ref rig:project \
  --run-record-id RUN_RECORD_ID \
  --record-id PLAN_RECORD_ID \
  --claimed-step-id CURRENT_STEP_ID \
  --authority-id AUTHORITY_ID \
  --cwd /path/to/registered/rig
```

The publisher checks the native run reference before the write.
The guarded batch publishes the record and plan reference together.
The batch also checks the retained membership revisions and current canonical reference.
A changed precondition refuses publication.
The command checks exact native intent readback after one submission.
An uncertain readback returns no success and permits no automatic resubmission.

Native expansion may also pass `--implementation-convoy-id` after it creates the implementation convoy.
The same guarded batch binds the convoy to the plan and updates the root's active implementation intake.
The immutable run retains its original input convoy and source anchor.
Replacing that intake also checks the preceding implementation convoy's native root, store and generation.
A changed preceding convoy refuses the whole publication.

## Advance a fix generation

Generation 1 starts from the immutable run base.
A fix generation starts from the current canonical result.
The fix plan records:

- **Generation:** the current canonical generation plus one.
- **Parent:** the current canonical generation and exact output commit.
- **Base:** the same canonical output commit.

A stale canonical parent refuses a new declaration.
An existing plan replays only with the same identity and payload.

## Guarantees

Source plan validation establishes the declared commit flow and native membership.
Accepted result consumption requires completed project checks and independent review for each exact result.
Git ancestry confirms that a checkout contains its required input commit.
Project tests establish the requested behavior at the accepted output commit.
