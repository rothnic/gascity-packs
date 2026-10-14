# Worktree dependencies

Gas City packs use formulas to turn a request into planned tasks, implementation,
review, and optional publication. A workspace is the recorded Git checkout where
a task edits source. In new mode, source dependencies select the commits that
checkout must contain before the task starts.

## Select a mode

`worktree_lifecycle` selects source handling for a run:

- **`new`:** the default for fresh supported work. Requires a recorded base
  commit, explicit task inputs, required project checks, and accepted outputs
  for dependent work.
- **`legacy`:** explicit deprecated compatibility through
  `--var worktree_lifecycle=legacy`. Uses the existing formula's source
  preparation and emits a deprecation warning.

Existing workflows retain their recorded mode. The task-creation CLI inherits
the native workflow's mode when its selector is omitted. An explicit conflicting
selector refuses creation. A workflow without a recorded or explicitly cooked
mode refuses admission and requires deliberate migration. Old `work_dir` or
artifact paths alone cannot establish a mode.

New-mode workflow execution and installation remain unverified. The examples
below describe the source contract under development. Use a matched core/pack
revision validated for the selected workflow before launch.

## Configure the run

Start with the pack and rig imports in the [Quick Start](../README.md#quick-start-your-first-build).
Add defaults under the existing rig entry in `city.toml`:

```toml
[rigs.formula_vars]
worktree_base_ref = "refs/heads/main"
worktree_checks = '{"required_checks":[{"argv":["make","test"],"id":"project-tests"}]}'
drain_policy = "separate"
push = "false"
open_pr = "false"
```

The example assumes the project defines `make test`. Replace that command with
checks that assert the requested behavior. Formula variables are strings.
Explicit `--var` values override [rig defaults](https://github.com/gastownhall/gascity/blob/main/docs/reference/config.md#rig).

- **Base:** `worktree_base_ref` defaults to `@default`, which resolves the
  registered checkout's `HEAD`. Capture performs no fetch. An explicit branch,
  tag, or commit must exist locally and resolve to a commit. Empty or ambiguous
  selectors refuse capture. Use full ref names when a branch and tag share a name.
- **Checks:** `worktree_checks` must be canonical JSON with a nonempty
  `required_checks` array. Each check has a unique, nonempty `id` and a nonempty
  `argv` array. Sort object keys and omit formatting whitespace, as in the
  example. The runner passes `argv` directly to the executable in the task's
  checkout.
- **Recorded inputs:** initial capture saves the base and check policy together.
  Later branch movement cannot change that base. A changed check policy refuses
  replay and requires an explicitly authorized new run.

Launch from the target rig with an existing request task. Replace `<run-target>`
with the build target from the Quick Start and `<request-id>` with the real task ID:

```sh
gc sling <run-target> <request-id> --on build-basic \
  --var artifact_root=plans/export-json/build
```

This launch uses the rig defaults above. Builds require a real task or convoy
as input. Targetless build launch is outside the supported route.
Inspect the selected formula before launch:

```sh
gc formula show build-basic --json
```

## Configure layout

In new mode, all five build packs accept the same workspace layout variables.
Set them under the rig's `[rigs.formula_vars]`, or pass explicit `--var` values
at launch:

| Variable | Default | Behavior |
| --- | --- | --- |
| `worktree_parent` | empty | Uses `<rig>/worktrees`, or `<rig>/workspaces` for a bare rig root. A custom parent must be an absolute, existing directory. |
| `worktree_name_prefix` | empty | Prepends a prefix to `<workspace-owner>-g<generation>`. Empty preserves that name. |
| `worktree_allow_external_parent` | `"false"` | `"true"` explicitly permits a parent outside the rig. |

For example, create `/srv/project-workspaces` before launch, then configure:

```toml
[rigs.formula_vars]
worktree_parent = "/srv/project-workspaces"
worktree_name_prefix = "feature-"
worktree_allow_external_parent = "true"
```

The parent may contain spaces. Prefixes may contain letters, digits, dots,
underscores, and hyphens. A nonempty prefix must begin with a letter or digit.
Symlinks, traversal, Git administration directories, and parents inside another
checkout refuse preparation before record allocation. External opt-in preserves
the same checks.

Preparation records the selected layout for each workspace. Resumes and shared
members retain that layout and stable owner name. Changed parent, prefix, or
permission settings refuse reuse. Native drain children use the original
workflow's settings, even when their own formula defaults differ.

Older records without a layout tuple retain their recorded path and provenance.
They cannot acquire a prefix or external permission from new formula defaults.
Use their original explicit layout arguments when required, after checking the
original authorization.

## Choose the workspace

Choose how tasks share source before the workflow creates implementation tasks:

- **Isolated work:** use `drain_policy="separate"`. Independent tasks start from
  the recorded base in separate workspaces. A dependent task starts from its
  declared predecessor's accepted output.
- **Shared chain:** use `drain_policy="same-session"` with an explicit
  `shared-chain` source strategy. Declare the members in order and set
  `single_lane: true`. Each member must produce an accepted checkpoint before
  the next member advances the same workspace.

Native execution has not yet verified shared checkpoints or continuation with
dirty files or new commits. Preserve a refused checkout until the workflow can
verify the recorded member and its current native ownership.

The pack prepares workspaces through native worktree commands. Detached or
attached HEAD, placement, and lock timeout are native command options rather
than additional workflow variables. Missing native capabilities stop preparation.
For topology and recovery details, see [managed checkout preparation](../assets/scripts/workspace_checkout.md#safety-and-topology).

## Declare task inputs

The task plan distinguishes two relationships:

- **Scheduling dependencies:** `dependencies` determine when a task may start.
- **Source dependencies:** `sources.nodes[].predecessors` select accepted code
  outputs, in the declared order. The creation helper adds the necessary
  scheduling dependencies for those source edges.

Ordinary scheduling dependencies transfer no commits. New mode requires an
explicit source plan with one terminal output. A source owner is the task or
task group whose workspace serves its listed members.

Add `sources` beside `convoys` and `beads` in the `tasks.md` creation payload.
Keep that file separate from the approved decomposition artifact; see the
[decomposition instructions](../assets/workflows/build-basic/decompose.md).
This example assumes the same payload defines tasks named `api`, `ui`, and `site`:

```yaml
sources:
  nodes:
    - owner: api
      strategy: isolated
      members: [api]
      predecessors: []
    - owner: ui
      strategy: isolated
      members: [ui]
      predecessors: []
    - owner: site
      strategy: integration
      members: [site]
      predecessors: [api, ui]
  terminal: site
```

`api` and `ui` receive the recorded base. `site` receives their accepted outputs
merged in that order. The integration task may then make its own changes.
Every owner and member must exist in the same task-creation payload. Unknown
inputs, cycles, and disconnected terminal outputs refuse the plan.

For one predecessor, use `dependent`. For an ordered shared group, use
`shared-chain` with ordered `members` and `single_lane: true`.
See the [source strategies](../schemas/workspace/source-plans.md#choose-a-strategy)
for the complete configuration rules. Customize decomposition through the
[workflow override interface](../README.md#stable-workflow-override-interface).

## Accept and integrate outputs

A predecessor becomes usable only after its result passes the configured checks
and independent review at the exact output commit. A closed task, valid artifact
schema, or Git ancestry check supplies no test credit. Ancestry verifies only
that the checkout contains the fixed input.

- **Accepted result:** required checks pass at a clean, unchanged output commit.
  Independent review covers that same commit and the retained artifacts.
- **No change:** an unchanged output still needs the required checks and review.
- **Integration:** the helper merges accepted predecessors in their declared
  order under exclusive workspace ownership. Run checks and review against the
  integration task's final output, including any task edits.

Pending, rejected, skipped, unrun, or setup-failure results stop dependent
preparation. Changed commits or evidence also stop consumption. See
[accepted inputs](../schemas/workspace/source-inputs.md#resolve-an-accepted-input).

A merge conflict preserves files, the index, and Git merge state. Resolve the
conflict through authorized recovery in the original workspace. Recovery must
verify ownership and the original inputs before the result can be accepted.
Preparation refuses an unfinished Git operation or unexplained HEAD change.

## Review and publish

The terminal accepted output becomes the run's canonical result: the exact
commit used for whole-result review and publication.

- **Review:** approval binds the canonical commit and required scope. Each fix
  generation is a new source plan based on the current canonical commit. The
  replacement commit needs fresh checks and review under the retained policy.
- **Publication:** `push` and `open_pr` default to `false`. Authorized publication
  requires current approval and authority for the exact commit and remote
  target. A new push requires the selected remote ref to match its authorized
  expected commit. Readback can confirm an already completed update. An uncertain
  response requires readback of the original operation before further action.

Approval of one commit cannot approve another commit. A no-op publication or
final report cannot convert blocked implementation or review into a pass.
Report-only review preserves source. Interactive source edits require fresh
checks and approval of the replacement commit.

The GitHub PR review adapter uses explicit deprecated legacy compatibility for
artifact-only methodology reports. Its snapshot does not establish a managed
source run.

## Continue existing work

Keep the original run, base, source plan, and workspace when work continues.
The [entrypoint guide](../README.md#choosing-an-entrypoint) identifies the
artifacts needed for each `build-from-*` continuation. Its artifact-only launch
recipes apply to legacy work. New mode also requires the retained run under its
original workflow or a verified native child.

- **Recorded new work:** continue through the original workflow's verified
  native binding. A separate workflow must prove its relationship to the
  original run. Artifact paths cannot establish that relationship. Inheritance
  between separate workflows remains under native validation.
- **Legacy work:** retain `worktree_lifecycle=legacy`. Captured-run validation
  rejects a changed mode. Supply the explicit legacy selector for a separately
  launched legacy continuation. A source plan or artifact path cannot convert
  the old run to new mode.
- **Refused continuation:** inspect the recorded checkout and original failure.
  Preserve dirty files, commits, and unfinished Git operations. The
  [checkout recovery interface](../assets/scripts/workspace_checkout.md#cli)
  provides `status` and `verify` with existing run and workspace identities.
  Use `recover` only for an explicitly identified partial result or checkpoint.
- **Worker replacement:** retain the original source and required-check policy.
  A current native claim may resume the same physical step. Published records
  transfer writer authority together with the record update; stale attempts and
  active foreign writers are refused. See
  [record allocation and recovery](../assets/scripts/workspace_run.md#native-record-allocation).
- **Blocked first preparation:** retry the original input through the dependency helper's
  [explicit recovery decision](../schemas/workspace/source-inputs.md#retry-first-preparation).
  The current native claim and recorded blocker must agree before provisioning.
- **Lost replies:** resolve the original guarded write before further effects.
  Native record allocation can recover one exact match by its original unique
  description. An unavailable or ambiguous lookup blocks another creation.
  Changing the diagnostic directory or worker attempt does not clear a pending
  write.

Read-only inspection helps identify the retained state:

```sh
git -C <recorded-worktree> status --short --branch
git -C <recorded-worktree> rev-parse HEAD
```

Inspection does not authorize a checkpoint or acceptance. Missing records,
changed ownership, conflicting modes, or an unknown command outcome require
repair of the original operation. Do not reset the checkout, choose a fresh
base, or recreate records to bypass a refusal.

[RFC #209](https://github.com/gastownhall/gascity-packs/issues/209) contains the
design discussion. [Issue #511](https://github.com/gastownhall/gascity-packs/issues/511)
tracks delivery across the pack workflows and their native dependencies.
