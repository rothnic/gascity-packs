#!/usr/bin/env python3
"""Resolve accepted source predecessors and materialize ordered Git integration."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from workspace_records import RecordError, record_sha256, validate_record
from workspace_source_plan import source_order
from workspace_outputs import read_artifact, validate_accepted_result, verify_artifact


def _node(plan: dict[str, Any], owner_id: str) -> dict[str, Any]:
    for node in plan["nodes"]:
        if node["owner_id"] == owner_id:
            return node
    raise RecordError(f"owner is absent from the source plan: {owner_id}")


def _scope(record: dict[str, Any], plan: dict[str, Any], owner_id: str) -> None:
    for field in ("workflow_root_id", "generation", "source_plan_owner_id"):
        if record[field] != plan[field]:
            raise RecordError(f"accepted source has a foreign {field}")
    if record["workspace_owner_id"] != owner_id:
        raise RecordError("accepted source belongs to another workspace owner")


def _initial_input(plan, node, load_owner_output):
    predecessors = node["source_predecessor_owner_ids"]
    if not predecessors:
        return plan["base_oid"]
    output = load_owner_output(predecessors[0])
    if output is None:
        raise RecordError("initial source input has no declared predecessor output")
    validate_record("owner-output", output)
    _scope(output, plan, predecessors[0])
    return output["output_oid"]


def _accepted_member(plan, owner_id, member_id, load_member_result, qualify_native, acceptance_context,
                     store_ref, artifact_root):
    result = load_member_result(member_id)
    if result is None:
        raise RecordError(f"missing accepted member result: {member_id}")
    validate_record("member-result", result)
    _scope(result, plan, owner_id)
    if result["member_id"] != member_id or result["acceptance"]["status"] != "accepted":
        raise RecordError(f"member has no exact accepted result: {member_id}")
    acceptance = result["acceptance"]
    for artifact in acceptance["artifacts"]:
        verify_artifact(artifact, artifact_root)
    for check in acceptance["project_checks"]:
        verify_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, artifact_root)
    review = acceptance["independent_review"]
    verify_artifact({"path": review["report_path"], "sha256": review["report_sha256"]}, artifact_root)
    native = qualify_native(result)
    expected = {"verified": True, "workflow_root_id": result["workflow_root_id"], "generation": result["generation"],
                "workspace_owner_id": owner_id, "member_id": member_id, "store_ref": store_ref,
                "head_oid": result["output_oid"], "clean": True, "recorder_step_id": result["writer_step_id"],
                "reviewer_step_id": review["reviewer"]}
    if not isinstance(native, dict) or any(type(native.get(key)) is not type(value) or native.get(key) != value
                                          for key, value in expected.items()):
        raise RecordError("current native acceptance does not match the exact source result")
    for key in ("recorder_session_id", "recorder_attempt_id", "producer_step_id", "producer_session_id",
                "producer_attempt_id", "reviewer_session_id", "reviewer_attempt_id", "native_attempt_id"):
        if not isinstance(native.get(key), str) or not native[key].strip():
            raise RecordError(f"native acceptance requires the exact {key}")
    if native["producer_session_id"] == native["reviewer_session_id"]:
        raise RecordError("native source review requires an independent session")
    context = acceptance_context(result, native)
    if not isinstance(context, dict) or set(context) != {"binding", "required_checks", "work_dir"}:
        raise RecordError("source acceptance requires its frozen project policy and exact checkout")
    binding = context["binding"]
    scope = {key: result[key] for key in ("workflow_root_id", "generation", "source_plan_owner_id",
                                        "workspace_owner_id", "member_id", "input_oid", "output_oid")}
    scope.update(store_ref=store_ref, native_attempt_id=native["native_attempt_id"])
    if not isinstance(context["work_dir"], (str, Path)):
        raise RecordError("source acceptance requires an exact checkout path")
    work_dir = str(Path(context["work_dir"]).resolve(strict=True))
    if (not isinstance(binding, dict) or any(binding.get(key) != value for key, value in scope.items())
            or binding.get("work_dir") != work_dir or native.get("work_dir") != work_dir
            or binding.get("common_git_dir") != native.get("common_git_dir")
            or not isinstance(binding.get("common_git_dir"), str)):
        raise RecordError("source acceptance context differs from the native result binding")
    if "result_binding" in native:
        if native["result_binding"] != binding or not isinstance(binding.get("rig_root"), str):
            raise RecordError("native qualification and frozen consumer binding differ")
        historical = native.get("historical_checkpoint")
        if type(historical) is not bool:
            raise RecordError("native qualification lacks its checkpoint classification")
        current = native.get("current_head_oid")
        if (not isinstance(current, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", current)
                or _git_output(Path(work_dir), "rev-parse", "HEAD") != current):
            raise RecordError("current native checkout differs from its qualified checkpoint")
        _merge_ready(Path(work_dir), current)
        if _git(Path(work_dir), "merge-base", "--is-ancestor", result["output_oid"], current).returncode:
            raise RecordError("accepted checkpoint is absent from the current native checkout")
        if not historical and current != result["output_oid"]:
            raise RecordError("live producer HEAD differs from its accepted output")
        validate_accepted_result(result, plan=plan, store_ref=store_ref, repo_dir=binding["rig_root"],
            native_evidence=native, required_checks=context["required_checks"], artifact_root=artifact_root,
            work_dir=None if historical else work_dir)
        # Historical consumption retains the original input-to-output history;
        # later accepted shared checkpoints do not rewrite earlier evidence.
        if (_git(Path(work_dir), "merge-base", "--is-ancestor", result["input_oid"], result["output_oid"]).returncode
                or _git_output(Path(work_dir), "rev-list", "--reverse", result["input_oid"] + ".." + result["output_oid"]).splitlines()
                != result["commit_oids"]):
            raise RecordError("accepted checkpoint history differs from its recorded commits")
    else:
        if native.get("historical_checkpoint"):
            raise RecordError("historical consumption requires its independently resolved native result binding")
        validate_accepted_result(result, binding=binding, required_checks=context["required_checks"],
                                 artifact_root=artifact_root, work_dir=work_dir)
    manifest = read_artifact({"path": review["report_path"], "sha256": review["report_sha256"]}, artifact_root)
    for role in ("producer", "reviewer"):
        expected_identity = {key: native[role + "_" + key] for key in ("step_id", "session_id", "attempt_id")}
        if manifest.get(role) != expected_identity:
            raise RecordError(f"accepted {role} identity differs from the native evidence")
    return result


def resolve_member_input(plan: dict[str, Any], owner_id: str, member_id: str, *,
                         load_owner_output: Callable, load_member_result: Callable,
                         qualify_native: Callable, acceptance_context: Callable,
                         store_ref: str, artifact_root: Path) -> dict[str, Any]:
    """Resolve a member's exact input without provisioning or inferring scheduler edges.

    The required native qualifier must compare retained producer/reviewer attempts,
    actual store/root relationships, native workspace provenance and current HEAD.
    The caller retains and fences the referenced rows before any workspace effects.
    """
    source_order(plan)
    node = _node(plan, owner_id)
    if member_id not in node["member_ids"]:
        raise RecordError(f"member is absent from its source owner: {member_id}")
    position = node["member_ids"].index(member_id)
    bundle = {"workflow_root_id": plan["workflow_root_id"], "generation": plan["generation"],
              "source_plan_owner_id": plan["source_plan_owner_id"], "workspace_owner_id": owner_id,
              "member_id": member_id, "member_position": position, "strategy": node["strategy"],
              "store_ref": store_ref, "base_oid": plan["base_oid"], "input_oid": plan["base_oid"],
              "predecessors": []}
    if node["strategy"] == "shared-chain" and position:
        previous_id = node["member_ids"][position - 1]
        result = _accepted_member(plan, owner_id, previous_id, load_member_result, qualify_native,
                                  acceptance_context, store_ref, artifact_root)
        if position == 1:
            expected_input = _initial_input(plan, node, load_owner_output)
        else:
            earlier_id = node["member_ids"][position - 2]
            earlier = load_member_result(earlier_id)
            if earlier is None:
                raise RecordError("shared source chain is missing an earlier accepted checkpoint")
            validate_record("member-result", earlier)
            _scope(earlier, plan, owner_id)
            if earlier["member_id"] != earlier_id or earlier["acceptance"]["status"] != "accepted":
                raise RecordError("shared source chain has an unaccepted or foreign checkpoint")
            expected_input = earlier["output_oid"]
        if result["input_oid"] != expected_input:
            raise RecordError("shared member input differs from its declared source chain")
        bundle["input_oid"] = result["output_oid"]
        bundle["previous_member_result_sha256"] = record_sha256(result)
        return bundle
    for predecessor_id in node["source_predecessor_owner_ids"]:
        output = load_owner_output(predecessor_id)
        if output is None:
            raise RecordError(f"missing accepted owner output: {predecessor_id}")
        validate_record("owner-output", output)
        _scope(output, plan, predecessor_id)
        predecessor = _node(plan, predecessor_id)
        if output["strategy"] != predecessor["strategy"] or output["final_member_id"] != predecessor["member_ids"][-1]:
            raise RecordError("owner output must retain its strategy and final member")
        result = _accepted_member(plan, predecessor_id, output["final_member_id"], load_member_result,
                                  qualify_native, acceptance_context, store_ref, artifact_root)
        if (record_sha256(result) != output["final_member_result_sha256"]
                or result["output_oid"] != output["output_oid"] or result["writer_step_id"] != output["writer_step_id"]):
            raise RecordError("owner output differs from its exact final member result")
        if output["strategy"] != "shared-chain" and result["input_oid"] != output["input_oid"]:
            raise RecordError("owner input differs from its final member input")
        if output["strategy"] != "integration" and output["input_oid"] != _initial_input(plan, predecessor, load_owner_output):
            raise RecordError("owner input differs from its declared source predecessor or plan base")
        if output["strategy"] == "integration":
            declared = predecessor["source_predecessor_owner_ids"]
            if [entry["owner_id"] for entry in output["integration_inputs"]] != declared:
                raise RecordError("integration output changed its declared predecessor order")
            receipt = read_artifact({"path": output["integration_evidence_path"],
                                     "sha256": output["integration_evidence_sha256"]}, artifact_root)
            if (not isinstance(receipt, dict) or receipt.get("base_oid") != plan["base_oid"]
                    or receipt.get("output_oid") != output["input_oid"]
                    or receipt.get("integration_inputs") != output["integration_inputs"]):
                raise RecordError("integration receipt differs from the exact merged input")
            for source in output["integration_inputs"]:
                upstream = load_owner_output(source["owner_id"])
                if upstream is None:
                    raise RecordError("integration receipt has a missing predecessor output")
                validate_record("owner-output", upstream)
                _scope(upstream, plan, source["owner_id"])
                if (source["output_oid"] != upstream["output_oid"]
                        or source["workspace_output_sha256"] != record_sha256(upstream)):
                    raise RecordError("integration receipt changed an accepted predecessor")
        bundle["predecessors"].append({"owner_id": predecessor_id, "output_oid": output["output_oid"],
                                       "workspace_output_sha256": record_sha256(output),
                                       "member_result_sha256": record_sha256(result)})
    if len(bundle["predecessors"]) == 1:
        bundle["input_oid"] = bundle["predecessors"][0]["output_oid"]
    elif len(bundle["predecessors"]) > 1:
        bundle["input_oid"] = None
    return bundle


def _git(work_dir: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    # Inherited Git routing must not redirect reads or merges to another checkout.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_MERGE_AUTOEDIT="no")
    return subprocess.run(["git", "-C", str(work_dir), *args], env=env, text=True, capture_output=True, timeout=timeout)


def _git_output(work_dir: Path, *args: str) -> str:
    result = _git(work_dir, *args)
    if result.returncode:
        raise RecordError(f"Git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _merge_ready(work_dir: Path, expected_head: str) -> None:
    if _git_output(work_dir, "rev-parse", "HEAD") != expected_head:
        raise RecordError("integration HEAD changed before merge")
    if _git_output(work_dir, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RecordError("integration requires a clean checkout and index")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        path = Path(_git_output(work_dir, "rev-parse", "--git-path", marker))
        path = path if path.is_absolute() else work_dir / path
        if path.exists():
            raise RecordError("integration requires completed prior Git operations")


def materialize_integration(work_dir: Path, bundle: dict[str, Any], *, verify_native: Callable) -> dict[str, Any]:
    """Merge ordered accepted outputs in the caller's locked native workspace.

    Native provisioning and exclusive ownership precede this call. The verifier
    checks the current retained owner/attempt before each mutation. Failed merges
    retain their actual index, files and merge state for explicit recovery.
    The returned commit still requires project tests and independent review.
    """
    work_dir = Path(work_dir).resolve(strict=True)
    inputs = bundle.get("predecessors")
    if bundle.get("strategy") != "integration" or bundle.get("input_oid") is not None or not isinstance(inputs, list) or len(inputs) < 2:
        raise RecordError("integration requires multiple ordered accepted inputs")
    owners = [entry.get("owner_id") for entry in inputs]
    if any(not isinstance(owner, str) or not owner for owner in owners) or len(set(owners)) != len(owners):
        raise RecordError("integration requires distinct source owners")
    for oid in [bundle.get("base_oid"), *(entry.get("output_oid") for entry in inputs)]:
        if not isinstance(oid, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid):
            raise RecordError("integration requires exact full commit OIDs")
    head = _git_output(work_dir, "rev-parse", "HEAD")
    if head != bundle["base_oid"]:
        raise RecordError("integration HEAD differs from its declared base")
    for entry in inputs:
        if _git_output(work_dir, "rev-parse", "--verify", entry["output_oid"] + "^{commit}") != entry["output_oid"]:
            raise RecordError("accepted integration input is not an exact commit")
        if _git(work_dir, "merge-base", "--is-ancestor", bundle["base_oid"], entry["output_oid"]).returncode:
            raise RecordError("accepted integration input does not descend from the plan base")
    merges, native_attempt = [], None
    def verify(head_oid):
        nonlocal native_attempt
        native = verify_native(work_dir, bundle, head_oid)
        expected = {"verified": True, "clean": True, "workspace_owner_id": bundle["workspace_owner_id"],
                    "head_oid": head_oid, "base_oid": bundle["base_oid"], "store_ref": bundle["store_ref"],
                    "workflow_root_id": bundle["workflow_root_id"], "generation": bundle["generation"],
                    "member_id": bundle["member_id"]}
        if (not isinstance(native, dict) or any(type(native.get(key)) is not type(value) or native.get(key) != value
                                               for key, value in expected.items())
                or not isinstance(native.get("native_attempt_id"), str) or not native["native_attempt_id"]
                or native_attempt is not None and native["native_attempt_id"] != native_attempt):
            raise RecordError("native integration ownership or expected HEAD changed")
        native_attempt = native["native_attempt_id"]
    for entry in inputs:
        _merge_ready(work_dir, head)
        verify(head)
        result = _git(work_dir, "merge", "--no-ff", "--no-edit", "-m", "Integrate accepted source " + entry["owner_id"],
                      "--", entry["output_oid"])
        if result.returncode:
            raise RecordError(f"integration merge failed. Preserve conflict state for recovery: {result.stdout.strip()} {result.stderr.strip()}")
        next_head = _git_output(work_dir, "rev-parse", "HEAD")
        if next_head != head:
            merges.append(next_head)
        head = next_head
    _merge_ready(work_dir, head)
    verify(head)
    for entry in inputs:
        if _git(work_dir, "merge-base", "--is-ancestor", entry["output_oid"], head).returncode:
            raise RecordError("integration output is missing an accepted input")
    return {"base_oid": bundle["base_oid"], "output_oid": head, "merge_oids": merges,
            "integration_inputs": [{key: entry[key] for key in ("owner_id", "output_oid", "workspace_output_sha256")}
                                   for entry in inputs]}


def inspect_integrated_history(work_dir: Path, bundle: dict[str, Any], expected_head: str) -> dict[str, Any]:
    """Inspect completed ordered merges for an explicit recovery decision.

    This read-only check grants no native ownership or result acceptance. The
    caller separately qualifies the native owner, accepted sources and decision.
    """
    work_dir = Path(work_dir).resolve(strict=True)
    inputs = bundle.get("predecessors")
    if bundle.get("strategy") != "integration" or not isinstance(inputs, list) or len(inputs) < 2:
        raise RecordError("recovery requires multiple declared integration inputs")
    _merge_ready(work_dir, expected_head)
    if _git(work_dir, "merge-base", "--is-ancestor", bundle["base_oid"], expected_head).returncode:
        raise RecordError("recovered input no longer descends from the exact plan base")
    commits = _git_output(work_dir, "rev-list", "--first-parent", "--reverse",
                          bundle["base_oid"] + ".." + expected_head).splitlines()
    current, merges = bundle["base_oid"], []
    for source in inputs:
        oid = source["output_oid"]
        if (_git_output(work_dir, "rev-parse", "--verify", oid + "^{commit}") != oid
                or _git(work_dir, "merge-base", "--is-ancestor", bundle["base_oid"], oid).returncode):
            raise RecordError("recovery changed an accepted integration input")
        if _git(work_dir, "merge-base", "--is-ancestor", oid, current).returncode == 0:
            continue
        if len(merges) >= len(commits):
            raise RecordError("recovered input is missing a declared predecessor merge")
        commit = commits[len(merges)]
        if _git_output(work_dir, "rev-list", "--parents", "-n", "1", commit).split() != [commit, current, oid]:
            raise RecordError("recovered merge parents differ from the exact declared source order")
        current = commit
        merges.append(commit)
    if current != expected_head or len(merges) != len(commits):
        raise RecordError("recovered input contains undeclared commits or source order")
    return {"base_oid": bundle["base_oid"], "output_oid": current, "merge_oids": merges,
            "integration_inputs": [{key: entry[key] for key in ("owner_id", "output_oid", "workspace_output_sha256")}
                                   for entry in inputs]}
