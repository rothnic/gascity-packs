
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

First read `worktree_lifecycle` from the captured run. Before run capture, require
an explicit cooked mode from the native runtime variables (`gc.graphv2_vars.v1`).
Fresh supported entries cook `new`. Existing new runs keep their recorded
mode; older or unclassified state requires explicit migration. Cooked selections must agree with the captured run. Missing, unknown, mixed
or conflicting modes or source classifications block before allocation.
A native drain child's cooked `new` selects the entry read below; that bridge
verifies the inherited recorded mode even when the child has no run reference.

Call the production dependency preparation bridge. A failure or missing input
blocks preparation with the original state preserved:

- Retain the actual claimed preparation step, its physical workflow root and
  native session incarnation. Resolve the selected native executable and
  registered city/rig/store from this runtime, not the caller's directory.
  Derive `SOURCE_GENERATION` from the exact native source row before running
  the read-only entry bridge. Read `CLAIMED_ROOT_BEAD_ID` with the selected
  `$GC_BIN`, city and rig. If that row has `gc.drain_member_id`, read that exact
  member row; otherwise read the row named by its current `gc.input_convoy_id`.
  Require each returned row's `id` to match the requested ID, its
  `gc.root_store_ref` to match `ROOT_STORE_REF`, and its `gc.source_root_id` to
  identify the expected source root. Take `gc.source_generation` from that
  exact member or convoy row, require a canonical positive integer, and export
  it as `SOURCE_GENERATION`. Do not expect it in the process environment or
  infer it from a plan filename. The entry bridge below independently checks
  the complete native root, drain, convoy, store and plan relationship; a
  missing, stale or conflicting row must stop preparation before allocation.

  ```sh
  : "${CLAIMED_ROOT_BEAD_ID:?native claim has no exact workflow root}"
  : "${ROOT_STORE_REF:?native runtime has no selected root store}"
  export CLAIMED_ROOT_BEAD_ID ROOT_STORE_REF
  CLAIMED_ROOT_JSON=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" bd show "$CLAIMED_ROOT_BEAD_ID" --json) || exit "$?"
  export CLAIMED_ROOT_JSON
  SOURCE_ROW_ID=$(python3 -c 'import json, os
root = json.loads(os.environ["CLAIMED_ROOT_JSON"])
if isinstance(root, list):
    assert len(root) == 1, "expected the one claimed workflow root"
    root = root[0]
assert root["id"] == os.environ["CLAIMED_ROOT_BEAD_ID"], "claimed workflow root changed"
metadata = root["metadata"]
source_id = metadata.get("gc.drain_member_id") or metadata.get("gc.input_convoy_id")
assert isinstance(source_id, str) and bool(source_id) and source_id.strip() == source_id, "workflow root has no exact source row"
print(source_id)') || exit "$?"
  DRAIN_CONTROL_ID=$(python3 -c 'import json, os
root = json.loads(os.environ["CLAIMED_ROOT_JSON"])
if isinstance(root, list): root = root[0]
metadata = root["metadata"]
print(metadata.get("gc.drain_control_id", "") if metadata.get("gc.drain_member_id") else "")') || exit "$?"
  export SOURCE_ROW_ID DRAIN_CONTROL_ID
  SOURCE_ROW_JSON=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" bd show "$SOURCE_ROW_ID" --json) || exit "$?"
  export SOURCE_ROW_JSON
  if [ -n "$DRAIN_CONTROL_ID" ]; then
    DRAIN_CONTROL_JSON=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" bd show "$DRAIN_CONTROL_ID" --json) || exit "$?"
    export DRAIN_CONTROL_JSON
  fi
  SOURCE_GENERATION=$(python3 -c 'import json, os, re
root = json.loads(os.environ["CLAIMED_ROOT_JSON"])
if isinstance(root, list): root = root[0]
row = json.loads(os.environ["SOURCE_ROW_JSON"])
if isinstance(row, list):
    assert len(row) == 1, "expected the one exact source row"
    row = row[0]
assert row["id"] == os.environ["SOURCE_ROW_ID"], "native source row changed"
root_metadata = root["metadata"]
metadata = row["metadata"]
assert root_metadata.get("gc.root_store_ref") == os.environ["ROOT_STORE_REF"], "claimed workflow root belongs to another native store"
assert metadata.get("gc.root_store_ref") == os.environ["ROOT_STORE_REF"], "source row belongs to another native store"
if os.environ["DRAIN_CONTROL_ID"]:
    control = json.loads(os.environ["DRAIN_CONTROL_JSON"])
    if isinstance(control, list):
        assert len(control) == 1, "expected the one native drain control"
        control = control[0]
    assert control["id"] == os.environ["DRAIN_CONTROL_ID"], "native drain control changed"
    control_metadata = control["metadata"]
    assert control_metadata.get("gc.root_store_ref") == os.environ["ROOT_STORE_REF"], "drain control belongs to another native store"
    expected_root = control_metadata.get("gc.root_bead_id")
else:
    expected_root = root["id"]
assert isinstance(expected_root, str) and expected_root, "native source root is missing"
assert metadata.get("gc.source_root_id") == expected_root, "source row belongs to another source root"
generation = metadata.get("gc.source_generation")
assert isinstance(generation, str) and re.fullmatch(r"[1-9][0-9]*", generation), "source row has no canonical positive generation"
print(generation)') || exit "$?"
  export SOURCE_GENERATION
  ```

  Use the retained source generation and run the read-only entry bridge before
  deciding whether the run or source plan exists:

  ```sh
  WORKSPACE_ENTRY_JSON=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace entry read \
    --gc "$GC_BIN" --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" \
    --rig "$RIG_NAME" --workflow-root "$CLAIMED_ROOT_BEAD_ID" \
    --claimed-step "$CLAIMED_BEAD_ID" --worktree-lifecycle new \
    --generation "$SOURCE_GENERATION" --require-plan) || exit "$?"
  export WORKSPACE_ENTRY_JSON
  printf '%s\n' "$WORKSPACE_ENTRY_JSON"
  ```

  Keep these commands in the same shell. Supply `ARTIFACT_ROOT` and
  `WORKSPACE_EVIDENCE_DIR` as existing admitted directories outside the repository
  and all worktrees. `CLAIMED_BEAD_ID` must be exported for the native-row check.
  Use the registered `gc` pack binding. Keep the actual command,
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
  CLAIMED_STEP_JSON=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" bd show "$CLAIMED_BEAD_ID" --json) || exit "$?"
  export CLAIMED_STEP_JSON
  SOURCE_MEMBER_ID=$(python3 -c 'import json, os
entry = json.loads(os.environ["WORKSPACE_ENTRY_JSON"])
row = json.loads(os.environ["CLAIMED_STEP_JSON"])
if isinstance(row, list):
    assert len(row) == 1, "expected the one claimed preparation step"
    row = row[0]
assert row["id"] == os.environ["CLAIMED_BEAD_ID"], "claimed step changed"
metadata = row["metadata"]
member = entry.get("native_continuation", {}).get("member_id")
cooked_member = metadata.get("gc.source_anchor_id", metadata.get("gc.drain_member_id", member or entry["workflow_root_id"]))
assert member is None or member == cooked_member, "native source membership changed"
print(cooked_member)') || exit "$?"
  export SOURCE_MEMBER_ID
  WORKSPACE_OWNER_ID=$(python3 -c 'import json, os
entry = json.loads(os.environ["WORKSPACE_ENTRY_JSON"])
owners = [node["owner_id"] for node in entry["source_plan"]["nodes"]
          if os.environ["SOURCE_MEMBER_ID"] in node["member_ids"]]
assert len(owners) == 1, "source member needs one declared workspace owner"
print(owners[0])') || exit "$?"
  "$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" gc workspace dependency \
    --gc "$GC_BIN" --worktree-lifecycle new --city-root "$CITY_ROOT" \
    --rig-name "$(python3 -c 'import json, os; print(json.loads(os.environ["WORKSPACE_ENTRY_JSON"])["rig_name"])')" \
    --store-ref "$(python3 -c 'import json, os; print(json.loads(os.environ["WORKSPACE_ENTRY_JSON"])["store_ref"])')" \
    --workflow-root-id "$(python3 -c 'import json, os; print(json.loads(os.environ["WORKSPACE_ENTRY_JSON"])["workflow_root_id"])')" \
    --input-convoy-id "$(python3 -c 'import json, os; e=json.loads(os.environ["WORKSPACE_ENTRY_JSON"]); print(e.get("native_input_convoy_id", e["input_convoy_id"]))')" \
    --generation "$(python3 -c 'import json, os; print(json.loads(os.environ["WORKSPACE_ENTRY_JSON"])["generation"])')" \
    --workspace-owner-id "$WORKSPACE_OWNER_ID" --member-id "$SOURCE_MEMBER_ID" \
    --claimed-step-id "$CLAIMED_BEAD_ID" \
    --artifact-root "$ARTIFACT_ROOT" --evidence-dir "$WORKSPACE_EVIDENCE_DIR"
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
