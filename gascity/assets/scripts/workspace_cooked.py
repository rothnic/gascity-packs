"""Resolve record writers from native cooked steps, never from a role assertion."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from workspace_records import RecordError, canonical_bytes
from workspace_run import native_json
from workspace_store import (CookedWriterMap, TOPOLOGY, _dependencies, _formula_identity, _kinds, _root,
                             require, validate_cooked_writer_map)


def _formula(root):
    name, digest, source = _formula_identity(root)
    path = Path(source)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(),
            "cooked formula source is unavailable or aliased")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == digest,
            "installed formula changed since cooking; retain its exact source before continuing")
    return name, digest, source


def _native_list(store, key, value):
    from workspace_store import ROUTING_ENV
    command = [store.gc, "--city", store.cwd]
    if store.store_ref.startswith("rig:"):
        command += ["--rig", store.store_ref.split(":", 1)[1]]
    command += ["bd", "list", "--metadata-field", key + "=" + value,
                "--all", "--include-infra", "--include-gates", "--limit", "101", "--json"]
    environment = {key: value for key, value in os.environ.items() if key not in ROUTING_ENV}
    result = subprocess.run(command, cwd=store.cwd, env=environment, capture_output=True,
                            text=True, encoding="utf-8", errors="strict", timeout=30)
    require(result.returncode == 0, "native bounded step listing failed")
    try:
        rows = json.loads(result.stdout)
    except ValueError as exc:
        raise RecordError("cooked writer admission: malformed native step listing") from exc
    require(isinstance(rows, list) and len(rows) < 101
            and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows),
            "native step listing is incomplete or exceeds the guarded operation bound")
    return [row["id"] for row in rows]


def read_cooked_writer_map(store, *, workflow_root_id, claimed_step_id, read_only=False):
    """Read an exact native occurrence; writing still requires its designated kind."""
    require(type(read_only) is bool, "read_only requires an explicit boolean")
    claim = store.snapshot([claimed_step_id])[claimed_step_id]
    require(_root(claim) == workflow_root_id and claim["metadata"].get("gc.root_store_ref") == store.store_ref,
            "claimed step belongs to another root/store")
    expansion_id = claim["metadata"].get("gc.attach_root_id") or workflow_root_id
    expansion = store.snapshot([expansion_id])[expansion_id]
    name, digest, source = _formula(expansion)
    key = "gc.attach_root_id" if expansion_id != workflow_root_id else "gc.root_bead_id"
    ids = _native_list(store, key, expansion_id)
    ids = list(dict.fromkeys([expansion_id, claimed_step_id, *ids]))
    require(len(ids) <= 98, "cooked chain exceeds the complete guarded row bound")
    rows = store.snapshot(ids)
    rig = store.store_ref.split(":", 1)[1] if store.store_ref.startswith("rig:") else None
    arguments = ["formula", "show", name, "--json"]
    for key, value in expansion["metadata"].items():
        if key.startswith("gc.var."):
            require(isinstance(value, str), "cooked formula variable is not a native string")
            arguments += ["--var", key.removeprefix("gc.var.") + "=" + value]
    formula = native_json(store.gc, store.cwd, arguments, rig)
    require(formula.get("ok") is True and formula.get("name") == name and isinstance(formula.get("steps"), list),
            "native formula readback does not match the cooked expansion")
    compiled = {step["id"]: step for step in formula["steps"] if isinstance(step, dict) and isinstance(step.get("id"), str)}
    require(len(compiled) == len(formula["steps"]), "compiled native steps are ambiguous")
    semantic = {ref: (step.get("metadata") or {}).get("gc.step_id", ref) for ref, step in compiled.items()}
    compiled_dependencies = {step_id: set() for step_id in semantic.values()}
    require(isinstance(formula.get("deps", []), list), "compiled native dependency readback is malformed")
    for edge in formula.get("deps", []):
        require(isinstance(edge, dict), "compiled native dependency is malformed")
        if edge.get("type") == "parent-child":
            continue
        require(edge.get("step_id") in semantic and edge.get("depends_on_id") in semantic,
                "compiled native dependency has no exact source occurrence")
        child, parent = semantic[edge["step_id"]], semantic[edge["depends_on_id"]]
        if child != parent:
            compiled_dependencies[child].add(parent)
    entries, physical_refs = [], set()
    member = claim["metadata"].get("gc.source_anchor_id", claim["metadata"].get("gc.drain_member_id", workflow_root_id))
    require(claim["metadata"].get("gc.drain_member_id", member) == member, "claimed step has conflicting source membership")
    for bead_id, row in rows.items():
        if bead_id == expansion_id:
            continue
        metadata = row["metadata"]
        if expansion_id == workflow_root_id and metadata.get("gc.attach_root_id"):
            continue  # A sibling attached occurrence is never this expansion.
        if not any(key in metadata for key in ("gc.step_ref", "gc.step_id", TOPOLOGY)):
            continue  # Ordinary source work belongs to the root, not its cooked chain.
        ref = metadata.get("gc.step_ref")
        require(isinstance(ref, str) and ref in compiled and ref not in physical_refs,
                "missing or duplicate physical occurrence for a compiled native step")
        physical_refs.add(ref)
        cooked = compiled[ref].get("metadata") or {}
        require(metadata.get("gc.step_id") == cooked.get("gc.step_id", ref), "semantic step differs from the cooked source")
        for fact in ("gc.kind", "gc.control_for", "gc.build.artifact_schema", "gc.lifecycle", "gc.run_target"):
            require(metadata.get(fact) == cooked.get(fact), "native writer designation differs from the cooked source")
        require(_dependencies(metadata) == sorted(compiled_dependencies[metadata["gc.step_id"]]),
                "native dependency declaration differs from the cooked source")
        entries.append({"bead_id": bead_id, "step_id": metadata["gc.step_id"], "step_ref": ref,
                        "dependencies": _dependencies(metadata), "record_kinds": _kinds(metadata, ref)})
    require(any(item["bead_id"] == claimed_step_id for item in entries), "claimed writer has no exact cooked occurrence")
    if member not in rows:
        rows.update(store.snapshot([member]))
    declaration = {"version": 1, "workflow_root_id": workflow_root_id, "store_ref": store.store_ref,
        "source_member_id": member, "expansion_root_id": expansion_id, "formula_name": name,
        "formula_hash": digest, "formula_source": source, "steps": sorted(entries, key=lambda item: item["step_ref"])}
    writer_map = CookedWriterMap(canonical_bytes(declaration))
    kind = None if read_only else next(iter(_kinds(claim["metadata"], claim["metadata"].get("gc.step_ref", ""))), "")
    validate_cooked_writer_map(writer_map, rows, store_ref=store.store_ref,
        workflow_root_id=workflow_root_id, record_kind=kind,
        claimed_step_id=claimed_step_id, read_only=read_only)
    return writer_map, rows
