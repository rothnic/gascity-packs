#!/usr/bin/env python3
"""Declare ordered source inheritance for existing native workflow nodes."""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

from workspace_records import (
    RecordError, contracts, parse_record, record_identity,
    record_sha256, validate_record, verify_replay,
)


NATIVE_ROOT_KEYS = ("workflow_id", "molecule_id", "gc.root_bead_id")
SOURCE_SCOPE_KEYS = ("gc.source_root_id", "gc.source_generation", "gc.root_store_ref")
RUN_REF_KEY = "gc.implementation_run_ref"
PLAN_REF_KEY = "gc.source_plan_ref"
CANONICAL_REF_KEY = "gc.canonical_ref"


def source_order(plan: dict[str, Any]) -> list[str]:
    """Validate the source DAG, retaining declaration and predecessor order."""
    validate_record("source-plan", plan)
    nodes = {}
    members = {}
    for node in plan["nodes"]:
        owner = node["owner_id"]
        if owner in nodes:
            raise RecordError(f"duplicate owner: {owner}")
        nodes[owner] = node
        for member in node["member_ids"]:
            if member in members:
                raise RecordError(f"member belongs to multiple owners: {member}")
            members[member] = owner
    for owner in nodes:
        if owner in members and members[owner] != owner:
            raise RecordError(f"member conflicts with another owner: {owner}")
    successors = {owner: [] for owner in nodes}
    remaining = {}
    for owner, node in nodes.items():
        predecessors = node["source_predecessor_owner_ids"]
        remaining[owner] = len(predecessors)
        for predecessor in predecessors:
            if predecessor == owner:
                raise RecordError(f"self source edge: {owner}")
            if predecessor not in nodes:
                raise RecordError(f"missing predecessor owner: {predecessor}")
            successors[predecessor].append(owner)
    ready = deque(owner for owner in nodes if remaining[owner] == 0)
    order = []
    while ready:
        owner = ready.popleft()
        order.append(owner)
        for successor in successors[owner]:
            remaining[successor] -= 1
            if remaining[successor] == 0:
                ready.append(successor)
    if len(order) != len(nodes):
        raise RecordError("source graph contains a cycle")
    terminals = [owner for owner in nodes if not successors[owner]]
    if terminals != [plan["terminal_owner_id"]]:
        raise RecordError("every source producer must reach the single declared terminal owner")
    return order


def source_node_ids(plan: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(bead_id for node in plan["nodes"]
                              for bead_id in (node["owner_id"], *node["member_ids"])))


def validate_native_nodes(plan: dict[str, Any], snapshots: dict[str, Any], store_ref: str) -> None:
    """Require native identity plus explicit pack source-generation membership."""
    if not isinstance(snapshots, dict):
        raise RecordError("native node snapshots must be an exact-ID object")
    for bead_id in dict.fromkeys([plan["source_plan_owner_id"], *source_node_ids(plan)]):
        row = snapshots.get(bead_id)
        if not isinstance(row, dict):
            raise RecordError(f"missing native node: {bead_id}")
        if row.get("id") != bead_id:
            raise RecordError(f"native node physical ID mismatch: {bead_id}")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            raise RecordError(f"native node scope missing: {bead_id}")
        native_root = next((metadata[key] for key in NATIVE_ROOT_KEYS if metadata.get(key)), None)
        if (native_root != plan["workflow_root_id"]
                or metadata.get("gc.source_root_id") != plan["workflow_root_id"]
                or metadata.get("gc.source_generation") != str(plan["generation"])
                or metadata.get("gc.root_store_ref") != store_ref):
            raise RecordError(f"native node scope conflicts with root, generation or store: {bead_id}")


