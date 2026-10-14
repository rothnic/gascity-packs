"""Command-port fixtures and real Git; native worker acceptance remains unrun."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import workspace_runtime as runtime
import workspace_outputs as outputs
from workspace_records import RecordError, canonical_bytes, contracts, record_identity, record_sha256
from workspace_run import capture_check_policy
from workspace_store import (Attempt, CONTINUATION_KEY, GRANT_KEY, InheritedRunReference,
                             NativeOwnerProjection, NativeWorktreeReference, OWNER_PROJECTION_KEYS,
                             RecordWrite, ReferenceWrite, SuccessorRelation, WorkspaceStore, TOPOLOGY)


PORT = r'''#!/usr/bin/env python3
import copy, json, pathlib, subprocess, sys
state_path = pathlib.Path(__file__).with_name('port.json')
data = json.loads(state_path.read_text())
args = sys.argv[1:]
with state_path.with_suffix('.commands').open('a') as log:
    log.write(json.dumps(args) + '\n')
def option(name):
    for i, arg in enumerate(args):
        if arg == '--' + name: return args[i + 1]
        if arg.startswith('--' + name + '='): return arg.split('=', 1)[1]
def emit(value):
    print(json.dumps(value)); sys.exit(0)
if 'rig' in args:
    emit(dict(city_name='fixture', city_path=data['city'], rigs=[dict(name='fixture', path=data['repo'])]))
if 'guarded-metadata-batch' in args:
    store = option('store-ref')
    rows = data['stores'][store]
    if option('snapshot'):
        if data.get('block_readback'): sys.exit('fixture readback unavailable')
        result = [rows[i] for i in option('snapshot').split(',')]
    else:
        request = json.loads(pathlib.Path(option('request')).read_text())
        for item in request['rows']:
            row = rows[item['id']]
            if row['revision'] != item['expected_revision'] or row['status'] != item.get('expected_status', row['status']) or row['assignee'] != item.get('expected_assignee', row['assignee']):
                sys.exit('original row guard changed')
        result = []
        for item in request['rows']:
            row = rows[item['id']]
            changes = item.get('set', {})
            changed = bool(changes)
            row['metadata'].update(changes)
            for key in item.get('delete', []): row['metadata'].pop(key, None)
            if changed: row['revision'] = str(int(row['revision']) + 1)
            result.append(dict(id=item['id'], revision=row['revision'], changed=changed))
        if data.get('lose_write_ack'):
            data['block_readback'] = True
            state_path.write_text(json.dumps(data))
            sys.exit('fixture committed write but lost acknowledgement')
        state_path.write_text(json.dumps(data))
    emit(dict(schema_version='1', ok=True, store_ref=store, rows=result))
if 'list' in args and 'bd' in args:
    key, value = option('metadata-field').split('=', 1)
    emit([row for row in data['stores']['rig:fixture'].values() if row['metadata'].get(key) == value])
if 'formula' in args:
    emit(data['formula'])
if 'worktree' in args:
    if '--help' in args:
        print('--repo --root --path --branch --mode --base --base-sha --bead --store-ref --creator --owner --generation --lifecycle --placement --json')
        sys.exit(0)
    if args[args.index('worktree') + 1] != 'verify': sys.exit('read-only port cannot provision')
    path = option('path')
    head = subprocess.check_output(['git', '-C', path, 'rev-parse', 'HEAD'], text=True).strip()
    emit(dict(schema_version='1', ok=True, command='worktree verify', action='verify', path=path,
        branch=option('branch'), mode=option('mode'), placement=option('placement') or 'outside-worktrees',
        head=head, created=False, branch_created=False, provenance=data.get('provenances', {}).get(path, data['provenance'])))
sys.exit('unsupported command ' + repr(args))
'''


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Retain fixtures and exact command logs, including failed cases.
        self.root = Path(tempfile.mkdtemp(prefix="native-runtime-", dir=os.environ.get("TMPDIR")))
        self.city = self.root / "city"
        self.repo = self.root / "project"
        self.work = self.root / "workspaces" / "member"
        self.artifacts = self.root / "artifacts"
        self.diagnostics = self.root / "diagnostics"
        for path in (self.city, self.repo, self.artifacts, self.diagnostics, self.work.parent):
            path.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "feature.py").write_text("VALUE = 0\n")
        self.git(self.repo, "add", "feature.py")
        self.git(self.repo, "commit", "-qm", "base")
        self.base = self.git(self.repo, "rev-parse", "HEAD")
        self.git(self.repo, "worktree", "add", "--detach", str(self.work), self.base)
        (self.work / "feature.py").write_text("VALUE = 42\n")
        self.git(self.work, "add", "feature.py")
        self.git(self.work, "commit", "-qm", "result")
        self.oid = self.git(self.work, "rev-parse", "HEAD")
        self.requirements = [{"id": "VALUE-42", "argv": [sys.executable, "-B", "-c", "from feature import VALUE; assert VALUE == 42"]}]
        fixture = json.loads((SCRIPTS.parents[1] / "tests/fixtures/workspace-records/valid.json").read_text())
        self.run = dict(fixture["run"], workflow_root_id="root", input_convoy_id="convoy", source_anchor_id="convoy",
            rig_root=str(self.repo), common_git_dir=str(self.repo / ".git"), base_oid=self.base, worktree_lifecycle="new")
        self.plan = dict(fixture["source-plan"], workflow_root_id="root", source_plan_owner_id="plan-owner",
            base_oid=self.base, nodes=[dict(owner_id="member", strategy="isolated", member_ids=["member"],
                source_predecessor_owner_ids=[], single_lane=False)], terminal_owner_id="member")
        self.provenance = dict(schema_version=2, bead_id="workspace-record", store_ref="rig:fixture",
            repo_identity=self.run["common_git_dir"], path=str(self.work), branch="", mode="detached", placement="outside-worktrees",
            base_ref=self.base, base_sha=self.base, creator="gascity.workspace.v1", owner="member", generation="1",
            created_at="2026-10-14T00:00:00Z", lifecycle="active", attempt_id="native-attempt-1")
        self.provenances = {}
        self.attempts = {role: Attempt(role + "-session", role + "-private-instance", role) for role in
                         ("producer", "reviewer", "recorder")}
        self.workspace = dict(fixture["workspace"], workflow_root_id="root", source_plan_owner_id="plan-owner",
            workspace_owner_id="member", workspace_bead_id="workspace-record", strategy="isolated", work_dir=str(self.work),
            work_branch=None, phase="result", input_oid=self.base, current_oid=self.oid, output_oid=self.oid,
            active_member_id="member", next_member_position=0, integration_inputs=None, writer_step_id="producer",
            writer_attempt_id=self.attempts["producer"].writer_attempt_id,
            native_attempt_id="native-attempt-1", native_provenance=self.provenance)
        self.workspace["claim_binding"] = {key: self.workspace[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        self.rows = {key: self.row(key) for key in ("root", "convoy", "plan-owner", "member", "expansion")}
        self.rows["root"]["metadata"].update({"gc.kind": "workflow", "gc.input_convoy_id": "convoy",
            "gc.var.worktree_checks": canonical_bytes({"required_checks": self.requirements}).decode(),
            "gc.implementation_run_ref": self.ref("run", "run-record", self.run)})
        self.rows["convoy"]["type"] = "convoy"
        for key in ("convoy", "plan-owner", "member"):
            self.rows[key]["metadata"].update({"gc.source_root_id": "root", "gc.source_generation": "1"})
        self.rows["convoy"]["metadata"]["gc.source_plan_owner_id"] = "plan-owner"
        self.rows["plan-owner"]["metadata"]["gc.source_plan_ref"] = self.ref("source-plan", "plan-record", self.plan)
        self.rows["member"]["metadata"]["gc.workspace_ref"] = self.ref("workspace", "workspace-record", self.workspace)
        for kind, key, payload in (("run", "run-record", self.run), ("source-plan", "plan-record", self.plan),
                                   ("workspace", "workspace-record", self.workspace)):
            self.rows[key] = self.row(key, {contracts()[kind]["metadata_key"]: canonical_bytes(payload).decode()}, status="closed", scoped=False)
        self.rows["run-record"]["metadata"]["gc.workspace_required_checks.v1"] = canonical_bytes(
            capture_check_policy(self.run, "run-record", self.rows["root"]["metadata"]["gc.var.worktree_checks"])).decode()
        owner_metadata = {"gc.worktree_repo": str(self.repo), "gc.worktree_root": str(self.work.parent),
            "gc.work_dir": str(self.work), "gc.work_branch": "", "gc.worktree_base_ref": self.base,
            "gc.worktree_base_sha": self.base, "gc.worktree_creator": "gascity.workspace.v1", "gc.worktree_owner": "member",
            "gc.worktree_generation": "1", "gc.worktree_lifecycle": "active", "gc.worktree_mode": "detached",
            "gc.worktree_placement": "outside-worktrees", "gc.root_bead_id": "root", "gc.root_store_ref": "rig:fixture"}
        self.rows["workspace-record"]["metadata"].update(owner_metadata)
        formula_path = self.root / "do-work.formula.toml"
        formula_path.write_text('formula = "do-work"\n')
        self.formula_path = formula_path
        self.rows["expansion"]["metadata"].update({"gc.formula_name": "do-work", "gc.formula_hash": hashlib.sha256(formula_path.read_bytes()).hexdigest(),
            "gc.formula_source": str(formula_path)})
        self.formula = {"ok": True, "name": "do-work", "steps": [], "deps": []}
        previous = None
        self.sessions = {}
        for role, stage, target in (("producer", "implement", "gc.implementation-worker"),
                                   ("reviewer", "independent-acceptance", "gc.implementation-reviewer"),
                                   ("recorder", "record-result", "gc.run-operator")):
            ref = "do-work." + stage
            metadata = {"gc.run_target": target}
            if role == "producer": metadata["gc.build.artifact_schema"] = "gc.build.implementation-summary.v1"
            step_meta = dict(metadata, **{"gc.step_id": ref, "gc.step_ref": ref, "gc.attach_root_id": "expansion",
                "gc.source_anchor_id": "member", "gc.drain_member_id": "member", "gc.session_id": role + "-session",
                "gc.session_name": role + "-runtime", TOPOLOGY: canonical_bytes([previous] if previous else []).decode()})
            self.rows[role] = self.row(role, step_meta, status="closed" if role != "recorder" else "in_progress")
            if role != "recorder": self.rows[role]["metadata"]["gc.outcome"] = "pass"
            else: self.rows[role]["assignee"] = "recorder-session"
            self.formula["steps"].append({"id": ref, "metadata": metadata})
            if previous: self.formula["deps"].append(dict(step_id=ref, depends_on_id=previous, type="blocks"))
            previous = ref
            session = self.row(role + "-session", {"template": "fixture/" + target, "session_name": role + "-runtime",
                "instance_token": self.attempts[role].instance_token, "session_origin": "ephemeral",
                "state": "active" if role == "recorder" else "asleep", "current_claim_bead_id": role if role == "recorder" else ""}, scoped=False)
            session["type"] = "session"
            self.sessions[session["id"]] = session
        launch = dict(version=1, binding_step_id="producer", workflow_root_id="root", generation=1,
            workspace_owner_id="member", workspace_bead_id="workspace-record", store_ref="rig:fixture", native_attempt_id="native-attempt-1")
        self.rows["producer"]["metadata"]["gc.worktree_ref"] = canonical_bytes(launch).decode()
        self.port = self.root / "gc-port"
        self.port.write_text(PORT)
        self.port.chmod(0o700)
        self.save()
        self.store = WorkspaceStore("rig:fixture", gc=str(self.port), cwd=self.city, common_git_dir=self.repo / ".git")
        self.environment = patch.dict(os.environ, {"GC_SESSION_ID": self.attempts["recorder"].session_id,
            "GC_INSTANCE_TOKEN": self.attempts["recorder"].instance_token, "PYTHONDONTWRITEBYTECODE": "1"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.binding = outputs.result_binding(self.run, self.plan, self.workspace, store_ref="rig:fixture", member_id="member", output_oid=self.oid)
        self.summary = self.artifacts / "summary.md"
        self.summary.write_text("VALUE-42 is implemented.\n")
        producer = self.identity("producer")
        checks = outputs.execute_checks(self.binding, self.work, self.requirements, producer, self.artifacts / "checks")
        self.policy_binding = dict(run_record_id="run-record", base_oid=self.base,
            policy_sha256=outputs.check_scope(self.requirements), run_sha256=record_sha256(self.run), source_plan_sha256=record_sha256(self.plan))
        for position, check in enumerate(checks):
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifacts)
            bound = outputs.immutable_json(self.artifacts / f"native-check-{position}.json", dict(proof, policy_binding=self.policy_binding))
            check.update(evidence_path=bound["path"], evidence_sha256=bound["sha256"])
        context = outputs.begin_review(self.binding, self.work, checks, self.requirements, producer,
            self.identity("reviewer"), [outputs.artifact(self.summary, self.artifacts)], self.artifacts)
        context["policy_binding"] = self.policy_binding
        report = self.artifacts / "report.md"
        report.write_text("Inspect exact source and required command result.\n")
        review = outputs.complete_review(context, self.work, report, "passed", self.artifacts / "review.json", self.artifacts)
        self.result = outputs.make_member_result(self.binding, writer_step_id="recorder", commit_oids=[self.oid], checks=checks,
            review=review, artifacts=[outputs.artifact(self.summary, self.artifacts)], required_checks=self.requirements,
            artifact_root=self.artifacts, work_dir=self.work)

    def git(self, path, *args):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_NAME="Fixture",
                   GIT_COMMITTER_EMAIL="fixture@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        return subprocess.check_output(["git", "-C", str(path), *args], env=env, stderr=subprocess.PIPE,
                                       text=True, timeout=10).strip()

    def row(self, key, metadata=None, status="open", scoped=True):
        return dict(id=key, revision="1", status=status, assignee="", type="task", labels=[], metadata={
            **({"gc.root_bead_id": "root", "gc.root_store_ref": "rig:fixture"} if scoped else {}), **(metadata or {})})

    def ref(self, kind, key, payload):
        return canonical_bytes(dict(kind=kind, bead_id=key, identity=list(record_identity(kind, payload)))).decode()

    def identity(self, role):
        attempt = self.attempts[role]
        return dict(step_id=role, session_id=attempt.session_id, attempt_id=attempt.writer_attempt_id)

    def save(self):
        (self.root / "port.json").write_text(json.dumps(dict(city=str(self.city), repo=str(self.repo),
            stores={"rig:fixture": self.rows, "city:fixture": self.sessions}, formula=self.formula,
            provenance=self.provenance, provenances=self.provenances)))

    def adapter(self, claimed="recorder"):
        return runtime.NativeSourceRuntime(self.store, gc=str(self.port), city_root=str(self.city), rig_name="fixture",
            run=self.run, plan=self.plan, artifact_root=self.artifacts, evidence_dir=str(self.diagnostics), claimed_step_id=claimed)

    def select_role(self, selected):
        for role in self.attempts:
            active = role == selected
            self.rows[role]["status"] = "in_progress" if active else "closed"
            self.rows[role]["assignee"] = role + "-session" if active else ""
            self.rows[role]["metadata"].pop("gc.outcome", None)
            if not active: self.rows[role]["metadata"]["gc.outcome"] = "pass"
            self.sessions[role + "-session"]["metadata"].update(state="active" if active else "asleep",
                current_claim_bead_id=role if active else "")
        os.environ.update(GC_SESSION_ID=self.attempts[selected].session_id,
                          GC_INSTANCE_TOKEN=self.attempts[selected].instance_token)
        self.save()

    def native_child(self, child="child", member="member", *, roles=None, expansion="expansion", published=True):
        roles = roles or tuple(self.attempts)
        control, unit = child + "-control", child + "-unit"
        self.rows["root"]["metadata"]["gc.build.implementation_convoy_id"] = "convoy"
        self.rows["convoy"]["metadata"]["gc.source_plan_sha256"] = record_sha256(self.plan)
        self.rows[control] = self.row(control, {"gc.kind": "drain"})
        self.rows[unit] = self.row(unit, {"gc.synthetic_kind": "drain-unit-convoy", "gc.parent_convoy_id": "convoy",
            "gc.drain_control_id": control, "gc.drain_member_id": member})
        self.rows[unit]["type"] = "convoy"
        self.rows[child] = self.row(child, {"gc.kind": "workflow", "gc.root_bead_id": child,
            "gc.input_convoy_id": unit, "gc.drain_control_id": control, "gc.drain_member_id": member})
        self.rows[expansion]["metadata"]["gc.root_bead_id"] = child
        for role in roles:
            self.rows[role]["metadata"].update({"gc.root_bead_id": child,
                "gc.source_anchor_id": member, "gc.drain_member_id": member})
            raw = self.rows[role]["metadata"].get("gc.worktree_ref")
            if raw:
                ref = json.loads(raw)
                ref["workflow_root_id"] = child
                self.rows[role]["metadata"]["gc.worktree_ref"] = canonical_bytes(ref).decode()
        self.save()
        from workspace_entry import read_native_continuation
        continuation, _ = read_native_continuation(self.store, claimed_step_id=roles[0], requested_root_id="root")
        if published:
            self.rows[child]["metadata"].update({
                "gc.implementation_run_ref": self.ref("run", "run-record", self.run),
                CONTINUATION_KEY: continuation.binding_bytes.decode()})
        self.save()
        return continuation

    def publish_child_workspace(self):
        continuation = self.native_child(published=False)
        owner = copy.deepcopy(self.rows["workspace-record"]["metadata"])
        owner.pop(contracts()["workspace"]["metadata_key"])
        owner["gc.root_bead_id"] = continuation.binding["child_root_id"]
        self.rows["workspace-record"] = self.row("workspace-record", status="closed", scoped=False)
        self.rows["workspace-authority"] = self.row("workspace-authority", status="closed", scoped=False)
        self.rows["member"]["metadata"].pop("gc.workspace_ref")
        launch = json.loads(self.rows["producer"]["metadata"].pop("gc.worktree_ref"))
        self.select_role("producer")
        adapter = self.adapter("producer")
        writer_map = adapter.writer_map
        adapter._fence.snapshot(["workspace-record", "workspace-authority"])
        scope = dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="workspace")
        writes = [RecordWrite("workspace", "workspace-record", self.workspace)]
        refs = [ReferenceWrite("member", "gc.workspace_ref", json.loads(self.ref("workspace", "workspace-record", self.workspace)))]
        projections = [InheritedRunReference(continuation), NativeOwnerProjection("workspace-record", owner),
                       NativeWorktreeReference("producer", "workspace-record", launch)]
        prepared = self.store.install_grant(self.attempts["producer"], scope, "workspace-authority", writes,
            references=refs, projections=projections, writer_map=writer_map,
            expected_rows=adapter.guard_rows, guards=adapter.guards)
        intended = json.loads(prepared.after_bytes)
        self.assertIn(CONTINUATION_KEY, intended["child"]["metadata"])
        self.assertEqual(intended["workspace-record"]["metadata"]["gc.root_bead_id"], "child")
        for key in continuation.row_ids:
            self.assertIn(key, {row["id"] for row in prepared.request["rows"]})
        self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
        resolved = self.store.resolve(prepared)
        adapter.advance_written_rows(resolved["rows"], prepared=prepared)
        state = json.loads((self.root / "port.json").read_text())
        self.rows, self.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
        adapter.recheck_continuation()
        return continuation

    def test_native_child_entry_preserves_logical_run_and_actual_physical_occurrences(self):
        continuation = self.native_child()
        self.rows["workspace-record"]["metadata"]["gc.root_bead_id"] = "child"
        self.save()
        adapter = self.adapter()
        self.assertEqual(adapter.continuation, continuation)
        self.assertEqual(adapter.native_workflow_root_id, "child")
        self.assertEqual(adapter.native_input_convoy_id, "child-unit")
        self.assertEqual(adapter.run["workflow_root_id"], "root")
        self.assertEqual(adapter.plan["workflow_root_id"], "root")
        self.assertEqual(adapter.writer_map.continuation, continuation)
        self.assertEqual(adapter.retained_workspace_continuation(self.workspace), continuation)
        self.assertEqual(adapter._fence.read_record("workspace", "workspace-record"), self.workspace)
        self.assertEqual(adapter.guard_rows["producer"]["metadata"]["gc.root_bead_id"], "child")
        adapter.recheck_continuation()

    def test_native_child_initial_workspace_and_real_acceptance_pipeline(self):
        self.publish_child_workspace()
        result = self.run_acceptance_pipeline()
        from workspace_flow import WorkspaceFlow
        flow = WorkspaceFlow(self.adapter())
        replay = flow.record_result("member", "member", self.oid, result["acceptance"]["project_checks"],
            result["acceptance"]["independent_review"], result["acceptance"]["artifacts"])
        self.assertEqual(replay["result"], result)
        self.assertEqual(replay["checkpoint"]["outcome"], "replayed")
        self.assertEqual(flow.runtime.writer_map.continuation.binding["child_root_id"], "child")

    def next_child_workspace(self, result):
        """Advance the actual writer grant and native owner through declared adjacency."""
        self.rows["member-next"] = self.row("member-next", {"gc.source_root_id": "root", "gc.source_generation": "1"})
        self.rows["next-expansion"] = copy.deepcopy(self.rows["expansion"])
        self.rows["next-expansion"]["id"] = "next-expansion"
        for role in ("producer", "reviewer", "recorder"):
            key = "next-" + role
            attempt = Attempt(key + "-session", key + "-private-instance", key)
            self.attempts[key] = attempt
            row = copy.deepcopy(self.rows[role])
            row["id"] = key
            row["metadata"].update({"gc.attach_root_id": "next-expansion", "gc.session_id": attempt.session_id,
                                     "gc.session_name": key + "-runtime"})
            row["metadata"].pop("gc.worktree_ref", None)
            self.rows[key] = row
            session = copy.deepcopy(self.sessions[role + "-session"])
            session["id"] = attempt.session_id
            session["metadata"].update(instance_token=attempt.instance_token, session_name=key + "-runtime")
            self.sessions[session["id"]] = session
        self.native_child("next-child", "member-next", roles=("next-producer", "next-reviewer", "next-recorder"),
                          expansion="next-expansion", published=False)
        self.select_role("next-producer")
        adapter = self.adapter("next-producer")
        adapter.qualify_native(result)
        old_context = adapter.retained_workspace_continuation(self.workspace)
        self.assertEqual(old_context.binding["child_root_id"], "child")
        adapter._fence.read_record("workspace", "workspace-record", continuation=old_context)
        with self.assertRaises(RecordError):
            self.store.read_record("workspace", "workspace-record", continuation=adapter.continuation)
        writer_map = adapter.writer_map
        adapter._fence.snapshot(["workspace-authority"])
        scope = dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="workspace")
        owner = {key: self.rows["workspace-record"]["metadata"][key] for key in OWNER_PROJECTION_KEYS}
        owner["gc.root_bead_id"] = "next-child"
        workspace = dict(self.workspace, phase="entry", input_oid=self.oid, current_oid=self.oid, output_oid=None,
            active_member_id="member-next", next_member_position=1,
            writer_step_id="next-producer", writer_attempt_id=self.attempts["next-producer"].writer_attempt_id)
        workspace["claim_binding"] = {key: workspace[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        launch = dict(version=1, binding_step_id="next-producer", workflow_root_id="next-child", generation=1,
            workspace_owner_id="member", workspace_bead_id="workspace-record", store_ref="rig:fixture",
            native_attempt_id=workspace["native_attempt_id"])
        prepared = self.store.accept_replacement(self.attempts["next-producer"], scope, "workspace-authority",
            [RecordWrite("workspace", "workspace-record", workspace)],
            expected_grant=json.loads(self.rows["workspace-authority"]["metadata"][GRANT_KEY]),
            successor_relation=SuccessorRelation("plan-record", "plan-owner"), writer_map=writer_map,
            expected_rows=adapter.guard_rows, guards=adapter.guards,
            projections=[InheritedRunReference(adapter.continuation), NativeOwnerProjection("workspace-record", owner),
                         NativeWorktreeReference("next-producer", "workspace-record", launch)])

        def commit(prepared, expected):
            self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
            resolved = self.store.resolve(prepared)
            adapter.advance_written_rows(resolved["rows"], prepared=prepared)
            state = json.loads((self.root / "port.json").read_text())
            self.rows, self.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
            self.workspace = copy.deepcopy(expected)
            adapter.recheck_continuation()

        commit(prepared, workspace)
        workspace = dict(self.workspace, phase="active")
        prepared = self.store.write_records(self.attempts["next-producer"], scope, "workspace-authority",
            [RecordWrite("workspace", "workspace-record", workspace)], writer_map=writer_map,
            expected_rows=adapter.guard_rows, guards=adapter.guards)
        commit(prepared, workspace)
        (self.work / "next.py").write_text("NEXT = 1\n")
        self.git(self.work, "add", "next.py")
        self.git(self.work, "commit", "-qm", "next shared member")
        head = self.git(self.work, "rev-parse", "HEAD")
        adapter._checkout(self.workspace, head, advancing=True)
        workspace = dict(self.workspace, phase="result", current_oid=head, output_oid=head)
        prepared = self.store.write_records(self.attempts["next-producer"], scope, "workspace-authority",
            [RecordWrite("workspace", "workspace-record", workspace)], writer_map=writer_map,
            expected_rows=adapter.guard_rows, guards=adapter.guards)
        commit(prepared, workspace)
        return adapter, head

    def test_native_child_historical_consumer_uses_retained_result_child_after_owner_handoff(self):
        self.plan["nodes"][0].update(strategy="shared-chain", member_ids=["member", "member-next"], single_lane=True)
        self.rows["plan-record"]["metadata"][contracts()["source-plan"]["metadata_key"]] = canonical_bytes(self.plan).decode()
        self.rows["plan-owner"]["metadata"]["gc.source_plan_ref"] = self.ref("source-plan", "plan-record", self.plan)
        self.rows["member-next"] = self.row("member-next", {"gc.source_root_id": "root", "gc.source_generation": "1"})
        self.policy_binding["source_plan_sha256"] = record_sha256(self.plan)
        self.workspace["strategy"] = "shared-chain"
        self.publish_child_workspace()
        result = self.run_acceptance_pipeline()
        adapter, head = self.next_child_workspace(result)
        self.rows["child"].update(status="closed", assignee="")
        self.rows["child"]["metadata"]["gc.outcome"] = "pass"
        self.save()
        adapter = self.adapter("next-producer")
        native = adapter.qualify_native(result)
        self.assertTrue(native["historical_checkpoint"])
        self.assertEqual(native["head_oid"], self.oid)
        self.assertEqual(native["current_head_oid"], head)
        self.assertEqual(adapter.native_workflow_root_id, "next-child")
        self.assertEqual(native["producer_step_id"], "producer")
        self.assertEqual(native["reviewer_step_id"], "reviewer")
        self.assertEqual(native["guard_rows"]["workspace-record"]["metadata"]["gc.root_bead_id"], "next-child")
        self.assertEqual(native["guard_rows"]["producer"]["metadata"]["gc.root_bead_id"], "child")
        rows, sessions = copy.deepcopy(self.rows), copy.deepcopy(self.sessions)
        for fault in ("chain", "store", "root", "attempt", "generation", "owner"):
            with self.subTest(fault=fault):
                self.rows, self.sessions = copy.deepcopy(rows), copy.deepcopy(sessions)
                if fault == "chain":
                    changed = dict(self.workspace, input_oid=self.base)
                    self.rows["workspace-record"]["metadata"][contracts()["workspace"]["metadata_key"]] = canonical_bytes(changed).decode()
                elif fault == "store": self.rows["child-control"]["metadata"]["gc.root_store_ref"] = "rig:foreign"
                elif fault == "root": self.rows["producer"]["metadata"]["gc.root_bead_id"] = "next-child"
                elif fault == "attempt": self.rows["producer"]["metadata"]["gc.session_attempt_id"] = "writer-" + "0" * 64
                elif fault == "generation": self.rows["member"]["metadata"]["gc.source_generation"] = "2"
                else: self.rows["workspace-record"]["metadata"]["gc.root_bead_id"] = "child"
                self.save()
                with self.assertRaises(RecordError): self.adapter("next-producer").qualify_native(result)

    def test_native_child_chain_store_root_attempt_and_generation_changes_refuse(self):
        self.native_child()
        original_rows, original_sessions = copy.deepcopy(self.rows), copy.deepcopy(self.sessions)
        cases = [("child", "gc.drain_control_id", "absent-control"),
                 ("child-unit", "gc.parent_convoy_id", "absent-convoy"),
                 ("child-control", "gc.root_store_ref", "rig:foreign"),
                 ("producer", "gc.root_bead_id", "root"),
                 ("member", "gc.source_generation", "2"),
                 ("child", "status", "closed"),
                 ("recorder", "gc.session_attempt_id", "writer-" + "0" * 64)]
        for key, name, value in cases:
            with self.subTest(key=key, name=name):
                self.rows, self.sessions = copy.deepcopy(original_rows), copy.deepcopy(original_sessions)
                if name == "status": self.rows[key][name] = value
                else: self.rows[key]["metadata"][name] = value
                self.save()
                with self.assertRaises(RecordError):
                    adapter = self.adapter()
                    adapter.role_identities("recorder")
        self.rows, self.sessions = original_rows, original_sessions
        self.save()
        adapter = self.adapter()
        adapter.writer_map
        self.rows["child-unit"]["revision"] = "2"
        self.save()
        with self.assertRaisesRegex(RecordError, "native row changed"):
            adapter.recheck_continuation()

    def test_native_rows_and_real_git_qualify_with_opaque_attempts(self):
        adapter = self.adapter()
        native = adapter.qualify_native(self.result)
        self.assertTrue(native["verified"])
        self.assertEqual(native["result_binding"], self.binding)
        self.assertEqual(native["producer_attempt_id"], self.attempts["producer"].writer_attempt_id)
        self.assertEqual(adapter.acceptance_context(self.result, native)["required_checks"], self.requirements)
        self.assertIn("gc.workspace_required_checks.v1", native["guard_rows"]["run-record"]["metadata"])
        self.assertNotIn("producer-session", native["guard_rows"])
        self.assertNotIn("private-instance", json.dumps(native))

    def test_role_session_and_attempt_counterfeits_refuse(self):
        original_rows, original_sessions = copy.deepcopy(self.rows), copy.deepcopy(self.sessions)
        for failure in ("wrong-role", "missing-session", "wrong-name", "rotated-instance", "stale-claim", "wrong-assignee", "same-session"):
            with self.subTest(failure=failure):
                self.rows, self.sessions = copy.deepcopy(original_rows), copy.deepcopy(original_sessions)
                if failure == "wrong-role": self.rows["producer"]["metadata"]["gc.run_target"] = "gc.publisher"
                elif failure == "missing-session": self.rows["producer"]["metadata"].pop("gc.session_id")
                elif failure == "wrong-name": self.sessions["producer-session"]["metadata"]["session_name"] = "foreign"
                elif failure == "rotated-instance": self.sessions["producer-session"]["metadata"]["instance_token"] = "new-instance"
                elif failure == "stale-claim": self.sessions["recorder-session"]["metadata"]["current_claim_bead_id"] = "foreign"
                elif failure == "wrong-assignee": self.rows["recorder"]["assignee"] = "another-worker"
                else:
                    self.rows["reviewer"]["metadata"].update({"gc.session_id": "producer-session", "gc.session_name": "producer-runtime"})
                self.save()
                with self.assertRaises(RecordError): self.adapter().qualify_native(self.result)

    def test_retained_native_attempt_stamp_survives_closed_pool_token_rotation(self):
        for role in ("producer", "reviewer"):
            self.rows[role]["metadata"]["gc.session_attempt_id"] = self.attempts[role].writer_attempt_id
            self.sessions[role + "-session"]["metadata"]["instance_token"] = role + "-next-instance"
        self.save()
        native = self.adapter().qualify_native(self.result)
        self.assertEqual(native["producer_attempt_id"], self.attempts["producer"].writer_attempt_id)
        self.assertEqual(native["reviewer_attempt_id"], self.attempts["reviewer"].writer_attempt_id)
        self.rows["recorder"]["metadata"]["gc.session_attempt_id"] = "writer-" + "0" * 64
        self.save()
        with self.assertRaisesRegex(RecordError, "live native attempt stamp is stale"):
            self.adapter()

    def test_actual_final_methodology_leaf_is_chosen_over_initial_inspection(self):
        original_rows, original_formula = copy.deepcopy(self.rows), copy.deepcopy(self.formula)
        for stage in ("record-item-result", "apply-story-findings"):
            with self.subTest(stage=stage):
                self.rows, self.formula = copy.deepcopy(original_rows), copy.deepcopy(original_formula)
                inspection = copy.deepcopy(self.rows["producer"])
                inspection["id"] = "inspection"
                self.rows["inspection"] = inspection
                inspection_ref = "do-work.implement"
                final_ref = "do-work." + stage
                self.rows["producer"]["metadata"].update({"gc.step_id": final_ref, "gc.step_ref": final_ref,
                    TOPOLOGY: canonical_bytes([inspection_ref]).decode()})
                self.rows["reviewer"]["metadata"][TOPOLOGY] = canonical_bytes([final_ref]).decode()
                self.formula["steps"][0]["id"] = final_ref
                self.formula["steps"].append({"id": inspection_ref, "metadata": original_formula["steps"][0]["metadata"]})
                self.formula["deps"][0]["depends_on_id"] = final_ref
                self.formula["deps"].append(dict(step_id=final_ref, depends_on_id=inspection_ref, type="blocks"))
                self.save()
                native = self.adapter().qualify_native(self.result)
                self.assertEqual(native["producer_step_id"], "producer")

    def test_missing_duplicate_and_stale_physical_occurrences_refuse(self):
        original = copy.deepcopy(self.rows)
        for failure in ("missing", "duplicate", "stale-ref", "control-only"):
            with self.subTest(failure=failure):
                self.rows = copy.deepcopy(original)
                if failure == "missing": self.rows.pop("reviewer")
                elif failure == "duplicate":
                    self.rows["other-producer"] = copy.deepcopy(self.rows["producer"])
                    self.rows["other-producer"]["id"] = "other-producer"
                elif failure == "stale-ref": self.rows["reviewer"]["metadata"]["gc.step_ref"] = "absent"
                else: self.rows["producer"]["metadata"]["gc.kind"] = "retry"
                self.save()
                with self.assertRaises(RecordError): self.adapter().qualify_native(self.result)

    def test_changed_policy_base_and_weakened_command_refuse(self):
        original = copy.deepcopy(self.rows)
        for failure in ("empty", "missing", "digest", "base", "weakened-command", "changed-config"):
            with self.subTest(failure=failure):
                self.rows = copy.deepcopy(original)
                policy = json.loads(self.rows["run-record"]["metadata"]["gc.workspace_required_checks.v1"])
                if failure == "missing": self.rows["run-record"]["metadata"].pop("gc.workspace_required_checks.v1")
                else:
                    if failure == "empty": policy["required_checks"] = []
                    elif failure == "digest": policy["policy_sha256"] = "0" * 64
                    elif failure == "base": policy["base_oid"] = self.oid
                    elif failure == "weakened-command":
                        checks = [{"id": "VALUE-42", "argv": [sys.executable, "-c", "pass"]}]
                        self.rows["root"]["metadata"]["gc.var.worktree_checks"] = canonical_bytes({"required_checks": checks}).decode()
                        policy = capture_check_policy(self.run, "run-record", self.rows["root"]["metadata"]["gc.var.worktree_checks"])
                    else: self.rows["root"]["metadata"]["gc.var.worktree_checks"] = canonical_bytes({"required_checks": self.requirements + self.requirements}).decode()
                    self.rows["run-record"]["metadata"]["gc.workspace_required_checks.v1"] = canonical_bytes(policy).decode()
                self.save()
                with self.assertRaises(RecordError): self.adapter().qualify_native(self.result)

    def test_source_formula_generation_and_head_drift_refuse(self):
        adapter = self.adapter()
        self.rows["convoy"]["metadata"]["gc.source_generation"] = "2"
        self.save()
        with self.assertRaises(RecordError): adapter.qualify_native(self.result)
        self.rows["convoy"]["metadata"]["gc.source_generation"] = "1"
        self.save()
        self.formula_path.write_text('formula = "changed"\n')
        with self.assertRaises(RecordError): self.adapter().qualify_native(self.result)
        self.formula_path.write_text('formula = "do-work"\n')
        self.git(self.work, "reset", "--hard", self.base)
        with self.assertRaises(RecordError): self.adapter().qualify_native(self.result)

    def test_original_rows_reach_actual_writer_request_and_stale_guard_refuses(self):
        adapter = self.adapter()
        native = adapter.qualify_native(self.result)
        self.rows["result-record"] = self.row("result-record", status="closed", scoped=False)
        self.rows["authority"] = self.row("authority", status="closed", scoped=False)
        self.save()
        prepared = adapter.prepare_member_result(self.result, record_id="result-record", authority_id="authority", initial_write=True)
        requested = {row["id"]: row for row in prepared.request["rows"]}
        for key, row in native["guard_rows"].items():
            self.assertEqual(requested[key]["expected_revision"], row["revision"])
            self.assertEqual(requested[key]["expected_status"], row["status"])
            self.assertEqual(requested[key]["expected_assignee"], row["assignee"])
        self.rows["producer"]["revision"] = "2"
        self.save()
        outcome = self.store.execute(prepared)
        self.assertEqual(outcome["outcome"], "unknown")
        self.assertFalse(outcome["retry_allowed"])
        self.assertEqual(native["guard_rows"]["producer"]["revision"], "1")

    def test_self_attested_verified_flag_and_failed_actual_check_give_no_pass(self):
        adapter = self.adapter()
        with self.assertRaisesRegex(RecordError, "actual native qualification"):
            adapter.acceptance_context(self.result, {"verified": True, "result_binding": self.binding})
        bad = copy.deepcopy(self.result)
        bad["acceptance"]["project_checks"][0]["exit_code"] = 1
        with self.assertRaises(RecordError): adapter.qualify_native(bad)

    def test_native_producer_review_recorder_pipeline_and_proven_row_advancement(self):
        self.run_acceptance_pipeline()

    def run_acceptance_pipeline(self):
        self.select_role("producer")
        producer = self.adapter("producer")
        checks = producer.execute_checks("member", "member", self.oid)
        proof = outputs.read_artifact({"path": checks[0]["evidence_path"], "sha256": checks[0]["evidence_sha256"]}, self.artifacts)
        self.assertEqual(proof["policy_binding"], self.policy_binding)
        self.select_role("reviewer")
        reviewer = self.adapter("reviewer")
        artifacts = [outputs.artifact(self.summary, self.artifacts)]
        context = reviewer.begin_review("member", "member", self.oid, checks, artifacts)
        review = reviewer.complete_review(context, self.artifacts / "report.md", "passed", self.artifacts / "native-review.json")
        self.select_role("recorder")
        recorder = self.adapter()
        result = recorder.make_member_result("member", "member", self.oid, checks, review, artifacts)
        self.rows["result-record"] = self.row("result-record", status="closed", scoped=False)
        self.rows["authority"] = self.row("authority", status="closed", scoped=False)
        self.save()
        prepared = recorder.prepare_member_result(result, record_id="result-record", authority_id="authority", initial_write=True)
        self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
        resolved = self.store.resolve(prepared)
        acknowledgement = recorder.advance_written_rows(resolved["rows"], prepared=prepared)
        self.assertEqual(acknowledgement["request_sha256"], prepared.sha256)
        state = json.loads((self.root / "port.json").read_text())
        self.rows, self.sessions = state["stores"]["rig:fixture"], state["stores"]["city:fixture"]
        recorder.recheck_continuation()
        self.assertTrue(recorder.qualify_native(result)["verified"])
        self.assertIn("gc.workspace_result_ref", recorder.guard_rows["member"]["metadata"])
        with self.assertRaises(RecordError): recorder.advance_written_rows({}, prepared=prepared)
        return result

    def test_continuation_admits_actual_current_and_historical_instances_then_rechecks(self):
        adapter = self.adapter()
        admission = adapter.admit_continuation(self.workspace, adapter.guard_rows, self.attempts["recorder"])
        self.assertEqual(admission["previous_identity"], self.identity("producer"))
        self.assertEqual(admission["identity"], self.identity("recorder"))
        self.sessions["producer-session"]["metadata"]["instance_token"] = "superseded-instance"
        self.save()
        with self.assertRaisesRegex(RecordError, "historical native session instance changed"):
            adapter.recheck_continuation()

    def test_retry_control_and_one_actual_attempt_are_distinct_physical_roles(self):
        control = self.rows["producer"]
        attempt = copy.deepcopy(control)
        attempt["id"] = "producer-attempt"
        attempt["metadata"].update({"gc.step_id": "implement", "gc.step_ref": "do-work.implement.attempt.1", "gc.control_for": "implement"})
        launch = json.loads(attempt["metadata"]["gc.worktree_ref"])
        launch["binding_step_id"] = "producer-attempt"
        attempt["metadata"]["gc.worktree_ref"] = canonical_bytes(launch).decode()
        control["metadata"].update({"gc.kind": "retry", "gc.step_id": "implement"})
        self.formula["steps"][0]["metadata"].update({"gc.kind": "retry", "gc.step_id": "implement"})
        self.formula["steps"].append({"id": "do-work.implement.attempt.1", "metadata": {
            "gc.step_id": "implement", "gc.control_for": "implement", "gc.run_target": "gc.implementation-worker",
            "gc.build.artifact_schema": "gc.build.implementation-summary.v1"}})
        self.rows["reviewer"]["metadata"][TOPOLOGY] = '["implement"]'
        self.rows["producer-attempt"] = attempt
        self.save()
        roles, _ = self.adapter()._roles("recorder")
        self.assertEqual(roles["producer"]["bead_id"], "producer-attempt")
        self.assertEqual(roles["producer"]["step_id"], "implement")
        self.assertEqual(roles["producer"]["step_ref"], "do-work.implement.attempt.1")

    def test_historical_shared_checkpoint_reports_current_head_without_claiming_old_live_head(self):
        self.plan["nodes"][0].update(strategy="shared-chain", member_ids=["member", "member-next"], single_lane=True)
        self.rows["plan-record"]["metadata"][contracts()["source-plan"]["metadata_key"]] = canonical_bytes(self.plan).decode()
        self.rows["plan-owner"]["metadata"]["gc.source_plan_ref"] = self.ref("source-plan", "plan-record", self.plan)
        self.policy_binding["source_plan_sha256"] = record_sha256(self.plan)
        checks = copy.deepcopy(self.result["acceptance"]["project_checks"])
        for position, check in enumerate(checks):
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifacts)
            bound = outputs.immutable_json(self.artifacts / f"historical-check-{position}.json", dict(proof, policy_binding=self.policy_binding))
            check.update(evidence_path=bound["path"], evidence_sha256=bound["sha256"])
        old_review = self.result["acceptance"]["independent_review"]
        proof = outputs.read_artifact({"path": old_review["report_path"], "sha256": old_review["report_sha256"]}, self.artifacts)
        bound = outputs.immutable_json(self.artifacts / "historical-review.json", dict(proof, checks=checks, policy_binding=self.policy_binding))
        self.result["acceptance"]["project_checks"] = checks
        old_review.update(report_path=bound["path"], report_sha256=bound["sha256"])
        self.rows["first-result"] = self.row("first-result", {contracts()["member-result"]["metadata_key"]: canonical_bytes(self.result).decode()},
                                              status="closed", scoped=False)
        self.rows["member"]["metadata"]["gc.workspace_result_ref"] = self.ref("member-result", "first-result", self.result)
        (self.work / "next.py").write_text("NEXT = 1\n")
        self.git(self.work, "add", "next.py")
        self.git(self.work, "commit", "-qm", "next member")
        current_head = self.git(self.work, "rev-parse", "HEAD")
        aggregate = Attempt("aggregate-session", "aggregate-private-instance", "aggregate")
        self.rows["aggregate"] = self.row("aggregate", {"gc.run_target": "gc.run-operator", "gc.session_id": aggregate.session_id,
            "gc.session_name": "aggregate-runtime", "gc.step_ref": "root.aggregate"}, status="in_progress")
        self.rows["aggregate"]["assignee"] = aggregate.session_id
        self.sessions[aggregate.session_id] = self.row(aggregate.session_id, {"template": "fixture/gc.run-operator",
            "session_name": "aggregate-runtime", "instance_token": aggregate.instance_token,
            "state": "active", "current_claim_bead_id": "aggregate", "session_origin": "ephemeral"}, scoped=False)
        self.sessions[aggregate.session_id]["type"] = "session"
        self.rows["recorder"].update(status="closed", assignee="")
        self.rows["recorder"]["metadata"]["gc.outcome"] = "pass"
        self.sessions["recorder-session"]["metadata"].update(state="asleep", current_claim_bead_id="")
        self.rows["member-next"] = self.row("member-next", {"gc.source_root_id": "root", "gc.source_generation": "1"})
        self.workspace.update(strategy="shared-chain", input_oid=self.oid, current_oid=current_head, output_oid=current_head,
            active_member_id="member-next", next_member_position=1, writer_step_id="aggregate", writer_attempt_id=aggregate.writer_attempt_id)
        self.workspace["claim_binding"] = {key: self.workspace[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        self.rows["workspace-record"]["metadata"][contracts()["workspace"]["metadata_key"]] = canonical_bytes(self.workspace).decode()
        self.rows["member"]["metadata"]["gc.workspace_ref"] = self.ref("workspace", "workspace-record", self.workspace)
        os.environ.update(GC_SESSION_ID=aggregate.session_id, GC_INSTANCE_TOKEN=aggregate.instance_token)
        self.save()
        adapter = self.adapter("aggregate")
        native = adapter.qualify_native(self.result)
        self.assertTrue(native["historical_checkpoint"])
        self.assertEqual(native["current_head_oid"], current_head)
        self.assertEqual(native["head_oid"], self.oid)
        self.assertEqual(native["result_binding"]["input_oid"], self.base)
        self.assertIn("first-result", native["guard_rows"])
        self.git(self.work, "reset", "--hard", self.base)
        with self.assertRaises(RecordError): adapter.qualify_native(self.result)

    def add_accepted_owner(self, owner):
        work = self.work.parent / owner
        self.git(self.repo, "worktree", "add", "--detach", str(work), self.base)
        (work / "feature.py").write_text("VALUE = 42\n")
        (work / (owner + ".py")).write_text("CONTRIBUTION = 1\n")
        self.git(work, "add", ".")
        self.git(work, "commit", "-qm", owner)
        oid = self.git(work, "rev-parse", "HEAD")
        identities = {}
        self.rows[owner + "-expansion"] = copy.deepcopy(self.rows["expansion"])
        self.rows[owner + "-expansion"]["id"] = owner + "-expansion"
        for role in ("producer", "reviewer", "recorder"):
            key = owner + "-" + role
            attempt = Attempt(key + "-session", key + "-private-instance", key)
            identities[role] = dict(step_id=key, session_id=attempt.session_id, attempt_id=attempt.writer_attempt_id)
            row = copy.deepcopy(self.rows[role])
            row.update(id=key, status="closed", assignee="")
            row["metadata"].update({"gc.attach_root_id": owner + "-expansion", "gc.source_anchor_id": owner,
                "gc.drain_member_id": owner, "gc.session_id": attempt.session_id, "gc.session_name": key + "-runtime", "gc.outcome": "pass"})
            self.rows[key] = row
            session = copy.deepcopy(self.sessions[role + "-session"])
            session["id"] = attempt.session_id
            session["metadata"].update(instance_token=attempt.instance_token, session_name=key + "-runtime",
                                        state="asleep", current_claim_bead_id="")
            self.sessions[session["id"]] = session
        workspace = copy.deepcopy(self.workspace)
        provenance = dict(self.provenance, bead_id=owner + "-workspace", path=str(work), owner=owner, attempt_id=owner + "-native-attempt")
        self.provenances[str(work)] = provenance
        workspace.update(workspace_owner_id=owner, workspace_bead_id=owner + "-workspace", work_dir=str(work), strategy="isolated",
            phase="result", input_oid=self.base, current_oid=oid, output_oid=oid, active_member_id=owner,
            writer_step_id=owner + "-producer", writer_attempt_id=identities["producer"]["attempt_id"], native_provenance=provenance,
            native_attempt_id=provenance["attempt_id"], integration_inputs=None)
        workspace["claim_binding"] = {key: workspace[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        row = copy.deepcopy(self.rows["workspace-record"])
        row["id"] = workspace["workspace_bead_id"]
        row["metadata"].update({"gc.work_dir": str(work), "gc.worktree_owner": owner,
                               contracts()["workspace"]["metadata_key"]: canonical_bytes(workspace).decode()})
        self.rows[row["id"]] = row
        self.rows[owner] = self.row(owner, {"gc.source_root_id": "root", "gc.source_generation": "1",
            "gc.workspace_ref": self.ref("workspace", row["id"], workspace)})
        launch = dict(version=1, binding_step_id=owner + "-producer", workflow_root_id="root", generation=1,
            workspace_owner_id=owner, workspace_bead_id=row["id"], store_ref="rig:fixture", native_attempt_id=provenance["attempt_id"])
        self.rows[owner + "-producer"]["metadata"]["gc.worktree_ref"] = canonical_bytes(launch).decode()
        binding = outputs.result_binding(self.run, self.plan, workspace, store_ref="rig:fixture", member_id=owner, output_oid=oid)
        checks = outputs.execute_checks(binding, work, self.requirements, identities["producer"], self.artifacts / owner)
        policy = dict(self.policy_binding, source_plan_sha256=record_sha256(self.plan))
        for position, check in enumerate(checks):
            proof = outputs.read_artifact({"path": check["evidence_path"], "sha256": check["evidence_sha256"]}, self.artifacts)
            bound = outputs.immutable_json(self.artifacts / owner / f"native-{position}.json", dict(proof, policy_binding=policy))
            check.update(evidence_path=bound["path"], evidence_sha256=bound["sha256"])
        artifacts = [outputs.artifact(self.summary, self.artifacts)]
        context = outputs.begin_review(binding, work, checks, self.requirements, identities["producer"], identities["reviewer"], artifacts, self.artifacts)
        context["policy_binding"] = policy
        review = outputs.complete_review(context, work, self.artifacts / "report.md", "passed", self.artifacts / owner / "review.json", self.artifacts)
        result = outputs.make_member_result(binding, writer_step_id=owner + "-recorder", commit_oids=[oid], checks=checks,
            review=review, artifacts=artifacts, required_checks=self.requirements, artifact_root=self.artifacts, work_dir=work)
        output = outputs.make_owner_output(self.plan, [result], artifact_root=self.artifacts,
            qualifications={owner: dict(binding=binding, required_checks=self.requirements)})
        for kind, value in (("member-result", result), ("owner-output", output)):
            key = owner + "-" + kind
            self.rows[key] = self.row(key, {contracts()[kind]["metadata_key"]: canonical_bytes(value).decode()}, status="closed", scoped=False)
            self.rows[owner]["metadata"][contracts()[kind]["metadata_key"] + "_ref"] = self.ref(kind, key, value)
        return result, output

    def test_actual_accepted_predecessors_integrate_with_native_owner_verification(self):
        from workspace_inputs import materialize_integration, resolve_member_input
        self.plan["nodes"] = [dict(owner_id=owner, strategy="isolated", member_ids=[owner],
            source_predecessor_owner_ids=[], single_lane=False) for owner in ("a", "b")] + [
            dict(owner_id="member", strategy="integration", member_ids=["member"], source_predecessor_owner_ids=["a", "b"], single_lane=False)]
        _, first = self.add_accepted_owner("a")
        _, second = self.add_accepted_owner("b")
        self.workspace.update(strategy="integration", phase="entry", current_oid=self.base, input_oid=self.base, output_oid=None,
            writer_step_id="recorder", writer_attempt_id=self.attempts["recorder"].writer_attempt_id,
            integration_inputs=[dict(owner_id=owner, output_oid=output["output_oid"], workspace_output_sha256=record_sha256(output))
                                for owner, output in (("a", first), ("b", second))])
        self.workspace["claim_binding"] = {key: self.workspace[key] for key in
            ("workflow_root_id", "generation", "workspace_owner_id", "writer_step_id", "writer_attempt_id")}
        self.rows["workspace-record"]["metadata"][contracts()["workspace"]["metadata_key"]] = canonical_bytes(self.workspace).decode()
        self.rows["member"]["metadata"]["gc.workspace_ref"] = self.ref("workspace", "workspace-record", self.workspace)
        self.rows["plan-record"]["metadata"][contracts()["source-plan"]["metadata_key"]] = canonical_bytes(self.plan).decode()
        self.rows["plan-owner"]["metadata"]["gc.source_plan_ref"] = self.ref("source-plan", "plan-record", self.plan)
        self.git(self.work, "reset", "--hard", self.base)
        self.git(self.repo, "config", "user.name", "Fixture")
        self.git(self.repo, "config", "user.email", "fixture@example.invalid")
        self.save()
        adapter = self.adapter()
        bundle = resolve_member_input(self.plan, "member", "member", load_owner_output=lambda owner: adapter._record("owner-output", owner),
            load_member_result=lambda member: adapter._record("member-result", member), qualify_native=adapter.qualify_native,
            acceptance_context=adapter.acceptance_context, store_ref=self.store.store_ref, artifact_root=self.artifacts)
        adapter.bind_workspace(self.workspace, adapter.guard_rows)
        bad = copy.deepcopy(bundle)
        bad["predecessors"][0]["workspace_output_sha256"] = "0" * 64
        with self.assertRaises(RecordError): adapter.verify_integration(self.work, bad, self.base)
        integrated = materialize_integration(self.work, bundle, verify_native=adapter.verify_integration)
        self.assertEqual(integrated["output_oid"], self.git(self.work, "rev-parse", "HEAD"))
        self.assertTrue((self.work / "a.py").is_file() and (self.work / "b.py").is_file())
        self.assertEqual([item["owner_id"] for item in integrated["integration_inputs"]], ["a", "b"])

    def test_cli_reads_native_policy_without_policy_or_identity_flags(self):
        result_path = self.artifacts / "result.json"
        result_path.write_bytes(canonical_bytes(self.result))
        command = [sys.executable, str(SCRIPTS / "workspace_runtime.py"), "qualify", "--gc", str(self.port),
            "--city-root", str(self.city), "--store-ref", "rig:fixture", "--rig-name", "fixture", "--workflow-root-id", "root",
            "--claimed-step-id", "recorder", "--artifact-root", str(self.artifacts), "--evidence-dir", str(self.diagnostics),
            "--generation", "1", "--result", str(result_path)]
        run = subprocess.run(command, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        public = json.loads(run.stdout)
        self.assertTrue(public["verified"])
        self.assertIn("guard_revisions", public)
        self.assertNotIn("private-instance", run.stdout)

    def test_cli_retains_unknown_result_and_resolves_without_resubmission(self):
        from workspace_requests import journal_directory
        self.rows["result-record"] = self.row("result-record", status="closed", scoped=False)
        self.rows["authority"] = self.row("authority", status="closed", scoped=False)
        self.save()
        state_path = self.root / "port.json"
        state = json.loads(state_path.read_text())
        state["lose_write_ack"] = True
        state_path.write_text(json.dumps(state))
        result_path = self.artifacts / "result.json"
        result_path.write_bytes(canonical_bytes(self.result))
        command = [sys.executable, "-B", str(SCRIPTS / "workspace_runtime.py"), "record-result",
            "--gc", str(self.port), "--city-root", str(self.city), "--store-ref", "rig:fixture",
            "--rig-name", "fixture", "--workflow-root-id", "root", "--claimed-step-id", "recorder",
            "--artifact-root", str(self.artifacts), "--evidence-dir", str(self.diagnostics),
            "--generation", "1", "--result", str(result_path), "--record-id", "result-record",
            "--authority-id", "authority", "--initial-write"]
        failed = subprocess.run(command, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(failed.returncode, 0)
        pending = list(journal_directory(self.store).glob("*.pending"))
        self.assertEqual(len(pending), 1, failed.stderr)
        request_path = Path(pending[0].read_text())
        retained = request_path.read_bytes()
        self.assertIn(str(request_path), failed.stderr)
        self.assertNotIn("private-instance", failed.stdout + failed.stderr)
        state = json.loads(state_path.read_text())
        self.assertIn("gc.workspace_result_ref", state["stores"]["rig:fixture"]["member"]["metadata"])
        state.pop("block_readback")
        state.pop("lose_write_ack")
        state_path.write_text(json.dumps(state))
        other_diagnostics = self.root / "other-diagnostics"
        other_diagnostics.mkdir()
        command[command.index("--evidence-dir") + 1] = str(other_diagnostics)
        refused = subprocess.run(command, text=True, capture_output=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(str(request_path), refused.stderr)
        resolver = """import json,sys
