#!/usr/bin/env python3
"""Qualify exact producer commits and publish immutable workspace output records."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

from workspace_records import (RecordError, canonical_bytes, contracts, parse_record,
                               record_identity, record_sha256, validate_record, verify_replay)

STATUSES = {"passed", "failed", "skipped", "unrun", "setup_failure"}
OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
SCOPE_FIELDS = ("workflow_root_id", "generation", "source_plan_owner_id", "workspace_owner_id")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def git(work_dir: Path | str, *args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_MERGE_AUTOEDIT="no")
    try:
        return subprocess.run(["git", "-C", str(work_dir), *args], env=env, text=True,
                              capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecordError(f"Git observation unavailable: {exc}") from exc


def git_value(work_dir: Path | str, *args: str) -> str:
    result = git(work_dir, *args)
    require(result.returncode == 0, f"Git observation failed: {result.stderr.strip()}")
    return result.stdout.strip()


def snapshot(work_dir: Path | str, binding: dict, *, clean: bool = True, exact: bool = True) -> dict:
    work = Path(work_dir).resolve(strict=True)
    require(str(work) == binding["work_dir"], "checkout differs from the retained workspace path")
    require(git_value(work, "rev-parse", "--show-toplevel") == str(work), "path is not the Git worktree root")
    common = str(Path(git_value(work, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True))
    head = git_value(work, "rev-parse", "--verify", "HEAD^{commit}")
    require(common == binding["common_git_dir"], "checkout belongs to another repository")
    if exact:
        require(head == binding["output_oid"], "HEAD differs from the exact result OID")
    dirty = git_value(work, "status", "--porcelain=v1", "--untracked-files=all")
    admin = Path(git_value(work, "rev-parse", "--absolute-git-dir"))
    in_progress = any((admin / marker).exists() for marker in
                      ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-apply", "rebase-merge", "sequencer"))
    if clean:
        require(not dirty and not in_progress, "result requires a clean checkout, index and Git operation state")
    return {"work_dir": str(work), "common_git_dir": common, "head_oid": head, "clean": not dirty and not in_progress}


def result_binding(run: dict, plan: dict, workspace: dict, *, store_ref: str,
                   member_id: str, output_oid: str) -> dict:
    for kind, record in (("run", run), ("source-plan", plan), ("workspace", workspace)):
        validate_record(kind, record)
    require(run["worktree_lifecycle"] == "new", "qualified output requires an explicit new-mode run")
    require(run["workflow_root_id"] == plan["workflow_root_id"], "run and plan roots differ")
    for field in SCOPE_FIELDS[:3]:
        require(workspace[field] == plan[field], f"workspace has a foreign {field}")
    require(isinstance(store_ref, str) and re.fullmatch(r"(?:city|rig):[A-Za-z0-9][A-Za-z0-9._-]*", store_ref),
            "output requires an exact native store reference")
    nodes = [node for node in plan["nodes"] if node["owner_id"] == workspace["workspace_owner_id"]]
    require(len(nodes) == 1 and member_id in nodes[0]["member_ids"], "result target is absent from the source plan")
    require(nodes[0]["strategy"] == workspace["strategy"] and workspace["active_member_id"] == member_id,
            "result is outside the active workspace member")
    require(workspace["phase"] in ("active", "result"), "workspace is not at producer completion")
    provenance = workspace["native_provenance"]
    require(isinstance(provenance, dict) and provenance["store_ref"] == store_ref
            and provenance["repo_identity"] == run["common_git_dir"]
            and provenance["path"] == workspace["work_dir"]
            and provenance["owner"] == workspace["workspace_owner_id"]
            and provenance["generation"] == str(plan["generation"])
            and provenance["attempt_id"] == workspace["native_attempt_id"], "native result provenance changed")
    require(isinstance(output_oid, str) and OID.fullmatch(output_oid), "result requires a full immutable commit OID")
    return {**{field: workspace[field] for field in SCOPE_FIELDS}, "member_id": member_id,
            "store_ref": store_ref, "rig_root": run["rig_root"], "common_git_dir": run["common_git_dir"],
            "input_convoy_id": run["input_convoy_id"], "source_anchor_id": run["source_anchor_id"],
            "workspace_bead_id": workspace["workspace_bead_id"], "native_attempt_id": workspace["native_attempt_id"],
            "work_dir": workspace["work_dir"], "input_oid": workspace["input_oid"], "output_oid": output_oid}


def artifact(path: Path | str, artifact_root: Path | str) -> dict:
    source, root = Path(path), Path(artifact_root).resolve(strict=True)
    resolved = source.resolve(strict=True)
    require(source.is_absolute() and source == resolved and resolved.is_relative_to(root)
            and resolved.is_file(), "artifact must be a canonical file inside the admitted evidence root")
    return {"path": str(resolved), "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}


def verify_artifact(reference: dict, artifact_root: Path | str) -> dict:
    require(isinstance(reference, dict) and set(reference) == {"path", "sha256"}, "artifact reference is incomplete")
    require(artifact(reference["path"], artifact_root) == reference, "artifact hash changed")
    return reference


def read_artifact(reference: dict, artifact_root: Path | str) -> dict:
    verify_artifact(reference, artifact_root)
    data = Path(reference["path"]).read_bytes()
    require(hashlib.sha256(data).hexdigest() == reference["sha256"], "artifact changed while reading its proof bytes")
    return parse_record(data.decode("utf-8"))


def immutable_json(path: Path | str, value: dict, *, return_created: bool = False) -> dict:
    """Publish complete bytes without replacing an earlier receipt."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(path.is_absolute() and path.parent == path.parent.resolve(strict=True), "receipt path must be canonical")
    data = canonical_bytes(value)
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    created = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            created = True
        except FileExistsError:
            require(not path.is_symlink() and path.read_bytes() == data, "conflicting immutable receipt replay")
    finally:
        os.unlink(temporary)
    reference = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    return dict(reference, created=created) if return_created else reference


