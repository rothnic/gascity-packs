"""Resolve record writers from native cooked steps, never from a role assertion."""
from __future__ import annotations

import hashlib
import copy
import json
import os
from pathlib import Path
import re
import subprocess

from workspace_records import RecordError, canonical_bytes
from workspace_attempts import discover_attempts
from workspace_run import native_json
from workspace_store import (CookedWriterMap, MAX_COOKED_CONTEXT_ROWS, TOPOLOGY,
                             _dependencies, _formula_identity, _kinds, _root,
                             read_cooked_context, require, validate_cooked_writer_map)


_VARIABLE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _metadata(step, variables):
    # Native formula show substitutes prose, but leaves metadata templates raw.
    metadata = step.get("metadata")
    metadata = {} if metadata is None else metadata
    require(isinstance(metadata, dict) and all(isinstance(key, str) and isinstance(value, str)
            for key, value in metadata.items()), "compiled native metadata is malformed")
    resolved = {key: _VARIABLE.sub(lambda match: variables.get(match[1], match[0]), value)
                for key, value in metadata.items()}
    require(not any(_VARIABLE.search(value) for value in resolved.values()),
            "compiled native metadata has unresolved variables")
    return resolved


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
                "--all", "--include-infra", "--include-gates", "--limit", str(MAX_COOKED_CONTEXT_ROWS + 1), "--json"]
    environment = {key: value for key, value in os.environ.items() if key not in ROUTING_ENV}
    result = subprocess.run(command, cwd=store.cwd, env=environment, capture_output=True,
                            text=True, encoding="utf-8", errors="strict", timeout=30)
    require(result.returncode == 0, "native bounded step listing failed")
    try:
        rows = json.loads(result.stdout)
    except ValueError as exc:
        raise RecordError("cooked writer admission: malformed native step listing") from exc
    require(isinstance(rows, list) and len(rows) <= MAX_COOKED_CONTEXT_ROWS
            and all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in rows)
            and len({row["id"] for row in rows}) == len(rows),
            "native step listing is malformed or exceeds the 4096-row cooked read bound")
    return [row["id"] for row in rows]


