#!/usr/bin/env python3
"""Capture build inputs and validate recorded inputs at workflow handoffs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from typing import Any

from workspace_records import (RecordError, canonical_bytes, contracts, parse_record,
                               record_identity, record_sha256, validate_record)
from workspace_run import (RunError, canonical_path, capture_payload, capture_run,
                           native_json, read_check_policy, registered_rig, repository_identity, source_context, run_scope)


RUN_REF = "gc.implementation_run_ref"
PLAN_REF = "gc.source_plan_ref"
ROOT_KEYS = ("workflow_id", "molecule_id", "gc.root_bead_id")


class EntryError(RecordError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EntryError(message)


def native_root(row: dict[str, Any]) -> str | None:
    metadata = row["metadata"]
    return next((metadata[key] for key in ROOT_KEYS if metadata.get(key)), None)


def reference(raw: Any, kind: str) -> dict[str, Any]:
    require(isinstance(raw, str), f"missing recorded {kind} reference; resume its original workflow or migrate explicitly")
    value = parse_record(raw)
    require(set(value) == {"kind", "identity", "bead_id"} and value["kind"] == kind
            and isinstance(value["identity"], list) and isinstance(value["bead_id"], str)
            and bool(value["bead_id"]), f"malformed exact {kind} reference")
    return value


def healthy(row: dict[str, Any]) -> None:
    metadata = row["metadata"]
    labels = row.get("labels") or []
    require(isinstance(metadata, dict) and isinstance(labels, list), "malformed native entry state")
    require(metadata.get("gc.outcome") not in ("fail", "skipped", "canceled", "cancelled")
            and metadata.get("molecule_failed") not in (True, "true")
            and metadata.get("gc.molecule_failed") not in (True, "true")
            and not metadata.get("gc.cancel_requested")
            and all(isinstance(label, str) and not label.startswith("hold:") for label in labels),
            "native entry is failed, canceled or held")


def allocate_placeholder(store, *, title: str, existing_id: str | None = None,
                         allocation_description: str | None = None,
                         verified_rows: dict[str, Any] | None = None) -> str:
    """Allocate one native closed record without publishing any lifecycle state.

    A lost create acknowledgement is not retried. The retained role journal can
    recover its physical ID through the native unique-description query.
    """
    if existing_id is None:
        rig = store.store_ref.split(":", 1)[1] if store.store_ref.startswith("rig:") else None
        try:
            args = ["bd", "create", title, "--type", "task", "--status", "closed",
                    "--assignee", "", "--metadata", "{}", "--json"]
            if allocation_description is not None:
                args += ["--description", allocation_description]
            response = native_json(store.gc, store.cwd, args, rig)
        except (RunError, RecordError, OSError) as exc:
            raise EntryError("native allocation outcome is uncertain; inspect the original create response before retrying") from exc
        existing_id = response.get("id")
        require(isinstance(existing_id, str) and bool(existing_id.strip()) and existing_id == existing_id.strip(),
                "native allocation outcome is unknown: create returned no exact physical ID; do not create a duplicate")
    try:
        row = store.snapshot([existing_id])[existing_id]
    except (RecordError, OSError, KeyError) as exc:
        raise EntryError(f"allocated native ID {existing_id} cannot be verified; retry verification of this ID, not creation") from exc
    require(row["id"] == existing_id and row["status"] == "closed" and not row["assignee"]
            and not row["metadata"] and row["type"] == "task" and not row.get("labels"),
            f"native ID {existing_id} is not an empty closed, unassigned record allocation")
    if allocation_description is not None:
        rig = store.store_ref.split(":", 1)[1] if store.store_ref.startswith("rig:") else None
        details = native_json(store.gc, store.cwd, ["bd", "show", existing_id, "--json"], rig,
                              unwrap_singleton=True)
        require(details.get("id") == existing_id and details.get("title") == title
                and details.get("description") == allocation_description,
                "native ID does not belong to the retained allocation intent")
        require(store.snapshot([existing_id])[existing_id] == row,
                "native allocation changed while reading its identity")
    if verified_rows is not None:
        verified_rows[existing_id] = row
    return existing_id


def allocate_run_placeholders(store, attempt, *, workflow_root_id: str, input_convoy_id: str,
                              source_anchor_id: str, rig_root: str, worktree_lifecycle: str,
                              base_ref: str = "@default", run_record_id: str | None = None,
                              authority_id: str | None = None, checks_config: str | None = None,
                              writer_map=None, writer_rows=None) -> dict[str, Any]:
    """Retain the source and each native create boundary before effects."""
    from workspace_requests import allocation_directory, require_resolved_scope
    from workspace_store import read_cooked_context, transition_locks
    from workspace_outputs import immutable_json
    from workspace_allocation import read_packet, writer_origin, admit_writer, allocate_roles
    scope = run_scope(workflow_root_id)
    directory = allocation_directory(store)
    prefix = "run-" + hashlib.sha256(canonical_bytes(scope)).hexdigest()
    path = directory / (prefix + ".intent.json")
    binding = {"store": parse_record(store._binding().decode()), "scope": scope,
               "base_ref": base_ref,
               "checks_config": checks_config}
    with transition_locks(store.common_git_dir, scope):
        require_resolved_scope(store, scope)
        original = read_packet(path) if path.exists() else None
        require(original is None or original.get("binding") == binding,
                "run allocation belongs to a different source configuration or attempt; inspect " + str(path))
        require(original is None or isinstance(original.get("origin"), dict),
                "retained allocation has no original cooked writer evidence; inspect " + str(path))
        if writer_rows is None and writer_map is not None:
            declared = writer_map.declaration
            writer_rows = read_cooked_context(store, list(dict.fromkeys([workflow_root_id, declared["source_member_id"],
                declared["expansion_root_id"], *(step["bead_id"] for step in declared["steps"])])))
        admit_writer(store, attempt, scope, writer_map, writer_rows,
                     origin=original.get("origin") if original else None)
        captured = capture_payload(workflow_root_id=workflow_root_id, input_convoy_id=input_convoy_id,
            source_anchor_id=source_anchor_id, rig_root=rig_root, writer_step_id=attempt.claimed_bead_id,
            worktree_lifecycle=worktree_lifecycle, base_ref=base_ref,
            stored=original["captured_run"] if original else None)
        if worktree_lifecycle == "new":
            # Validate policy before the first native allocation, with its later
            # physical record binding still owned by the publication adapter.
            from workspace_outputs import check_scope
            config = parse_record(checks_config) if isinstance(checks_config, str) else None
            require(config is not None and set(config) == {"required_checks"}
                    and canonical_bytes(config).decode() == checks_config,
                    "new run allocation requires canonical native worktree_checks")
            check_scope(config["required_checks"])
        packet = original or {"version": 1, "binding": binding, "captured_run": captured,
                              "origin": writer_origin(attempt, writer_map), "nonce": secrets.token_hex(32)}
        require(set(packet) == {"version", "binding", "captured_run", "origin", "nonce"}
                and type(packet["version"]) is int and packet["version"] == 1
                and isinstance(packet["nonce"], str) and len(packet["nonce"]) == 64
                and all(value in "0123456789abcdef" for value in packet["nonce"]),
                "retained run allocation intent is malformed")
        immutable_json(path, packet)
        ids, rows = allocate_roles(store, packet, prefix=prefix,
            roles=(("run", "Immutable build run", run_record_id),
                   ("authority", "Build run writer grant", authority_id)),
            allocate=allocate_placeholder, native_read=native_json,
            admit=lambda: admit_writer(store, attempt, scope, writer_map, writer_rows, origin=packet["origin"]))
        return {"run_record_id": ids["run"], "authority_id": ids["authority"],
                "captured_run": captured, "allocation_rows": rows, "allocation_journal": str(path)}


def _load(store, kind: str, ref: dict[str, Any]) -> dict[str, Any]:
    payload = store.read_record(kind, ref["bead_id"], identity=ref["identity"])
    require(payload is not None, f"{kind} reference points to a missing record")
    validate_record(kind, payload)
    require(list(record_identity(kind, payload)) == ref["identity"], f"{kind} reference identity changed")
    return payload


def read_native_continuation(store, *, claimed_step_id: str, requested_root_id: str | None = None,
                             recorded_root_id: str | None = None):
    """Resolve a native drain child through its recorded control and unit convoy.

    This reads native rows only. Publishing inherited references belongs in the
    guarded workspace transaction that consumes these exact original rows.
    """
    from workspace_store import NativeRunContinuation, validate_native_continuation
    from workspace_suffix import read as read_suffix
    suffix = read_suffix(store, claimed_step_id=claimed_step_id, requested_root_id=requested_root_id,
                         recorded_root_id=recorded_root_id)
    if suffix is not None:
        return suffix
    rows = {}

    def read(bead_id):
        require(isinstance(bead_id, str) and bool(bead_id.strip()) and bead_id == bead_id.strip(),
                "native continuation has no exact physical relationship ID")
        if bead_id not in rows:
            require(len(rows) < 100, "native continuation exceeds the guarded row bound")
            snapshot = store.snapshot([bead_id])
            require(set(snapshot) == {bead_id} and snapshot[bead_id]["id"] == bead_id,
                    "native continuation readback has a different physical ID")
            rows.update(snapshot)
        healthy(rows[bead_id])
        return rows[bead_id]

    def payload(kind, ref):
        row = read(ref["bead_id"])
        raw = row["metadata"].get(contracts()[kind]["metadata_key"])
        require(isinstance(raw, str), "native continuation reference points to an empty " + kind)
        value = parse_record(raw)
        validate_record(kind, value)
        require(list(record_identity(kind, value)) == ref["identity"], "native continuation record identity changed")
        return value

    claim = read(claimed_step_id)
    child_id = native_root(claim)
    child = read(child_id)
    control_id = child["metadata"].get("gc.drain_control_id")
    control = read(control_id)
    run_root_id = native_root(control)
    require(run_root_id != child_id and requested_root_id in (None, run_root_id, child_id)
            and recorded_root_id in (None, run_root_id),
            "native drain child does not continue the requested workflow")
    root = read(run_root_id)
    require(all(row["metadata"].get("gc.var.worktree_run_root") in (None, "", run_root_id)
                for row in (root, child)), "native drain selector conflicts with its original workflow")
    unit_id = child["metadata"].get("gc.input_convoy_id")
    unit = read(unit_id)
    implementation_id = unit["metadata"].get("gc.parent_convoy_id")
    implementation = read(implementation_id)
    member_id = child["metadata"].get("gc.drain_member_id")
    read(member_id)
    owner_id = implementation["metadata"].get("gc.source_plan_owner_id")
    owner = read(owner_id)
    run_ref = reference(root["metadata"].get(RUN_REF), "run")
    plan_ref = reference(owner["metadata"].get(PLAN_REF), "source-plan")
    run_payload = payload("run", run_ref)
    plan = payload("source-plan", plan_ref)
    raw_policy = rows[run_ref["bead_id"]]["metadata"].get("gc.workspace_required_checks.v1")
    require(isinstance(raw_policy, str), "native continuation has no captured check policy")
    policy = parse_record(raw_policy)
    require(canonical_bytes(policy).decode() == raw_policy, "captured check policy is noncanonical")
    binding = {"version": 1, "workflow_root_id": run_root_id, "store_ref": store.store_ref,
        "generation": plan["generation"], "child_root_id": child_id, "unit_convoy_id": unit_id,
        "implementation_convoy_id": implementation_id, "drain_control_id": control_id,
        "member_id": member_id, "run_ref": run_ref, "source_plan_ref": plan_ref,
        "run_sha256": record_sha256(run_payload), "source_plan_sha256": record_sha256(plan),
        "check_policy_sha256": hashlib.sha256(canonical_bytes(policy)).hexdigest()}
    continuation = NativeRunContinuation(canonical_bytes(binding))
    validate_native_continuation(continuation, rows, store_ref=store.store_ref,
        workflow_root_id=run_root_id, claimed_step_id=claimed_step_id)
    return continuation, rows


def _continuation_candidate(store, root, requested_root_id=None, recorded_root_id=None):
    from workspace_store import CONTINUATION_KEY
    metadata = root["metadata"]
    if (metadata.get("gc.drain_control_id") or CONTINUATION_KEY in metadata
            or recorded_root_id not in (None, root["id"])
            or metadata.get("gc.var.worktree_run_root") not in (None, "", root["id"])
            or requested_root_id not in (None, root["id"])):
        return True
    if RUN_REF not in metadata and metadata.get("gc.input_convoy_id"):
        convoy = store.snapshot([metadata["gc.input_convoy_id"]])[metadata["gc.input_convoy_id"]]
        source_root = convoy["metadata"].get("gc.source_root_id")
        return bool(source_root) and source_root != root["id"]
    return False


def read_entry(store, *, gc: str, city_root: str, rig_name: str,
               workflow_root_id: str, claimed_step_id: str, worktree_lifecycle: str,
               generation: int, input_convoy_id: str | None = None,
               require_plan: bool = False, expected_run_sha256: str | None = None,
               expected_plan_sha256: str | None = None, recorded_root_id: str | None = None) -> dict[str, Any]:
    """Read immutable provenance separately from the mutable current convoy.

    Native attached suffixes retain the original root. Drain children retain
    their own native root and inherit the original run through their control.
    The caller must fence this state again in the operation that uses it.
    """
    try:
        require(type(generation) is int and generation > 0, "generation must be a positive integer")
        city_root = canonical_path(city_root)
        require(city_root == store.cwd, "selected city conflicts with the native store adapter")
        rig_root = registered_rig(gc, city_root, rig_name, store.store_ref)
        rows = store.snapshot(list(dict.fromkeys([workflow_root_id, claimed_step_id])))
        root, step = rows[workflow_root_id], rows[claimed_step_id]
        continuation = None
        physical_root_id = native_root(step)
        physical_root = root if physical_root_id == workflow_root_id else store.snapshot([physical_root_id])[physical_root_id]
        if _continuation_candidate(store, physical_root, workflow_root_id, recorded_root_id):
            continuation, continuation_rows = read_native_continuation(store, claimed_step_id=claimed_step_id,
                requested_root_id=workflow_root_id, recorded_root_id=recorded_root_id)
            require(all(bead_id not in rows or rows[bead_id] == row for bead_id, row in continuation_rows.items()),
                    "native continuation changed after its original entry snapshot")
            rows.update(continuation_rows)
            workflow_root_id = continuation.binding["workflow_root_id"]
            next_plan = (continuation.binding["version"] == 2 and not require_plan
                         and generation == continuation.binding["generation"] + 1
                         and continuation.binding["canonical_ref"] is not None
                         and continuation.binding["canonical_ref"]["identity"][1] == generation - 1)
            require(generation == continuation.binding["generation"] or next_plan,
                    "requested generation differs from the native child source plan")
            root = rows[workflow_root_id]
            physical_root = rows[physical_root_id]
        healthy(root)
        healthy(step)
        require(root["metadata"].get("gc.kind") == "workflow"
                and root["metadata"].get("gc.root_store_ref") == store.store_ref,
                "workflow root belongs to another native store")
        require(native_root(step) == (continuation.binding["child_root_id"] if continuation else workflow_root_id)
                and step["metadata"].get("gc.root_store_ref") == store.store_ref
                and step["status"] == "in_progress" and bool(step["assignee"]),
                "claimed entry step belongs to another native root/store or is no longer claimed")
        ref = reference(root["metadata"].get(RUN_REF), "run")
        captured = _load(store, "run", ref)
        require(captured["workflow_root_id"] == workflow_root_id,
                "recorded run belongs to another workflow")
        # Reuse the capture validator without selecting HEAD or any current ref.
        replay = capture_payload(workflow_root_id=workflow_root_id,
            input_convoy_id=captured["input_convoy_id"], source_anchor_id=captured["source_anchor_id"],
            rig_root=rig_root, writer_step_id=captured["writer_step_id"],
            worktree_lifecycle=worktree_lifecycle, stored=captured)
        digest = record_sha256(replay)
        if continuation:
            require(ref == continuation.binding["run_ref"] and digest == continuation.binding["run_sha256"],
                    "inherited run changed after its original native snapshot")
        pin = expected_run_sha256 or root["metadata"].get("gc.implementation_run_sha256")
        require(pin is None or pin == digest, "recorded run hash differs from the continuation binding")
        original_ids = list(dict.fromkeys([captured["input_convoy_id"], captured["source_anchor_id"]]))
        original = store.snapshot(original_ids)
        require(all(bead_id not in rows or rows[bead_id] == row for bead_id, row in original.items()),
                "original source changed after continuation admission")
        rows.update(original)
        require(original[captured["input_convoy_id"]]["type"] == "convoy", "original run input is no longer a native convoy")
        for row in original.values():
            healthy(row)
            for key in ("gc.root_store_ref", "gc.source_store_ref"):
                require(key not in row["metadata"] or row["metadata"][key] == store.store_ref,
                        "original source changed native store")
            require(native_root(row) in (None, workflow_root_id), "original source changed native workflow")
        require(original[captured["source_anchor_id"]]["metadata"].get("gc.synthetic") != "true",
                "original source anchor became synthetic")
        current_id = root["metadata"].get("gc.input_convoy_id")
        require(isinstance(current_id, str) and bool(current_id), "current workflow has no native input convoy")
        rendered_id = continuation.binding["unit_convoy_id"] if continuation else current_id
        require(input_convoy_id is None or input_convoy_id == rendered_id, "rendered input differs from the current native convoy")
        convoy = store.snapshot([current_id])[current_id]
        require(current_id not in rows or rows[current_id] == convoy,
                "current convoy changed after continuation admission")
        rows[current_id] = convoy
        healthy(convoy)
        require(convoy["type"] == "convoy", "continuation input is not a native convoy")
        if current_id != captured["input_convoy_id"] or require_plan:
            require(native_root(convoy) == workflow_root_id
                    and convoy["metadata"].get("gc.root_store_ref") == store.store_ref
                    and convoy["metadata"].get("gc.source_root_id") == workflow_root_id
                    and convoy["metadata"].get("gc.source_generation") == str(
                        continuation.binding["generation"] if continuation else generation),
                    "implementation convoy conflicts with the original root, native store or source generation")
        result = {"state": "recorded", "run": replay, "run_reference": ref, "run_sha256": digest,
                  "workflow_root_id": workflow_root_id, "generation": generation,
                  "store_ref": store.store_ref, "rig_name": rig_name, "input_convoy_id": current_id}
        if continuation:
            result.update(native_workflow_root_id=physical_root_id, native_input_convoy_id=rendered_id,
                          native_continuation=continuation.binding, _native_rows=rows)
        if worktree_lifecycle == "new":
            result["check_policy"] = read_check_policy(store, ref["bead_id"], replay)
            if continuation:
                require(hashlib.sha256(canonical_bytes(result["check_policy"])).hexdigest()
                        == continuation.binding["check_policy_sha256"],
                        "inherited check policy changed after its original native snapshot")
        if require_plan:
            from workspace_source_plan import source_node_ids, validate_source_plan
            owner_id = convoy["metadata"].get("gc.source_plan_owner_id")
            require(isinstance(owner_id, str) and bool(owner_id), "implementation convoy has no declared source-plan owner")
            owner = store.snapshot([owner_id])[owner_id]
            plan_ref = reference(owner["metadata"].get(PLAN_REF), "source-plan")
            plan = _load(store, "source-plan", plan_ref)
            require(plan["source_plan_owner_id"] == owner_id and plan["generation"] == generation,
                    "source plan has a different owner or generation")
            plan_digest = record_sha256(plan)
            if continuation:
                require(plan_ref == continuation.binding["source_plan_ref"]
                        and plan_digest == continuation.binding["source_plan_sha256"],
                        "inherited source plan changed after its original native snapshot")
            pin = expected_plan_sha256 or convoy["metadata"].get("gc.source_plan_sha256")
            require(pin is None or pin == plan_digest, "source-plan hash differs from the continuation binding")
            nodes = store.snapshot(list(dict.fromkeys([owner_id, *source_node_ids(plan)])))
            require(all(bead_id not in rows or rows[bead_id] == row for bead_id, row in nodes.items()),
                    "source membership changed after continuation admission")
            rows.update(nodes)
            canonical = None
            if generation > 1:
                canonical_ref = reference(root["metadata"].get("gc.canonical_ref"), "canonical")
                canonical = _load(store, "canonical", canonical_ref)
            # An existing generation is exact replay, not a proposal based on
            # the current canonical result that it may have produced itself.
            from workspace_suffix import retain_source_owner
            rows = retain_source_owner(store, plan, rows)
            validate_source_plan(plan, replay, rows, store_ref=store.store_ref, canonical=canonical, stored=plan)
            result.update(source_plan=plan, source_plan_reference=plan_ref, source_plan_sha256=plan_digest)
        if continuation or (require_plan and len(rows) > len(nodes)):
            result['_native_rows'] = rows
        return result
    except (RecordError, RunError, OSError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, EntryError):
            raise
        raise EntryError(f"recorded workflow handoff failed: {exc}; resume the original workflow or migrate explicitly") from exc


def prepare_entry(store, attempt, *, gc: str, city_root: str, rig_name: str,
                  workflow_root_id: str, entrypoint: str, worktree_lifecycle: str,
                  base_ref: str = "@default", generation: int = 1,
                  input_convoy_id: str | None = None, run_record_id: str | None = None,
                  authority_id: str | None = None, require_plan: bool = False,
                  allow_pending_source: bool = False, recorded_root_id: str | None = None) -> dict[str, Any]:
    require(worktree_lifecycle in ("legacy", "new"), "unknown worktree lifecycle")
    require(type(generation) is int and generation > 0, "generation must be a positive integer")
    require(canonical_path(city_root) == store.cwd, "selected city conflicts with the native store adapter")
    rows = store.snapshot([workflow_root_id, attempt.claimed_bead_id])
    root = rows[workflow_root_id]
    physical_id = native_root(rows[attempt.claimed_bead_id])
    physical = root if physical_id == workflow_root_id else store.snapshot([physical_id])[physical_id]
    if RUN_REF in root["metadata"] or _continuation_candidate(store, physical, workflow_root_id, recorded_root_id):
        result = read_entry(store, gc=gc, city_root=city_root, rig_name=rig_name,
            workflow_root_id=workflow_root_id, claimed_step_id=attempt.claimed_bead_id,
            worktree_lifecycle=worktree_lifecycle, generation=generation,
            input_convoy_id=input_convoy_id, require_plan=require_plan, recorded_root_id=recorded_root_id)
        from workspace_requests import require_resolved_scope
        store.common_git_dir = result["run"]["common_git_dir"]
        require_resolved_scope(store, run_scope(result["run"]["workflow_root_id"]))
        return result
    require(entrypoint in ("build", "implement", "requirements", "plan", "decompose"),
            "continuation has no recorded run; artifact-only legacy input requires explicit migration")
    require(generation == 1, "an initial run cannot begin at a later generation")
    step = rows[attempt.claimed_bead_id]
    healthy(root)
    healthy(step)
    require(root["metadata"].get("gc.kind") == "workflow"
            and root["metadata"].get("gc.root_store_ref") == store.store_ref
            and native_root(step) == workflow_root_id
            and step["metadata"].get("gc.root_store_ref") == store.store_ref
            and step["metadata"].get("gc.session_id") == attempt.session_id
            and step["status"] == "in_progress" and bool(step["assignee"]),
            "entry lacks the retained native claimed step, session, root or store")
    current_id = root["metadata"].get("gc.input_convoy_id")
    if not current_id:
        require(allow_pending_source and entrypoint in ("build", "requirements"),
                "capture requires a valid native source convoy before implementation")
        require(native_root(rows[attempt.claimed_bead_id]) == workflow_root_id
                and root["metadata"].get("gc.root_store_ref") == store.store_ref,
                "pending source entry has no matching native root/store")
        return {"state": "awaiting-source", "workflow_root_id": workflow_root_id,
                "store_ref": store.store_ref, "implementation_allowed": False}
    require(input_convoy_id is None or current_id == input_convoy_id, "rendered input differs from native source convoy")
    # Validate the actual source boundary before allocating records or grants.
    anchor, source_rows = source_context(store, gc=gc, city_root=city_root, workflow_root_id=workflow_root_id,
                                        input_convoy_id=current_id, claimed_step_id=attempt.claimed_bead_id)
    rig_root = registered_rig(gc, canonical_path(city_root), rig_name, store.store_ref)
    store.common_git_dir = repository_identity(rig_root)[1]
    from workspace_requests import require_resolved_scope
    require_resolved_scope(store, run_scope(workflow_root_id))
    from workspace_cooked import read_cooked_writer_map
    writer_map, writer_rows = read_cooked_writer_map(store, workflow_root_id=workflow_root_id,
                                                    claimed_step_id=attempt.claimed_bead_id)
    checks_config = source_rows[workflow_root_id]["metadata"].get("gc.var.worktree_checks")
    allocated = allocate_run_placeholders(store, attempt, workflow_root_id=workflow_root_id,
        input_convoy_id=current_id, source_anchor_id=anchor, rig_root=rig_root,
        worktree_lifecycle=worktree_lifecycle, base_ref=base_ref,
        run_record_id=run_record_id, authority_id=authority_id, checks_config=checks_config,
        writer_map=writer_map, writer_rows=writer_rows)
    run_record_id, authority_id = allocated["run_record_id"], allocated["authority_id"]
    captured = capture_run(store, attempt, gc=gc, city_root=city_root, rig_name=rig_name,
        workflow_root_id=workflow_root_id, input_convoy_id=current_id, record_bead_id=run_record_id,
        authority_id=authority_id, worktree_lifecycle=worktree_lifecycle, base_ref=base_ref,
        writer_map=writer_map, writer_rows=writer_rows, allocation_rows=allocated["allocation_rows"],
        captured_run=allocated["captured_run"], captured_checks_config=checks_config)
    require(captured["receipt"].get("outcome") in ("committed", "replayed"),
            "run publication is uncertain; resolve the original guarded request before continuing: "
            + str(captured["receipt"].get("request_path", "unavailable")))
    result = read_entry(store, gc=gc, city_root=city_root, rig_name=rig_name,
        workflow_root_id=workflow_root_id, claimed_step_id=attempt.claimed_bead_id,
        worktree_lifecycle=worktree_lifecycle, generation=generation, require_plan=require_plan)
    result["receipt"] = captured["receipt"]
    result["allocation_journal"] = allocated["allocation_journal"]
    return result


def read_entry_mode(store, *, workflow_root_id: str, claimed_step_id: str,
                    worktree_lifecycle: str | None = None, recorded_root_id: str | None = None):
    """Read the retained run or explicit cooked mode before source effects."""
    observed = store.snapshot(list(dict.fromkeys([workflow_root_id, claimed_step_id])))
    root = observed[workflow_root_id]
    step = observed[claimed_step_id]
    healthy(root)
    healthy(step)
    physical_root_id = native_root(step)
    require(isinstance(physical_root_id, str) and bool(physical_root_id), "claimed entry step has no native workflow")
    physical_root = root if physical_root_id == workflow_root_id else store.snapshot([physical_root_id])[physical_root_id]
    healthy(physical_root)
    metadata = physical_root["metadata"]
    require(root["metadata"].get("gc.kind") == "workflow" and root["metadata"].get("gc.root_store_ref") == store.store_ref
            and metadata.get("gc.kind") == "workflow" and metadata.get("gc.root_store_ref") == store.store_ref
            and (physical_root_id == workflow_root_id or _continuation_candidate(store, physical_root, workflow_root_id, recorded_root_id))
            and step["metadata"].get("gc.root_store_ref") == store.store_ref
            and step["status"] == "in_progress" and bool(step["assignee"]),
            "lifecycle selection requires the exact native workflow, store and claimed step")
    mode = metadata.get("gc.var.worktree_lifecycle")
    from workspace_suffix import read as read_suffix
    suffix = (read_suffix(store, claimed_step_id=claimed_step_id, requested_root_id=workflow_root_id,
                         recorded_root_id=recorded_root_id)
              if _continuation_candidate(store, physical_root, workflow_root_id, recorded_root_id) else None)
    if suffix is not None:
        continuation, inherited_rows = suffix
        retained = parse_record(inherited_rows[continuation.binding["run_ref"]["bead_id"]]["metadata"][contracts()["run"]["metadata_key"]])
        mode = retained["worktree_lifecycle"] if mode is None else mode
        require(mode == retained["worktree_lifecycle"], "suffix mode conflicts with its immutable recorded run")
    elif metadata.get("gc.drain_control_id"):
        control = store.snapshot([metadata["gc.drain_control_id"]])[metadata["gc.drain_control_id"]]
        original_root_id = native_root(control)
        require(original_root_id and original_root_id != physical_root_id
                and workflow_root_id in (physical_root_id, original_root_id)
                and control["metadata"].get("gc.kind") == "drain"
                and control["metadata"].get("gc.root_store_ref") == store.store_ref,
                "native legacy or inherited child has no exact original root/store")
        original_root = store.snapshot([original_root_id])[original_root_id]
        require(original_root["metadata"].get("gc.kind") == "workflow"
                and original_root["metadata"].get("gc.root_store_ref") == store.store_ref,
                "native child original root/store changed")
        if RUN_REF in original_root["metadata"]:
            continuation, inherited_rows = read_native_continuation(store, claimed_step_id=claimed_step_id,
                requested_root_id=workflow_root_id, recorded_root_id=recorded_root_id)
            inherited = inherited_rows[continuation.binding["run_ref"]["bead_id"]]
            retained = parse_record(inherited["metadata"][contracts()["run"]["metadata_key"]])
            mode = retained["worktree_lifecycle"] if mode is None else mode
            require(retained["worktree_lifecycle"] == mode
                    and original_root["metadata"].get("gc.var.worktree_lifecycle", mode) == mode,
                    "native child mode conflicts with its immutable inherited run")
        else:
            original_mode = original_root["metadata"].get("gc.var.worktree_lifecycle")
            mode = original_mode if mode is None else mode
            require(mode == "legacy" and original_mode == "legacy"
                    and RUN_REF not in metadata,
                    "native child cannot bypass an original managed run or its required capture")
            retained = None
    elif RUN_REF in metadata:
        retained = _load(store, "run", reference(metadata[RUN_REF], "run"))
        mode = retained["worktree_lifecycle"] if mode is None else mode
        require(retained["workflow_root_id"] == workflow_root_id
                and retained["worktree_lifecycle"] == mode,
                "native workflow mode conflicts with its immutable recorded run")
    else:
        retained = None
    require(mode in ("legacy", "new"),
            "native workflow has no valid recorded worktree lifecycle; resume its original classified workflow or migrate explicitly")
    claimed_mode = step["metadata"].get("gc.lifecycle")
    require(claimed_mode is None or claimed_mode == mode,
            "claimed native lifecycle conflicts with the workflow mode")
    require(worktree_lifecycle is None or worktree_lifecycle == mode,
            "rendered lifecycle conflicts with the native workflow")
    return mode, retained


def gate_entry(store, attempt, *, gc: str, city_root: str, rig_name: str,
               workflow_root_id: str, entrypoint: str, generation: int = 1,
               worktree_lifecycle: str | None = None, **kwargs) -> dict[str, Any]:
    """Apply the mode recorded by native cooking at the real entry boundary."""
    mode, retained = read_entry_mode(store, workflow_root_id=workflow_root_id,
        claimed_step_id=attempt.claimed_bead_id, worktree_lifecycle=worktree_lifecycle,
        recorded_root_id=kwargs.get("recorded_root_id"))
    if retained is not None:
        from workspace_requests import require_resolved_scope
        rig_root = registered_rig(gc, canonical_path(city_root), rig_name, store.store_ref)
        common = repository_identity(rig_root)[1]
        require(common == retained["common_git_dir"], "recorded run lock repository changed")
        store.common_git_dir = common
        require_resolved_scope(store, run_scope(retained["workflow_root_id"]))
    if mode == "legacy":
        return {"state": "legacy", "workflow_root_id": workflow_root_id, "store_ref": store.store_ref}
    base = store.snapshot([workflow_root_id])[workflow_root_id]["metadata"].get("gc.var.worktree_base_ref", "@default")
    return prepare_entry(store, attempt, gc=gc, city_root=city_root, rig_name=rig_name,
        workflow_root_id=workflow_root_id, entrypoint=entrypoint, generation=generation,
        worktree_lifecycle=mode, base_ref=base, **kwargs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("gate", "prepare", "read", "allocate"))
    parser.add_argument("--gc", default="gc")
    parser.add_argument("--city-root", required=True)
    parser.add_argument("--store-ref", required=True)
    parser.add_argument("--rig", required=True)
    parser.add_argument("--workflow-root")
    parser.add_argument("--claimed-step")
    parser.add_argument("--entrypoint", choices=("build", "implement", "requirements", "plan", "decompose", "convoy", "review"), default="build")
    parser.add_argument("--recorded-root", help="Locate an original run; native input relationships must still prove its authority")
    parser.add_argument("--worktree-lifecycle", choices=("legacy", "new"))
    parser.add_argument("--base-ref", default="@default")
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--input-convoy-id")
    parser.add_argument("--run-record-id")
    parser.add_argument("--authority-id")
    parser.add_argument("--require-plan", action="store_true")
    parser.add_argument("--allow-pending-source", action="store_true")
    parser.add_argument("--expected-run-sha256")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--title", default="Workspace record")
    args = parser.parse_args(argv)
    try:
        from workspace_store import Attempt, WorkspaceStore
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city_root)
        if args.action == "allocate":
            require(args.run_record_id is not None,
                    "fresh native allocation requires an admitted workflow entry; allocate only verifies a known native ID")
            result = {"bead_id": allocate_placeholder(store, title=args.title, existing_id=args.run_record_id)}
        else:
            require(bool(args.workflow_root) and bool(args.claimed_step), "entry requires exact workflow root and claimed step")
            mode = args.worktree_lifecycle
            if args.action != "gate":
                mode, _ = read_entry_mode(store, workflow_root_id=args.workflow_root,
                    claimed_step_id=args.claimed_step, worktree_lifecycle=mode, recorded_root_id=args.recorded_root)
            kwargs = dict(gc=args.gc, city_root=args.city_root, rig_name=args.rig,
                workflow_root_id=args.workflow_root, worktree_lifecycle=mode,
                generation=args.generation, input_convoy_id=args.input_convoy_id, require_plan=args.require_plan,
                recorded_root_id=args.recorded_root)
            if args.action == "read":
                result = read_entry(store, claimed_step_id=args.claimed_step,
                    expected_run_sha256=args.expected_run_sha256, expected_plan_sha256=args.expected_plan_sha256, **kwargs)
            elif args.action == "gate":
                kwargs.pop("worktree_lifecycle")
                result = gate_entry(store, Attempt.from_env(args.claimed_step), entrypoint=args.entrypoint,
                    worktree_lifecycle=args.worktree_lifecycle, run_record_id=args.run_record_id,
                    authority_id=args.authority_id, allow_pending_source=args.allow_pending_source, **kwargs)
            else:
                result = prepare_entry(store, Attempt.from_env(args.claimed_step), entrypoint=args.entrypoint,
                    base_ref=args.base_ref, run_record_id=args.run_record_id, authority_id=args.authority_id,
                    allow_pending_source=args.allow_pending_source, **kwargs)
        print(json.dumps({key: value for key, value in result.items() if not key.startswith("_")}, sort_keys=True))
        return 0
    except (RecordError, RunError, OSError, ValueError) as exc:
        print(f"workspace entry: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
