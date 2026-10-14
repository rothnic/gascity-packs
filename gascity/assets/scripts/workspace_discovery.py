#!/usr/bin/env python3
"""Check the declared workspace source inventory without running a workflow."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tomllib


SUPPORTED_PACKS = {"gascity", "compound-engineering", "superpowers", "bmad", "gstack"}
MANIFEST = Path("gascity/schemas/workspace/affected-surfaces.v1.json")
MIGRATION = "Coordinate the inventory classification, responsibility, content hash, owning steps and final source checkpoint. See gascity/schemas/workspace/discovery.md."


def formula_name(name):
    for suffix in (".formula.toml", ".toml", ".formula.json"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def walk_steps(steps):
    for step in steps:
        yield step
        yield from walk_steps(step.get("children", []))
        yield from walk_steps(step.get("loop", {}).get("body", []))


def source_asset(root, formula, raw_path, seen=()):
    """Resolve a supplied source pack's documented ../assets import fallback."""
    direct = (root / formula).parent / raw_path
    if direct.is_file():
        return direct.resolve().relative_to(root).as_posix()
    pack = Path(formula).parts[0]
    if not raw_path.startswith("../assets/") or pack in seen:
        raise ValueError(f"unresolved source asset {raw_path!r} from {formula}")
    definition = tomllib.loads((root / pack / "pack.toml").read_text())
    matches = set()
    for imported in definition.get("imports", {}).values():
        supplied = imported.get("source", "")
        if not supplied.startswith("."):
            continue
        location = (root / pack / supplied).resolve().relative_to(root)
        try:
            matches.add(source_asset(root, str(location / "formulas" / "source.formula.toml"),
                                     raw_path, (*seen, pack)))
        except (OSError, ValueError):
            continue
    if len(matches) != 1:
        raise ValueError(f"missing or ambiguous declared import asset {raw_path!r} from {formula}")
    return matches.pop()