def validate_source_plan(plan: dict[str, Any], run: dict[str, Any], snapshots: dict[str, Any], *,
                         store_ref: str, canonical: dict[str, Any] | None = None,
                         stored: dict[str, Any] | None = None) -> dict[str, Any]:
    source_order(plan)
    validate_record("run", run)
    if run["workflow_root_id"] != plan["workflow_root_id"] or run["worktree_lifecycle"] != "new":
        raise RecordError("source plan requires the same workflow root and new run lifecycle")
    validate_native_nodes(plan, snapshots, store_ref)
    if stored is not None:
        verify_replay("source-plan", stored, plan)
        return plan
    if plan["generation"] == 1:
        if plan["base_oid"] != run["base_oid"]:
            raise RecordError("initial source plan must retain the immutable run base")
        if canonical is not None:
            raise RecordError("initial declaration conflicts with an existing canonical result")
    else:
        if canonical is None:
            raise RecordError("fix generation requires the current canonical parent")
        validate_record("canonical", canonical)
        if canonical["workflow_root_id"] != plan["workflow_root_id"]:
            raise RecordError("canonical parent belongs to another workflow root")
        if (plan["generation"] != canonical["generation"] + 1
                or plan["parent_canonical_generation"] != canonical["generation"]):
            raise RecordError("fix generation must follow the current canonical generation")
        if plan["parent_canonical_oid"] != canonical["output_oid"] or plan["base_oid"] != canonical["output_oid"]:
            raise RecordError("fix base and parent must equal the exact current canonical output")
    return plan


def _reference(raw: Any, kind: str, *, required: bool = True) -> dict[str, Any] | None:
    if raw is None and not required:
        return None
    if not isinstance(raw, str):
        raise RecordError(f"{kind} reference must be an explicit JSON-string native reference")
    ref = parse_record(raw)
    if (set(ref) != {"kind", "identity", "bead_id"} or ref["kind"] != kind
            or not isinstance(ref["identity"], list) or not isinstance(ref["bead_id"], str) or not ref["bead_id"]):
        raise RecordError(f"invalid exact {kind} record reference")
    return ref


