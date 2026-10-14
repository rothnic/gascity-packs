#!/usr/bin/env python3
"""Run native result, canonical review and publication transitions."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile

from workspace_records import RecordError, canonical_bytes, contracts, parse_record, record_sha256
from workspace_entry import allocate_placeholder, read_entry, reference
from workspace_cooked import read_cooked_writer_map
from workspace_store import (GRANT_REFS_KEY, GRANT_KEY, WorkspaceStore, validate_cooked_writer_map,
                             NativeSourceClose, RecordWrite, ReferenceWrite, SuccessorRelation, record_reference)
from workspace_requests import retain_request, resolve_request, require_resolved_scope, allocation_directory
from workspace_runtime import NativeSourceRuntime
import workspace_outputs as outputs
import workspace_review as review
import workspace_publish as publish
import github_api


class WorkspaceFlow:
    """One admitted native attempt with original rows through guarded readback."""

    def __init__(self, runtime: NativeSourceRuntime):
        outputs.require(isinstance(runtime, NativeSourceRuntime), "an actual native source runtime is required")
        self.runtime, self.store = runtime, runtime.store
        self.run, self.plan = runtime.run, runtime.plan
        self.identity, self.attempt = runtime._admitted()
        self._writer_map = None
        self._terminated = False

    @property
    def writer_map(self):
        if self._writer_map is None:
            self._writer_map = self.runtime.writer_map
        return self._writer_map

    def record(self, kind, owner):
        return outputs.referenced_record(self.runtime._fence, kind, owner)[0]

    def _allocation(self, kind, scope_owner, reference_owner, *, generation=None):
        outputs.require(not self._terminated, "this transition ended the retained runtime; load the next source plan")
        validate_cooked_writer_map(self.writer_map, self.runtime.guard_rows,
            workflow_root_id=self.run["workflow_root_id"], store_ref=self.store.store_ref,
            record_kind=kind, claimed_step_id=self.attempt.claimed_bead_id)
        scope = dict(workflow_root_id=self.run["workflow_root_id"], generation=generation or self.plan["generation"],
                     writer_scope_id=scope_owner, record_kind=kind)
        require_resolved_scope(self.store, scope)
        root = self.store.snapshot([self.run["workflow_root_id"]])[self.run["workflow_root_id"]]
        raw = root["metadata"].get(GRANT_REFS_KEY)
        index = parse_record(raw) if raw else {"version": 1, "scopes": {}}
        scope_hash = hashlib.sha256(canonical_bytes(scope)).hexdigest()
        grant = index["scopes"].get(scope_hash)
        owner = self.store.snapshot([reference_owner])[reference_owner]
        pointer = owner["metadata"].get(contracts()[kind]["metadata_key"] + "_ref")
        if pointer:
            outputs.require(grant and grant["scope"] == scope, "record has no exact native writer grant")
            return dict(record_id=reference(pointer, kind)["bead_id"],
                        authority_id=grant["authority_id"], initial_write=False)

        # Persist an allocation boundary before each native create. A lost reply
        # leaves a pending journal; rerunning cannot allocate a duplicate.
        directory = allocation_directory(self.store)
        path = directory / (scope_hash + ".json")
        binding = dict(scope=scope, store_ref=self.store.store_ref,
                       attempt_id=self.attempt.writer_attempt_id)
        def save(value):
            fd, tmp = tempfile.mkstemp(dir=directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_bytes(value))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        with (directory / (scope_hash + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if path.exists():
                receipt = parse_record(path.read_text())
                outputs.require(receipt.get("binding") == binding and receipt.get("status") == "ready",
                                "native allocation is uncertain or belongs to another attempt; inspect its journal")
            else:
                outputs.require(grant is None, "missing record pointer under an existing grant requires the original allocation journal")
                receipt = dict(binding=binding, status="record_pending")
                save(receipt)
                receipt["record_id"] = allocate_placeholder(self.store, title="Workspace " + kind)
                receipt["status"] = "authority_pending"
                save(receipt)
                receipt["authority_id"] = allocate_placeholder(self.store, title="Workspace " + kind + " writer")
                receipt["status"] = "ready"
                save(receipt)
        return {key: receipt[key] for key in ("record_id", "authority_id")} | {"initial_write": grant is None}

    def _commit(self, prepared, payload, *, terminal=False):
        outputs.require(not self._terminated, "this transition ended the retained runtime; load the next source plan")
        if terminal:
            scope = parse_record(prepared.scope_bytes.decode())
            outputs.require(scope["record_kind"] == "source-plan"
                            and payload["generation"] == self.plan["generation"] + 1,
                            "only the next source plan can end this retained runtime")
        self.runtime._fresh()
        path, pending = retain_request(self.store, prepared)
        self.store.execute(prepared)
        resolved = self.store.resolve(prepared)
        outputs.require(resolved.get("outcome") in ("committed", "replayed"),
                        "native write is unresolved; resolve the original request without another effect: " + str(path))
        if not terminal:
            self.runtime.advance_written_rows(resolved["rows"], prepared=prepared)
        outputs.immutable_json(path.with_suffix(".receipt.json"),
            dict(outcome=resolved["outcome"], request_sha256=prepared.sha256, record_sha256=record_sha256(payload)))
        pending.unlink()
        self._terminated = terminal
        return dict(outcome=resolved["outcome"], request_sha256=prepared.sha256,
                    record_sha256=record_sha256(payload))

    def record_result(self, owner_id, member_id, output_oid, checks, independent_review, artifacts):
        result = self.runtime.make_member_result(owner_id, member_id, output_oid, checks, independent_review, artifacts)
        allocation = self._allocation("member-result", member_id, member_id)
        prepared = self.runtime.prepare_member_result(result, **allocation)
        receipt = self._commit(prepared, result)
        checkpoint = self.checkpoint_result(result)
        return dict(result=result, record_id=allocation["record_id"], receipt=receipt, checkpoint=checkpoint)

    def checkpoint_result(self, result):
        from workspace_dependency import FrozenRecords, _authority, publish_checkpoint, writer_checkpoint
        from workspace_checkout import manage_workspace
        self.runtime.qualify_native(result)
        workspace = self.record("workspace", result["workspace_owner_id"])
        if workspace["phase"] == "result":
            outputs.require(workspace["active_member_id"] == result["member_id"]
                            and workspace["input_oid"] == result["input_oid"]
                            and workspace["current_oid"] == workspace["output_oid"] == result["output_oid"],
                            "existing checkpoint differs from this exact accepted member")
            self.runtime._fresh()
            return dict(outcome="replayed", output_oid=result["output_oid"])
        frozen = FrozenRecords(self.store, self.runtime.guard_rows)
        scope = dict(workflow_root_id=result["workflow_root_id"], generation=result["generation"],
                     writer_scope_id=result["workspace_owner_id"], record_kind="workspace")
        authority_id = _authority(frozen, scope)
        outputs.require(authority_id, "checkpoint requires the existing exact workspace authority")
        frozen.ensure([authority_id])
        transfer = publish_checkpoint(frozen, self.attempt, writer_checkpoint(workspace, self.attempt),
            authority_id=authority_id, writer_map=self.writer_map,
            plan_record_id=self.runtime.plan_record_id, native_runtime=self.runtime)
        native_member = frozen.rows[result["member_id"]]
        result_ref = reference(native_member["metadata"].get("gc.workspace_result_ref"), "member-result")
        recovered = manage_workspace(self.store, self.attempt, action="recover", gc=self.runtime.gc,
            city_root=self.runtime.city_root, rig_name=self.runtime.rig_name,
            workflow_root_id=self.run["workflow_root_id"], input_convoy_id=self.runtime.input_convoy_id,
            run_record_id=self.runtime.run_record_id, plan_record_id=self.runtime.plan_record_id,
            workspace_record_id=workspace["workspace_bead_id"], evidence_dir=self.runtime.evidence_dir,
            selected_mode="new", authority_id=authority_id,
            parent=str(Path(workspace["work_dir"]).parent), allow_external_parent=True,
            launch_step_ids=(self.attempt.claimed_bead_id,), result_record_id=result_ref["bead_id"],
            writer_map=self.writer_map, writer_rows=frozen.rows, native_runtime=self.runtime,
            artifact_root=str(self.runtime.artifact_root))
        outputs.require(recovered.get("ok") is True and recovered["workspace"]["phase"] == "result"
                        and recovered["workspace"]["output_oid"] == result["output_oid"],
                        "accepted result has no exact guarded workspace checkpoint readback")
        return dict(outcome="committed", transfer=transfer, output_oid=result["output_oid"])

    def close_source(self, member_id):
        from workspace_dependency import FrozenRecords, _authority, writer_checkpoint
        result = self.record("member-result", member_id)
        scope = dict(workflow_root_id=self.run["workflow_root_id"], generation=self.plan["generation"],
                     writer_scope_id=result["workspace_owner_id"], record_kind="workspace")
        require_resolved_scope(self.store, scope)
        self.runtime.qualify_native(result)
        workspace = self.record("workspace", result["workspace_owner_id"])
        outputs.require(workspace["phase"] == "result" and workspace["active_member_id"] == member_id
                        and workspace["output_oid"] == result["output_oid"],
                        "source closure requires its exact completed workspace checkpoint")
        node = next(node for node in self.plan["nodes"] if node["owner_id"] == result["workspace_owner_id"])
        if member_id == node["member_ids"][-1]:
            output = self.record("owner-output", result["workspace_owner_id"])
            outputs.require(output["final_member_result_sha256"] == record_sha256(result),
                            "source closure requires its final accepted owner output")
        outputs.require(member_id not in (self.run["workflow_root_id"], self.runtime.input_convoy_id),
                        "a source close cannot close the workflow root or convoy")
        row = self.runtime._fence.snapshot([member_id])[member_id]
        outcome = "no-op" if result["status"] == "no_change" else "shipped"
        reason = "Accepted exact workspace result and checkpoint"
        if row["status"] == "closed":
            outputs.require(row["metadata"].get("gc.outcome") == "pass"
                            and row["metadata"].get("gc.work_outcome") == outcome
                            and (outcome == "no-op" or row["metadata"].get("gc.work_commit") == result["output_oid"])
                            and row.get("close_reason") == reason and bool(row.get("closed_by_session")),
                            "source already closed without this accepted outcome and native closure receipt")
            return dict(outcome="replayed", member_id=member_id, status="closed")
        self.runtime._fresh()
        frozen = FrozenRecords(self.store, self.runtime.guard_rows)
        authority_id = _authority(frozen, scope)
        outputs.require(authority_id, "source closure requires the existing exact workspace writer authority")
        frozen.ensure([authority_id])
        grant = parse_record(frozen.metadata(authority_id, GRANT_KEY))
        frozen.ensure([grant["attempt"]["claimed_bead_id"], grant["writer_occurrence"]["expansion_root_id"]])
        result_ref = reference(frozen.metadata(member_id, "gc.workspace_result_ref"), "member-result")
        frozen.ensure([result_ref["bead_id"]])
        checkpoint = writer_checkpoint(workspace, self.attempt)
        arguments = dict(writer_map=self.writer_map, guards=frozen.guards, expected_rows=frozen.rows,
            projections=[NativeSourceClose(member_id, result_ref["bead_id"], reason)])
        if grant["attempt"] == self.attempt.admission:
            method = self.store.write_records
        else:
            method = self.store.accept_replacement
            arguments.update(expected_grant=grant, successor_relation=SuccessorRelation(
                self.runtime.plan_record_id, self.plan["source_plan_owner_id"]))
        prepared = method(self.attempt, scope, authority_id,
            [RecordWrite("workspace", workspace["workspace_bead_id"], checkpoint)],
            [ReferenceWrite(result["workspace_owner_id"], "gc.workspace_ref",
                            record_reference("workspace", workspace["workspace_bead_id"], checkpoint))], **arguments)
        receipt = self._commit(prepared, checkpoint)
        return dict(outcome=receipt["outcome"], member_id=member_id, status="closed", request_sha256=prepared.sha256)

    def owner_output(self, owner_id, integration_evidence_path=None):
        nodes = [node for node in self.plan["nodes"] if node["owner_id"] == owner_id]
        outputs.require(len(nodes) == 1, "owner is absent from the current source plan")
        results = [self.record("member-result", member) for member in nodes[0]["member_ids"]]
        qualifications = {}
        for result in results:
            native = self.runtime.qualify_native(result)
            context = self.runtime.acceptance_context(result, native)
            qualifications[result["member_id"]] = {key: context[key] for key in ("binding", "required_checks")}
        workspace = self.record("workspace", owner_id)
        evidence = None
        if workspace["strategy"] == "integration":
            outputs.require(integration_evidence_path, "integration owner requires the actual bridge receipt")
            evidence = outputs.artifact(integration_evidence_path, self.runtime.artifact_root)
        output = outputs.make_owner_output(self.plan, results, artifact_root=self.runtime.artifact_root,
            qualifications=qualifications, integration_inputs=workspace["integration_inputs"],
            integration_evidence=evidence)
        allocation = self._allocation("owner-output", owner_id, owner_id)
        prepared = outputs.prepare_owner_output(self.store, self.attempt, output,
            plan_owner_id=self.plan["source_plan_owner_id"], qualifications=qualifications,
            artifact_root=self.runtime.artifact_root, qualify_native=self.runtime.qualify_native,
            writer_map=self.writer_map, **allocation)
        return dict(output=output, receipt=self._commit(prepared, output))

    def subject(self):
        terminal = outputs.terminal_node(self.plan)
        result = self.record("member-result", terminal["member_ids"][-1])
        native = self.runtime.qualify_native(result)
        context = self.runtime.acceptance_context(result, native)
        return result, context

    def canonical(self, summary_path):
        result, context = self.subject()
        owner_id = result["workspace_owner_id"]
        allocation = self._allocation("canonical", self.plan["source_plan_owner_id"], self.run["workflow_root_id"])
        prepared = outputs.prepare_canonical(self.store, self.attempt,
            run_owner_id=self.run["workflow_root_id"], plan_owner_id=self.plan["source_plan_owner_id"],
            output_owner_id=owner_id, result_member_id=result["member_id"],
            summary=outputs.artifact(summary_path, self.runtime.artifact_root),
            artifact_root=self.runtime.artifact_root, qualify_native=self.runtime.qualify_native,
            writer_map=self.writer_map, **context, **allocation)
        payload = parse_record(prepared.after_bytes.decode())[allocation["record_id"]]["metadata"][contracts()["canonical"]["metadata_key"]]
        payload = parse_record(payload)
        return dict(canonical=payload, receipt=self._commit(prepared, payload))

    def begin_canonical_review(self):
        result, context = self.subject()
        canonical = self.record("canonical", self.run["workflow_root_id"])
        return review.begin_canonical_review(canonical, result, artifact_root=self.runtime.artifact_root,
            reviewer=self.identity, **context)

    def complete_canonical_review(self, context, report, evidence_path, status="passed"):
        result, current = self.subject()
        canonical = self.record("canonical", self.run["workflow_root_id"])
        outputs.require(context["context"]["reviewer"] == self.identity,
                        "canonical review belongs to another native attempt")
        approval = review.finish_canonical_review(context, canonical, result,
            writer_step_id=self.attempt.claimed_bead_id, review_id=self.attempt.claimed_bead_id,
            artifact_root=self.runtime.artifact_root, work_dir=current["work_dir"],
            report=report, evidence_path=evidence_path, status=status)
        allocation = self._allocation("review", approval["review_id"], self.run["workflow_root_id"])
        prepared = review.prepare_review_record(self.store, self.attempt, approval,
            result_member_id=result["member_id"], artifact_root=self.runtime.artifact_root,
            plan_owner_id=self.plan["source_plan_owner_id"], qualify_native=self.runtime.qualify_native,
            writer_map=self.writer_map, **current, **allocation)
        return dict(review=approval, receipt=self._commit(prepared, approval))

    def approved_subject(self, review_owner_id=None):
        result, context = self.subject()
        canonical = self.record("canonical", self.run["workflow_root_id"])
        approval = self.record("review", review_owner_id or self.run["workflow_root_id"])
        review.validate_approval(approval, canonical, result,
                                artifact_root=self.runtime.artifact_root, **context)
        _, rows = read_cooked_writer_map(self.runtime._fence,
            workflow_root_id=self.run["workflow_root_id"], claimed_step_id=approval["writer_step_id"])
        self.runtime._fence.retain(rows)
        native_reviewer, _ = self.runtime._session(rows[approval["writer_step_id"]])
        proof = outputs.read_artifact({"path": approval["report_path"], "sha256": approval["report_sha256"]},
                                     self.runtime.artifact_root)
        outputs.require(proof["reviewer"] == native_reviewer, "canonical approval lost its actual native reviewer identity")
        self.runtime._fresh()
        return canonical, approval, result, context

    def fix_plan(self, nodes, owner_id, terminal_owner_id, implementation_convoy_id, max_iterations):
        from workspace_source_plan import declare_plan
        self.subject()
        canonical = self.record("canonical", self.run["workflow_root_id"])
        findings = self.record("review", self.run["workflow_root_id"])
        outputs.require(findings["verdict"] == "changes_required", "fix generation requires current blocking canonical findings")
        plan = review.fix_plan(canonical, findings, self.plan,
            writer_step_id=self.attempt.claimed_bead_id, source_plan_owner_id=owner_id,
            nodes=nodes, terminal_owner_id=terminal_owner_id, max_iterations=max_iterations)
        allocation = self._allocation("source-plan", owner_id, owner_id, generation=plan["generation"])
        self.runtime._fresh()
        prepared = declare_plan(self.store, self.attempt, plan,
            run_record_id=self.runtime.run_record_id, record_bead_id=allocation["record_id"],
            authority_id=allocation["authority_id"], implementation_convoy_id=implementation_convoy_id,
            writer_map=self.writer_map, writer_rows=self.runtime.guard_rows)
        receipt = self._commit(prepared, plan, terminal=True)
        return dict(source_plan=plan, receipt=receipt)

    def publication(self, review_owner_id, decision_path, *, title_path=None, body_path=None):
        canonical, approval, result, context = self.approved_subject(review_owner_id)
        root = self.runtime._fence.snapshot([self.run["workflow_root_id"]])[self.run["workflow_root_id"]]
        metadata = root["metadata"]
        if (metadata.get("gc.var.push", "false") == "false"
                and metadata.get("gc.var.open_pr", "false") == "false"
                and metadata.get("gc.var.pr_mode", "none") == "none"):
            self.runtime._fresh()
            return dict(status="disabled", output_oid=result["output_oid"], canonical_sha256=record_sha256(canonical))
        outputs.require(decision_path, "authorized publication requires its existing exact authority decision")
        decision_ref = outputs.artifact(decision_path, self.runtime.artifact_root)
        decision = outputs.read_artifact(decision_ref, self.runtime.artifact_root)
        outputs.require(not decision.get("push") or metadata.get("gc.var.push") == "true",
                        "native launch did not authorize pushing")
        outputs.require(not decision.get("open_pr") or metadata.get("gc.var.open_pr") == "true"
                        or metadata.get("gc.var.pr_mode") in ("draft", "ready"),
                        "native launch did not authorize PR creation")
        publish_id = self.attempt.claimed_bead_id
        row = self.store.snapshot([publish_id])[publish_id]
        pointer = row["metadata"].get(contracts()["publish"]["metadata_key"] + "_ref")
        intent = self.record("publish", publish_id) if pointer else publish.publication_intent(
            canonical, approval, result, artifact_root=self.runtime.artifact_root,
            authorization=dict(push=decision["push"], open_pr=decision["open_pr"],
                               decision_path=decision_ref["path"], decision_sha256=decision_ref["sha256"]),
            remote=decision["remote"], ref=decision["ref"], publish_id=publish_id,
            writer_step_id=publish_id, **context)
        def current():
            return outputs.referenced_record(self.store, "canonical", self.run["workflow_root_id"])[0]
        def provider_readback(value):
            spec = decision["pr_spec"]
            outputs.require(github_api.actor()["login"] == spec["actor"], "authenticated publication actor changed")
            found = github_api.pr_search(spec["repo"], spec["marker"], author=spec["actor"])
            prs = []
            for item in found["items"]:
                actual = github_api.pr_snapshot(item["url"])
                if spec["marker"] in actual["body"]:
                    detail = github_api.require_object(github_api.gh_api([
                        f"repos/{actual['repo']}/pulls/{actual['number']}"]))
                    prs.append(dict(repo=actual["base_repo"], base=actual["base_ref"],
                        actor=actual["author"], marker=spec["marker"], head_oid=actual["head_sha"],
                        mode="draft" if detail.get("draft") is True else "ready", url=actual["canonical_url"]))
            return dict(pr_spec=spec, prs=prs)
        def persist(value):
            allocation = self._allocation("publish", publish_id, publish_id)
            prepared = publish.prepare_publication_record(self.store, self.attempt, value,
                review_owner_id=review_owner_id, result_member_id=result["member_id"],
                artifact_root=self.runtime.artifact_root, plan_owner_id=self.plan["source_plan_owner_id"],
                qualify_native=self.runtime.qualify_native, writer_map=self.writer_map,
                publication_readback=provider_readback, **context, **allocation)
            return self._commit(prepared, value)
        if not pointer:
            persist(intent)
        value = publish.push_publication(intent, canonical=canonical, approval=approval, result=result,
            artifact_root=self.runtime.artifact_root, persist=persist, current=current, **context)
        if value["authorization"]["open_pr"]:
            spec = decision["pr_spec"]
            observed = provider_readback(value)
            value = publish.reconcile_publication(value,
                remote_oid=publish.remote_oid(context["work_dir"], decision["remote_url"], value["ref"]), **observed)
            if value["status"] != "observed" and not observed["prs"]:
                outputs.require(title_path and body_path, "PR creation requires sanitized title and body files")
                body = Path(body_path).read_text()
                outputs.require(spec["marker"] in body, "PR body lacks the authorized reservation marker")
                reservation = publish.reserve_pr_attempt(value, spec,
                    self.runtime.artifact_root / ("pr-attempt-" + publish_id + ".json"),
                    canonical=canonical, approval=approval, result=result,
                    artifact_root=self.runtime.artifact_root, current=current, **context)
                if reservation["create_allowed"]:
                    github_api.pr_create(spec["repo"], head=value["ref"].removeprefix("refs/heads/"),
                        base=spec["base"], title_path=Path(title_path), body_path=Path(body_path), draft=spec["mode"] == "draft")
                value = publish.reconcile_publication(value,
                    remote_oid=publish.remote_oid(context["work_dir"], decision["remote_url"], value["ref"]),
                    **provider_readback(value))
            persist(value)
        return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("action", choices=("record-result", "owner-output", "canonical", "begin-canonical-review",
                                         "complete-canonical-review", "publish", "verify", "artifacts", "close-source", "fix-plan", "inspect", "resolve-write"))
    for name in ("city-root", "store-ref", "rig-name", "workflow-root-id", "claimed-step-id", "artifact-root", "evidence-dir"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--gc", default="gc")
    parser.add_argument("--generation", type=int, required=True)
    for name in ("owner-id", "member-id", "output-oid", "checks", "review", "artifacts", "summary", "context",
                 "report", "review-evidence", "review-owner-id", "decision", "title-file", "body-file", "integration-evidence"):
        parser.add_argument("--" + name)
    parser.add_argument("--status", choices=sorted(outputs.STATUSES), default="passed")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--nodes")
    parser.add_argument("--plan-owner-id")
    parser.add_argument("--terminal-owner-id")
    parser.add_argument("--implementation-convoy-id")
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--prepared-request")
    args = parser.parse_args(argv)
    def read(path):
        outputs.require(path, "action requires its evidence artifact")
        return parse_record('{"value":' + Path(path).read_text() + '}')["value"]
    try:
        store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city_root)
        if args.action == "resolve-write":
            outputs.require(args.prepared_request, "resolve-write requires the original retained request path")
            value = resolve_request(store, args.prepared_request)
            print(json.dumps(value, sort_keys=True))
            return 0 if value.get("outcome") in ("committed", "replayed") else 1
        entry = read_entry(store, gc=args.gc, city_root=args.city_root, rig_name=args.rig_name,
            workflow_root_id=args.workflow_root_id, claimed_step_id=args.claimed_step_id,
            worktree_lifecycle="new", generation=args.generation, require_plan=True)
        store.common_git_dir = entry["run"]["common_git_dir"]
        native = NativeSourceRuntime(store, gc=args.gc, city_root=args.city_root, rig_name=args.rig_name,
            run=entry["run"], plan=entry["source_plan"], artifact_root=args.artifact_root,
            evidence_dir=args.evidence_dir, claimed_step_id=args.claimed_step_id,
            native_rows=entry["_native_rows"])
        flow = WorkspaceFlow(native)
        if args.action == "record-result":
            value = flow.record_result(args.owner_id, args.member_id, args.output_oid,
                                       read(args.checks), read(args.review), read(args.artifacts))
        elif args.action == "owner-output":
            value = flow.owner_output(args.owner_id, args.integration_evidence)
        elif args.action == "canonical":
            outputs.require(args.summary, "canonical requires its accepted terminal summary")
            value = flow.canonical(args.summary)
        elif args.action == "begin-canonical-review":
            value = flow.begin_canonical_review()
        elif args.action == "complete-canonical-review":
            value = flow.complete_canonical_review(read(args.context), args.report, args.review_evidence, args.status)
        elif args.action == "publish":
            value = flow.publication(args.review_owner_id or args.workflow_root_id, args.decision,
                                     title_path=args.title_file, body_path=args.body_file)
        elif args.action == "artifacts":
            outputs.require(args.artifact, "artifacts requires at least one actual artifact path")
            value = [outputs.artifact(path, native.artifact_root) for path in args.artifact]
        elif args.action == "close-source":
            outputs.require(args.member_id, "source closure requires its exact member")
            value = flow.close_source(args.member_id)
        elif args.action == "fix-plan":
            outputs.require(args.plan_owner_id and args.terminal_owner_id and args.implementation_convoy_id,
                            "fix plan requires its actual native owner, terminal and implementation convoy")
            value = flow.fix_plan(read(args.nodes), args.plan_owner_id, args.terminal_owner_id,
                                  args.implementation_convoy_id, args.max_iterations)
        elif args.action == "inspect":
            result, context = flow.subject()
            canonical = flow.record("canonical", native.run["workflow_root_id"])
            review.canonical_subject(canonical, result, artifact_root=native.artifact_root, **context)
            value = dict(ok=True, output_oid=result["output_oid"], canonical_sha256=record_sha256(canonical))
        else:
            canonical, approval, result, context = flow.approved_subject(args.review_owner_id)
            value = dict(ok=True, output_oid=result["output_oid"], policy_binding=native.policy_binding)
        print(json.dumps(value, sort_keys=True))
        if args.action == "complete-canonical-review" and value["review"]["verdict"] != "approved":
            return 1
        if args.action == "publish" and value["status"] not in ("observed", "disabled"):
            return 1
        return 0
    except (RecordError, OSError, KeyError, TypeError, ValueError) as exc:
        import sys
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
