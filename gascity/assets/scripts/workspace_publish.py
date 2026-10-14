#!/usr/bin/env python3
"""Exact-OID publication intents, lease-safe Git effects and read-only reconciliation.

Provider queries and PR creation belong to the existing publication adapter.
This helper reserves one creation intent and consumes exact provider readbacks.
"""
from __future__ import annotations

import copy
from pathlib import Path
import re

from workspace_records import RecordError, record_sha256, validate_record
from workspace_outputs import (SCOPE_FIELDS, git, git_value, immutable_json, prepare_record,
                               native_rows, read_artifact, referenced_record, require, snapshot, validate_accepted_result)
from workspace_review import validate_approval


def pr_scope(spec: dict) -> dict:
    require(isinstance(spec, dict) and set(spec) == {"repo", "base", "actor", "mode", "marker"}
            and all(isinstance(value, str) and value.strip() for value in spec.values())
            and spec["mode"] in ("draft", "ready"), "PR authority requires exact repository, base, actor, mode and marker")
    return spec


def authority(intent: dict, binding: dict, artifact_root: Path | str, work_dir: Path | str) -> dict:
    auth = intent["authorization"]
    decision = read_artifact({"path": auth["decision_path"], "sha256": auth["decision_sha256"]}, artifact_root)
    require(decision.get("schema") == "gc.workspace.publication-authority.v1" and decision.get("binding") == binding
            and decision.get("canonical_sha256") == intent["canonical_record_sha256"]
            and decision.get("review_sha256") == intent["approved_review_sha256"]
            and decision.get("remote") == intent["remote"] and decision.get("ref") == intent["ref"]
            and type(auth["push"]) is bool and type(auth["open_pr"]) is bool
            and decision.get("push") is auth["push"] and decision.get("open_pr") is auth["open_pr"]
            and (auth["push"] or auth["open_pr"]), "publication lacks exact positive existing authority")
    require(isinstance(intent["remote"], str) and intent["remote"] and not intent["remote"].startswith("-")
            and not re.search(r"[\x00-\x20\x7f]", intent["remote"]), "remote must be one exact configured name")
    urls = git_value(work_dir, "remote", "get-url", "--push", "--all", intent["remote"]).splitlines()
    require(urls == [decision.get("remote_url")] and urls[0] and not urls[0].startswith("-")
            and not re.search(r"[\x00-\x1f\x7f]", urls[0]), "configured publication destination changed or is ambiguous")
    require(intent["ref"].startswith("refs/heads/") and git(work_dir, "check-ref-format", intent["ref"]).returncode == 0,
            "publication requires an explicit valid full branch ref")
    expected = decision.get("expected_remote_oid")
    require("expected_remote_oid" in decision and (expected is None or isinstance(expected, str)
            and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", expected)), "publication requires a frozen expected remote object")
    if auth["open_pr"]:
        pr_scope(decision.get("pr_spec"))
    return decision


def publication_intent(canonical: dict, approval: dict, result: dict, *, binding: dict, required_checks: list[dict],
                       artifact_root: Path | str, work_dir: Path | str, authorization: dict, remote: str,
                       ref: str, publish_id: str, writer_step_id: str) -> dict:
    validate_approval(approval, canonical, result, binding=binding, required_checks=required_checks,
                       artifact_root=artifact_root, work_dir=work_dir)
    intent = dict(version=1, **{field: canonical[field] for field in SCOPE_FIELDS[:3]}, writer_step_id=writer_step_id,
                  publish_id=publish_id, output_oid=canonical["output_oid"], canonical_record_sha256=record_sha256(canonical),
                  approved_review_sha256=record_sha256(approval), remote=remote, ref=ref,
                  authorization=copy.deepcopy(authorization), status="intended", observed_oid=None, pr_url=None)
    validate_record("publish", intent)
    authority(intent, binding, artifact_root, work_dir)
    return intent


def validate_intent(intent: dict, *, canonical: dict, approval: dict, result: dict, binding: dict,
                    required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str) -> dict:
    validate_record("publish", intent)
    validate_approval(approval, canonical, result, binding=binding, required_checks=required_checks,
                       artifact_root=artifact_root, work_dir=work_dir)
    require(intent["output_oid"] == canonical["output_oid"]
            and intent["canonical_record_sha256"] == record_sha256(canonical)
            and intent["approved_review_sha256"] == record_sha256(approval)
            and all(intent[field] == canonical[field] for field in SCOPE_FIELDS[:3]), "publication intent has stale approval or a different commit")
    return authority(intent, binding, artifact_root, work_dir)


def remote_oid(work_dir: Path | str, remote_url: str, ref: str) -> str | None:
    observation = git(work_dir, "ls-remote", "--refs", "--", remote_url, ref)
    require(observation.returncode == 0, "remote ref observation failed: " + observation.stderr.strip())
    lines = observation.stdout.strip().splitlines()
    if not lines:
        return None
    require(len(lines) == 1, "remote ref observation is ambiguous")
    parts = lines[0].split("\t")
    require(len(parts) == 2 and parts[1] == ref and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", parts[0]),
            "remote ref observation is malformed")
    return parts[0]


def reconcile_publication(intent: dict, *, remote_oid: str | None, pr_spec: dict | None = None,
                          prs: list[dict] | None = None) -> dict:
    """Unknown/divergent readback preserves the intent; no effect is retried."""
    validate_record("publish", intent)
    if remote_oid != intent["output_oid"]:
        return copy.deepcopy(intent)
    candidate = dict(intent, observed_oid=remote_oid)
    if intent["authorization"]["open_pr"]:
        if pr_spec is None or prs is None:
            return dict(candidate, status="uncertain")
        pr_scope(pr_spec)
        # A conflicting marker is ambiguous even when another observation fits.
        marked = [pr for pr in prs if pr.get("marker") == pr_spec["marker"]]
        exact = [pr for pr in marked if all(pr.get(key) == value for key, value in pr_spec.items())
                 and pr.get("head_oid") == intent["output_oid"] and isinstance(pr.get("url"), str)
                 and re.fullmatch(r"https://[^\s]+", pr["url"])]
        if len(marked) != 1 or len(exact) != 1:
            return dict(candidate, status="uncertain")
        candidate["pr_url"] = exact[0]["url"]
    candidate["status"] = "observed"
    return validate_record("publish", candidate)


def persist_observed(persist, value: dict) -> None:
    receipt = persist(value)
    require(isinstance(receipt, dict) and receipt.get("outcome") in ("committed", "replayed")
            and receipt.get("record_sha256") == record_sha256(value), "publication state has no exact committed native readback")


def push_publication(intent: dict, *, canonical: dict, approval: dict, result: dict, binding: dict,
                     required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str,
                     persist, current) -> dict:
    """Persist an uncertain effect before explicit OID:ref push; replay only reads."""
    decision = validate_intent(intent, canonical=canonical, approval=approval, result=result, binding=binding,
                                required_checks=required_checks, artifact_root=artifact_root, work_dir=work_dir)
    require(record_sha256(current()) == record_sha256(canonical), "canonical generation advanced before publication")
    if intent["status"] == "observed":
        require(remote_oid(work_dir, decision["remote_url"], intent["ref"]) == intent["output_oid"],
                "previously observed remote now differs; preserve a publication blocker")
        return copy.deepcopy(intent)
    def observe():
        try:
            return remote_oid(work_dir, decision["remote_url"], intent["ref"]), None
        except RecordError as exc:
            return None, str(exc)
    observed_remote, observation_error = observe()
    if observation_error is not None:
        uncertain = dict(intent, status="uncertain")
        if uncertain != intent:
            persist_observed(persist, uncertain)
        blocker = dict(schema="gc.workspace.publication-blocker.v1", binding=binding,
                       intent_sha256=record_sha256(intent), reason=observation_error, retry_allowed=False)
        immutable_json(Path(artifact_root) / ("publish-blocker-" + intent["publish_id"] + "-" + record_sha256(blocker) + ".json"), blocker)
        return uncertain
    if intent["status"] == "uncertain":
        observed = reconcile_publication(intent, remote_oid=observed_remote)
        if observed != intent:
            persist_observed(persist, observed)
        return observed
    if observed_remote == intent["output_oid"]:
        observed = reconcile_publication(intent, remote_oid=observed_remote)
        persist_observed(persist, observed)
        return observed
    require(intent["authorization"]["push"], "remote is not approved and push authority is absent")
    require(observed_remote == decision["expected_remote_oid"], "remote diverged from the frozen publication lease")
    uncertain = dict(intent, status="uncertain")
    persist_observed(persist, uncertain)
    require(record_sha256(current()) == record_sha256(canonical), "canonical generation advanced before the external effect")
    validate_intent(uncertain, canonical=canonical, approval=approval, result=result, binding=binding,
                    required_checks=required_checks, artifact_root=artifact_root, work_dir=work_dir)
    snapshot(work_dir, binding)
    expected = decision["expected_remote_oid"] or ""
    response_error = None
    try:
        response = git(work_dir, "push", "--porcelain", f"--force-with-lease={intent['ref']}:{expected}", "--",
                       decision["remote_url"], f"{intent['output_oid']}:{intent['ref']}")
        if response.returncode:
            response_error = dict(exit_code=response.returncode, stdout=response.stdout, stderr=response.stderr)
    except RecordError as exc:
        response_error = {"outcome": "unknown", "reason": str(exc)}
    # The command's response, including a lost/failed response, never supplies credit.
    readback_oid, readback_error = observe()
    observed = reconcile_publication(uncertain, remote_oid=readback_oid)
    observation = dict(schema="gc.workspace.publication-readback.v1", binding=binding,
                       intent_sha256=record_sha256(intent), status=observed["status"], observed_oid=observed["observed_oid"],
                       remote_oid=readback_oid, readback_error=readback_error,
                       command_response=response_error, retry_allowed=False)
    immutable_json(Path(artifact_root) / ("publish-" + intent["publish_id"] + "-" + record_sha256(observation) + ".json"), observation)
    if observed != uncertain:
        persist_observed(persist, observed)
    return observed


def reserve_pr_attempt(intent: dict, spec: dict, path: Path | str, *, canonical: dict, approval: dict,
                       result: dict, binding: dict, required_checks: list[dict], artifact_root: Path | str,
                       work_dir: Path | str, current) -> dict:
    """One atomic marker permits one caller effect; provider calls stay outside."""
    validate_record("publish", intent)
    decision = validate_intent(intent, canonical=canonical, approval=approval, result=result, binding=binding,
                                required_checks=required_checks, artifact_root=artifact_root, work_dir=work_dir)
    require(record_sha256(current()) == record_sha256(canonical), "canonical generation advanced before PR creation")
    pr_scope(spec)
    require(intent["authorization"]["open_pr"] and intent["observed_oid"] == intent["output_oid"],
            "PR creation requires positive authority and exact remote readback")
    require(remote_oid(work_dir, decision["remote_url"], intent["ref"]) == intent["output_oid"],
            "PR creation lacks current exact remote readback")
    auth = intent["authorization"]
    require(decision.get("schema") == "gc.workspace.publication-authority.v1"
            and decision.get("open_pr") is True and decision.get("pr_spec") == spec
            and decision.get("canonical_sha256") == intent["canonical_record_sha256"]
            and decision.get("review_sha256") == intent["approved_review_sha256"], "PR reservation has foreign or revoked authority")
    marker = dict(schema="gc.workspace.pr-create-intent.v1", workflow_root_id=intent["workflow_root_id"],
                  generation=intent["generation"], publish_id=intent["publish_id"], output_oid=intent["output_oid"],
                  canonical_sha256=intent["canonical_record_sha256"], review_sha256=intent["approved_review_sha256"],
                  authorization=auth, spec=spec)
    proof = immutable_json(path, marker, return_created=True)
    return {"create_allowed": proof.pop("created"), "retry_allowed": False, "intent": proof}


def prepare_publication_record(store, attempt, intent: dict, *, record_id: str, authority_id: str,
                               review_owner_id: str, result_member_id: str, binding: dict,
                               required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str,
                               plan_owner_id: str, qualify_native, writer_map, publication_readback=None,
                               initial_write: bool = False, operation_nonce: str | None = None):
    loaded = [referenced_record(store, kind, owner) for kind, owner in
              (("canonical", intent["workflow_root_id"]), ("review", review_owner_id), ("member-result", result_member_id))]
    canonical, approval, result = [entry[0] for entry in loaded]
    plan, _, plan_guards = referenced_record(store, "source-plan", plan_owner_id)
    native = qualify_native(result)
    require(isinstance(native, dict) and native.get("result_binding") == binding, "publication lacks current native qualification")
    validate_accepted_result(result, plan=plan, store_ref=store.store_ref, repo_dir=binding["rig_root"],
                             required_checks=required_checks, artifact_root=artifact_root, native_evidence=native)
    require(binding["store_ref"] == store.store_ref and binding["common_git_dir"] == str(store.common_git_dir),
            "publication selected another store or repository")
    decision = validate_intent(intent, canonical=canonical, approval=approval, result=result, binding=binding,
                               required_checks=required_checks, artifact_root=artifact_root, work_dir=work_dir)
    if intent["status"] == "observed":
        actual = remote_oid(work_dir, decision["remote_url"], intent["ref"])
        require(actual == intent["output_oid"], "publication completion lacks current exact Git readback")
        if intent["authorization"]["open_pr"]:
            require(callable(publication_readback), "PR completion requires actual provider readback")
            readback = publication_readback(intent)
            require(isinstance(readback, dict) and readback.get("pr_spec") == decision["pr_spec"]
                    and isinstance(readback.get("prs"), list), "PR readback scope differs from existing authority")
            observed = reconcile_publication(dict(intent, status="uncertain", pr_url=None), remote_oid=actual,
                                              pr_spec=readback["pr_spec"], prs=readback["prs"])
            require(observed == intent, "PR completion lacks an exact unambiguous provider readback")
    return prepare_record(store, attempt, intent, kind="publish", record_id=record_id, authority_id=authority_id,
                          reference_owner_id=intent["publish_id"], writer_map=writer_map,
                          guards=[*plan_guards, *(guard for _, _, collection in loaded for guard in collection)],
                          native_rows=native_rows(native, result), initial_write=initial_write, operation_nonce=operation_nonce)
