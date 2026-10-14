"""Compose native command contracts with the real record writer, without a service."""
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "scripts"))

import create_beads_from_tasks as tasks
import workspace_cooked as cooked
import workspace_entry as entry
from workspace_inputs import resolve_member_input
from workspace_records import RecordError, canonical_bytes, record_identity
import workspace_run as run
from workspace_store import Attempt, WorkspaceStore
from test_workspace_entry import source_payload
from test_workspace_store import MemoryPort, row


class ExpansionCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workspace-expansion-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.city = Path(self.tmp.name)
        self.repo = self.city / "rig"
        self.git("init", "-b", "main", str(self.repo), cwd=self.city)
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "file").write_text("base\n")
        self.git("add", "file")
        self.git("commit", "-m", "base")
        formula = self.city / "build.formula.toml"
        formula.write_text('formula = "build"\n')
        self.record = run.capture_payload(workflow_root_id="root-1", input_convoy_id="initial-1",
            source_anchor_id="initial-1", rig_root=str(self.repo), writer_step_id="prepare-1",
            worktree_lifecycle="new")
        self.run_ref = {"kind": "run", "identity": list(record_identity("run", self.record)), "bead_id": "run-record"}
        policy = run.capture_check_policy(self.record, "run-record", canonical_bytes({
            "required_checks": [{"id": "unit", "argv": ["python3", "-m", "unittest"]}]}).decode())
        rows = {
            "root-1": row("root-1", status="in_progress", metadata={"gc.kind": "workflow",
                "gc.root_store_ref": "rig:example", "gc.input_convoy_id": "initial-1",
                "gc.var.worktree_lifecycle": "new", entry.RUN_REF: canonical_bytes(self.run_ref).decode(),
                "gc.formula_name": "build", "gc.formula_source": str(formula),
                "gc.formula_hash": hashlib.sha256(formula.read_bytes()).hexdigest()}),
            "decompose-1": row("decompose-1", status="in_progress", assignee="worker", metadata={
                "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:example", "gc.session_id": "session-1",
                "gc.step_id": "build.decompose", "gc.step_ref": "build.decompose",
                "gc.build.artifact_schema": "gc.build.decomposition.v1", cooked.TOPOLOGY: "[]"}),
            "initial-1": dict(row("initial-1", status="open", metadata={"gc.root_store_ref": "rig:example"}), type="convoy"),
            "run-record": row("run-record", metadata={"gc.implementation_run": canonical_bytes(self.record).decode(),
                run.CHECKS_POLICY_KEY: canonical_bytes(policy).decode()}),
        }
        self.port = MemoryPort(rows)
        self.store = WorkspaceStore("rig:example", cwd=self.city, common_git_dir=self.repo / ".git")
        self.attempt = Attempt("session-1", "incarnation-1", "decompose-1")
        self.state = {"run": self.record, "run_reference": self.run_ref, "workflow_root_id": "root-1",
                      "generation": 1, "rig_name": "example", "store_ref": "rig:example"}
        evidence = self.city / "evidence"
        evidence.mkdir(mode=0o700)
        self.workspace = {"store": self.store, "state": self.state, "attempt": self.attempt,
                          "evidence_dir": evidence}
        self.path = self.city / "tasks.md"
        self.path.write_text("---\nstatus: approved\n---\n# Task plan\n\n## Bead Creation Payload\n\n```yaml\n"
            + tasks.yaml.safe_dump(source_payload(), sort_keys=False) + "```\n")
        self.commands, self.dependencies = [], set()
        self.fail_create = False
        for target in (
            patch.object(self.store, "_command", side_effect=self.port),
            patch.object(cooked, "_native_list", return_value=["decompose-1"]),
            patch.object(cooked, "native_json", return_value={"ok": True, "name": "build", "steps": [
                {"id": "build.decompose", "metadata": {"gc.build.artifact_schema": "gc.build.decomposition.v1"}}], "deps": []}),
            patch.object(tasks.subprocess, "run", side_effect=self.native_command),
            patch.object(entry, "native_json", side_effect=self.native_placeholder),
        ):
            target.start()
            self.addCleanup(target.stop)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], text=True,
                              capture_output=True, check=True).stdout.strip()

    def native_placeholder(self, gc, city, arguments, rig):
        self.assertEqual((gc, city, rig), ("gc", str(self.city), "example"))
        self.assertEqual(arguments[:2], ["bd", "create"])
        self.assertIn("closed", arguments)
        self.assertIn("{}", arguments)
        bead_id = "record-" + str(len(self.port.rows))
        self.port.rows[bead_id] = row(bead_id)
        return {"id": bead_id}

    def native_command(self, command, **kwargs):
        self.commands.append(copy.deepcopy(command))
        self.assertEqual(command[:5], ["gc", "--city", str(self.city), "--rig", "example"])
        self.assertEqual(kwargs["cwd"], str(self.city))
        family, args = command[5], command[6:]
        output = ""
        if family == "bd" and args[0] == "create":
            metadata = json.loads(args[args.index("--metadata") + 1])
            bead_id = "physical-" + metadata["gc.plan.key"]
            self.assertNotIn(bead_id, self.port.rows)
            self.assertEqual(args[args.index("--parent") + 1], "root-1")
            self.assertEqual(args[args.index("--status") + 1], "open")
            self.assertEqual(args[args.index("--assignee") + 1], "")
            self.assertNotIn("--id", args)
            self.port.rows[bead_id] = row(bead_id, status="open", metadata=metadata)
            if "--deps" in args:
                self.dependencies.update((bead_id, dependency) for dependency in args[args.index("--deps") + 1].split(","))
            if self.fail_create:
                raise subprocess.TimeoutExpired(command, 30)
            output = json.dumps({"id": bead_id})
        elif family == "convoy" and args[0] == "create":
            self.assertEqual(set(args[3:]), {"physical-a", "physical-b", "physical-d-inputs", "physical-d"})
            self.port.rows["physical-convoy"] = dict(row("physical-convoy", status="open"), type="convoy")
            output = json.dumps({"schema_version": "1", "ok": True, "command": "convoy.create",
                                 "convoy_id": "physical-convoy"})
        elif family == "bd" and args[0] == "update":
            bead_id = args[1]
            self.port.rows[bead_id]["metadata"].update(json.loads(args[args.index("--metadata") + 1]))
            self.port.rows[bead_id]["revision"] = str(int(self.port.rows[bead_id]["revision"]) + 1)
        elif family == "bd" and args[:2] == ["dep", "list"]:
            output = json.dumps([{"depends_on_id": parent, "type": "blocks"}
                for child, parent in self.dependencies if child == args[2]])
        elif family == "bd" and args[:2] == ["dep", "add"]:
            self.dependencies.add((args[2], args[3]))
        else:
            self.fail("unexpected native command: " + repr(command))
        return subprocess.CompletedProcess(command, 0, output, "")

    def expand(self):
        return tasks.create_from_tasks(self.path, city=str(self.city), dry_run=False,
                                       force=False, workspace=self.workspace)

    def published_plan(self):
        ref = json.loads(self.port.rows["decompose-1"]["metadata"][entry.PLAN_REF])
        return self.store.read_record("source-plan", ref["bead_id"], ref["identity"])

    def test_native_expansion_publishes_pending_fan_in_and_exact_convoy_in_one_batch(self):
        self.assertEqual(self.expand(), 0)
        plan = self.published_plan()
        self.assertEqual(plan["nodes"][2]["source_predecessor_owner_ids"], ["physical-b", "physical-a"])
        self.assertEqual(plan["nodes"][2]["member_ids"], ["physical-d-inputs"])
        self.assertEqual(plan["terminal_owner_id"], "physical-d")
        self.assertEqual(self.store.read_record("run", "run-record"), self.record)
        self.assertEqual(self.port.rows["root-1"]["metadata"]["gc.input_convoy_id"], "physical-convoy")
        self.assertEqual(len(self.port.requests), 1)
        for member in ("physical-a", "physical-b", "physical-d-inputs", "physical-d"):
            native = self.port.rows[member]
            self.assertEqual(native["metadata"]["gc.source_generation"], "1")
            self.assertEqual(native["metadata"]["gc.root_bead_id"], "root-1")
            self.assertEqual(native["assignee"], "")
            self.assertNotIn("gc.run_target", native["metadata"])
        self.assertIn(("physical-d-inputs", "physical-a"), self.dependencies)
        self.assertIn(("physical-d-inputs", "physical-b"), self.dependencies)
        self.assertIn(("physical-d", "physical-d-inputs"), self.dependencies)
        self.assertEqual(tasks.front_matter_status(self.path.read_text()), "created")

    def test_pending_outputs_allow_declaration_but_block_integration_input(self):
        self.expand()
        with self.assertRaisesRegex(RecordError, "missing accepted owner output: physical-b"):
            resolve_member_input(self.published_plan(), "physical-d-inputs", "physical-d-inputs",
                load_owner_output=lambda _: None, load_member_result=lambda _: None,
                qualify_native=lambda *_: self.fail("missing output cannot earn qualification"),
                acceptance_context=lambda *_: self.fail("missing output cannot reach acceptance"),
                store_ref="rig:example", artifact_root=self.city)

    def test_unknown_native_creation_keeps_recovery_marker_and_never_duplicates(self):
        self.fail_create = True
        with self.assertRaisesRegex(tasks.PlanError, "uncertain"):
            self.expand()
        self.assertIn("native_allocation_pending: a", self.path.read_text())
        self.assertIn("physical-a", self.port.rows)
        before = copy.deepcopy(self.commands)
        self.fail_create = False
        with self.assertRaisesRegex(tasks.PlanError, "previous native creation.*uncertain"):
            self.expand()
        self.assertEqual(self.commands, before)
        self.assertEqual(self.port.requests, [])
        self.assertEqual(self.port.rows["root-1"]["metadata"]["gc.input_convoy_id"], "initial-1")

    def test_malformed_allocation_ack_never_adopts_a_coerced_or_ambiguous_id(self):
        for response in ({"id": 7}, {"id": " padded "}, {"id": ""}, ["physical-a"]):
            with self.subTest(response=response), self.assertRaises(tasks.PlanError):
                tasks.parse_native_create_output(json.dumps(response))
        for response in ({"id": "physical-convoy"}, {"convoy_id": "physical-convoy", "ok": False},
                         {"convoy_id": "physical-convoy", "schema_version": "1", "ok": True, "command": "convoy.close"}):
            with self.subTest(response=response), self.assertRaises(tasks.PlanError):
                tasks.parse_native_create_output(json.dumps(response), convoy=True)

    def test_changed_original_cooked_row_cannot_partially_publish_plan_or_convoy(self):
        execute = self.store.execute
        def race(prepared):
            self.port.rows["root-1"]["revision"] = "2"
            return execute(prepared)
        with patch.object(self.store, "execute", side_effect=race):
            with self.assertRaisesRegex(tasks.PlanError, "uncertain"):
                self.expand()
        self.assertEqual(self.port.rows["root-1"]["metadata"]["gc.input_convoy_id"], "initial-1")
        self.assertNotIn(entry.PLAN_REF, self.port.rows["decompose-1"]["metadata"])
        self.assertNotIn("gc.source_plan_sha256", self.port.rows["physical-convoy"]["metadata"])
        self.assertEqual(tasks.front_matter_status(self.path.read_text()), "partial")


if __name__ == "__main__":
    unittest.main()