def declare_plan(store, attempt, plan: dict[str, Any], *, run_record_id: str,
                 record_bead_id: str, authority_id: str, implementation_convoy_id: str | None = None,
                 operation_nonce: str | None = None, writer_map=None, writer_rows=None):
    """Prepare one fenced publication using the production record-access adapter."""
    from workspace_store import (CookedWriterMap, GRANT_KEY, GuardRead, MISSING, RecordWrite,
                                 ReferenceWrite, SourceMembershipProjection, SourcePlanConvoyBinding)

    source_order(plan)
    if plan["writer_step_id"] != attempt.claimed_bead_id:
        raise RecordError("source-plan writer must equal the retained native claimed step")
    root_id = plan["workflow_root_id"]
    owner_id = plan["source_plan_owner_id"]
    if not isinstance(writer_map, CookedWriterMap):
        raise RecordError("source-plan publication requires the actual cooked native writer map")
    declaration = writer_map.declaration
    map_ids = [declaration["expansion_root_id"], declaration["source_member_id"],
               *(step["bead_id"] for step in declaration["steps"])]
    rows = {} if writer_rows is None else dict(writer_rows)
    if any(not isinstance(row, dict) or row.get("id") != bead_id for bead_id, row in rows.items()):
        raise RecordError("cooked writer rows require their exact original native snapshots")
    needed = list(dict.fromkeys([authority_id, attempt.claimed_bead_id, root_id, owner_id,
                                run_record_id, record_bead_id, *source_node_ids(plan), *map_ids,
                                *([implementation_convoy_id] if implementation_convoy_id is not None else [])]))
    missing = [bead_id for bead_id in needed if bead_id not in rows]
    if missing:
        rows.update(store.snapshot(missing))
    root_metadata = rows[root_id]["metadata"]
    owner_metadata = rows[owner_id]["metadata"]
    run_ref_raw = root_metadata.get(RUN_REF_KEY, MISSING)
    run_ref = _reference(run_ref_raw, "run")
    if run_ref["bead_id"] != run_record_id:
        raise RecordError("run physical record conflicts with the exact root reference")
    run = store.read_record("run", run_record_id, identity=run_ref["identity"])
    if run is None:
        raise RecordError("run record is absent")
    common_git_dir = Path(run["common_git_dir"]).resolve(strict=True)
    if str(common_git_dir) != run["common_git_dir"]:
        raise RecordError("recorded common Git directory is no longer canonical")
    if store.common_git_dir is not None and Path(store.common_git_dir).resolve(strict=True) != common_git_dir:
        raise RecordError("writer lock directory conflicts with the immutable run")
    store.common_git_dir = common_git_dir
    canonical_raw = root_metadata.get(CANONICAL_REF_KEY, MISSING)
    canonical = None
    guards = [GuardRead(root_id, RUN_REF_KEY, run_ref_raw),
              GuardRead(run_record_id, contracts()["run"]["metadata_key"], rows[run_record_id]["metadata"].get(contracts()["run"]["metadata_key"], MISSING)),
              GuardRead(root_id, CANONICAL_REF_KEY, canonical_raw)]
    if canonical_raw is not MISSING:
        canonical_ref = _reference(canonical_raw, "canonical")
        if canonical_ref["bead_id"] in rows:
            canonical_row = rows[canonical_ref["bead_id"]]
        else:
            canonical_row = store.snapshot([canonical_ref["bead_id"]])[canonical_ref["bead_id"]]
            rows[canonical_ref["bead_id"]] = canonical_row
        canonical = store.read_record("canonical", canonical_ref["bead_id"], identity=canonical_ref["identity"])
        if canonical is None:
            raise RecordError("current canonical reference has no record")
        guards.append(GuardRead(canonical_ref["bead_id"], contracts()["canonical"]["metadata_key"],
                                canonical_row["metadata"].get(contracts()["canonical"]["metadata_key"], MISSING)))
    plan_ref_raw = owner_metadata.get(PLAN_REF_KEY, MISSING)
    stored = None
    if plan_ref_raw is not MISSING:
        plan_ref = _reference(plan_ref_raw, "source-plan")
        if plan_ref["bead_id"] != record_bead_id or plan_ref["identity"] != list(record_identity("source-plan", plan)):
            raise RecordError("source-plan reference conflicts with the exact candidate identity")
        stored = store.read_record("source-plan", record_bead_id, identity=plan_ref["identity"])
        if stored is None:
            raise RecordError("source-plan reference has no record")
    validation_rows, projections = rows, []
    source_membership = {"gc.source_root_id": root_id, "gc.source_generation": str(plan["generation"])}
    if any(key not in owner_metadata for key in source_membership):
        native_root = next((owner_metadata[key] for key in NATIVE_ROOT_KEYS if owner_metadata.get(key)), None)
        if native_root != root_id or owner_metadata.get("gc.root_store_ref") != store.store_ref:
            raise RecordError("source-plan owner has a foreign native root or store")
        if any(key in owner_metadata and owner_metadata[key] != value for key, value in source_membership.items()):
            raise RecordError("source-plan owner has conflicting source membership")
        validation_rows = dict(rows)
        validation_rows[owner_id] = dict(rows[owner_id], metadata=dict(owner_metadata, **source_membership))
        projections = [SourceMembershipProjection(owner_id, root_id, plan["generation"])]
    validate_source_plan(plan, run, validation_rows, store_ref=store.store_ref, canonical=canonical, stored=stored)
    if implementation_convoy_id is not None:
        projections.append(SourcePlanConvoyBinding(implementation_convoy_id))
        guards.append(GuardRead(root_id, "gc.input_convoy_id", root_metadata.get("gc.input_convoy_id", MISSING)))
        previous_convoy_id = root_metadata.get("gc.build.implementation_convoy_id", MISSING)
        guards.append(GuardRead(root_id, "gc.build.implementation_convoy_id", previous_convoy_id))
        if previous_convoy_id is not MISSING and previous_convoy_id != implementation_convoy_id:
            if not isinstance(previous_convoy_id, str) or not previous_convoy_id:
                raise RecordError("preceding implementation convoy requires an exact native ID")
            if previous_convoy_id not in rows:
                rows[previous_convoy_id] = store.snapshot([previous_convoy_id])[previous_convoy_id]
            previous = rows[previous_convoy_id]
            metadata = previous["metadata"]
            native_root = next((metadata[key] for key in NATIVE_ROOT_KEYS if metadata.get(key)), None)
            if (previous["type"] != "convoy" or native_root != root_id
                    or metadata.get("gc.root_bead_id") != root_id
                    or metadata.get("gc.root_store_ref") != store.store_ref
                    or metadata.get("gc.source_root_id") != root_id
                    or metadata.get("gc.source_generation") != str(plan["generation"] - 1)):
                raise RecordError("convoy replacement requires the exact preceding native source generation")
            for key in (*NATIVE_ROOT_KEYS, *SOURCE_SCOPE_KEYS):
                guards.append(GuardRead(previous_convoy_id, key, metadata.get(key, MISSING)))
    guards.append(GuardRead(owner_id, PLAN_REF_KEY, plan_ref_raw))
    for bead_id in dict.fromkeys([owner_id, *source_node_ids(plan)]):
        metadata = rows[bead_id]["metadata"]
        for key in (*NATIVE_ROOT_KEYS, *SOURCE_SCOPE_KEYS):
            guards.append(GuardRead(bead_id, key, metadata.get(key, MISSING)))
    reference = {"kind": "source-plan", "identity": list(record_identity("source-plan", plan)), "bead_id": record_bead_id}
    operation = store.write_records if GRANT_KEY in rows[authority_id]["metadata"] else store.install_grant
    return operation(attempt=attempt, scope={"workflow_root_id": root_id, "generation": plan["generation"],
                               "writer_scope_id": owner_id, "record_kind": "source-plan"}, authority_id=authority_id,
                               writes=[RecordWrite("source-plan", record_bead_id, plan)],
                               references=[ReferenceWrite(owner_id, PLAN_REF_KEY, reference)], guards=guards,
                               projections=projections, writer_map=writer_map,
                               expected_rows=rows, operation_nonce=operation_nonce)