def check_inventory(root: Path, manifest: dict, stage="a", layers=()):
    root = root.resolve(strict=True)
    report = {"ok": False, "stage": stage, "classifications": {}, "issues": [],
              "inspected_roots": [], "unresolved_inputs": [], "runtime_verified": False,
              "source_owner_count": len(manifest.get("source_owners", []))}

    def fail(path, reason, classification="unclassified"):
        report["issues"].append({"path": str(path), "classification": classification,
                                 "reason": reason, "migration": MIGRATION})

    if stage not in {"a", "b"}:
        fail(MANIFEST, "unknown discovery stage")
    if type(manifest.get("version")) is not int or manifest["version"] != 1:
        fail(MANIFEST, "unsupported inventory version")
    if (not isinstance(manifest.get("packs"), list) or len(manifest["packs"]) != len(SUPPORTED_PACKS)
            or set(manifest["packs"]) != SUPPORTED_PACKS):
        report["unresolved_inputs"].append("supported pack inventory")
        fail(MANIFEST, "inventory must retain all five supported packs")
        return report

    inventory = manifest["inventory"]
    helpers = manifest["source_helpers"]
    entries = dict(inventory)
    for path, row in helpers.items():
        relative = Path(path)
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path:
            fail(path, "helper path must be nonempty, canonical and repository-relative")
            continue
        if path in entries:
            fail(path, "duplicate inventory/helper entry")
        entries[path] = row
    if report["issues"]:
        return report
    discovered = set()
    for supplied, override in [(p, False) for p in manifest["packs"]] + [(p, True) for p in layers]:
        directory = Path(supplied)
        if not directory.is_absolute():
            directory = root / directory
        try:
            directory = directory.resolve(strict=True)
            relative = directory.relative_to(root).as_posix()
            if not directory.is_dir() or directory == root:
                raise ValueError("expected a scoped pack/layer directory")
        except (OSError, ValueError) as exc:
            report["unresolved_inputs"].append(str(supplied))
            fail(supplied, f"unresolved source root: {exc}")
            continue
        if relative not in report["inspected_roots"]:
            report["inspected_roots"].append(relative)
        formula_root = directory / "formulas"
        paths = {directory / Path(path).relative_to(Path(path).parts[0]) for path in helpers}
        # A description can use any suffix. Overrides can also replace checks.
        for subtree in (formula_root, directory / ("assets" if override else "assets/workflows")):
            paths.add(subtree)
            if not subtree.is_symlink():
                paths.update(subtree.rglob("*"))
        for path in sorted(paths):
            name = path.relative_to(root).as_posix()
            if path.is_symlink() and not path.is_file():
                report["unresolved_inputs"].append(name)
                fail(name, "uninspected symlink directory or dangling asset; supply an explicit source directory")
                continue
            if not path.is_file():
                continue
            if path.is_relative_to(formula_root) and not path.name.endswith((".toml", ".formula.json")):
                continue
            try:
                path.resolve(strict=True).relative_to(root)
            except (OSError, ValueError):
                fail(name, "asset resolves outside the supplied repository scope")
                continue
            discovered.add(name)

    for path in helpers:
        discovered.add(path)
    for path in sorted(discovered - entries.keys()):
        fail(path, "unclassified source or shadowing asset")
    counts = Counter({"legacy": 0, "new": 0, "reference": 0})
    for path, row in sorted(entries.items()):
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != path:
            fail(path, "inventory path must be canonical and repository-relative")
            continue
        classification = row.get("classification")
        if classification not in counts or not row.get("responsibility"):
            fail(path, "unclassified asset: declare legacy/new or a planning-only reference")
        else:
            counts[classification] += 1
        if path not in discovered:
            fail(path, "missing asset or asset outside inspected source roots")
            continue
        try:
            (root / path).resolve(strict=True).relative_to(root)
            actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            fail(path, f"missing or out-of-scope asset: {exc}")
            continue
        if actual != row.get("sha256"):
            fail(path, "changed content requires a coordinated migration declaration")
        if stage == "b" and classification == "legacy":
            fail(path, "Stage B requires completed migration and an explicit new declaration", "legacy")
    report["classifications"] = dict(counts)
    if report["issues"]:
        return report

    formulas = {}
    names = {}
    for path in sorted(discovered):
        if "/formulas/" not in path:
            continue
        data = (json.loads((root / path).read_text()) if path.endswith(".json")
                else tomllib.loads((root / path).read_text()))
        formulas[path] = data
        name = formula_name(Path(path).name)
        names.setdefault(name, []).append(path)

    resolved = {}

    def resolve_steps(path, chain=()):
        if path in chain:
            raise ValueError(f"circular inherited formula: {path}")
        if path in resolved:
            return resolved[path]
        data = formulas[path]
        result = {}
        for parent in data.get("extends", []):
            matches = names.get(formula_name(parent), [])
            if len(matches) != 1:
                if parent not in report["unresolved_inputs"]:
                    report["unresolved_inputs"].append(parent)
                raise ValueError(f"unresolved/ambiguous inherited formula {parent!r}; supply its exact source inventory")
            for step_id, value in resolve_steps(matches[0], chain + (path,)).items():
                if step_id in result:
                    raise ValueError(f"ambiguous parent step {step_id!r}; native composition review required")
                result[step_id] = value
        # Native child overrides replace the whole parent step by ID.
        for step in data.get("steps", []) + data.get("template", []):
            result[step["id"]] = (path, step)
        resolved[path] = result
        return result

    def effective_steps(path):
        return {step["id"]: (origin, step) for origin, top in resolve_steps(path).values()
                for step in walk_steps([top])}

    bindings = {}
    roles_by_path = {}
    for binding in manifest["owning_steps"]:
        formula, step_id, asset = (binding[key] for key in ("formula", "step_id", "asset"))
        key = (formula, step_id)
        if key in bindings:
            fail(formula, f"duplicate owning binding for {step_id}")
        bindings[key] = binding
        roles = binding.get("roles", [])
        for path in (formula, asset):
            roles_by_path.setdefault(path, set()).update(roles)
            if path not in inventory or inventory[path]["classification"] not in {"legacy", "new"}:
                fail(path, "owning assets require an explicit legacy/new classification")
        try:
            origin, step = effective_steps(formula)[step_id]
            actual = source_asset(root, origin, step["description_file"])
            if actual != asset or not roles:
                raise ValueError(f"{step_id} binds {actual}, expected {asset}")
        except (KeyError, OSError, ValueError) as exc:
            fail(formula, f"owning step binding changed: {exc}")
    for path, row in inventory.items():
        responsibility = set(row["responsibility"].split(","))
        if responsibility - {"reference", "inherited-contract"} - roles_by_path.get(path, set()):
            fail(path, "owning responsibility lacks a concrete step binding")

    contexts = set()
    delegated = set()
    for owner in manifest["source_owners"]:
        path, context = owner["formula"], owner["context"]
        if (path.split("/")[0], context) in contexts:
            fail(path, "duplicate source owner for this pack/context")
        contexts.add((path.split("/")[0], context))
        try:
            steps = effective_steps(path)
            writers = [step_id for step_id in steps if "source-writer" in bindings.get((path, step_id), {}).get("roles", [])]
            final = owner["final_source_step"]
            if (not writers or writers != owner["source_writer_steps"] or final != bindings.get((path, writers[-1]))
                    or owner["commit_contract"] not in {"explicit", "missing-explicit-commit"}
                    or not owner["checkpoint_requirement"] or not owner["delegators"] or not owner["inherited_entrypoints"]):
                fail(path, "final source commit/checkpoint binding differs from the ordered leaf writers")
            target = formula_name(Path(path).name)
            for delegator in owner["delegators"]:
                delegated.add((delegator["formula"], delegator["step_id"]))
                origin, step = effective_steps(delegator["formula"])[delegator["step_id"]]
                if formula_name(step.get("drain", {}).get("formula", "")) != target or step["drain"].get("context") != context:
                    fail(delegator["formula"], f"delegation binding changed for {delegator['step_id']}: expected {target}/{context}")
            for entrypoint in owner["inherited_entrypoints"]:
                if not any(formula_name(step.get("drain", {}).get("formula", "")) == target and step["drain"].get("context") == context
                           for _, step in effective_steps(entrypoint).values()):
                    fail(entrypoint, f"inherited delegation no longer reaches {target}/{context}")
        except (KeyError, ValueError) as exc:
            fail(path, f"source owner binding changed: {exc}")
    leaf_names = {formula_name(Path(owner["formula"]).name)
                  for owner in manifest["source_owners"]}
    for path, data in formulas.items():
        for step in walk_steps(data.get("steps", []) + data.get("template", [])):
            target = step.get("drain", {}).get("formula", "")
            if formula_name(target) in leaf_names and (path, step["id"]) not in delegated:
                fail(path, f"unclassified delegation to a source owner at {step['id']}: {target!r}")
    if contexts != {(pack, context) for pack in SUPPORTED_PACKS for context in ("separate", "shared")}:
        fail(MANIFEST, "source owner inventory must retain separate/shared leaves for all supported packs")
    report["ok"] = not report["issues"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3], help="Source repository root")
    parser.add_argument("--manifest", type=Path, help="Explicit version 1 inventory, otherwise the base pack inventory")
    parser.add_argument("--stage", choices=("a", "b"), default="a")
    parser.add_argument("--layer", action="append", default=[], help="Additional pack/override root inside --root, repeatable")
    args = parser.parse_args(argv)
    try:
        manifest_path = args.manifest or args.root / MANIFEST
        manifest = json.loads(manifest_path.read_text())
        report = check_inventory(args.root, manifest, args.stage, args.layer)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        report = {"ok": False, "stage": args.stage, "runtime_verified": False,
                  "inspected_roots": [], "unresolved_inputs": [str(args.manifest or MANIFEST)],
                  "issues": [{"path": str(args.manifest or MANIFEST), "classification": "unclassified",
                              "reason": f"invalid inventory/source input: {exc}", "migration": MIGRATION}]}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
