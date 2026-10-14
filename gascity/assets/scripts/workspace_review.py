#!/usr/bin/env python3
"""Commit-bound canonical review and explicit parent-bound fix generations."""
from __future__ import annotations

import copy
from pathlib import Path

from workspace_records import record_sha256, validate_record
from workspace_outputs import (SCOPE_FIELDS, begin_review, check_evidence, check_scope, complete_review,
                               native_rows, prepare_record, read_artifact, referenced_record, require, snapshot,
                               terminal_node, validate_accepted_result, verify_artifact)


def canonical_subject(canonical: dict, result: dict, *, binding: dict, required_checks: list[dict],
                      artifact_root: Path | str, work_dir: Path | str) -> dict:
    validate_record("canonical", canonical)
    validate_accepted_result(result, binding=binding, required_checks=required_checks,
                             artifact_root=artifact_root, work_dir=work_dir)
    require(all(canonical[field] == binding[field] for field in SCOPE_FIELDS)
            and canonical["output_oid"] == result["output_oid"], "review subject differs from the canonical generation or OID")
    summary = {"path": canonical["summary_path"], "sha256": canonical["summary_sha256"]}
    verify_artifact(summary, artifact_root)
    require(summary in result["acceptance"]["artifacts"], "canonical summary was not independently accepted")
    return result


def begin_canonical_review(canonical: dict, result: dict, *, binding: dict, required_checks: list[dict],
                           artifact_root: Path | str, work_dir: Path | str, reviewer: dict,
                           review_mode: str = "report") -> dict:
    canonical_subject(canonical, result, binding=binding, required_checks=required_checks,
                       artifact_root=artifact_root, work_dir=work_dir)
    accepted = result["acceptance"]
    previous = read_artifact({"path": accepted["independent_review"]["report_path"],
                              "sha256": accepted["independent_review"]["report_sha256"]}, artifact_root)
    context = begin_review(binding, work_dir, accepted["project_checks"], required_checks, previous["producer"],
                            reviewer, accepted["artifacts"], artifact_root, review_mode=review_mode)
    return dict(context=context, canonical_sha256=record_sha256(canonical), result_sha256=record_sha256(result),
                reusable_review=copy.deepcopy(accepted["independent_review"]) if previous["reviewer"] == reviewer else None)


def finish_canonical_review(context: dict, canonical: dict, result: dict, *, writer_step_id: str, review_id: str,
                            artifact_root: Path | str, work_dir: Path | str, report: Path | str | None = None,
                            evidence_path: Path | str | None = None, status: str = "passed") -> dict:
    require(context["canonical_sha256"] == record_sha256(canonical) and context["result_sha256"] == record_sha256(result),
            "canonical source or acceptance changed during review")
    evidence = context["context"]
    canonical_subject(canonical, result, binding=evidence["binding"], required_checks=evidence["required_checks"],
                       artifact_root=artifact_root, work_dir=work_dir)
    after = snapshot(work_dir, evidence["binding"])
    require(after == evidence["before"], "source drifted during canonical review")
    if report is None:
        require(status == "passed" and context["reusable_review"] is not None,
                "new canonical reviewer requires an actually completed independent report")
        review = context["reusable_review"]
        read_artifact({"path": review["report_path"], "sha256": review["report_sha256"]}, artifact_root)
    else:
        require(evidence_path is not None, "completed canonical review requires an immutable evidence path")
        review = complete_review(evidence, work_dir, report, status, evidence_path, artifact_root)
    verdict = "approved" if status == "passed" else "changes_required" if status == "failed" else "blocked"
    payload = dict(version=1, **{field: canonical[field] for field in SCOPE_FIELDS[:3]},
                   writer_step_id=writer_step_id, review_id=review_id, reviewed_oid=canonical["output_oid"],
                   canonical_record_sha256=record_sha256(canonical), verdict=verdict,
                   report_path=review["report_path"], report_sha256=review["report_sha256"],
                   clean_before=evidence["before"]["clean"], clean_after=after["clean"])
    validate_record("review", payload)
    if verdict == "approved":
        validate_approval(payload, canonical, result, binding=evidence["binding"],
                           required_checks=evidence["required_checks"], artifact_root=artifact_root, work_dir=work_dir)
    return payload


