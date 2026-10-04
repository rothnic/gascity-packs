#!/usr/bin/env python3
"""Pack policy over native claims, managed worktrees, and returned evidence."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# Reuse this pack's immutable artifact schemas and validator.
_validator_spec = importlib.util.spec_from_file_location(
    "_managed_do_work_artifacts", Path(__file__).with_name("validate_build_artifact.py"))
artifacts = importlib.util.module_from_spec(_validator_spec)
sys.modules[_validator_spec.name] = artifacts
_validator_spec.loader.exec_module(artifacts)

PREFIX = "gc.implementation."
CREATOR = "gascity/do-work"
OWNERSHIP = {
    "repo": "gc.worktree_repo", "root": "gc.worktree_root",
    "path": "gc.work_dir", "branch": "gc.work_branch",
    "base": "gc.worktree_base_ref", "base-sha": "gc.worktree_base_sha",
    "creator": "gc.worktree_creator", "owner": "gc.worktree_owner",
    "generation": "gc.worktree_generation", "lifecycle": "gc.worktree_lifecycle",
}
BLOCKING = {"blocks", "waits-for", "conditional-blocks"}
STAGES = {
    "prepare": "prepare-worktree", "output": "implement",
    "acceptance": "independent-acceptance", "close": "close-source-anchor",
}


class Error(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise Error(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def decode(text):
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except (ValueError, TypeError) as exc:
        raise Error("invalid JSON: " + str(exc)) from exc


def command(args):
    env = os.environ.copy()
    if args[0] == "git":
        # Explicit -C must not be redirected by an inherited Git worktree/index.
        for key in list(env):
            if key.startswith("GIT_"):
                del env[key]
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    require(result.returncode == 0,
            "command failed: " + repr(args) + ": " + result.stderr[-2000:])
    return result.stdout


def absolute(value):
    require(isinstance(value, str) and Path(value).is_absolute(),
            "an absolute path is required")
    return str(Path(value).resolve())


def oid(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value),
            "full exact commit SHA is required")
    return value


def file_record(path):
    path = absolute(path)
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise Error("cannot read evidence " + path + ": " + str(exc)) from exc
    require(bool(data), "empty evidence: " + path)
    return {"path": path, "sha256": hashlib.sha256(data).hexdigest()}


def read_record(record):
    require(isinstance(record, dict), "missing evidence record")
    observed = file_record(record.get("path", ""))
    require(observed == record, "evidence hash or location changed: " + observed["path"])
    return decode(Path(observed["path"]).read_text())


def write_receipt(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    path = Path(path)
    try:
        with path.open("xb") as output:
            output.write(data)
    except FileExistsError:
        require(path.read_bytes() == data, "receipt already exists with different evidence: " + str(path))
    return file_record(str(path))


def metadata(bead):
    raw = bead.get("metadata")
    if raw is None:
        raw = {}
    require(isinstance(raw, dict), "invalid native metadata")
    result = {}
    for key, value in raw.items():
        require(isinstance(key, str) and
                (value is None or isinstance(value, (str, bool, int, float))),
                "invalid structured native metadata")
        # Match native Bead.StringMap's scalar JSON normalization.
        result[key] = (value if isinstance(value, str) else
                       "" if value is None else json.dumps(value, allow_nan=False))
    return result


def healthy(bead):
    meta = metadata(bead)
    outcome = meta.get("gc.outcome", "").strip()
    require(outcome not in {"fail", "canceled", "cancelled", "skipped"}
            and meta.get("molecule_failed") != "true"
            and meta.get("gc.molecule_failed") != "true"
            and not meta.get("gc.cancel_requested", "").strip()
            and (bead.get("status") != "closed" or outcome == "pass"),
            "native work failed, was canceled, or closed without pass: " + bead["id"])
    labels = bead.get("labels") or []
    require(isinstance(labels, list) and all(isinstance(label, str) for label in labels),
            "invalid native labels")
    require(not any(label.startswith("hold:") for label in labels),
            "native work is held: " + bead["id"])


def frozen_input(data):
    fields = {"schema_version", "source_anchor_id", "source_store_ref", "repo_dir",
              "worktree_root", "base_sha", "branch", "generation", "verification_command", "parents"}
    require(isinstance(data, dict) and set(data) == fields
            and type(data["schema_version"]) is int and data["schema_version"] == 1,
            "invalid frozen input contract")
    for key in fields - {"schema_version", "parents"}:
        require(isinstance(data[key], str) and bool(data[key].strip()),
                "frozen input string is required: " + key)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", data["source_anchor_id"]),
            "source ID is not a safe worktree child")
    for key in ("repo_dir", "worktree_root"):
        require(data[key] == absolute(data[key]), "frozen path must be canonical: " + key)
    oid(data["base_sha"])
    require(isinstance(data["parents"], list), "frozen parents must be a list")
    parent_fields = {"source_anchor_id", "source_store_ref", "accepted_commit",
                     "acceptance_path", "acceptance_sha256"}
    for parent in data["parents"]:
        require(isinstance(parent, dict) and set(parent) == parent_fields
                and all(isinstance(value, str) and bool(value.strip()) for value in parent.values()),
                "invalid frozen parent contract")
        oid(parent["accepted_commit"])
        require(parent["acceptance_path"] == absolute(parent["acceptance_path"])
                and re.fullmatch(r"[0-9a-f]{64}", parent["acceptance_sha256"]),
                "invalid frozen parent receipt location/hash")


class Workflow:
    def __init__(self, bead_id, run=None, env=None):
        self.run = run or command
        self.env = dict(os.environ if env is None else env)
        self.step = self.show(bead_id)
        root_id = metadata(self.step).get("gc.root_bead_id", "")
        require(bool(root_id), "claimed step has no native workflow root")
        self.root = self.show(root_id)
        healthy(self.root)
        require(metadata(self.root).get("gc.kind") == "workflow",
                "step root is not a native workflow")

    def show(self, bead_id):
        require(isinstance(bead_id, str) and bool(bead_id), "missing native bead ID")
        value = decode(self.run(["gc", "bd", "show", bead_id, "--json"]))
        if isinstance(value, list):
            require(len(value) == 1, "native bead read must return exactly one row")
            value = value[0]
        require(isinstance(value, dict) and value.get("id") == bead_id,
                "native bead read did not return the exact requested ID: " + bead_id)
        metadata(value)
        return value

    def update(self, bead, patch, status=None):
        changed = {key: value for key, value in patch.items()
                   if metadata(bead).get(key) != value}
        if not changed and (status is None or bead.get("status") == status):
            return bead
        args = ["gc", "bd", "update", bead["id"]]
        if status is not None:
            args += ["--status", status]
        for key, value in sorted(changed.items()):
            args += ["--set-metadata", key + "=" + value]
        self.run(args)
        observed = self.show(bead["id"])
        require(all(metadata(observed).get(key) == value for key, value in patch.items())
                and (status is None or observed.get("status") == status),
                "native publication readback mismatch: " + bead["id"])
        return observed

    def identity(self, bead, closed=False):
        meta = metadata(bead)
        healthy(bead)
        session = meta.get("gc.session_id", "")
        attempt = meta.get("gc.attempt", "")
        require(bool(session) and isinstance(session, str), "native session identity is missing")
        require(isinstance(attempt, str) and attempt.isdecimal() and int(attempt) > 0,
                "native physical attempt is missing")
        if closed:
            require(bead.get("status") == "closed" and meta.get("gc.outcome") == "pass",
                    "native producer/reviewer has not returned closed/pass")
        return {"bead_id": bead["id"], "session_id": session, "attempt": int(attempt)}

    def worker(self, stage=None):
        require(self.root.get("status") != "closed", "native workflow root is settled")
        healthy(self.step)
        require(self.step.get("status") == "in_progress", "native claim is not in progress")
        session = self.env.get("GC_SESSION_ID", "")
        require(bool(session), "native session GC_SESSION_ID is required for a worker")
        require(self.run(["gc", "hook", "current", "--id-only"]).strip() == self.step["id"],
                "native current claim does not match this physical step")
        require(self.identity(self.step)["session_id"] == session,
                "claimed step native session does not match this worker")
        if stage:
            require(metadata(self.step).get("gc.step_id") == stage, "wrong native stage")
        return self.identity(self.step)

    def resolve_anchor(self, initial=False):
        meta = metadata(self.root)
        intake_id = meta.get("gc.input_convoy_id") or meta.get("gc.source_bead_id")
        require(bool(intake_id), "native root has no source/intake link")
        intake = self.show(intake_id)
        intake_meta = metadata(intake)
        anchor_id = intake_id
        if intake_meta.get("gc.synthetic_kind") == "drain-unit-convoy":
            anchor_id = intake_meta.get("gc.drain_member_id", "")
            require(bool(anchor_id) and anchor_id != intake_id,
                    "drain unit has no original source")
        elif intake_meta.get("gc.synthetic") == "true":
            status = decode(self.run(["gc", "convoy", "status", intake_id, "--json"]))
            children = status.get("children") if isinstance(status, dict) else None
            require(isinstance(children, list) and len(children) == 1
                    and isinstance(children[0], dict), "synthetic intake must track exactly one source")
            anchor_id = children[0].get("id", "")
            require(bool(anchor_id) and anchor_id != intake_id, "synthetic intake is not an original source")
        source = self.show(anchor_id)
        healthy(source)
        require(metadata(source).get("gc.synthetic") != "true", "source anchor is synthetic")
        require(meta.get("gc.source_anchor_id", anchor_id) == anchor_id,
                "stamped source anchor conflicts with native intake")
        require(meta.get("gc.source_bead_id", intake_id) in {intake_id, anchor_id},
                "root source link conflicts with native intake")
        require(meta.get("gc.drain_member_id", anchor_id) == anchor_id,
                "root drain member conflicts with native source")
        source_meta = metadata(source)
        link = source_meta.get("workflow_id")
        unpublished = (
            not any(key in source_meta for key in (*OWNERSHIP.values(), "work_dir",
                                                   PREFIX + "worktree_attempt_id"))
            and not any(key in meta for key in (PREFIX + "input_path", PREFIX + "input_sha256",
                                               PREFIX + "worktree_attempt_id")))
        require(link == self.root["id"] or
                (initial and not link and unpublished),
                "source workflow owner changed or prepared link is missing")
        stores = [value for value in (
            metadata(source).get("gc.root_store_ref"), meta.get("gc.source_store_ref"),
            intake_meta.get("gc.root_store_ref"), meta.get("gc.root_store_ref")) if value]
        require(bool(stores) and len(set(stores)) == 1
                and stores[0] == stores[0].strip()
                and (stores[0].startswith("city:") or stores[0].startswith("rig:"))
                and bool(stores[0].split(":", 1)[1]),
                "native source store pins are missing or conflicting")
        return source, stores[0]

    def inputs(self, input_path=None, preparing=False):
        source, store = self.resolve_anchor(initial=preparing)
        root_meta, source_meta = metadata(self.root), metadata(source)
        path = input_path or root_meta.get(PREFIX + "input_path")
        if not path and preparing:
            path = source_meta.get(PREFIX + "input_path")
            if path:
                require(bool(source_meta.get(PREFIX + "input_sha256")),
                        "source input handoff hash is required")
        require(bool(path), "frozen input_path is required")
        record = file_record(path)
        data = read_record(record)
        frozen_input(data)
        require(data["source_anchor_id"] == source["id"] and data["source_store_ref"] == store,
                "frozen input source/store does not match native authority")
        for bead in (self.root, source):
            meta = metadata(bead)
            path_key, hash_key = PREFIX + "input_path", PREFIX + "input_sha256"
            absent = path_key not in meta and hash_key not in meta
            require((preparing and absent) or
                    (meta.get(path_key) == record["path"] and meta.get(hash_key) == record["sha256"]),
                    "frozen input bytes or location changed, or input pins are incomplete")
        require(source.get("status") != "closed" or
                (source_meta.get("gc.outcome") == "pass" and source_meta.get("gc.work_outcome") == "shipped"),
                "source is closed without accepted output")
        dependencies = decode(self.run([
            "gc", "bd", "dep", "list", source["id"], "--direction", "down", "--json"]))
        require(isinstance(dependencies, list), "native dependencies are not a complete array")
        blockers = set()
        for dep in dependencies:
            require(isinstance(dep, dict), "invalid native dependency")
            kind = dep.get("dependency_type", dep.get("dep_type"))
            related = dep.get("id")
            if "depends_on_id" in dep:
                related, kind = dep["depends_on_id"], dep.get("type")
            require(isinstance(kind, str) and bool(kind) and isinstance(related, str) and bool(related),
                    "native dependency lacks identity/type")
            if kind in BLOCKING and related != self.root["id"]:
                blockers.add(related)
        parents = data["parents"]
        ids = [parent["source_anchor_id"] for parent in parents]
        require(len(ids) == len(set(ids)) and set(ids) == blockers,
                "frozen parent set does not match native dependencies")
        for parent in parents:
            self.parent(parent, data)
        return source, data, record

    def spec(self, source, data, root_id=None):
        return {
            "repo": data["repo_dir"], "root": data["worktree_root"],
            "path": str(Path(data["worktree_root"]) / source["id"]),
            "branch": data["branch"], "base": data["base_sha"],
            "base-sha": data["base_sha"], "bead": source["id"],
            "store-ref": data["source_store_ref"], "creator": CREATOR,
            "owner": root_id or self.root["id"], "generation": data["generation"],
            "lifecycle": "active",
        }

    def workspace(self, source, data, action="verify", root_id=None):
        spec = self.spec(source, data, root_id)
        if action == "verify":
            meta = metadata(source)
            require(all(meta.get(key) == spec[flag] for flag, key in OWNERSHIP.items())
                    and meta.get("work_dir") == spec["path"]
                    and meta.get("gc.root_store_ref") == spec["store-ref"],
                    "managed source ownership metadata is incomplete or changed")
        args = ["gc", "worktree", action]
        for flag, value in spec.items():
            args += ["--" + flag, value]
        args.append("--json")
        report = decode(self.run(args))
        require(isinstance(report, dict) and report.get("ok") is True, "native worktree verification failed")
        provenance = report.get("provenance") or {}
        expected = {
            "bead_id": spec["bead"], "store_ref": spec["store-ref"],
            "path": spec["path"], "branch": spec["branch"], "base_ref": spec["base"],
            "base_sha": spec["base-sha"], "creator": CREATOR, "owner": spec["owner"],
            "generation": spec["generation"], "lifecycle": "active",
        }
        require(all(provenance.get(key) == value for key, value in expected.items())
                and bool(provenance.get("repo_identity"))
                and bool(provenance.get("attempt_id"))
                and report.get("path") == spec["path"] and report.get("branch") == spec["branch"],
                "native worktree report does not match frozen ownership")
        oid(report.get("head"))
        if action == "verify":
            require(provenance["attempt_id"] == metadata(source).get(PREFIX + "worktree_attempt_id"),
                    "native worktree provisioning attempt changed")
        return report

    def prepare(self, input_path=None):
        self.worker(STAGES["prepare"])
        source, data, record = self.inputs(input_path, preparing=True)
        require(source.get("status") != "closed", "cannot provision a closed source")
        existing = metadata(source)
        root_meta = metadata(self.root)
        attempt_key = PREFIX + "worktree_attempt_id"
        root_attempt = root_meta.get(attempt_key)
        if attempt_key in root_meta or any(key in existing for key in
                (*OWNERSHIP.values(), "work_dir", attempt_key)):
            verified = self.workspace(source, data)
            require(attempt_key not in root_meta or root_attempt == verified["provenance"]["attempt_id"],
                    "root provisioning attempt changed")
        report = self.workspace(source, data, "ensure")
        attempt = report["provenance"]["attempt_id"]
        require(attempt_key not in root_meta or root_attempt == attempt, "root provisioning attempt changed")
        previous = metadata(source).get(PREFIX + "worktree_attempt_id")
        require(not previous or previous == attempt, "existing provisioning attempt changed")
        spec = self.spec(source, data)
        pins = {PREFIX + "input_path": record["path"], PREFIX + "input_sha256": record["sha256"],
                PREFIX + "worktree_attempt_id": attempt}
        patch = {key: spec[flag] for flag, key in OWNERSHIP.items()}
        patch.update(pins)
        patch.update({"work_dir": spec["path"], "gc.root_store_ref": spec["store-ref"],
                      "workflow_id": self.root["id"]})
        self.update(source, patch)
        self.root = self.update(self.root, {**pins, "gc.source_anchor_id": source["id"]})
        return report

    def verify(self, worker=True):
        if worker:
            self.worker()
        source, data, record = self.inputs()
        report = self.workspace(source, data)
        require(metadata(self.root).get(PREFIX + "worktree_attempt_id") ==
                report["provenance"]["attempt_id"], "root provisioning attempt changed")
        return source, data, record, report

    def receipt(self, kind):
        meta = metadata(self.root)
        record = {"path": meta.get(PREFIX + kind + "_path", ""),
                  "sha256": meta.get(PREFIX + kind + "_sha256", "")}
        return read_record(record), record

    def artifact(self, record, schema, identity, upstream):
        require(file_record(record.get("path", "")) == record, "artifact evidence changed")
        try:
            artifact = artifacts.validate_artifact_text(
                Path(record["path"]).read_text(), expected_schema=schema)
        except artifacts.CLI_ERROR_TYPES as exc:
            raise Error("invalid build artifact: " + str(exc)) from exc
        front = artifact.front_matter
        stage = STAGES["output"] if schema.endswith("implementation-summary.v1") else STAGES["acceptance"]
        require(front.get("status") == "approved", "build artifact must be approved")
        require(isinstance(front.get("workflow"), dict)
                and front["workflow"].get("id") == self.root["id"]
                and front["workflow"].get("formula") == "do-work"
                and isinstance(front.get("producer"), dict)
                and front["producer"].get("formula") == "do-work"
                and front["producer"].get("stage") == stage
                and type(front["producer"].get("attempt")) is int
                and front["producer"]["attempt"] == identity["attempt"],
                "build artifact workflow/producer attempt does not match native authority")
        refs = [entry for entry in artifact.upstream if entry["path"] == upstream["path"]]
        require(len(refs) == 1 and refs[0]["hash"] == "sha256:" + upstream["sha256"],
                "build artifact upstream is not bound to exact current receipt bytes")

    def result(self, source, data, record, report, producer, summary, verification):
        return {
            "schema_version": 1, "source_anchor_id": source["id"],
            "source_store_ref": data["source_store_ref"], "workflow_root_id": self.root["id"],
            "input_path": record["path"], "input_sha256": record["sha256"],
            "base_sha": data["base_sha"], "output_commit": report["head"],
            "worktree": report["provenance"], "producer": producer,
            "summary": summary, "verification": verification,
        }

    def publish_output(self, summary, verification):
        producer = self.worker(STAGES["output"])
        source, data, record, report = self.verify(worker=False)
        require(source.get("status") != "closed", "cannot publish output for a closed source")
        proof = file_record(verification)
        test = read_record(proof)
        require(isinstance(test, dict) and test.get("tested_commit") == report["head"]
                and test.get("result") == "pass" and isinstance(test.get("command"), str)
                and test["command"] == data["verification_command"],
                "verification must pass at the tested output commit / HEAD with the frozen command")
        proof.update({key: test[key] for key in ("tested_commit", "result", "command")})
        summary_record = file_record(summary)
        self.artifact(summary_record, "gc.build.implementation-summary.v1", producer, record)
        result = self.result(source, data, record, report, producer, summary_record, proof)
        path = Path(record["path"]).parent / (source["id"] + "." + self.step["id"] + ".output.json")
        output = write_receipt(path, result)
        self.root = self.update(self.root, {
            PREFIX + "output_path": output["path"], PREFIX + "output_sha256": output["sha256"],
            PREFIX + "summary_path": result["summary"]["path"],
        })
        return result

    def validate_output(self, output, source, data, record, report, closed=True):
        require(isinstance(output, dict) and type(output.get("schema_version")) is int and output["schema_version"] == 1
                and output.get("source_anchor_id") == source["id"]
                and output.get("source_store_ref") == data["source_store_ref"]
                and output.get("workflow_root_id") == self.root["id"]
                and output.get("input_path") == record["path"]
                and output.get("input_sha256") == record["sha256"]
                and output.get("base_sha") == data["base_sha"]
                and output.get("worktree") == report["provenance"]
                and output.get("output_commit") == report["head"],
                "output receipt does not match frozen input or exact current HEAD")
        producer = output.get("producer") or {}
        require(isinstance(producer, dict) and type(producer.get("attempt")) is int,
                "invalid native output producer identity")
        bead = self.show(producer.get("bead_id", ""))
        require(metadata(bead).get("gc.root_bead_id") == self.root["id"]
                and metadata(bead).get("gc.step_id") == STAGES["output"]
                and self.identity(bead, closed) == producer, "native output producer identity changed")
        summary = output.get("summary")
        require(isinstance(summary, dict), "missing summary evidence")
        self.artifact(summary, "gc.build.implementation-summary.v1", producer, record)
        proof = output.get("verification") or {}
        evidence = read_record({key: proof.get(key, "") for key in ("path", "sha256")})
        require(isinstance(evidence, dict) and evidence.get("tested_commit") == report["head"] and evidence.get("result") == "pass"
                and evidence.get("command") == data["verification_command"]
                and all(proof.get(key) == evidence.get(key) for key in ("tested_commit", "result", "command")),
                "verification evidence changed or names a different commit")

    def record_acceptance(self, report_path):
        reviewer = self.worker(STAGES["acceptance"])
        source, data, record, report = self.verify(worker=False)
        output, output_record = self.receipt("output")
        self.validate_output(output, source, data, record, report)
        require(reviewer["bead_id"] != output["producer"]["bead_id"]
                and reviewer["session_id"] != output["producer"]["session_id"],
                "independent acceptance requires distinct native producer and reviewer sessions")
        review_record = file_record(report_path)
        self.artifact(review_record, "gc.build.review.v1", reviewer, output_record)
        acceptance = {**output, "output_sha256": output_record["sha256"],
                      "reviewer": reviewer, "verdict": "approved",
                      "review_report": review_record}
        path = Path(record["path"]).parent / (source["id"] + "." + self.step["id"] + ".acceptance.json")
        receipt = write_receipt(path, acceptance)
        self.root = self.update(self.root, {
            PREFIX + "acceptance_path": receipt["path"],
            PREFIX + "acceptance_sha256": receipt["sha256"],
            PREFIX + "review_report_path": acceptance["review_report"]["path"],
        })
        return acceptance

    def validate_acceptance(self, acceptance, source, data, record, report, reviewer_closed=True):
        output, output_record = self.receipt("output")
        self.validate_output(output, source, data, record, report)
        require(isinstance(acceptance, dict) and acceptance.get("verdict") == "approved"
                and acceptance.get("output_sha256") == output_record["sha256"]
                and all(acceptance.get(key) == value for key, value in output.items()),
                "acceptance is not bound to the current exact output")
        reviewer = acceptance.get("reviewer") or {}
        require(isinstance(reviewer, dict) and type(reviewer.get("attempt")) is int,
                "invalid independent native reviewer identity")
        bead = self.show(reviewer.get("bead_id", ""))
        require(metadata(bead).get("gc.root_bead_id") == self.root["id"]
                and metadata(bead).get("gc.step_id") == STAGES["acceptance"]
                and self.identity(bead, reviewer_closed) == reviewer
                and reviewer["bead_id"] != output["producer"]["bead_id"]
                and reviewer["session_id"] != output["producer"]["session_id"],
                "independent native acceptance identity changed")
        review_record = acceptance.get("review_report")
        require(isinstance(review_record, dict), "missing independent review evidence")
        self.artifact(review_record, "gc.build.review.v1", reviewer, output_record)

    def parent(self, parent, child_input):
        source = self.show(parent["source_anchor_id"])
        meta = metadata(source)
        healthy(source)
        require(source.get("status") == "closed" and meta.get("gc.outcome") == "pass"
                and meta.get("gc.work_outcome") == "shipped"
                and meta.get("gc.work_commit") == oid(parent["accepted_commit"])
                and meta.get("gc.root_store_ref") == parent["source_store_ref"]
                and meta.get(PREFIX + "acceptance_path") == parent["acceptance_path"]
                and meta.get(PREFIX + "acceptance_sha256") == parent["acceptance_sha256"],
                "parent has no exact native closed/shipped/pass acceptance")
        acceptance_record = {"path": parent["acceptance_path"], "sha256": parent["acceptance_sha256"]}
        acceptance = read_record(acceptance_record)
        parent_root = self.show(acceptance.get("workflow_root_id", ""))
        healthy(parent_root)
        require(meta.get("workflow_id") == parent_root["id"], "parent workflow ownership changed")
        frozen_record = {"path": meta.get(PREFIX + "input_path", ""),
                         "sha256": meta.get(PREFIX + "input_sha256", "")}
        frozen = read_record(frozen_record)
        frozen_input(frozen)
        require(frozen.get("repo_dir") == child_input["repo_dir"]
                and frozen.get("source_anchor_id") == source["id"]
                and frozen.get("source_store_ref") == parent["source_store_ref"],
                "parent belongs to a different frozen source/repository")
        context = object.__new__(Workflow)
        context.run, context.env, context.root, context.step = self.run, self.env, parent_root, self.step
        proven_source, proven_store = context.resolve_anchor()
        require(proven_source["id"] == source["id"] and proven_store == parent["source_store_ref"],
                "parent native source ownership changed")
        require(all(metadata(parent_root).get(PREFIX + key) == frozen_record[field]
                    for key, field in (("input_path", "path"), ("input_sha256", "sha256"))),
                "parent root frozen input publication changed")
        report = context.workspace(source, frozen)
        require(metadata(parent_root).get(PREFIX + "worktree_attempt_id") ==
                report["provenance"]["attempt_id"], "parent root provisioning attempt changed")
        require(report["head"] == parent["accepted_commit"], "parent accepted commit is not its current HEAD")
        context.validate_acceptance(acceptance, source, frozen, frozen_record, report)
        context.accepted_source(source, acceptance, acceptance_record)
        require(metadata(parent_root).get(PREFIX + "acceptance_path") == parent["acceptance_path"]
                and metadata(parent_root).get(PREFIX + "acceptance_sha256") == parent["acceptance_sha256"],
                "parent native acceptance readback changed")
        self.run(["git", "-C", child_input["repo_dir"], "merge-base", "--is-ancestor",
                  parent["accepted_commit"], child_input["base_sha"]])

    def check(self, phase):
        require(phase in STAGES and metadata(self.step).get("gc.step_id") == STAGES[phase],
                "check was invoked for the wrong native stage")
        self.identity(self.step, closed=True)
        source, data, record, report = self.verify(worker=False)
        if phase == "output":
            output, _ = self.receipt("output")
            self.validate_output(output, source, data, record, report)
        elif phase in {"acceptance", "close"}:
            acceptance, receipt = self.receipt("acceptance")
            self.validate_acceptance(acceptance, source, data, record, report)
            if phase == "close":
                self.accepted_source(source, acceptance, receipt)
        return report

    def accepted_source(self, source, acceptance, receipt):
        expected = {
            "gc.outcome": "pass", "gc.work_outcome": "shipped",
            "gc.work_commit": acceptance["output_commit"],
            "gc.work_verification": receipt["path"] + "#sha256:" + receipt["sha256"],
            PREFIX + "acceptance_path": receipt["path"],
            PREFIX + "acceptance_sha256": receipt["sha256"],
        }
        require(source.get("status") == "closed"
                and all(metadata(source).get(key) == value for key, value in expected.items()),
                "source accepted publication readback is not exact closed/shipped/pass")
        return expected

    def close_source(self):
        self.worker(STAGES["close"])
        source, data, record, report = self.verify(worker=False)
        acceptance, receipt = self.receipt("acceptance")
        self.validate_acceptance(acceptance, source, data, record, report)
        expected = {
            "gc.outcome": "pass", "gc.work_outcome": "shipped",
            "gc.work_commit": acceptance["output_commit"],
            "gc.work_verification": receipt["path"] + "#sha256:" + receipt["sha256"],
            PREFIX + "acceptance_path": receipt["path"],
            PREFIX + "acceptance_sha256": receipt["sha256"],
        }
        if source.get("status") == "closed":
            self.accepted_source(source, acceptance, receipt)
        else:
            source = self.update(source, expected, status="closed")
            self.accepted_source(source, acceptance, receipt)
        return acceptance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify", "publish-output",
                        "record-acceptance", "check", "close-source"))
    parser.add_argument("--bead", default=os.environ.get("GC_BEAD_ID", ""))
    parser.add_argument("--input")
    parser.add_argument("--summary")
    parser.add_argument("--verification")
    parser.add_argument("--report")
    parser.add_argument("--phase", choices=tuple(STAGES))
    args = parser.parse_args(argv)
    try:
        workflow = Workflow(args.bead)
        if args.mode == "prepare":
            result = workflow.prepare(args.input)
        elif args.mode == "verify":
            result = workflow.verify()[-1]
        elif args.mode == "publish-output":
            result = workflow.publish_output(args.summary, args.verification)
        elif args.mode == "record-acceptance":
            result = workflow.record_acceptance(args.report)
        elif args.mode == "check":
            result = workflow.check(args.phase)
        else:
            result = workflow.close_source()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Error, OSError, ValueError, TypeError, KeyError) as exc:
        print("managed-do-work: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
