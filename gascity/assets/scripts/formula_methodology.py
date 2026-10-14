#!/usr/bin/env python3
"""Read compact methodology declarations from the selected native formula."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from workspace_records import RecordError
from workspace_run import native_json, require


VOCABULARY = {
    "allowed_drain_policies": {"separate", "same-session"},
    "implementation_strategy": {"drain", "convoy-step"},
    "interaction_modes": {"interactive", "autonomous", "headless"},
    "review_modes": {"report", "agent", "interactive"},
}


def read_methodology(gc: str, city_root: str, formula: str, rig: str | None = None) -> dict[str, Any]:
    require(bool(formula) and formula == formula.strip() and not formula.startswith("-"),
            "formula name must be explicit")
    recipe = native_json(gc, city_root, ["formula", "show", formula, "--json"], rig)
    require(recipe.get("schema_version") == "1" and recipe.get("ok") is True
            and recipe.get("name") == formula, "native formula readback does not match the requested formula")
    result = {"name": formula, "declared": False}
    metadata = recipe
    for key in ("metadata", "gc", "methodology"):
        if key not in metadata:
            return result
        metadata = metadata[key]
        require(isinstance(metadata, dict), "declared methodology metadata must be an object")
    policy = {}
    for field, allowed in VOCABULARY.items():
        value = metadata.get(field)
        if field == "implementation_strategy":
            require(isinstance(value, str) and value in allowed, "invalid methodology " + field)
        else:
            require(isinstance(value, list) and all(isinstance(item, str) and item in allowed for item in value),
                    "invalid methodology " + field)
            value = list(dict.fromkeys(value))
        policy[field] = value
    return dict(result, declared=True, methodology=policy)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--formula", required=True)
    parser.add_argument("--gc", default="gc")
    parser.add_argument("--city-root", required=True)
    parser.add_argument("--rig")
    args = parser.parse_args(argv)
    try:
        result = read_methodology(args.gc, args.city_root, args.formula, args.rig)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (RecordError, OSError, UnicodeError) as exc:
        print(f"UNREADABLE methodology: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
