"""Recover retained native record allocations without repeating an unknown create."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from workspace_records import RecordError, canonical_bytes, parse_record, record_sha256
from workspace_store import Attempt, CookedWriterMap, StoreError, validate_cooked_writer_map


def require(condition, message):
    if not condition:
        raise StoreError(message)


def read_packet(path: Path) -> dict:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_nlink == 1 and not stat.S_IMODE(info.st_mode) & 0o077,
            "allocation journal has unknown ownership or permissions")
    raw = path.read_text()
    value = parse_record(raw)
    require(canonical_bytes(value).decode() == raw, "allocation journal is not canonical")
    return value


def writer_origin(attempt, writer_map) -> dict:
    require(isinstance(writer_map, CookedWriterMap), "allocation requires its native cooked writer map")
    return {"attempt": attempt.admission, "writer_map_sha256": writer_map.sha256}


def admit_writer(store, attempt, scope, writer_map, writer_rows, *, origin=None):
    """Prove the current occurrence without changing the original allocation owner."""
    require(isinstance(writer_map, CookedWriterMap) and isinstance(writer_rows, dict) and writer_rows,
            "allocation requires original native writer rows")
    from workspace_store import read_cooked_context
    require(canonical_bytes(read_cooked_context(store, list(writer_rows))) == canonical_bytes(writer_rows),
            "native allocation writer changed after admission")
    declaration = validate_cooked_writer_map(writer_map, writer_rows, store_ref=store.store_ref,
        workflow_root_id=scope["workflow_root_id"], record_kind=scope["record_kind"],
        claimed_step_id=attempt.claimed_bead_id)
    claim = writer_rows[attempt.claimed_bead_id]
    native = claim["metadata"]
    require(claim["status"] == "in_progress" and bool(claim["assignee"])
            and native.get("gc.session_id") == attempt.session_id,
            "allocation lacks the current native claimed session")
    stamp = native.get("gc.session_attempt_id")
    require(stamp is None or stamp == attempt.writer_attempt_id,
            "allocation belongs to a different source configuration or attempt: stale native claim")
    if origin is None:
        return
    require(isinstance(origin, dict) and set(origin) == {"attempt", "writer_map_sha256"}
            and origin["writer_map_sha256"] == writer_map.sha256,
            "retained allocation lacks its original cooked writer designation")
    old = origin["attempt"]
    require(isinstance(old, dict) and set(old) == {"session_id", "instance_token", "claimed_bead_id"},
            "retained allocation has no original native attempt")
    Attempt(**old)
    if old == attempt.admission:
        return
    require(stamp == attempt.writer_attempt_id,
            "allocation belongs to a different source configuration or attempt: replacement lacks its native stamp")
    if old["claimed_bead_id"] == attempt.claimed_bead_id:
        return
    require(scope["record_kind"] != "run", "initial run publication must retain its original physical writer")
    entries = {item["bead_id"]: item for item in declaration["steps"]}
    before = entries.get(old["claimed_bead_id"])
    after = entries[attempt.claimed_bead_id]
    require(before is not None and scope["record_kind"] in before["record_kinds"]
            and writer_rows[old["claimed_bead_id"]]["status"] == "closed",
            "allocation replacement requires its closed native predecessor")
    semantic = {}
    for item in declaration["steps"]:
        semantic.setdefault(item["step_id"], []).append(item)
    pending, seen = list(after["dependencies"]), set()
    while pending:
        step_id = pending.pop()
        if step_id in seen:
            continue
        seen.add(step_id)
        occurrences = semantic[step_id]
        if any(writer_rows[item["bead_id"]]["status"] != "closed" for item in occurrences):
            continue
        if step_id == before["step_id"]:
            return
        pending.extend(occurrences[0]["dependencies"])
    raise RecordError("allocation replacement lacks a closed declared native predecessor path")


def allocate_roles(store, packet, *, prefix, roles, allocate, native_read, admit):
    """Use one immutable receipt per role and read back an uncertain native create."""
    from workspace_outputs import immutable_json
    from workspace_requests import allocation_directory
    directory = allocation_directory(store)
    ids, rows = {}, {}
    rig = store.store_ref.split(":", 1)[1] if store.store_ref.startswith("rig:") else None
    for role, title, supplied in roles:
        admit()
        pending = directory / (prefix + "." + role + ".pending.json")
        receipt = directory / (prefix + "." + role + ".json")
        description = "Gas City workspace allocation " + hashlib.sha256(
            canonical_bytes({"intent": packet, "role": role})).hexdigest()
        expected = {"intent_sha256": record_sha256(packet), "role": role,
                    "title": title, "description": description}
        saved = None
        if receipt.exists():
            saved = read_packet(receipt)
            require(set(saved) == {*expected, "bead_id", "snapshot"}
                    and all(saved[key] == value for key, value in expected.items()),
                    "native allocation receipt conflicts with its original intent")
            require(supplied is None or supplied == saved["bead_id"], "supplied native allocation ID changed")
            supplied = saved["bead_id"]
        elif pending.exists():
            require(read_packet(pending) == expected, "native allocation pending intent changed")
            if supplied is None:
                try:
                    found = native_read(store.gc, store.cwd,
                        ["bd", "list", "--all", "--desc-contains", description,
                         "--limit", "2", "--json", "--readonly"], rig,
                        unwrap_singleton=True, require_array=True)
                    require(isinstance(found, dict) and found.get("title") == title and found.get("description") == description,
                            "native lookup does not match the original allocation intent")
                    supplied = found.get("id")
                    require(isinstance(supplied, str) and bool(supplied.strip()) and supplied == supplied.strip(),
                            "native lookup has no exact physical ID")
                except (RecordError, OSError) as exc:
                    raise RecordError("native allocation is uncertain with no known physical ID; "
                                      "resolve its original creation: " + str(pending)) from exc
        immutable_json(pending, expected)
        admit()
        try:
            bead_id = allocate(store, title=title, existing_id=supplied,
                               allocation_description=description, verified_rows=rows)
        except (RecordError, OSError) as exc:
            raise RecordError(f"native {role} allocation unresolved; retained intent {pending}: {exc}") from exc
        require(bead_id not in ids.values(), "record and authority must be distinct native allocations")
        if saved is not None:
            require(rows[bead_id] == saved["snapshot"], "native allocation changed since its original receipt")
            rows[bead_id] = saved["snapshot"]
        immutable_json(receipt, {**expected, "bead_id": bead_id, "snapshot": rows[bead_id]})
        ids[role] = bead_id
    admit()
    return ids, rows
