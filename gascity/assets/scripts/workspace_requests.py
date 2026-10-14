#!/usr/bin/env python3
"""Retain exact native write intent and resolve its acknowledgement by readback."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from workspace_records import RecordError, canonical_bytes, parse_record
from workspace_store import PreparedWrite, _filesystem
import workspace_outputs as outputs


def _private_directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    outputs.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                    and not stat.S_IMODE(info.st_mode) & 0o077,
                    "workspace intent directory has unknown ownership or permissions")
    return path


def journal_directory(store):
    """One retained-intent root for the exact captured repository/city/store."""
    binding = parse_record(store._binding().decode())
    common = Path(binding["common_git_dir"])
    outputs.require(common.is_dir(), "workspace intent root requires the captured common Git directory")
    _filesystem(common)
    lock_root = _private_directory(common / "gc-workspace-locks")
    selected = {key: binding[key] for key in ("city_root", "store_ref")}
    return _private_directory(lock_root / ("intents-" + hashlib.sha256(canonical_bytes(selected)).hexdigest()))


def allocation_directory(store):
    return _private_directory(journal_directory(store) / "allocations")


def require_resolved_scope(store, scope):
    """Refuse allocation or a new effect while this exact scope is unresolved."""
    pending = journal_directory(store) / (hashlib.sha256(canonical_bytes(scope)).hexdigest() + ".pending")
    if pending.exists():
        raise RecordError("a native write is unresolved; resolve the original retained request: " + pending.read_text())


def retain_request(store, prepared):
    store._prepared(prepared)
    directory = journal_directory(store)
    packet = {key: getattr(prepared, key).decode() for key in
              ("request_bytes", "before_bytes", "after_bytes", "scope_bytes", "binding_bytes")}
    packet["replay"] = prepared.replay
    packet["request_sha256"] = prepared.sha256
    path = directory / (prepared.sha256 + ".json")
    outputs.immutable_json(path, packet)
    pending = directory / (hashlib.sha256(prepared.scope_bytes).hexdigest() + ".pending")
    try:
        fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RecordError("a native write is unresolved; resolve the original retained request: " + pending.read_text()) from exc
    with os.fdopen(fd, "w") as stream:
        stream.write(str(path))
        stream.flush()
        os.fsync(stream.fileno())
    return path, pending


def resolve_request(store, path):
    path = Path(path)
    outputs.require(path.is_absolute() and path.resolve(strict=True) == path, "retained request requires its canonical original path")
    info = path.lstat()
    outputs.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and info.st_nlink == 1 and not stat.S_IMODE(info.st_mode) & 0o077,
                    "retained request has unknown ownership or permissions")
    packet = parse_record(path.read_text())
    prepared = PreparedWrite(**{key: packet[key].encode() for key in
        ("request_bytes", "before_bytes", "after_bytes", "scope_bytes", "binding_bytes")}, replay=packet["replay"])
    outputs.require(prepared.sha256 == packet["request_sha256"], "retained native request hash changed")
    binding = parse_record(prepared.binding_bytes.decode())
    outputs.require(binding["city_root"] == store.cwd and binding["store_ref"] == store.store_ref,
                    "retained request belongs to another city/store")
    store.common_git_dir = binding["common_git_dir"]
    outputs.require(path.parent == journal_directory(store) and path.name == prepared.sha256 + ".json",
                    "retained request is outside the original repository/city/store intent root")
    receipt = store.resolve(prepared)
    if receipt.get("outcome") in ("committed", "replayed"):
        pending = Path(path).parent / (hashlib.sha256(prepared.scope_bytes).hexdigest() + ".pending")
        if pending.exists() and pending.read_text() == str(path):
            pending.unlink()
    return {key: value for key, value in receipt.items() if key != "rows"}