def identity(value: dict) -> dict:
    require(isinstance(value, dict) and set(value) == {"step_id", "session_id", "attempt_id"}
            and all(isinstance(item, str) and item.strip() for item in value.values()), "native evidence identity is incomplete")
    return value


def check_scope(required_checks: list[dict]) -> str:
    require(isinstance(required_checks, list) and bool(required_checks), "required project checks cannot be absent")
    seen = set()
    for check in required_checks:
        require(isinstance(check, dict) and set(check) == {"id", "argv"}
                and isinstance(check["id"], str) and check["id"] and check["id"] not in seen
                and isinstance(check["argv"], list) and check["argv"]
                and all(isinstance(arg, str) and arg and "\0" not in arg for arg in check["argv"]),
                "required check scope must contain unique IDs and explicit argv")
        seen.add(check["id"])
    return record_sha256({"required_checks": required_checks})


def execute_checks(binding: dict, work_dir: Path | str, required_checks: list[dict], producer: dict,
                   evidence_dir: Path | str, *, timeout: float = 60) -> list[dict]:
    """Run the declared commands, retaining actual exit, output and setup failures."""
    scope = check_scope(required_checks)
    identity(producer)
    require(0 < timeout <= 300, "project check timeout must be bounded")
    before = snapshot(work_dir, binding)
    references = []
    for position, check in enumerate(required_checks):
        snapshot(work_dir, binding)
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        try:
            executed = subprocess.run(check["argv"], cwd=work_dir, env=env, text=True, capture_output=True, timeout=timeout)
            code, stdout, stderr = executed.returncode, executed.stdout, executed.stderr
            status = "passed" if code == 0 else "failed"
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, stdout, stderr, status = None, "", str(exc), "setup_failure"
        after = snapshot(work_dir, binding, clean=False, exact=False)
        if after != before:
            status = "failed"
        evidence = dict(schema="gc.workspace.project-check.v1", binding=binding, required_scope_sha256=scope,
                        check_id=check["id"], argv=check["argv"], status=status, exit_code=code,
                        producer=producer, before=before, after=after, stdout=stdout, stderr=stderr)
        proof = immutable_json(Path(evidence_dir) / f"check-{position}.json", evidence)
        references.append(dict(command=shlex.join(check["argv"]), subject_oid=binding["output_oid"], exit_code=code,
                               evidence_path=proof["path"], evidence_sha256=proof["sha256"]))
    return references


