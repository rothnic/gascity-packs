#!/usr/bin/env python3
"""Bind a passing plan review to the current plan and its upstream files."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import validate_build_artifact as build
import validate_verdict_report as verdict


REQUIRED_KEY = "gc.build.plan_review_required"
PLAN_KEYS = ("gc.build.plan_path", "gc.var.plan_path")
REPORT_KEYS = ("gc.build.plan_review_report_path", "gc.var.plan_review_path")
REQUIREMENTS_KEYS = ("gc.build.requirements_path", "gc.var.requirements_path")
ROOT_KEYS = ("workflow_id", "molecule_id", "gc.root_bead_id")


class ReviewError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def artifact_path(value: str, root: Path) -> Path:
    require(isinstance(value, str) and bool(value.strip()), "artifact path is missing")
    path = Path(value)
    require(path.is_absolute() or ".." not in path.parts, "artifact path escapes its durable root")
    path = (path if path.is_absolute() else root / path).resolve(strict=True)
    require(path.is_file(), f"artifact is not a file: {path}")
    return path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def current_subject(plan_path: Path, *, workflow_root_id: str, artifact_root: Path,
                    required_upstream: tuple[str, ...] = ()) -> dict[str, Any]:
    """Read a subject; this does not approve it or write an artifact."""
    require(bool(workflow_root_id), "native workflow root is required")
    plan_path = artifact_path(str(plan_path), artifact_root)
    raw = plan_path.read_bytes()
    plan = build.validate_artifact_text(raw.decode("utf-8"), expected_schema="gc.build.plan.v1")
    require(plan.front_matter["workflow"]["id"] == workflow_root_id, "plan belongs to another workflow")
    require(plan.front_matter["status"] == "approved", "current plan is not approved")
    upstream = []
    seen = set()
    for entry in plan.upstream:
        path = artifact_path(entry["path"], artifact_root)
        require(path not in seen, "plan has duplicate upstream files")
        seen.add(path)
        content = path.read_bytes()
        declared = entry["hash"]
        scheme, value = declared.split(":", 1)
        if scheme == "sha256":
            require(value == digest(content), f"plan upstream hash is stale: {path}")
        elif scheme == "git":
            require(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is not None,
                    "git upstream must name a full immutable commit")
            top = subprocess.run(["git", "--no-replace-objects", "-C", str(path.parent),
                                  "rev-parse", "--show-toplevel"], check=True,
                                 capture_output=True, text=True, timeout=15).stdout.strip()
            relative = path.relative_to(Path(top).resolve(strict=True))
            result = subprocess.run(["git", "--no-replace-objects", "-C", top,
                                     "cat-file", "blob", value + ":" + relative.as_posix()],
                                    check=True, capture_output=True, timeout=15)
            require(result.stdout == content, f"plan upstream differs from its Git revision: {path}")
        else:
            raise ReviewError(f"unsupported plan upstream hash scheme: {scheme}")
        upstream.append({"path": str(path), "sha256": digest(content), "declared_hash": declared})
    require(all(artifact_path(value, artifact_root) in seen for value in required_upstream),
            "plan omits a current native-recorded upstream artifact")
    return {"workflow_root_id": workflow_root_id,
            "plan": {"path": str(plan_path), "sha256": digest(raw)}, "upstream": upstream}


def validate_review(plan_path: Path, report_path: Path, *, workflow_root_id: str,
                    artifact_root: Path, required_upstream: tuple[str, ...] = ()) -> dict[str, Any]:
    report_path = artifact_path(str(report_path), artifact_root)
    text = report_path.read_text(encoding="utf-8")
    report = verdict.validate_report_text(text, expected_kind="review")
    require(report.verdict == "pass" and not report.findings,
            "plan review has unresolved findings; repair or retain a failing verdict")
    _, data, _ = build.parse_front_matter(text)
    subject = current_subject(plan_path, workflow_root_id=workflow_root_id,
                              artifact_root=artifact_root, required_upstream=required_upstream)
    require(data.get("subject") == subject,
            "plan review does not approve the exact current plan and upstream files")
    return subject


def review_claim(row: dict[str, Any], *, workflow_root_id: str, step: str) -> int:
    metadata = row.get("metadata", {})
    require(isinstance(row.get("id"), str) and bool(row["id"])
            and native_root(row) == workflow_root_id
            and row.get("issue_type") == "task"
            and metadata.get("gc.kind", "task") == "task"
            and metadata.get("gc.ralph_step_id") == "plan-review"
            and metadata.get("gc.step_id") == step,
            "repair claim is not this workflow's native plan-review child")
    attempt = metadata.get("gc.attempt")
    require(attempt in ("1", "2", "3"), "native plan-review attempt is malformed")
    return int(attempt)


def repair_subject(plan_path: Path, *, workflow_root_id: str, artifact_root: Path,
                   reviewer: dict[str, Any], required_upstream: tuple[str, ...] = ()) -> dict[str, Any]:
    """Identify repair inputs without asserting that the plan's trace is valid."""
    attempt = review_claim(reviewer, workflow_root_id=workflow_root_id, step="plan-review-verdict")
    plan_path = artifact_path(str(plan_path), artifact_root)
    raw = plan_path.read_bytes()
    schema, data, _ = build.parse_front_matter(raw.decode("utf-8"))
    require(schema == "gc.build.plan.v1" and isinstance(data.get("workflow"), dict)
            and data["workflow"].get("id") == workflow_root_id,
            "repair plan belongs to another schema or workflow")
    upstream = [artifact_path(value, artifact_root) for value in required_upstream]
    return {"workflow_root_id": workflow_root_id,
            "plan": {"path": str(plan_path), "sha256": digest(raw)},
            "required_upstream": [{"path": str(path), "sha256": digest(path.read_bytes())}
                                  for path in upstream],
            "reviewer": {"bead_id": reviewer["id"], "attempt": attempt}}


