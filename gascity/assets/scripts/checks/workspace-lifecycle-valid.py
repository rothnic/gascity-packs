#!/usr/bin/env python3
"""Read-only preflight check for a workflow's declared source lifecycle."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_records import RecordError, parse_record, verify_source_modes


def main() -> int:
    try:
        bead_id = os.environ.get("GC_BEAD_ID", "")
        if not bead_id:
            raise RecordError("GC_BEAD_ID is required")
        result = subprocess.run(["gc", "bd", "show", bead_id, "--json"], check=True,
                                capture_output=True, text=True, timeout=30)
        # Native show can return one object or a one-element list.
        payload = parse_record('{"beads":' + result.stdout + '}')["beads"]
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        if not isinstance(payload, dict) or payload.get("id") != bead_id:
            raise RecordError("show must return the exact check bead")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise RecordError("check metadata is required")
        mode = metadata.get("gc.lifecycle")
        source_modes = metadata.get("gc.lifecycle.source_modes")
        if not isinstance(source_modes, str):
            raise RecordError("source classifications are required")
        verify_source_modes(mode, parse_record(source_modes))
        print(json.dumps({"ok": True, "worktree_lifecycle": mode}, sort_keys=True))
        return 0
    except (RecordError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        print(f"workspace-lifecycle-check: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