from workspace_store import WorkspaceStore
from workspace_requests import resolve_request
store=WorkspaceStore('rig:fixture',gc=sys.argv[1],cwd=sys.argv[2],common_git_dir=sys.argv[3])
print(json.dumps(resolve_request(store,sys.argv[4])))
"""
        resolved = subprocess.run([sys.executable, "-B", "-c", resolver, str(self.port), str(self.city),
            str(self.repo / ".git"), str(request_path)], text=True, capture_output=True, timeout=30)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        receipt = json.loads(resolved.stdout)
        self.assertEqual(receipt["outcome"], "committed")
        self.assertNotIn("rows", receipt)
        self.assertEqual(request_path.read_bytes(), retained)
        self.assertFalse(pending[0].exists())
        commands = [json.loads(line) for line in state_path.with_suffix(".commands").read_text().splitlines()]
        writes = [args for args in commands if "guarded-metadata-batch" in args
                  and any(arg == "--request" or arg.startswith("--request=") for arg in args)]
        self.assertEqual(len(writes), 1)


class PolicyTests(unittest.TestCase):
    def test_policy_shape_requires_unique_nonempty_actual_argv(self):
        for checks in ([], [{"id": "A", "argv": []}], [{"id": "A", "argv": ["python", ""]}],
                       [{"id": "A", "argv": ["python"]}, {"id": "A", "argv": ["python"]}]):
            with self.subTest(checks=checks), self.assertRaises(RecordError): outputs.check_scope(checks)


if __name__ == "__main__":
    unittest.main()