def validate_recorded_repair(root: dict[str, Any], author: dict[str, Any], *,
                             artifact_root: Path, report_sha256: str) -> dict[str, Any]:
    """Check current blocked feedback before a permitted author edit, not approval."""
    attempt = review_claim(author, workflow_root_id=root["id"], step="author-repair")
    require(author.get("status") == "in_progress" and attempt > 1,
            "repair requires a current claimed author on attempt two or three")
    report_path = artifact_path(recorded_path(root["metadata"], REPORT_KEYS), artifact_root)
    raw = report_path.read_bytes()
    require(re.fullmatch("[0-9a-f]{64}", report_sha256) is not None
            and digest(raw) == report_sha256, "current native repair report changed since it was read")
    text = raw.decode("utf-8")
    report = verdict.validate_report_text(text, expected_kind="review")
    require(report.verdict == "fail" and bool(report.findings), "repair needs real blocked findings")
    _, data, _ = build.parse_front_matter(text)
    subject = data.get("repair_subject")
    require(isinstance(subject, dict) and isinstance(subject.get("reviewer"), dict)
            and isinstance(subject["reviewer"].get("bead_id"), str)
            and bool(subject["reviewer"]["bead_id"])
            and type(subject["reviewer"].get("attempt")) is int,
            "blocked report has no native repair subject")
    reviewer = show(subject["reviewer"]["bead_id"])
    previous = review_claim(reviewer, workflow_root_id=root["id"], step="plan-review-verdict")
    require(reviewer.get("status") == "closed" and reviewer["metadata"].get("gc.outcome") == "fail"
            and previous == attempt - 1, "repair report is not the preceding closed failing native review")
    requirements = recorded_path(root["metadata"], REQUIREMENTS_KEYS, optional=True)
    current = repair_subject(Path(recorded_path(root["metadata"], PLAN_KEYS)),
        workflow_root_id=root["id"], artifact_root=artifact_root, reviewer=reviewer,
        required_upstream=(requirements,) if requirements else ())
    require(subject == current, "repair report subject is stale or foreign")
    return {"repair_subject": current, "report": {"path": str(report_path), "sha256": digest(raw)},
            "author_bead_id": author["id"], "author_attempt": attempt}


def recorded_path(metadata: dict[str, Any], keys: tuple[str, ...], *, optional: bool = False) -> str:
    value = next((metadata[key] for key in keys if metadata.get(key)), "")
    require(isinstance(value, str) and (bool(value) or optional),
            "native artifact path is missing: " + ", ".join(keys))
    return value


def validate_recorded_review(root: dict[str, Any], *, artifact_root: Path) -> dict[str, Any]:
    metadata = root.get("metadata")
    require(isinstance(metadata, dict) and isinstance(root.get("id"), str), "native workflow row is malformed")
    requirements = recorded_path(metadata, REQUIREMENTS_KEYS, optional=True)
    return validate_review(Path(recorded_path(metadata, PLAN_KEYS)),
                           Path(recorded_path(metadata, REPORT_KEYS)), workflow_root_id=root["id"],
                           artifact_root=artifact_root,
                           required_upstream=(requirements,) if requirements else ())


def review_required(rows: list[dict[str, Any]]) -> bool:
    flags = [row.get("metadata", {}).get(REQUIRED_KEY) for row in rows]
    require(all(value in (None, "true") for value in flags), "native plan-review requirement is malformed")
    return "true" in flags


def native_root(row: dict[str, Any]) -> str:
    metadata = row.get("metadata")
    require(isinstance(metadata, dict), "native step metadata is missing")
    root = next((metadata[key] for key in ROOT_KEYS if metadata.get(key)), None)
    require(isinstance(root, str) and bool(root), "native step has no workflow root")
    return root