def check_evidence(checks: list[dict], binding: dict, required_checks: list[dict], artifact_root: Path | str,
                   *, require_pass: bool = True) -> list[dict]:
    scope = check_scope(required_checks)
    require(len(checks) == len(required_checks), "required project checks are absent or duplicated")
    proofs = []
    expected_snapshot = {"work_dir": binding["work_dir"], "common_git_dir": binding["common_git_dir"],
                         "head_oid": binding["output_oid"], "clean": True}
    for check, requirement in zip(checks, required_checks):
        proof = read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, artifact_root)
        require(proof.get("schema") == "gc.workspace.project-check.v1" and proof.get("binding") == binding
                and proof.get("required_scope_sha256") == scope and proof.get("check_id") == requirement["id"]
                and proof.get("argv") == requirement["argv"] and proof.get("status") in STATUSES
                and check["command"] == shlex.join(requirement["argv"]) and check["subject_oid"] == binding["output_oid"]
                and check["exit_code"] == proof.get("exit_code"), "check evidence has a foreign subject or required scope")
        identity(proof["producer"])
        if require_pass:
            require(proof["status"] == "passed" and type(proof["exit_code"]) is int and proof["exit_code"] == 0
                    and proof.get("before") == expected_snapshot and proof.get("after") == expected_snapshot,
                    "required project check did not actually complete successfully at the clean result")
        proofs.append(proof)
    require(all(proof["producer"] == proofs[0]["producer"] for proof in proofs), "check producer identity changed")
    return proofs


def begin_review(binding: dict, work_dir: Path | str, checks: list[dict], required_checks: list[dict],
                 producer: dict, reviewer: dict, artifacts: list[dict], artifact_root: Path | str,
                 *, review_mode: str = "report") -> dict:
    identity(producer)
    identity(reviewer)
    require(review_mode in ("report", "agent", "interactive"), "unknown review authority")
    require(producer["step_id"] != reviewer["step_id"] and producer["session_id"] != reviewer["session_id"],
            "acceptance requires independent native producer and reviewer sessions")
    proofs = check_evidence(checks, binding, required_checks, artifact_root, require_pass=False)
    require(all(proof["producer"] == producer for proof in proofs), "review names a different check producer")
    require(bool(artifacts), "acceptance requires inspectable producer artifacts")
    for reference in artifacts:
        verify_artifact(reference, artifact_root)
    return copy.deepcopy(dict(schema="gc.workspace.producer-review.v1", binding=binding,
                              required_scope_sha256=check_scope(required_checks), required_checks=required_checks,
                              checks=checks, artifacts=artifacts, producer=producer, reviewer=reviewer,
                              review_mode=review_mode, before=snapshot(work_dir, binding)))


def complete_review(context: dict, work_dir: Path | str, report: Path | str, status: str,
                    evidence_path: Path | str, artifact_root: Path | str) -> dict:
    require(status in STATUSES, "unknown review execution status")
    check_evidence(context["checks"], context["binding"], context["required_checks"], artifact_root, require_pass=status == "passed")
    for reference in context["artifacts"]:
        verify_artifact(reference, artifact_root)
    after = snapshot(work_dir, context["binding"], clean=status == "passed", exact=status == "passed")
    if status == "passed":
        require(after == context["before"], "source changed during independent review")
    proof = immutable_json(evidence_path, dict(context, status=status, after=after, report=artifact(report, artifact_root)))
    record_status = {"passed": "passed", "failed": "failed", "unrun": "unrun"}.get(status, "pending")
    return dict(status=record_status, reviewed_oid=context["binding"]["output_oid"], reviewer=context["reviewer"]["step_id"],
                report_path=proof["path"], report_sha256=proof["sha256"])