def validate_approval(approval: dict, canonical: dict, result: dict, *, binding: dict,
                      required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str) -> dict:
    canonical_subject(canonical, result, binding=binding, required_checks=required_checks,
                       artifact_root=artifact_root, work_dir=work_dir)
    validate_record("review", approval)
    require(approval["verdict"] == "approved" and approval["reviewed_oid"] == canonical["output_oid"]
            and approval["canonical_record_sha256"] == record_sha256(canonical)
            and all(approval[field] == canonical[field] for field in SCOPE_FIELDS[:3])
            and approval["clean_before"] and approval["clean_after"], "approval is stale, blocked or bound to another commit")
    proof = read_artifact({"path": approval["report_path"], "sha256": approval["report_sha256"]}, artifact_root)
    producer = check_evidence(result["acceptance"]["project_checks"], binding, required_checks, artifact_root)[0]["producer"]
    require(proof.get("schema") == "gc.workspace.producer-review.v1" and proof.get("binding") == binding
            and proof.get("status") == "passed" and proof.get("required_scope_sha256") == check_scope(required_checks)
            and proof.get("required_checks") == required_checks and proof.get("checks") == result["acceptance"]["project_checks"]
            and proof.get("producer") == producer
            and proof.get("artifacts") == result["acceptance"]["artifacts"]
            and proof.get("before") == snapshot(work_dir, binding) == proof.get("after"),
            "approval report did not complete the exact canonical requirement scope")
    require(proof["producer"]["session_id"] != proof["reviewer"]["session_id"]
            and proof["producer"]["step_id"] != proof["reviewer"]["step_id"], "canonical review is not independent")
    verify_artifact(proof["report"], artifact_root)
    return approval


def validate_fix_parent(plan: dict, current: dict) -> dict:
    terminal_node(plan)
    validate_record("canonical", current)
    require(plan["workflow_root_id"] == current["workflow_root_id"] and plan["generation"] == current["generation"] + 1
            and plan["parent_canonical_generation"] == current["generation"]
            and plan["parent_canonical_oid"] == current["output_oid"] == plan["base_oid"],
            "fix generation cannot replace a newer canonical parent")
    return plan


def fix_plan(canonical: dict, findings: dict, previous_plan: dict, *, writer_step_id: str,
             source_plan_owner_id: str, nodes: list[dict], terminal_owner_id: str, max_iterations: int) -> dict:
    require(type(max_iterations) is int and max_iterations > 0, "fix limit must be a positive integer")
    require(canonical["generation"] <= max_iterations, "bounded fix attempts exhausted; retain the blocker and findings")
    validate_record("review", findings)
    require(findings["canonical_record_sha256"] == record_sha256(canonical)
            and findings["reviewed_oid"] == canonical["output_oid"]
            and all(findings[field] == canonical[field] == previous_plan[field] for field in SCOPE_FIELDS[:3]),
            "fix findings do not belong to the current canonical generation")
    plan = dict(version=1, workflow_root_id=canonical["workflow_root_id"], generation=canonical["generation"] + 1,
                writer_step_id=writer_step_id, source_plan_owner_id=source_plan_owner_id,
                base_oid=canonical["output_oid"], parent_canonical_generation=canonical["generation"],
                parent_canonical_oid=canonical["output_oid"], nodes=copy.deepcopy(nodes), terminal_owner_id=terminal_owner_id)
    return validate_fix_parent(plan, canonical)


def prepare_review_record(store, attempt, approval: dict, *, record_id: str, authority_id: str,
                          result_member_id: str, binding: dict, required_checks: list[dict],
                          artifact_root: Path | str, work_dir: Path | str, plan_owner_id: str,
                          qualify_native, writer_map, initial_write: bool = False, operation_nonce: str | None = None):
    canonical, _, canonical_guards = referenced_record(store, "canonical", approval["workflow_root_id"])
    result, _, result_guards = referenced_record(store, "member-result", result_member_id)
    plan, _, plan_guards = referenced_record(store, "source-plan", plan_owner_id)
    native = qualify_native(result)
    require(isinstance(native, dict) and native.get("result_binding") == binding, "review publication lacks current native qualification")
    validate_accepted_result(result, plan=plan, store_ref=store.store_ref, repo_dir=binding["rig_root"],
                             artifact_root=artifact_root, required_checks=required_checks, native_evidence=native)
    require(binding["store_ref"] == store.store_ref and binding["common_git_dir"] == str(store.common_git_dir),
            "review publication selected another store or repository")
    if approval["verdict"] == "approved":
        validate_approval(approval, canonical, result, binding=binding, required_checks=required_checks,
                           artifact_root=artifact_root, work_dir=work_dir)
        original = result["acceptance"]["independent_review"]
        if (approval["report_path"], approval["report_sha256"]) != (original["report_path"], original["report_sha256"]):
            proof = read_artifact({"path": approval["report_path"], "sha256": approval["report_sha256"]}, artifact_root)
            require(proof["reviewer"] == {"step_id": attempt.claimed_bead_id, "session_id": attempt.session_id,
                                          "attempt_id": attempt.writer_attempt_id},
                    "new canonical review must bind the actually admitted native reviewer attempt")
    else:
        require(approval["canonical_record_sha256"] == record_sha256(canonical), "findings target is no longer current")
        read_artifact({"path": approval["report_path"], "sha256": approval["report_sha256"]}, artifact_root)
    return prepare_record(store, attempt, approval, kind="review", record_id=record_id, authority_id=authority_id,
                          reference_owner_id=approval["workflow_root_id"], writer_map=writer_map, guards=[*canonical_guards, *result_guards, *plan_guards],
                          native_rows=native_rows(native, result), initial_write=initial_write, operation_nonce=operation_nonce)
