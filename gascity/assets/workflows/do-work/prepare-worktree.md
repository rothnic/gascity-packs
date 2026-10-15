
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

First read `worktree_lifecycle` from the captured run. Before run capture, require
an explicit cooked mode from the native runtime variables (`gc.graphv2_vars.v1`).
Fresh supported entries cook `new`. Existing new runs keep their recorded
mode; older or unclassified state requires explicit migration. Cooked selections must agree with the captured run. Missing, unknown, mixed
or conflicting modes or source classifications block before allocation.

Call the production dependency preparation bridge. A failure or missing input
blocks preparation with the original state preserved:

- Read the exact registered city/rig/store, original workflow root, current
  implementation convoy, source generation, declared workspace owner and source
  member from the native run/source-plan references. Preserve the native wrapper
  relationship. A synthetic convoy is never the source member.
- Retain the actual claimed preparation step and native session incarnation.
  Resolve every physical launch consumer from the cooked graph. Include the
  implementation, test/story continuation, acceptance and result occurrences
  that will use this checkout. Physical IDs must come from native readback.
- Validate context path {{context_path}}, files ownership and the captured
  required-check policy. Call the installed production helper:

  ```sh
  python3 <pack-root>/assets/scripts/workspace_dependency.py \
    --worktree-lifecycle new --city-root '<registered-city>' \
    --rig-name '<registered-rig>' --store-ref '<exact-store-ref>' \
    --workflow-root-id '<original-root-id>' \
    --input-convoy-id '<current-implementation-convoy>' --generation '<source-generation>' \
    --workspace-owner-id '<declared-owner>' --member-id '<source-member>' \
    --claimed-step-id '<current-preparation-step>' \
    --launch-step-id '<actual-consumer-step>' \
    --artifact-root '<existing-artifact-directory-outside-worktrees>' \
    --evidence-dir '<existing-evidence-directory-outside-worktrees>'
  ```

  Repeat `--launch-step-id` for each physical consumer. The bridge reads layout
  from the original logical workflow root:

  - `gc.var.worktree_parent`: empty selects the rig's default parent.
  - `gc.var.worktree_name_prefix`: empty preserves the owner/generation name.
  - `gc.var.worktree_allow_external_parent`: only `true` permits an external parent.

  Preparation validates layout before record allocation and stores its complete
  selection in `workspace.layout`. Resumes and shared members reuse that tuple.
  Optional `--parent`, `--name-prefix` and external-permission flags must agree
  with the original root and recorded layout. Preserve `--work-branch` when
  configured. Do not derive layout from the child's defaults or caller CWD.
  For known allocations, carry `--workspace-record-id` and
  `--authority-id` from the exact prior receipt. Existing native references take
  priority. On first entry, the bridge allocates closed records and atomically
  publishes the preparing payload, owner reference and first writer grant.
- The bridge reads accepted predecessor outputs through `NativeSourceRuntime`,
  resolves the selected input, calls native checkout preparation and performs
  ordered integration when declared. It retains original source/policy revisions
  through the guarded writes. Let the production helpers obtain native evidence.
  Do not manufacture qualification fields, manifests, grants or provisioning
  provenance. Missing acceptance or immutable check policy blocks preparation.
- Require `ok=true`, `state=prepared`, exact input/path/workspace identity and
  committed/replayed receipts. Every launch consumer must retain its exact
  `gc.worktree_ref`. Use the returned absolute path for the implementation
  directory. First entry equals the selected input. Preserve an integration
  receipt separately from the member's later accepted result.
- For an unfinished same-member test/story continuation, use
  `workspace_checkout.py continue` with the retained native claim, current owner
  authority, original run/plan/workspace references and artifact directory.
  Continuation checks the cooked dependency path, sessions, native provisioning,
  current generation, policy, HEAD ancestry and Git operation state.
  It can return an owned path with partial edits. The member still requires its
  result and checkpoint before logical advancement.
- Preserve known partial state and external blocker evidence. `recover` requires
  the exact recorded result or an explicit declaration under admitted native
  authority. Missing, failed or unknown evidence cannot earn a preparation pass.
