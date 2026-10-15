
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

First read `worktree_lifecycle` from the captured run. Before run capture, require
an explicit cooked mode from the native runtime variables (`gc.graphv2_vars.v1`).
Fresh supported entries cook `new` by default. Existing runs keep their recorded
mode. Cooked selections must agree with the captured run. Missing, unknown, mixed
or conflicting modes or source classifications block before allocation.
A native drain child's cooked `new` selects the entry read below; that bridge
verifies the inherited recorded mode even when the child has no run reference.

For selected `new`, call the production dependency preparation bridge. Never
fall through to the legacy preparation below after a failure or missing input:

- Retain the actual claimed preparation step, its physical workflow root and
  native session incarnation. Resolve the selected native executable and
  registered city/rig/store from this runtime, not the caller's directory.
  Use the retained source generation and run the read-only entry bridge before
  deciding whether the run or source plan exists:

  ```sh
  python3 "$PACK_ROOT/assets/scripts/workspace_entry.py" read \
    --gc "$GC_BIN" --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" \
    --rig "$RIG_NAME" --workflow-root "$CLAIMED_ROOT_BEAD_ID" \
    --claimed-step "$CLAIMED_BEAD_ID" --worktree-lifecycle new \
    --generation "$SOURCE_GENERATION" --require-plan
  ```

  Resolve `PACK_ROOT` from this installed prompt's pack. Keep the actual command,
  exit status and complete JSON output in the preparation evidence. A successful
  read returns `state=recorded`; it does not prepare a checkout. On refusal,
  retain the helper's actual diagnostic. Reading prompts or inspecting root
  metadata is not an entry-helper execution receipt.
- Use the returned `workflow_root_id`, `generation`, `rig_name` and `store_ref`.
  `input_convoy_id` is the current logical implementation convoy; the immutable
  `run.input_convoy_id` remains the original run input and can differ. A native
  drain child also returns `native_workflow_root_id`, `native_input_convoy_id`
  and `native_continuation`. Keep that physical child and its unit convoy:
  pass `native_input_convoy_id` to dependency preparation when present,
  otherwise pass `input_convoy_id`. The bridge checks the rendered native input
  before resolving the logical implementation convoy internally.
- For a native child, use `native_continuation.member_id` as the source member
  and the sole returned `source_plan.nodes` entry containing that member as its
  workspace owner. For other entries, retain the exact cooked source member and
  require the same unique plan membership. `source_plan.source_plan_owner_id`
  identifies the plan's producer, not the workspace owner. The helper follows
  the native child, drain control, unit convoy and implementation convoy to that
  producer's source-plan reference. Neither the physical child nor the original
  root is required to carry `gc.source_plan_ref`. Do not copy or inject that
  reference, infer a missing plan from its absence on a root, or use a synthetic
  convoy as the source member.
- Validate context path {{context_path}}, files ownership and the captured
  required-check policy. Call the installed production helper:

  ```sh
  python3 "$PACK_ROOT/assets/scripts/workspace_dependency.py" \
    --gc "$GC_BIN" --worktree-lifecycle new --city-root '<registered-city>' \
    --rig-name '<registered-rig>' --store-ref '<exact-store-ref>' \
    --workflow-root-id '<original-root-id>' \
    --input-convoy-id '<native-input-convoy-from-entry>' --generation '<source-generation>' \
    --workspace-owner-id '<declared-owner>' --member-id '<source-member>' \
    --claimed-step-id '<current-preparation-step>' \
    --artifact-root '<existing-artifact-directory-outside-worktrees>' \
    --evidence-dir '<existing-evidence-directory-outside-worktrees>'
  ```

  Run this command and retain its actual result before reporting preparation
  success or failure. The bridge resolves all physical launch consumers from
  the cooked writer map when `--launch-step-id` is omitted. If explicitly
  supplying those IDs, include every implementation, test/story continuation,
  acceptance and result occurrence that uses the checkout; derive each from
  native readback, never a logical step name. The bridge reads layout from the
  original logical workflow root:

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

For explicit or recorded `legacy` selection, preserve this existing preparation:

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that do-work root with `gc bd show <root-bead-id> --json`. If
   `gc bd show --json` returns a one-element list, unwrap the first element before
   reading metadata.
2. Resolve `<source-anchor-id>` from the do-work root:
   - read root metadata `gc.input_convoy_id`; hard-fail if it is missing
   - verify `gc.input_convoy_id` matches rendered runtime convoy `{{convoy_id}}`
   - read that input convoy with `gc bd show <input-convoy-id> --json`; unwrap a
     one-element list response before reading metadata
   - if input convoy metadata has `gc.synthetic_kind=drain-unit-convoy`, use
     input convoy metadata `gc.drain_member_id`
   - do not use the synthetic drain-unit convoy id as `<source-anchor-id>`;
     hard-fail if the selected source anchor id equals the synthetic input convoy id
   - else if it has `gc.synthetic=true` (the wrapper `gc sling <item>` makes),
     use its one tracked member from `gc convoy status <input-convoy-id> --json`
     `.children` (hard-fail unless exactly one). Never use the synthetic wrapper
     convoy id as `<source-anchor-id>`; that leaves the real item open
   - otherwise use `<input-convoy-id>` as the source anchor
   - if root metadata also has `gc.drain_member_id`, it must match the selected
     drain member
   - stamp it for later steps:
     `gc bd update <root-bead-id> --set-metadata gc.source_anchor_id=<source-anchor-id>`.
     If the root already has `gc.source_anchor_id` (a retry), it must equal the
     id resolved above; hard-fail on a mismatch instead of overwriting it
3. Validate context path {{context_path}}, files ownership, and verification
   policy for the resolved source anchor.
4. Create or reuse a deterministic git worktree at
   `$(pwd)/worktrees/<source-anchor-id>`, based on the up-to-date remote
   default branch — never the launcher's local `HEAD`, which may be behind
   `origin`. If the path is missing:
   - Resolve the remote default branch (do not hardcode `main`). Read the
     local ref first, and only touch the network if it is missing:

     ```sh
     DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
     if [ -z "$DEFAULT_BRANCH" ]; then
       git remote set-head origin --auto >/dev/null 2>&1 || true
       DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
     fi
     ```

     `refs/remotes/origin/HEAD` is written by `git clone` and refreshed by
     `git remote set-head origin --auto`. It is NOT written by `git init` plus
     `git fetch`, which is how `actions/checkout` and several of our own
     checkouts are built, so the refresh branch is load-bearing rather than
     defensive. The fetch on the next line still guarantees the base is
     current, so a stale ref costs nothing.

     If it is still empty, fail closed — do not fall back to local `HEAD`.
   - Fetch it so the base is current:
     `git fetch --prune origin "$DEFAULT_BRANCH"`.
   - Create the worktree detached at the freshly fetched tip:
     `git worktree add "$WORKTREE" --detach "origin/$DEFAULT_BRANCH"`.
   If the path exists but is not the worktree for this repository, fail closed.
5. Persist the absolute path on the source anchor with
   `gc bd update <source-anchor-id> --set-metadata work_dir=<absolute worktree path>`.
   For synthetic drain-unit convoys, never persist `work_dir` on the synthetic drain-unit convoy; the original drain member/source anchor is authoritative.
   Verify the source anchor now has `work_dir` and the root now has
   `gc.source_anchor_id=<source-anchor-id>` before closing this step with
   `gc.outcome=pass`.
