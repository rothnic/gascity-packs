#!/usr/bin/env python3
"""Order-project Git fixtures and behavioral oracles for workspace acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import workspace_records as records


PACK_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = PACK_ROOT / "gascity/tests/fixtures/workspace-acceptance"
CATALOG = PACK_ROOT / "gascity/schemas/workspace/scenario-coverage.v1.json"
STAGES = ("A", "B", "AB", "C", "D")
TOPOLOGIES = ("ordinary", "bare-root", "bare-control-root")


class FixtureError(ValueError):
    pass


def git(repo: Path, *arguments: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0", GIT_AUTHOR_NAME="Workspace fixture",
               GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="Workspace fixture",
               GIT_COMMITTER_EMAIL="fixture@example.invalid", GIT_AUTHOR_DATE="2020-01-01T00:00:00Z",
               GIT_COMMITTER_DATE="2020-01-01T00:00:00Z")
    run = subprocess.run(["git", "-C", str(repo), *arguments], env=env, capture_output=True,
                         text=True, timeout=30)
    if run.returncode:
        raise FixtureError(f"git {' '.join(arguments)} exited {run.returncode}: {run.stderr.strip()}")
    return run.stdout


def verify_requirements(fixture: Path = FIXTURE) -> dict:
    manifest = json.loads((fixture / "frozen-requirements.json").read_text())
    if manifest["version"] != 1 or set(manifest["files"]) != {"requirements.py", "requirements.json"}:
        raise FixtureError("unrecognized frozen requirement manifest")
    for name, digest in manifest["files"].items():
        if hashlib.sha256((fixture / name).read_bytes()).hexdigest() != digest:
            raise FixtureError(f"frozen requirement digest mismatch: {name}")
    return manifest


def full_oid(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", value):
        raise FixtureError("expected a full lowercase commit OID")
    return value


def check_project(project: Path, stage: str = "D", *, expected_oid: str | None = None,
                  reviewed_oid: str | None = None) -> dict:
    """Run frozen requirements at observed source; write no Git or lifecycle state."""
    if not project.is_absolute() or stage not in STAGES:
        raise FixtureError("check requires an absolute project path and known stage")
    for value in (expected_oid, reviewed_oid):
        if value is not None:
            full_oid(value)
    verify_requirements()
    head = git(project, "rev-parse", "HEAD").strip()
    before = git(project, "status", "--porcelain=v1")
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-B", "-I", str(FIXTURE / "requirements.py"),
               "--project", str(project), "--stage", stage]
    run = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
    try:
        observed = json.loads(run.stdout)
    except ValueError as exc:
        raise FixtureError(f"requirement oracle exited {run.returncode}: {run.stderr.strip()}") from exc
    if run.returncode != (0 if observed["status"] == "pass" else 1):
        raise FixtureError("requirement oracle status disagrees with its exit code")
    after_head = git(project, "rev-parse", "HEAD").strip()
    after = git(project, "status", "--porcelain=v1")
    verify_requirements()
    for name, expected in (("exact-input-oid", expected_oid), ("exact-reviewed-oid", reviewed_oid)):
        if expected is not None:
            expected = full_oid(expected)
            observed["checks"].append({"name": name, "expected": expected, "actual": head,
                                       "status": "pass" if head == expected else "fail"})
    if before or after or head != after_head:
        observed["checks"].append({"name": "clean-unchanged-source", "status": "fail",
                                   "before": before, "after": after, "head_after": after_head})
    observed.update(status="pass" if all(c["status"] == "pass" for c in observed["checks"]) else "fail",
                    subject_oid=head, head_after=after_head, clean_before=not before, clean_after=not after,
                    command=command, exit_code=run.returncode,
                    requirements_sha256=records.record_sha256(verify_requirements()))
    return observed


def seed(root: Path, topology: str = "ordinary") -> dict:
    """Create one fresh owned fixture; existing roots are never adopted or reset."""
    if not root.is_absolute() or topology not in TOPOLOGIES:
        raise FixtureError("seed requires an absolute new root and known Git topology")
    verify_requirements()
    try:
        root.mkdir()
    except FileExistsError as exc:
        raise FixtureError(f"fixture root already exists: {root}") from exc
    (root / "caller").mkdir()
    project = root / "seed"
    shutil.copytree(FIXTURE / "project", project)
    git(project, "init", "--initial-branch=main")
    git(project, "add", ".")
    git(project, "commit", "-m", "Seed order project before A/B/C/D")
    base = git(project, "rev-parse", "HEAD").strip()
    (project / "ambient.txt").write_text("The default branch moved after base capture.\n")
    git(project, "add", "ambient.txt")
    git(project, "commit", "-m", "Advance default branch independently")
    default = git(project, "rev-parse", "HEAD").strip()
    rig = project
    if topology != "ordinary":
        rig = root / ("rig.git" if topology == "bare-root" else "rig")
        destination = rig
        if topology == "bare-control-root":
            rig.mkdir()
            destination = rig / ".git"
        git(root / "caller", "clone", "--bare", str(project), str(destination))
    common = Path(git(rig, "rev-parse", "--git-common-dir").strip())
    common = common.resolve() if common.is_absolute() else (rig / common).resolve()
    return {"root": str(root), "rig_root": str(rig), "common_git_dir": str(common),
            "topology": topology, "is_bare_repository": git(rig, "rev-parse", "--is-bare-repository").strip(),
            "base_oid": base, "default_oid_after_capture": default}


def scenario_status(cases: list[dict]) -> str:
    if any(c["status"] not in ("pass", "fail", "skip", "unrun") for c in cases):
        raise FixtureError("unknown case status")
    if any(c["status"] == "fail" for c in cases):
        return "fail"
    required = [c for c in cases if c["required"]]
    if not required or any(c["status"] == "unrun" for c in required):
        return "unrun"
    if any(c["status"] == "skip" for c in required):
        return "skip"
    return "pass"


def exercise(root: Path, topology: str = "ordinary", core_oid: str | None = None) -> dict:
    """Exercise deterministic Git oracles; native product drivers remain unrun."""
    if core_oid is not None:
        full_oid(core_oid)
    state = seed(root, topology)
    rig = Path(state["rig_root"])
    cases = []
    inputs, outputs, workspaces = {}, {}, {}

    def workspace(name, oid):
        path = root / "workspaces" / name
        path.parent.mkdir(exist_ok=True)
        git(rig, "worktree", "add", "--detach", str(path), oid)
        if git(path, "rev-parse", "HEAD").strip() != oid:
            raise FixtureError("new fixture worktree did not start at its explicit OID")
        workspaces[name] = str(path)
        return path

    def contribution(path, member):
        for change in (FIXTURE / "changes" / member).iterdir():
            shutil.copyfile(change, path / change.name)
            git(path, "add", change.name)
        git(path, "commit", "-m", f"Contribution {member}")
        return git(path, "rev-parse", "HEAD").strip()

    def probe(scenario, name, observed, failures=(), **details):
        failed = {c["name"] for c in observed["checks"] if c["status"] == "fail"}
        passed = (observed["status"] == "fail" and set(failures) <= failed) if failures else observed["status"] == "pass"
        if name == "stale-review":
            passed = passed and observed["exit_code"] == 0 and failed == {"exact-reviewed-oid"}
        cases.append({"scenario": scenario, "name": name, "layer": "deterministic-git",
                      "required": False, "status": "pass" if passed else "fail",
                      "expected": "refuse" if failures else "pass", "expected_failures": list(failures),
                      "observed": observed, **details})

    for member in ("A", "B"):
        inputs[member] = state["base_oid"]
        path = workspace(member, inputs[member])
        outputs[member] = contribution(path, member)
        probe(5, f"isolated-{member}", check_project(path, member))
    integration = workspace("integration", state["base_oid"])
    for member in ("A", "B"):
        git(integration, "merge", "--no-ff", "--no-edit", outputs[member])
    outputs["integration"] = git(integration, "rev-parse", "HEAD").strip()
    ancestry = {member: git(integration, "merge-base", "--is-ancestor", outputs[member], "HEAD") == ""
                for member in ("A", "B")}
    probe(8, "ordered-A-B-integration", check_project(integration, "AB"))
    inputs["C"] = outputs["integration"]
    outputs["C"] = contribution(integration, "C")
    probe(6, "dependent-C", check_project(integration, "C"))
    unchanged = check_project(integration, "C")
    no_change_oid = git(integration, "rev-parse", "HEAD").strip()
    probe(7, "no-change-checkpoint", unchanged, input_oid=outputs["C"], output_oid=no_change_oid,
          commit_oids=git(integration, "rev-list", f"{outputs['C']}..{no_change_oid}").splitlines())
    inputs["D"] = outputs["C"]
    outputs["D"] = contribution(integration, "D")
    probe(7, "shared-D", check_project(integration, "D"))

    bypass = workspace("default-bypass", state["default_oid_after_capture"])
    probe(6, "default-branch-bypass", check_project(bypass, "AB", expected_oid=inputs["C"]),
          ("exact-input-oid", "A.quantity-subtotal", "B.domestic-shipping"))
    premature = workspace("premature", outputs["A"])
    probe(6, "premature-readiness", check_project(premature, "AB"),
          ("B.domestic-shipping", "B.international-shipping"))
    reverted = workspace("semantic-revert", outputs["D"])
    git(reverted, "revert", "--no-edit", outputs["B"])
    outputs["semantic-revert"] = git(reverted, "rev-parse", "HEAD").strip()
    prerequisite_ancestor = git(reverted, "merge-base", "--is-ancestor", outputs["B"], "HEAD") == ""
    probe(6, "ancestry-valid-semantic-revert", check_project(reverted, "D"),
          ("B.domestic-shipping", "C.domestic-quote", "D.domestic-receipt"),
          prerequisite_is_ancestor=prerequisite_ancestor)
    review = workspace("review", outputs["D"])
    probe(13, "exact-readonly-review", check_project(review, "D", reviewed_oid=outputs["D"]))
    fix = workspace("fix", outputs["D"])
    with (fix / "quote.py").open("a") as stream:
        stream.write("\n# Shipping remains part of the quote total.\n")
    git(fix, "add", "quote.py")
    git(fix, "commit", "-m", "Clarify quote implementation after review")
    outputs["fix"] = git(fix, "rev-parse", "HEAD").strip()
    probe(13, "stale-review", check_project(fix, "D", reviewed_oid=outputs["D"]),
          ("exact-reviewed-oid",), reviewed_oid=outputs["D"])

    run_record = {"version": 1, "workflow_root_id": "fixture-run", "generation": 1,
                  "writer_step_id": "capture-fixture", "input_convoy_id": "fixture-input",
                  "source_anchor_id": "fixture-source", "rig_root": state["rig_root"],
                  "common_git_dir": state["common_git_dir"], "base_oid": state["base_oid"],
                  "worktree_lifecycle": "new"}
    records.validate_record("run", run_record)
    records.verify_replay("run", run_record, dict(run_record))
    for scenario, name, record in (
        (2, "moving-default-conflicting-replay", {**run_record, "base_oid": state["default_oid_after_capture"]}),
        (23, "unknown-version-refusal", {**run_record, "version": 2}),
        (23, "missing-base-refusal", {key: value for key, value in run_record.items() if key != "base_oid"}),
    ):
        try:
            records.verify_replay("run", run_record, record)
            status, observed_status, reason = "fail", "pass", "record unexpectedly accepted"
        except records.RecordError as exc:
            status, observed_status, reason = "pass", "fail", str(exc)
        cases.append({"scenario": scenario, "name": name, "layer": "component", "required": False,
                      "status": status, "expected": "refuse", "observed": {"status": observed_status, "reason": reason}})

    catalog = records.parse_record(CATALOG.read_text())
    scenarios = []
    for scenario in catalog["scenarios"]:
        number = scenario["scenario"]
        local = [case for case in cases if case["scenario"] == number]
        driver = scenario["implementation_owner"]["component"] + "; " + scenario["oracle"]
        pending = [{"name": f"runtime-{number}", "layer": "native-controller"}]
        if number in (5, 6, 7, 8, 9):
            pending.append({"name": f"native-worker-{number}", "layer": "native-worker"})
        if number == 16:
            pending += [{"name": f"native-{path}", "layer": "native-worker"} for path in
                        ("separate", "dependent", "shared", "fanout-fanin", "review-fix", "publish", "restart")]
        if number == 19:
            pending = [{"name": name, "layer": "native-controller"} for name in
                       ("explicit-legacy-completes", "unclassified-asset-refuses")]
        if number == 20:
            pending = [{"name": name, "layer": "store-concurrency"} for name in
                       ("barrier-dedicated-record-race", "real-store-stress")]
        local += [{**case, "required": True, "status": "unrun", "needed_driver": driver} for case in pending]
        scenarios.append({"scenario": number, "name": scenario["name"], "oracle": scenario["oracle"],
                          "status": scenario_status(local), "cases": local})
    fixture_hash = records.record_sha256({str(path.relative_to(FIXTURE)): hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in sorted(FIXTURE.rglob("*")) if path.is_file()})
    return {"version": 1, "scope": "fixture-and-git-oracles", "git": {**state, "inputs": inputs,
            "outputs": outputs, "workspaces": workspaces, "integration_inputs": [outputs["A"], outputs["B"]],
            "integration_ancestry": ancestry}, "scenarios": scenarios,
            "fixture_checks_passed": all(case["status"] == "pass" for case in cases),
            "acceptance_passed": all(scenario["status"] == "pass" for scenario in scenarios),
            "pins": {"pack_oid": git(PACK_ROOT, "rev-parse", "HEAD").strip(),
                     "pack_dirty": bool(git(PACK_ROOT, "status", "--porcelain=v1")),
                     "fixture_sha256": fixture_hash, "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
                     "core_oid": core_oid, "core_pin_kind": "declared source only" if core_oid else "unrun",
                     "native_evidence": "unrun", "git_version": git(root, "--version").strip(),
                     "python_version": sys.version.split()[0]}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("seed", "exercise"):
        command = actions.add_parser(action)
        command.add_argument("--root", required=True, type=Path)
        command.add_argument("--topology", choices=TOPOLOGIES, default="ordinary")
        if action == "exercise":
            command.add_argument("--core-oid", help="Declared source pin, not native execution evidence")
            command.add_argument("--require-acceptance", action="store_true")
    command = actions.add_parser("check")
    command.add_argument("--project", required=True, type=Path)
    command.add_argument("--stage", choices=STAGES, default="D")
    command.add_argument("--expected-oid")
    command.add_argument("--reviewed-oid")
    args = parser.parse_args(argv)
    try:
        if args.action == "seed":
            result, passed = seed(args.root, args.topology), True
        elif args.action == "check":
            result = check_project(args.project, args.stage, expected_oid=args.expected_oid,
                                   reviewed_oid=args.reviewed_oid)
            passed = result["status"] == "pass"
        else:
            result = exercise(args.root, args.topology, args.core_oid)
            passed = result["acceptance_passed"] if args.require_acceptance else result["fixture_checks_passed"]
        print(records.canonical_bytes(result).decode())
        return 0 if passed else 1
    except (FixtureError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