def publish_plan(store, prepared) -> dict[str, Any]:
    """Submit once and classify the exact native readback without exposing grants."""
    submitted = store.execute(prepared)
    observed = store.resolve(prepared)
    result = {"outcome": observed["outcome"], "request_sha256": observed["request_sha256"],
              "submission_outcome": submitted["outcome"], "retry_allowed": False}
    if result["outcome"] not in ("committed", "replayed"):
        result["error"] = observed.get("error", submitted.get("error", "exact native intent readback did not prove publication"))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    validate = subparsers.add_parser("validate", help="validate supplied snapshots without store writes")
    validate.add_argument("--run", required=True, type=Path)
    validate.add_argument("--native-nodes", required=True, type=Path)
    validate.add_argument("--canonical", type=Path)
    declare = subparsers.add_parser("declare", help="publish through the guarded native record adapter")
    for flag in ("run-record-id", "record-id", "claimed-step-id", "authority-id"):
        declare.add_argument("--" + flag, required=True)
    declare.add_argument("--operation-nonce")
    declare.add_argument("--implementation-convoy-id")
    declare.add_argument("--gc", default="gc")
    declare.add_argument("--cwd", required=True, type=Path)
    for child in (validate, declare):
        child.add_argument("--plan", required=True, type=Path)
        child.add_argument("--store-ref", required=True)
    args = parser.parse_args(argv)
    try:
        plan = parse_record(args.plan.read_text(encoding="utf-8"))
        if args.action == "validate":
            run = parse_record(args.run.read_text(encoding="utf-8"))
            nodes = parse_record(args.native_nodes.read_text(encoding="utf-8"))
            canonical = parse_record(args.canonical.read_text(encoding="utf-8")) if args.canonical else None
            validate_source_plan(plan, run, nodes, store_ref=args.store_ref, canonical=canonical)
            result = {"ok": True, "sha256": record_sha256(plan), "source_order": source_order(plan)}
        else:
            from workspace_store import Attempt, WorkspaceStore
            from workspace_cooked import read_cooked_writer_map
            store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.cwd)
            writer_map, writer_rows = read_cooked_writer_map(store, workflow_root_id=plan["workflow_root_id"],
                                                            claimed_step_id=args.claimed_step_id)
            prepared = declare_plan(store, Attempt.from_env(args.claimed_step_id), plan,
                                    run_record_id=args.run_record_id, record_bead_id=args.record_id,
                                    authority_id=args.authority_id, implementation_convoy_id=args.implementation_convoy_id,
                                    operation_nonce=args.operation_nonce, writer_map=writer_map, writer_rows=writer_rows)
            result = publish_plan(store, prepared)
        print(json.dumps(result, sort_keys=True))
        return 0 if args.action == "validate" or result.get("outcome") in ("committed", "replayed") else 1
    except (RecordError, OSError, UnicodeError, ValueError) as exc:
        print(f"workspace source plan: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