def validate_accepted_result(result: dict, *, required_checks: list[dict], artifact_root: Path | str,
                             binding: dict | None = None, work_dir: Path | str | None = None,
                             plan: dict | None = None, store_ref: str | None = None,
                             repo_dir: Path | str | None = None, native_evidence: dict | None = None) -> dict:
    validate_record("member-result", result)
    if binding is None:
        require(isinstance(plan, dict) and isinstance(native_evidence, dict) and repo_dir is not None,
                "consumer acceptance requires its frozen plan, repository and actual native qualifier")
        validate_record("source-plan", plan)
        binding = native_evidence.get("result_binding")
        require(isinstance(binding, dict) and binding.get("store_ref") == store_ref,
                "native qualifier lacks the independently resolved result binding")
        expected = dict(verified=True, workflow_root_id=result["workflow_root_id"], generation=result["generation"],
                        workspace_owner_id=result["workspace_owner_id"], member_id=result["member_id"], store_ref=store_ref,
                        head_oid=result["output_oid"], clean=True, recorder_step_id=result["writer_step_id"],
                        reviewer_step_id=result["acceptance"]["independent_review"]["reviewer"])
        require(all(type(native_evidence.get(key)) is type(value) and native_evidence.get(key) == value for key, value in expected.items()),
                "native result qualification is stale or foreign")
        for key in ("producer_session_id", "producer_attempt_id", "reviewer_session_id", "reviewer_attempt_id", "native_attempt_id"):
            require(isinstance(native_evidence.get(key), str) and native_evidence[key].strip(), "native acceptance identity is incomplete")
        require(native_evidence["producer_session_id"] != native_evidence["reviewer_session_id"]
                and native_evidence["native_attempt_id"] == binding["native_attempt_id"], "native result review or workspace attempt changed")
        require(all(result[field] == plan[field] for field in SCOPE_FIELDS[:3]), "dependent consumed a stale source generation")
        nodes = [node for node in plan["nodes"] if node["owner_id"] == result["workspace_owner_id"]]
        require(len(nodes) == 1 and result["member_id"] in nodes[0]["member_ids"], "dependent result target is outside the frozen plan")
        common = str(Path(git_value(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True))
        require(common == binding["common_git_dir"] and str(Path(repo_dir).resolve(strict=True)) == binding["rig_root"],
                "dependent selected another registered repository")
        for oid in (result["input_oid"], result["output_oid"]):
            require(git_value(repo_dir, "cat-file", "-t", oid) == "commit", "accepted commit is absent from the repository")
    require(result["acceptance"]["status"] == "accepted", "member output is not accepted")
    for field in (*SCOPE_FIELDS, "member_id", "input_oid", "output_oid"):
        require(result[field] == binding[field], f"accepted output has a foreign {field}")
    acceptance = result["acceptance"]
    proofs = check_evidence(acceptance["project_checks"], binding, required_checks, artifact_root)
    artifacts = acceptance["artifacts"]
    require(bool(artifacts), "accepted output has no inspectable artifacts")
    for reference in artifacts:
        verify_artifact(reference, artifact_root)
    review = acceptance["independent_review"]
    proof = read_artifact({"path": review["report_path"], "sha256": review["report_sha256"]}, artifact_root)
    expected_snapshot = {"work_dir": binding["work_dir"], "common_git_dir": binding["common_git_dir"],
                         "head_oid": binding["output_oid"], "clean": True}
    require(proof.get("schema") == "gc.workspace.producer-review.v1" and proof.get("binding") == binding
            and proof.get("status") == "passed" and proof.get("required_scope_sha256") == check_scope(required_checks)
            and proof.get("required_checks") == required_checks and proof.get("checks") == acceptance["project_checks"]
            and proof.get("artifacts") == artifacts and proof.get("producer") == proofs[0]["producer"]
            and proof.get("before") == expected_snapshot and proof.get("after") == expected_snapshot,
            "independent review is absent, stale or outside the accepted scope")
    producer, reviewer = identity(proof["producer"]), identity(proof["reviewer"])
    require(producer["session_id"] != reviewer["session_id"] and producer["step_id"] != reviewer["step_id"]
            and review["reviewer"] == reviewer["step_id"] and reviewer["step_id"] != result["writer_step_id"],
            "accepted review is not independent of the producer and recorder")
    if native_evidence is not None:
        expected = {"producer_step_id": producer["step_id"], "producer_session_id": producer["session_id"],
                    "producer_attempt_id": producer["attempt_id"], "reviewer_step_id": reviewer["step_id"],
                    "reviewer_session_id": reviewer["session_id"], "reviewer_attempt_id": reviewer["attempt_id"],
                    "recorder_step_id": result["writer_step_id"]}
        require(all(native_evidence.get(key) == value for key, value in expected.items()),
                "manifest identities differ from the authoritative native producer, reviewer or recorder")
    verify_artifact(proof["report"], artifact_root)
    if work_dir is not None:
        snapshot(work_dir, binding)
        require(git_value(work_dir, "cat-file", "-t", binding["input_oid"]) == "commit", "input commit is absent")
        require(git(work_dir, "merge-base", "--is-ancestor", binding["input_oid"], binding["output_oid"]).returncode == 0,
                "result does not contain its exact accepted input")
        actual_commits = git_value(work_dir, "rev-list", "--reverse", binding["input_oid"] + ".." + binding["output_oid"]).splitlines()
        require(actual_commits == result["commit_oids"], "result commits differ from the actual input-to-output source history")
    return result


def make_member_result(binding: dict, *, writer_step_id: str, commit_oids: list[str], checks: list[dict],
                       review: dict, artifacts: list[dict], required_checks: list[dict],
                       artifact_root: Path | str, work_dir: Path | str) -> dict:
    changed = binding["input_oid"] != binding["output_oid"]
    result = dict(version=1, **{field: binding[field] for field in SCOPE_FIELDS}, writer_step_id=writer_step_id,
                  member_id=binding["member_id"], status="changed" if changed else "no_change",
                  input_oid=binding["input_oid"], output_oid=binding["output_oid"], commit_oids=commit_oids,
                  acceptance=dict(status="accepted", subject_oid=binding["output_oid"], project_checks=checks,
                                  independent_review=review, artifacts=artifacts))
    return validate_accepted_result(result, binding=binding, required_checks=required_checks,
                                    artifact_root=artifact_root, work_dir=work_dir)


def terminal_node(plan: dict) -> dict:
    from workspace_source_plan import source_order
    source_order(plan)
    return next(node for node in plan["nodes"] if node["owner_id"] == plan["terminal_owner_id"])


def make_owner_output(plan: dict, results: list[dict], *, artifact_root: Path | str, qualifications: dict,
                      integration_inputs: list[dict] | None = None, integration_evidence: dict | None = None) -> dict:
    terminal_node(plan)
    require(bool(results), "owner output requires completed member results")
    owner = results[0]["workspace_owner_id"]
    nodes = [node for node in plan["nodes"] if node["owner_id"] == owner]
    require(len(nodes) == 1, "output owner is absent from the plan")
    node = nodes[0]
    require([result["member_id"] for result in results] == node["member_ids"], "owner output is missing member checkpoints")
    for position, result in enumerate(results):
        qualification = qualifications.get(result["member_id"])
        require(isinstance(qualification, dict) and set(qualification) == {"binding", "required_checks"},
                "owner output requires frozen qualification for every member")
        validate_accepted_result(result, artifact_root=artifact_root, **qualification)
        require(result["acceptance"]["status"] == "accepted" and result["workspace_owner_id"] == owner
                and all(result[field] == plan[field] for field in SCOPE_FIELDS[:3]), "owner output contains an unaccepted or foreign member")
        if position:
            require(result["input_oid"] == results[position - 1]["output_oid"], "shared checkpoints do not form an exact source chain")
    if node["strategy"] == "integration":
        require(integration_inputs is not None and [entry["owner_id"] for entry in integration_inputs] == node["source_predecessor_owner_ids"],
                "integration requires all ordered accepted predecessor outputs")
        evidence = read_artifact(integration_evidence, artifact_root)
        require(evidence.get("integration_inputs") == integration_inputs and evidence.get("output_oid") == results[0]["input_oid"],
                "integration evidence differs from the first member input")
    else:
        require(integration_inputs is None and integration_evidence is None, "non-integration output cannot substitute composed source")
    final = results[-1]
    output = dict(version=1, **{field: final[field] for field in SCOPE_FIELDS}, writer_step_id=final["writer_step_id"],
                  strategy=node["strategy"], input_oid=results[0]["input_oid"], output_oid=final["output_oid"],
                  final_member_id=final["member_id"], final_member_result_sha256=record_sha256(final),
                  integration_inputs=integration_inputs,
                  integration_evidence_path=integration_evidence["path"] if integration_evidence else None,
                  integration_evidence_sha256=integration_evidence["sha256"] if integration_evidence else None)
    return validate_record("owner-output", output)


def canonical_payload(run: dict, plan: dict, output: dict, result: dict, summary: dict, *, writer_step_id: str,
                      binding: dict, required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str,
                      current: dict | None = None, stored: dict | None = None) -> dict:
    validate_record("run", run)
    validate_record("owner-output", output)
    node = terminal_node(plan)
    require(run["workflow_root_id"] == plan["workflow_root_id"] and run["common_git_dir"] == binding["common_git_dir"],
            "canonical source belongs to another run or repository")
    require(output["workspace_owner_id"] == node["owner_id"] and output["strategy"] == node["strategy"]
            and output["final_member_id"] == node["member_ids"][-1]
            and output["final_member_result_sha256"] == record_sha256(result)
            and output["output_oid"] == result["output_oid"]
            and output["workspace_owner_id"] == result["workspace_owner_id"]
            and output["final_member_id"] == result["member_id"]
            and all(output[field] == plan[field] for field in SCOPE_FIELDS[:3]), "canonical terminal output is absent or changed")
    validate_accepted_result(result, binding=binding, required_checks=required_checks, artifact_root=artifact_root, work_dir=work_dir)
    verify_artifact(summary, artifact_root)
    require(summary in result["acceptance"]["artifacts"], "canonical summary was not part of independent acceptance")
    if output["strategy"] == "integration":
        evidence = read_artifact({"path": output["integration_evidence_path"], "sha256": output["integration_evidence_sha256"]}, artifact_root)
        require([entry["owner_id"] for entry in output["integration_inputs"]] == node["source_predecessor_owner_ids"]
                and evidence.get("integration_inputs") == output["integration_inputs"] and evidence.get("output_oid") == output["input_oid"],
                "canonical integration evidence changed")
    candidate = dict(version=1, **{field: output[field] for field in SCOPE_FIELDS}, writer_step_id=writer_step_id,
                     output_oid=output["output_oid"], owner_output_sha256=record_sha256(output),
                     summary_path=summary["path"], summary_sha256=summary["sha256"])
    validate_record("canonical", candidate)
    if stored is not None:
        candidate["writer_step_id"] = stored["writer_step_id"]
        verify_replay("canonical", stored, candidate)
    if current is not None and record_identity("canonical", current) == record_identity("canonical", candidate):
        verify_replay("canonical", current, candidate)
    elif plan["generation"] == 1:
        require(current is None and plan["base_oid"] == run["base_oid"], "conflicting current canonical pointer")
    else:
        require(current is not None and current["workflow_root_id"] == plan["workflow_root_id"]
                and current["generation"] + 1 == plan["generation"]
                and plan["parent_canonical_generation"] == current["generation"]
                and plan["parent_canonical_oid"] == current["output_oid"] == plan["base_oid"],
                "fix canonical parent is stale or no longer current")
    return candidate


def referenced_record(store, kind: str, reference_owner_id: str) -> tuple[dict, dict, list]:
    from workspace_store import GuardRead, MISSING
    key = contracts()[kind]["metadata_key"] + "_ref"
    row = store.snapshot([reference_owner_id])[reference_owner_id]
    raw = row["metadata"].get(key, MISSING)
    require(isinstance(raw, str), f"missing exact {kind} record reference")
    reference = parse_record(raw)
    require(set(reference) == {"kind", "identity", "bead_id"} and reference["kind"] == kind, "invalid physical record reference")
    payload = store.read_record(kind, reference["bead_id"], identity=reference["identity"])
    require(payload is not None, f"referenced {kind} record is absent")
    guards = [GuardRead(reference_owner_id, key, raw),
              GuardRead(reference["bead_id"], contracts()[kind]["metadata_key"], canonical_bytes(payload).decode())]
    return payload, reference, guards


def prepare_record(store, attempt, payload: dict, *, kind: str, record_id: str, authority_id: str,
                   reference_owner_id: str, writer_map, guards=(), native_rows=None, initial_write: bool = False,
                   operation_nonce: str | None = None):
    """Use the writer-owned transaction; callers supply every qualified dependency guard."""
    from workspace_store import CookedWriterMap, GuardRead, MISSING, RecordWrite, ReferenceWrite, SCOPE_OWNER, record_reference
    require(isinstance(writer_map, CookedWriterMap), "native cooked writer map is required")
    validate_record(kind, payload)
    require(store.common_git_dir is not None, "record write requires its exact repository lock root")
    key = contracts()[kind]["metadata_key"] + "_ref"
    row = store.snapshot([reference_owner_id])[reference_owner_id]
    raw = row["metadata"].get(key, MISSING)
    guards = [*guards, GuardRead(reference_owner_id, key, raw)]
    expected_rows = None
    if native_rows is not None:
        require(isinstance(native_rows, dict) and bool(native_rows)
                and all(isinstance(value, dict) and value.get("id") == bead_id for bead_id, value in native_rows.items()),
                "native qualification must retain original full row snapshots")
        guards.extend(GuardRead(bead_id, "gc.workspace_transition_nonce", value["metadata"].get("gc.workspace_transition_nonce", MISSING))
                      for bead_id, value in native_rows.items())
        ids = list(dict.fromkeys([authority_id, attempt.claimed_bead_id, payload["workflow_root_id"], record_id,
                                  reference_owner_id, *(guard.bead_id for guard in guards),
                                  writer_map.declaration["expansion_root_id"], writer_map.declaration["source_member_id"],
                                  *(step["bead_id"] for step in writer_map.declaration["steps"])]))
        expected_rows = store.snapshot(ids)
        expected_rows.update(copy.deepcopy(native_rows))
    require(type(initial_write) is bool, "initial write admission must be explicit boolean authority")
    method = store.install_grant if initial_write else store.write_records
    return method(attempt=attempt, scope={"workflow_root_id": payload["workflow_root_id"],
                               "generation": payload["generation"], "writer_scope_id": payload[SCOPE_OWNER[kind]], "record_kind": kind},
                               authority_id=authority_id, writes=[RecordWrite(kind, record_id, payload)],
                               references=[ReferenceWrite(reference_owner_id, key, record_reference(kind, record_id, payload))],
                               writer_map=writer_map, guards=guards, expected_rows=expected_rows, operation_nonce=operation_nonce)


def native_rows(evidence: dict, result: dict) -> dict:
    rows = evidence.get("guard_rows")
    require(type(evidence.get("current_generation")) is int and evidence["current_generation"] == result["generation"],
            "result generation is no longer the currently selected native source plan")
    required = {evidence.get("producer_step_id"), evidence.get("reviewer_step_id"), result["writer_step_id"],
                result["workflow_root_id"], evidence.get("result_binding", {}).get("workspace_bead_id")}
    require(isinstance(rows, dict) and all(isinstance(bead_id, str) and bead_id in rows for bead_id in required),
            "publication requires original producer, reviewer and recorder rows for native status/revision fencing")
    return rows


def prepare_canonical(store, attempt, *, run_owner_id: str, plan_owner_id: str, output_owner_id: str,
                      result_member_id: str, record_id: str, authority_id: str, binding: dict,
                      required_checks: list[dict], artifact_root: Path | str, work_dir: Path | str,
                      summary: dict, qualify_native, writer_map, initial_write: bool = False, operation_nonce: str | None = None):
    from workspace_store import GuardRead, MISSING
    loaded = [referenced_record(store, kind, owner) for kind, owner in
              (("run", run_owner_id), ("source-plan", plan_owner_id), ("owner-output", output_owner_id),
               ("member-result", result_member_id))]
    run, plan, output, result = [entry[0] for entry in loaded]
    workspace, _, workspace_guards = referenced_record(store, "workspace", output_owner_id)
    require(result_binding(run, plan, workspace, store_ref=store.store_ref, member_id=result["member_id"],
                            output_oid=result["output_oid"]) == binding,
            "canonical binding differs from its exact current workspace")
    if output["strategy"] == "integration":
        require(workspace["integration_inputs"] == output["integration_inputs"], "canonical predecessor tuple differs from its recorded workspace")
    native = qualify_native(result)
    require(isinstance(native, dict) and native.get("result_binding") == binding,
            "canonical publication lacks the current independently resolved native result binding")
    validate_accepted_result(result, plan=plan, store_ref=store.store_ref, repo_dir=run["rig_root"],
                             artifact_root=artifact_root, required_checks=required_checks, native_evidence=native)
    require(binding["store_ref"] == store.store_ref and binding["common_git_dir"] == str(store.common_git_dir),
            "canonical publication selected another store or lock repository")
    root = store.snapshot([run["workflow_root_id"]])[run["workflow_root_id"]]
    key = contracts()["canonical"]["metadata_key"] + "_ref"
    raw = root["metadata"].get(key, MISSING)
    current, current_guards = None, []
    if raw is not MISSING:
        current, _, current_guards = referenced_record(store, "canonical", run["workflow_root_id"])
    stored = store.read_record("canonical", record_id)
    payload = canonical_payload(run, plan, output, result, summary, writer_step_id=attempt.claimed_bead_id,
                                binding=binding, required_checks=required_checks, artifact_root=artifact_root,
                                work_dir=work_dir, current=current, stored=stored)
    guards = [*workspace_guards, *(guard for _, _, collection in loaded for guard in collection)]
    return prepare_record(store, attempt, payload, kind="canonical", record_id=record_id, authority_id=authority_id,
                          reference_owner_id=run["workflow_root_id"], writer_map=writer_map,
                          guards=[*guards, *current_guards, GuardRead(root["id"], key, raw)],
                          native_rows=native_rows(native, result), initial_write=initial_write, operation_nonce=operation_nonce)


def prepare_member_result(store, attempt, result: dict, *, run_owner_id: str, plan_owner_id: str,
                          workspace_owner_id: str, record_id: str, authority_id: str,
                          required_checks: list[dict], artifact_root: Path | str, qualify_native, writer_map,
                          initial_write: bool = False, operation_nonce: str | None = None):
    loaded = [referenced_record(store, kind, owner) for kind, owner in
              (("run", run_owner_id), ("source-plan", plan_owner_id), ("workspace", workspace_owner_id))]
    run, plan, workspace = [entry[0] for entry in loaded]
    binding = result_binding(run, plan, workspace, store_ref=store.store_ref,
                              member_id=result["member_id"], output_oid=result["output_oid"])
    native = qualify_native(result)
    require(isinstance(native, dict) and native.get("result_binding") == binding
            and str(store.common_git_dir) == run["common_git_dir"], "result publication lacks exact current native provenance")
    validate_accepted_result(result, plan=plan, store_ref=store.store_ref, repo_dir=run["rig_root"],
                             required_checks=required_checks, artifact_root=artifact_root, native_evidence=native)
    snapshot(workspace["work_dir"], binding)
    return prepare_record(store, attempt, result, kind="member-result", record_id=record_id, authority_id=authority_id,
                          reference_owner_id=result["member_id"], writer_map=writer_map,
                          guards=[guard for _, _, collection in loaded for guard in collection],
                          native_rows=native_rows(native, result), initial_write=initial_write, operation_nonce=operation_nonce)


def prepare_owner_output(store, attempt, output: dict, *, plan_owner_id: str, record_id: str,
                         authority_id: str, qualifications: dict, artifact_root: Path | str,
                         qualify_native, writer_map, initial_write: bool = False, operation_nonce: str | None = None):
    plan, _, plan_guards = referenced_record(store, "source-plan", plan_owner_id)
    workspace, _, workspace_guards = referenced_record(store, "workspace", output["workspace_owner_id"])
    if output["strategy"] == "integration":
        require(workspace["integration_inputs"] == output["integration_inputs"], "output predecessor tuple differs from its recorded workspace")
    nodes = [node for node in plan["nodes"] if node["owner_id"] == output["workspace_owner_id"]]
    require(len(nodes) == 1, "output owner is absent from the exact recorded plan")
    loaded = [referenced_record(store, "member-result", member) for member in nodes[0]["member_ids"]]
    results = [entry[0] for entry in loaded]
    retained_rows = {}
    for result in results:
        qualification = qualifications.get(result["member_id"])
        require(isinstance(qualification, dict), "output member has no frozen required check scope")
        native = qualify_native(result)
        require(isinstance(native, dict) and native.get("result_binding") == qualification["binding"], "owner output lacks native member qualification")
        validate_accepted_result(result, plan=plan, store_ref=store.store_ref,
                                 repo_dir=qualification["binding"]["rig_root"], artifact_root=artifact_root,
                                 required_checks=qualification["required_checks"], native_evidence=native)
        for bead_id, row in native_rows(native, result).items():
            require(bead_id not in retained_rows or retained_rows[bead_id] == row, "native rows changed during owner qualification")
            retained_rows[bead_id] = row
    evidence = ({"path": output["integration_evidence_path"], "sha256": output["integration_evidence_sha256"]}
                if output["strategy"] == "integration" else None)
    expected = make_owner_output(plan, results, artifact_root=artifact_root, qualifications=qualifications,
                                  integration_inputs=output["integration_inputs"], integration_evidence=evidence)
    verify_replay("owner-output", expected, output)
    return prepare_record(store, attempt, output, kind="owner-output", record_id=record_id, authority_id=authority_id,
                          reference_owner_id=output["workspace_owner_id"], writer_map=writer_map,
                          guards=[*plan_guards, *workspace_guards, *(guard for _, _, collection in loaded for guard in collection)],
                          native_rows=retained_rows, initial_write=initial_write, operation_nonce=operation_nonce)


def main(argv=None) -> int:
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(description="Validate supplied producer evidence; this does not authorize workflow activation or writes.")
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--required-checks", required=True, type=Path, help="JSON object containing required_checks [{id, argv}]")
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = parse_record(args.result.read_text())
        binding = parse_record(args.binding.read_text())
        requirements = parse_record(args.required_checks.read_text())["required_checks"]
        validate_accepted_result(result, binding=binding, required_checks=requirements,
                                  artifact_root=args.artifact_root, work_dir=args.work_dir)
        print(json.dumps({"ok": True, "scope": "component_record_validation", "sha256": record_sha256(result)}, sort_keys=True))
        return 0
    except (RecordError, OSError, UnicodeError, KeyError, TypeError) as exc:
        print(f"workspace output: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
