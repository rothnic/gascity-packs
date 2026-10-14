Use the captured `new` lifecycle for managed source. Legacy keeps its existing
workflow instructions.

Read the explicit city, store, rig, workflow root and physical claimed step from
native claim and registration readback. Read the current generation from the
selected source-plan reference. Keep `ARTIFACT_ROOT` and `WORKSPACE_EVIDENCE_DIR`
outside the source checkout. The following shell array passes those exact values
to the installed pack command:

```bash
WORKSPACE_ARGS=(--city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF"
  --rig-name "$RIG_NAME" --workflow-root-id "$ROOT_ID"
  --claimed-step-id "$CLAIMED_BEAD_ID" --generation "$SOURCE_GENERATION"
  --artifact-root "$ARTIFACT_ROOT" --evidence-dir "$WORKSPACE_EVIDENCE_DIR")
```

Resolve `OWNER_ID` and `MEMBER_ID` from the current source plan and actual cooked
member. Resolve `OUTPUT_OID` with Git in that owner's verified checkout. Keep
receipts under `MEMBER_RECEIPTS="$ARTIFACT_ROOT/member-$MEMBER_ID"`.

**Source access:** read `RUN_RECORD_ID`, `PLAN_RECORD_ID`, `WORKSPACE_RECORD_ID`
and `WORKSPACE_AUTHORITY_ID` from their exact native references and grant index.
Resume an unfinished member through the actual continuation adapter:

```bash
WORKSPACE_PATH=$(gc gc workspace checkout continue \
  --city-root "$CITY_ROOT" --store-ref "$ROOT_STORE_REF" --rig-name "$RIG_NAME" \
  --workflow-root-id "$ROOT_ID" --claimed-step-id "$CLAIMED_BEAD_ID" \
  --input-convoy-id "$INPUT_CONVOY_ID" --run-record-id "$RUN_RECORD_ID" \
  --plan-record-id "$PLAN_RECORD_ID" --workspace-record-id "$WORKSPACE_RECORD_ID" \
  --authority-id "$WORKSPACE_AUTHORITY_ID" --worktree-lifecycle new \
  --artifact-root "$ARTIFACT_ROOT" --evidence-dir "$WORKSPACE_EVIDENCE_DIR")
cd "$WORKSPACE_PATH"
```

A recognized same-member continuation may retain partial edits or linear commits.
The continuation command grants no result acceptance or next-member advancement.
Missing records, revoked identity, unexpected Git operations or policy drift stop
source access with the checkout preserved.

**Producer:** write the implementation summary, commit source changes, then run
the captured project policy at the exact clean output:

```bash
gc gc workspace flow artifacts "${WORKSPACE_ARGS[@]}" \
  --artifact "$SUMMARY_PATH" > "$MEMBER_RECEIPTS.artifacts.json"
gc gc workspace runtime checks "${WORKSPACE_ARGS[@]}" \
  --owner-id "$OWNER_ID" --member-id "$MEMBER_ID" --output-oid "$OUTPUT_OID" \
  > "$MEMBER_RECEIPTS.checks.json"
```

**Independent acceptance:** use another native session. The runtime discovers
the actual producer, reviewer and recorder from the cooked graph:

```bash
gc gc workspace runtime begin-review "${WORKSPACE_ARGS[@]}" \
  --owner-id "$OWNER_ID" --member-id "$MEMBER_ID" --output-oid "$OUTPUT_OID" \
  --checks "$MEMBER_RECEIPTS.checks.json" --artifacts "$MEMBER_RECEIPTS.artifacts.json" \
  > "$MEMBER_RECEIPTS.review-context.json"
```

Inspect source, required behavior, check output and the accepted summary. Write
`REVIEW_REPORT` with the findings. Record the observed typed status:

```bash
gc gc workspace runtime complete-review "${WORKSPACE_ARGS[@]}" \
  --context "$MEMBER_RECEIPTS.review-context.json" --report "$REVIEW_REPORT" \
  --review-evidence "$MEMBER_RECEIPTS.review-evidence.json" --status "$REVIEW_STATUS" \
  > "$MEMBER_RECEIPTS.review.json"
```

Only `passed` permits a result. Preserve failed, skipped, unrun and setup failure
evidence. A source edit during review requires a replacement commit, checks and
review. Never author a native identity or qualification object.

**Recorder:** publish the qualified result through the actual native adapter:

```bash
gc gc workspace flow record-result "${WORKSPACE_ARGS[@]}" \
  --owner-id "$OWNER_ID" --member-id "$MEMBER_ID" --output-oid "$OUTPUT_OID" \
  --checks "$MEMBER_RECEIPTS.checks.json" --review "$MEMBER_RECEIPTS.review.json" \
  --artifacts "$MEMBER_RECEIPTS.artifacts.json" > "$MEMBER_RECEIPTS.result.json"
```

The command allocates native records and grants, retains allocation journals and
requires exact guarded write readback. Unknown allocation or write outcomes stop
the handoff. Keep the original operation for recovery.

After the actual workspace checkpoint is recorded, the final member publishes
its owner output. Integration owners also pass the bridge's actual
`--integration-evidence` path:

```bash
gc gc workspace flow owner-output "${WORKSPACE_ARGS[@]}" --owner-id "$OWNER_ID"
```

**Source closure:** the owning close step calls the shared command after result,
checkpoint and final owner-output readback:

```bash
gc gc workspace flow close-source "${WORKSPACE_ARGS[@]}" --member-id "$MEMBER_ID"
```

Close the physical workflow step only after successful native readback. Source
closure supplies no additional acceptance credit.

Native flow writes retain the original guarded request in a private journal
under the repository's common Git directory, scoped to the captured city and
store. An unresolved request blocks another flow write in that same scope.
Use the original request path reported by the command to reconcile the write
without resubmitting it:

```bash
gc gc workspace flow resolve-write "${WORKSPACE_ARGS[@]}" \
  --prepared-request "$ORIGINAL_PREPARED_REQUEST"
```

Only exact committed/replayed readback clears the pending flow write. Keep
not-committed or unknown outcomes for explicit owner recovery.