def durable_root(environment: dict[str, str]) -> Path:
    value = next((environment[key] for key in ("GC_RIG_ROOT", "GC_BEADS_SCOPE_ROOT", "GC_DIR",
                  "GC_STORE_PATH", "GC_WORK_DIR") if environment.get(key)), "")
    root = Path(value)
    require(bool(value) and root.is_absolute() and root.is_dir(), "durable native artifact root is required")
    return root.resolve(strict=True)


def show(bead_id: str) -> dict[str, Any]:
    result = subprocess.run(["gc", "bd", "show", bead_id, "--json"], check=True,
                            capture_output=True, text=True, timeout=30)
    rows = json.loads(result.stdout)
    if isinstance(rows, list) and len(rows) == 1:
        rows = rows[0]
    require(isinstance(rows, dict) and rows.get("id") == bead_id, "native show returned another row")
    return rows


def check_creator_review(workspace: dict[str, Any] | None, *, bd_command: list[str]) -> None:
    """Recheck an authored review requirement before the first task allocation.

    Workspace callers pass already source-validated cooked rows. Legacy native
    callers use the same explicit city/rig route as their subsequent allocation.
    Unscoped legacy CLI use remains unchanged. Default and specialized
    authored requirements use the same current-subject acceptance boundary.
    """
    if workspace is not None:
        declared = workspace["writer_map"].declaration["steps"]
        rows = [workspace["writer_rows"][item["bead_id"]] for item in declared]
        if not review_required(rows):
            return
        claim = workspace["writer_rows"][workspace["attempt"].claimed_bead_id]
        root = workspace["writer_rows"][native_root(claim)]
        artifact_root = Path(workspace["state"]["run"]["rig_root"])
    else:
        bead_id = os.environ.get("GC_BEAD_ID")
        if not bead_id:
            return
        def read(args):
            result = subprocess.run([*bd_command, *args], capture_output=True, text=True,
                                    check=True, timeout=30)
            return json.loads(result.stdout)
        step = read(["show", bead_id, "--json"])
        if isinstance(step, list) and len(step) == 1:
            step = step[0]
        require(isinstance(step, dict) and step.get("id") == bead_id, "native claimed step changed")
        root_id = native_root(step)
        rows = read(["list", "--metadata-field", "gc.root_bead_id=" + root_id,
                     "--all", "--include-infra", "--include-gates", "--limit", "4097", "--json"])
        require(isinstance(rows, list) and len(rows) <= 4096
                and all(isinstance(row, dict) and native_root(row) == root_id for row in rows),
                "native review context is malformed or exceeds its bound")
        if not review_required(rows):
            return
        root = read(["show", root_id, "--json"])
        if isinstance(root, list) and len(root) == 1:
            root = root[0]
        require(isinstance(root, dict) and root.get("id") == root_id, "native workflow root changed")
        artifact_root = durable_root(os.environ)
    validate_recorded_review(root, artifact_root=artifact_root)


ERRORS = (ValueError, build.ValidationError, verdict.ValidationError, OSError, UnicodeError,
          subprocess.SubprocessError) + build.YAML_ERROR_TYPES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("subject", "check", "native-check",
                                        "native-repair-subject", "native-repair-check"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--workflow-root")
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--report-sha256")
    args = parser.parse_args(argv)
    try:
        if args.mode.startswith("native-"):
            bead_id = os.environ.get("GC_BEAD_ID", "")
            require(bool(bead_id), "GC_BEAD_ID is required")
            claim = show(bead_id)
            root = show(native_root(claim))
            require(isinstance(root.get("metadata"), dict), "native workflow metadata is missing")
            artifact_root = durable_root(os.environ)
            if args.mode == "native-repair-subject":
                require(claim.get("status") == "in_progress", "repair subject requires a claimed native reviewer")
                requirements = recorded_path(root["metadata"], REQUIREMENTS_KEYS, optional=True)
                subject = repair_subject(Path(recorded_path(root["metadata"], PLAN_KEYS)),
                    workflow_root_id=root["id"], artifact_root=artifact_root, reviewer=claim,
                    required_upstream=(requirements,) if requirements else ())
            elif args.mode == "native-repair-check":
                require(args.report_sha256 is not None, "--report-sha256 is required")
                subject = validate_recorded_repair(root, claim, artifact_root=artifact_root,
                                                   report_sha256=args.report_sha256)
            else:
                subject = validate_recorded_review(root, artifact_root=artifact_root)
        else:
            require(args.plan is not None and args.workflow_root and args.artifact_root is not None,
                    "--plan, --workflow-root and --artifact-root are required")
            if args.mode == "subject":
                subject = current_subject(args.plan, workflow_root_id=args.workflow_root,
                                          artifact_root=args.artifact_root)
            else:
                require(args.report is not None, "--report is required")
                subject = validate_review(args.plan, args.report, workflow_root_id=args.workflow_root,
                                          artifact_root=args.artifact_root)
        print(json.dumps(subject, sort_keys=True))
        return 0
    except ERRORS as exc:
        print(f"plan-review-check: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