def read_cooked_writer_map(store, *, workflow_root_id, claimed_step_id, read_only=False,
                          continuation=None, continuation_rows=None):
    """Read an exact native occurrence; writing still requires its designated kind."""
    require(type(read_only) is bool, "read_only requires an explicit boolean")
    retained = copy.deepcopy(continuation_rows or {})
    require(isinstance(retained, dict) and (continuation is not None or not retained),
            "continuation rows require their typed native binding")

    def snapshot(ids):
        missing = [bead_id for bead_id in ids if bead_id not in retained]
        if missing:
            retained.update(read_cooked_context(store, missing))
        require(all(bead_id in retained and retained[bead_id].get("id") == bead_id for bead_id in ids),
                "native cooked readback has a different physical ID")
        return {bead_id: retained[bead_id] for bead_id in ids}

    claim = snapshot([claimed_step_id])[claimed_step_id]
    physical_root_id = workflow_root_id
    if continuation is not None:
        from workspace_store import NativeRunContinuation, validate_native_continuation
        require(isinstance(continuation, NativeRunContinuation), "typed native continuation is required")
        snapshot(continuation.row_ids)
        validate_native_continuation(continuation, retained, store_ref=store.store_ref,
            workflow_root_id=workflow_root_id, claimed_step_id=claimed_step_id)
        physical_root_id = continuation.binding["child_root_id"]
    require(_root(claim) == physical_root_id and claim["metadata"].get("gc.root_store_ref") == store.store_ref,
            "claimed step belongs to another root/store")
    expansion_id = claim["metadata"].get("gc.attach_root_id") or physical_root_id
    # Later native attachments point to a physical control, not a formula root.
    cursor, visited = claim, set()
    while True:
        pointer = cursor["metadata"].get("gc.control_for")
        if pointer and pointer == cursor["metadata"].get("gc.logical_bead_id"):
            require(pointer not in visited and len(visited) < MAX_COOKED_CONTEXT_ROWS,
                    "native attempt control ancestry is cyclic or oversized")
            visited.add(pointer)
            cursor = snapshot([pointer])[pointer]
            require(_root(cursor) == physical_root_id and cursor["metadata"].get("gc.root_store_ref") == store.store_ref,
                    "native attempt control belongs to another root/store")
            expansion_id = cursor["metadata"].get("gc.attach_root_id") or physical_root_id
        expansion = snapshot([expansion_id])[expansion_id]
        if expansion["metadata"].get("gc.formula_name"):
            break
        require(expansion is not cursor, "native attachment has no original formula expansion")
        cursor = expansion
    name, digest, source = _formula(expansion)
    key = "gc.attach_root_id" if expansion_id != physical_root_id else "gc.root_bead_id"
    ids = _native_list(store, key, expansion_id)
    ids = list(dict.fromkeys([expansion_id, claimed_step_id, *ids]))
    require(len(ids) <= MAX_COOKED_CONTEXT_ROWS, "cooked chain exceeds the 4096-row read bound")
    snapshot(ids)
    if visited or any(row["metadata"].get("gc.kind") in ("ralph", "retry")
                      and row["metadata"].get("gc.control_epoch", "1") != "1" for row in retained.values()):
        ids = list(dict.fromkeys([*ids, *_native_list(store, "gc.root_bead_id", physical_root_id)]))
        require(len(ids) <= MAX_COOKED_CONTEXT_ROWS, "cooked chain exceeds the 4096-row read bound")
        snapshot(ids)
    rows = retained
    rig = store.store_ref.split(":", 1)[1] if store.store_ref.startswith("rig:") else None
    arguments = ["formula", "show", name, "--json"]
    variables = {}
    for key, value in expansion["metadata"].items():
        if key.startswith("gc.var."):
            require(isinstance(value, str), "cooked formula variable is not a native string")
            variable = key.removeprefix("gc.var.")
            variables[variable] = value
            arguments += ["--var", variable + "=" + value]
    formula = native_json(store.gc, store.cwd, arguments, rig)
    require(formula.get("ok") is True and formula.get("name") == name and isinstance(formula.get("steps"), list),
            "native formula readback does not match the cooked expansion")
    definitions = formula.get("vars", [])
    require(isinstance(definitions, list), "compiled native variable definitions are malformed")
    names = set()
    for definition in definitions:
        require(isinstance(definition, dict) and isinstance(definition.get("name"), str)
                and definition["name"] and definition["name"] not in names,
                "compiled native variable definitions are ambiguous")
        names.add(definition["name"])
        if "default" in definition:
            require(isinstance(definition["default"], str), "compiled native variable default is not a string")
            variables.setdefault(definition["name"], definition["default"])
    compiled_ids = {step["id"]: step for step in formula["steps"] if isinstance(step, dict) and isinstance(step.get("id"), str)}
    require(len(compiled_ids) == len(formula["steps"]), "compiled native steps are ambiguous")
    compiled = {}
    for step in compiled_ids.values():
        metadata = _metadata(step, variables)
        metadata.setdefault("gc.step_id", step["id"])
        metadata.setdefault("gc.step_ref", step["id"])
        step = dict(step, metadata=metadata)
        compiled_ids[step["id"]] = step
        ref = metadata.get("gc.step_ref", step["id"])
        require(isinstance(ref, str) and ref.strip() and ref not in compiled,
                "compiled native step references are malformed or ambiguous")
        compiled[ref] = step
    semantic = {step_id: (step.get("metadata") or {}).get("gc.step_id", step_id)
                for step_id, step in compiled_ids.items()}
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
    dynamic, descriptors, owners = {}, [], {}
    if any(row["metadata"].get("gc.logical_bead_id") == row["metadata"].get("gc.control_for")
           and row["metadata"].get("gc.control_for") in rows for row in rows.values()):
        raw_formula = native_json(store.gc, store.cwd, ["formula", "show", name, "--json"], rig)
        require(raw_formula.get("ok") is True and raw_formula.get("name") == name
                and isinstance(raw_formula.get("steps"), list), "native raw formula source differs")
        def show_spec(bead_id):
            return native_json(store.gc, store.cwd, ["bd", "show", bead_id, "--json"], rig,
                               unwrap_singleton=True, require_array=True)
        dynamic, descriptors, owners = discover_attempts(compiled, compiled_dependencies, rows, expansion_id,
            raw_formula, variables, show_spec, store.snapshot)
    entries, physical_refs = [], set()
    default_member = continuation.binding["member_id"] if continuation is not None else workflow_root_id
    member = claim["metadata"].get("gc.source_anchor_id", claim["metadata"].get("gc.drain_member_id", default_member))
    require(claim["metadata"].get("gc.drain_member_id", member) == member, "claimed step has conflicting source membership")
    for bead_id, row in rows.items():
        if bead_id == expansion_id:
            continue
        metadata = row["metadata"]
        if expansion_id == physical_root_id and metadata.get("gc.attach_root_id") and bead_id not in owners:
            continue  # A sibling attached occurrence is never this expansion.
        if expansion_id != physical_root_id and (metadata.get("gc.attach_root_id") or physical_root_id) != expansion_id and bead_id not in owners:
            continue
        if bead_id not in ids or not any(key in metadata for key in ("gc.step_ref", "gc.step_id", TOPOLOGY)):
            continue  # Ordinary source work belongs to the root, not its cooked chain.
        ref = metadata.get("gc.step_ref")
        require(isinstance(ref, str) and (ref in compiled or ref in dynamic) and ref not in physical_refs,
                "missing or duplicate physical occurrence for a compiled native step")
        physical_refs.add(ref)
        cooked = dynamic[ref]["metadata"] if ref in dynamic else compiled[ref]["metadata"]
        require(metadata.get("gc.step_id") == cooked["gc.step_id"],
                "semantic step differs from the cooked source")
        for fact in ("gc.kind", "gc.control_for", "gc.build.artifact_schema", "gc.build.plan_review_required", "gc.lifecycle", "gc.run_target",
                     "gc.scope_role", "gc.scope_ref", "gc.ralph_step_id", "gc.attempt", "gc.on_fail"):
            require(metadata.get(fact) == cooked.get(fact), "native writer designation differs from the cooked source")
        expected_dependencies = dynamic[ref]["dependencies"] if ref in dynamic else compiled_dependencies[metadata["gc.step_id"]]
        require(_dependencies(metadata) == sorted(expected_dependencies),
                "native dependency declaration differs from the cooked source")
        entries.append({"bead_id": bead_id, "step_id": metadata["gc.step_id"], "step_ref": ref,
                        "dependencies": _dependencies(metadata), "record_kinds": _kinds(metadata, ref)})
    require(any(item["bead_id"] == claimed_step_id for item in entries), "claimed writer has no exact cooked occurrence")
    if member not in rows:
        snapshot([member])
    require(len(rows) <= MAX_COOKED_CONTEXT_ROWS, "native context and cooked chain exceed the 4096-row read bound")
    declaration = {"version": 1, "workflow_root_id": workflow_root_id, "store_ref": store.store_ref,
        "source_member_id": member, "expansion_root_id": expansion_id, "formula_name": name,
        "formula_hash": digest, "formula_source": source, "steps": sorted(entries, key=lambda item: item["step_ref"])}
    writer_map = CookedWriterMap(canonical_bytes(declaration), continuation=continuation,
        lineage_bytes=canonical_bytes(dict(version=1, controls=descriptors)) if descriptors else None)
    kind = None if read_only else next(iter(_kinds(claim["metadata"], claim["metadata"].get("gc.step_ref", ""))), "")
    validate_cooked_writer_map(writer_map, rows, store_ref=store.store_ref,
        workflow_root_id=workflow_root_id, record_kind=kind,
        claimed_step_id=claimed_step_id, read_only=read_only)
    return writer_map, rows
