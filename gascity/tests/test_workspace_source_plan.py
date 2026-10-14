from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def module():
    spec = importlib.util.spec_from_file_location("workspace_source_plan", SCRIPTS / "workspace_source_plan.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def run_record():
    return {
        "version": 1, "workflow_root_id": "root-1", "generation": 1,
        "writer_step_id": "capture-1", "input_convoy_id": "convoy-1",
        "source_anchor_id": "anchor-1", "rig_root": "/project",
        "common_git_dir": "/project/.git", "base_oid": "a" * 40,
        "worktree_lifecycle": "new",
    }


def node(owner, predecessors=(), *, strategy=None, members=None):
    return {
        "owner_id": owner,
        "strategy": strategy or ("integration" if len(predecessors) > 1 else "dependent" if predecessors else "isolated"),
        "member_ids": members or [owner],
        "source_predecessor_owner_ids": list(predecessors),
        "single_lane": strategy == "shared-chain",
    }


def plan_record():
    return {
        "version": 1, "workflow_root_id": "root-1", "generation": 1,
        "writer_step_id": "declare-1", "source_plan_owner_id": "convoy-1",
        "base_oid": "a" * 40, "parent_canonical_generation": None,
        "parent_canonical_oid": None,
        "nodes": [node("A"), node("B"), node("C", ["B", "A"]), node("D", ["C"])],
        "terminal_owner_id": "D",
    }


def native_nodes(plan):
    ids = {plan["source_plan_owner_id"]} | {n["owner_id"] for n in plan["nodes"]} | {member for n in plan["nodes"] for member in n["member_ids"]}
    return {bead_id: {
        "id": bead_id, "revision": "17", "status": "open", "assignee": "",
        "metadata": {"gc.root_bead_id": plan["workflow_root_id"], "gc.root_store_ref": "rig:project",
                     "gc.source_root_id": plan["workflow_root_id"], "gc.source_generation": str(plan["generation"])},
    } for bead_id in ids}


def canonical_record(generation=1, oid="b" * 40):
    return {
        "version": 1, "workflow_root_id": "root-1", "generation": generation,
        "writer_step_id": "bind-1", "source_plan_owner_id": "convoy-1",
        "workspace_owner_id": "D", "output_oid": oid,
        "owner_output_sha256": "0" * 64, "summary_path": "/project/summary.md",
        "summary_sha256": "1" * 64,
    }


class SourcePlanGraphTests(unittest.TestCase):
    def setUp(self):
        self.helper = module()

    def check(self, plan=None, *, snapshots=None, run=None, canonical=None):
        plan = plan or plan_record()
        return self.helper.validate_source_plan(
            plan, run or run_record(), native_nodes(plan) if snapshots is None else snapshots,
            store_ref="rig:project", canonical=canonical,
        )

    def test_pending_ab_to_c_to_d_plan_freezes_order_without_output_reads(self):
        plan = plan_record()
        before = copy.deepcopy(plan)
        self.assertEqual(self.check(plan), plan)
        self.assertEqual(plan, before)
        self.assertEqual(plan["nodes"][2]["source_predecessor_owner_ids"], ["B", "A"])
        self.assertEqual(self.helper.source_order(plan), ["A", "B", "C", "D"])

    def test_source_order_is_explicit_and_independent_of_scheduler_dependencies(self):
        plan = plan_record()
        plan["nodes"] = [plan["nodes"][3], plan["nodes"][2], plan["nodes"][1], plan["nodes"][0]]
        snapshots = native_nodes(plan)
        snapshots["A"]["metadata"]["blocks"] = ["D"]
        self.assertEqual(self.check(plan, snapshots=snapshots), plan)
        self.assertEqual(self.helper.source_order(plan), ["B", "A", "C", "D"])

    def test_shared_chain_preserves_member_order_and_allows_owner_as_own_member(self):
        plan = plan_record()
        plan["nodes"] = [node("A"), node("chain", ["A"], strategy="shared-chain", members=["chain", "step-2", "step-3"])]
        plan["terminal_owner_id"] = "chain"
        self.check(plan)
        self.assertEqual(plan["nodes"][1]["member_ids"], ["chain", "step-2", "step-3"])

    def test_duplicate_owners_members_self_and_missing_predecessors_are_refused(self):
        cases = []
        duplicate_owner = plan_record()
        duplicate_owner["nodes"][1]["owner_id"] = "A"
        cases.append(("duplicate owner", duplicate_owner))
        duplicate_member = plan_record()
        duplicate_member["nodes"][1]["member_ids"] = ["A"]
        cases.append(("member.*owner|member.*multiple", duplicate_member))
        self_edge = plan_record()
        self_edge["nodes"][3]["source_predecessor_owner_ids"] = ["D"]
        cases.append(("self", self_edge))
        unknown = plan_record()
        unknown["nodes"][3]["source_predecessor_owner_ids"] = ["missing"]
        cases.append(("missing predecessor", unknown))
        for error, plan in cases:
            with self.subTest(error=error), self.assertRaisesRegex(self.helper.RecordError, error):
                self.check(plan)

    def test_cycles_and_disconnected_producers_cannot_choose_a_terminal(self):
        cyclic = plan_record()
        cyclic["nodes"][0] = node("A", ["D"])
        with self.assertRaisesRegex(self.helper.RecordError, "cycle"):
            self.check(cyclic)
        disconnected = plan_record()
        disconnected["nodes"].append(node("unused"))
        with self.assertRaisesRegex(self.helper.RecordError, "terminal"):
            self.check(disconnected)
        wrong_terminal = plan_record()
        wrong_terminal["terminal_owner_id"] = "C"
        with self.assertRaisesRegex(self.helper.RecordError, "terminal"):
            self.check(wrong_terminal)

    def test_strategy_arity_and_single_lane_are_enforced(self):
        for replacement in [node("D", [], strategy="dependent"), node("D", ["C"], strategy="integration"),
                            node("D", ["A", "B"], strategy="shared-chain")]:
            plan = plan_record()
            plan["nodes"][3] = replacement
            with self.subTest(node=replacement), self.assertRaises(self.helper.RecordError):
                self.check(plan)
        plan = plan_record()
        plan["nodes"][3] = node("D", ["C"], strategy="shared-chain")
        plan["nodes"][3]["single_lane"] = False
        with self.assertRaises(self.helper.RecordError):
            self.check(plan)

    def test_only_exact_native_existing_same_root_generation_and_store_nodes_are_allowed(self):
        plan = plan_record()
        cases = []
        missing = native_nodes(plan)
        del missing["C"]
        cases.append(("missing native", missing))
        wrong_id = native_nodes(plan)
        wrong_id["C"]["id"] = "other-C"
        cases.append(("physical ID", wrong_id))
        for key, value in [("gc.root_bead_id", "foreign-root"), ("gc.root_store_ref", "rig:elsewhere"),
                           ("gc.source_root_id", "foreign-root"), ("gc.source_generation", "2"),
                           ("gc.source_generation", 1), ("gc.source_generation", "01")]:
            invalid = native_nodes(plan)
            invalid["C"]["metadata"][key] = value
            cases.append(("native.*scope", invalid))
        pack_keys_only = native_nodes(plan)
        del pack_keys_only["C"]["metadata"]["gc.root_bead_id"]
        cases.append(("native.*scope", pack_keys_only))
        for error, snapshots in cases:
            with self.subTest(error=error, snapshots=snapshots), self.assertRaisesRegex(self.helper.RecordError, error):
                self.check(plan, snapshots=snapshots)

    def test_native_root_uses_native_precedence_without_adopting_foreign_run(self):
        plan = plan_record()
        snapshots = native_nodes(plan)
        snapshots["C"]["metadata"]["workflow_id"] = "foreign-root"
        with self.assertRaisesRegex(self.helper.RecordError, "native.*scope"):
            self.check(plan, snapshots=snapshots)
        snapshots["C"]["metadata"]["workflow_id"] = "root-1"
        snapshots["C"]["metadata"]["gc.root_bead_id"] = "nested-formula-root"
        self.check(plan, snapshots=snapshots)

    def test_initial_generation_uses_immutable_run_base(self):
        plan = plan_record()
        plan["base_oid"] = "c" * 40
        with self.assertRaisesRegex(self.helper.RecordError, "run base"):
            self.check(plan)
        with self.assertRaisesRegex(self.helper.RecordError, "canonical"):
            self.check(canonical=canonical_record())
        for field, value in [("workflow_root_id", "other-root"), ("worktree_lifecycle", "legacy")]:
            run = run_record()
            run[field] = value
            with self.subTest(field=field), self.assertRaises(self.helper.RecordError):
                self.check(run=run)

    def test_fix_generation_uses_exact_current_canonical_parent(self):
        plan = plan_record()
        plan.update(generation=2, parent_canonical_generation=1, parent_canonical_oid="b" * 40, base_oid="b" * 40)
        self.check(plan, canonical=canonical_record())
        for parent in [None, canonical_record(generation=2), canonical_record(oid="c" * 40),
                       dict(canonical_record(), workflow_root_id="other-root")]:
            with self.subTest(canonical=parent), self.assertRaisesRegex(self.helper.RecordError, "canonical|parent|generation"):
                self.check(plan, canonical=parent)
        invalid = dict(plan, generation=3)
        with self.assertRaisesRegex(self.helper.RecordError, "generation"):
            self.check(invalid, canonical=canonical_record())
        invalid = dict(plan, base_oid="c" * 40)
        with self.assertRaisesRegex(self.helper.RecordError, "parent"):
            self.check(invalid, canonical=canonical_record())

    def test_exact_replay_and_changed_predecessor_order_are_distinct(self):
        plan = plan_record()
        self.assertTrue(self.helper.verify_replay("source-plan", plan, copy.deepcopy(plan)))
        changed = copy.deepcopy(plan)
        changed["nodes"][2]["source_predecessor_owner_ids"].reverse()
        with self.assertRaisesRegex(self.helper.RecordError, "conflicting replay"):
            self.helper.verify_replay("source-plan", plan, changed)

    def test_cli_validation_reports_digest_and_order_and_refuses_missing_node(self):
        plan = plan_record()
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for filename, payload in [("plan.json", plan), ("run.json", run_record()), ("nodes.json", native_nodes(plan))]:
                (root / filename).write_text(json.dumps(payload))
            command = [sys.executable, str(SCRIPTS / "workspace_source_plan.py"), "validate", "--plan", str(root / "plan.json"),
                       "--run", str(root / "run.json"), "--native-nodes", str(root / "nodes.json"), "--store-ref", "rig:project"]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["source_order"], ["A", "B", "C", "D"])
            self.assertEqual(output["sha256"], self.helper.record_sha256(plan))
            (root / "nodes.json").write_text("{}")
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")


class SourcePlanWriterTests(unittest.TestCase):
    """Exercise the production adapter through a deterministic native command port."""
    def setUp(self):
        import workspace_store
        self.adapter = workspace_store
        self.helper = module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.common = self.root / "common.git"
        self.common.mkdir()
        self.plan = plan_record()
        run = run_record()
        run["rig_root"], run["common_git_dir"] = str(self.root), str(self.common)
        self.rows = native_nodes(self.plan)
        self.rows.update({
            "root-1": self.row("root-1", "open", {"gc.implementation_run_ref": json.dumps(
                {"kind": "run", "identity": list(self.helper.record_identity("run", run)), "bead_id": "run-record"})}),
            "run-record": self.row("run-record", "closed", {"gc.implementation_run": json.dumps(run)}),
            "plan-record": self.row("plan-record", "closed", {}),
            "authority-1": self.row("authority-1", "closed", {}),
            "declare-1": self.row("declare-1", "in_progress", {
                "gc.session_id": "session-1", "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:project",
                "gc.step_ref": "declare-source-plan",
            }, assignee="worker"),
        })
        for row in self.rows.values():
            row.setdefault("type", "task")
            row.setdefault("labels", [])
        formula = SCRIPTS.parents[1] / "formulas" / "build-basic.formula.toml"
        self.rows["root-1"]["metadata"].update({"gc.root_store_ref": "rig:project",
            "gc.formula_name": "build-basic", "gc.formula_source": str(formula),
            "gc.formula_hash": hashlib.sha256(formula.read_bytes()).hexdigest()})
        self.rows["declare-1"]["metadata"].update({"gc.step_id": "decompose",
            "gc.build.artifact_schema": "gc.build.decomposition.v1", "gc.native_step_dependencies.v1": "[]"})
        self.store = workspace_store.WorkspaceStore("rig:project", cwd=self.root, common_git_dir=self.common)
        self.store._command = self.command
        self.attempt = workspace_store.Attempt("session-1", "instance-1", "declare-1")
        self.requests = []

    @staticmethod
    def row(bead_id, status, metadata, assignee=""):
        return {"id": bead_id, "revision": "17", "status": status, "assignee": assignee,
                "type": "task", "labels": [], "metadata": metadata}

    def command(self, arguments, attempt=None):
        if arguments[0].startswith("--snapshot="):
            ids = arguments[0].partition("=")[2].split(",")
            rows = [copy.deepcopy(self.rows[bead_id]) for bead_id in ids]
        else:
            self.assertEqual(attempt, self.attempt)
            request = json.loads(pathlib.Path(arguments[0].partition("=")[2]).read_text())
            self.requests.append(request)
            for patch in request["rows"]:
                row = self.rows[patch["id"]]
                if row["revision"] != patch["expected_revision"]:
                    raise self.adapter.StoreError("native revision changed before transaction")
                self.assertEqual(row["status"], patch["expected_status"])
                self.assertEqual(row["assignee"], patch["expected_assignee"])
            rows = []
            for patch in request["rows"]:
                row = self.rows[patch["id"]]
                changed = any(row["metadata"].get(key) != value for key, value in patch["set"].items())
                row["metadata"].update(patch["set"])
                row["revision"] = str(int(row["revision"]) + 1)
                rows.append({"id": row["id"], "revision": row["revision"], "changed": changed})
        return {"schema_version": "1", "ok": True, "store_ref": "rig:project", "rows": rows}

    def writer_map(self):
        from workspace_records import canonical_bytes
        claim_id = self.attempt.claimed_bead_id
        metadata = self.rows[claim_id]["metadata"]
        expansion = metadata.get("gc.attach_root_id", "root-1")
        formula = self.rows[expansion]["metadata"]
        return self.adapter.CookedWriterMap(canonical_bytes({
            "version": 1, "workflow_root_id": "root-1", "store_ref": "rig:project",
            "source_member_id": "root-1", "expansion_root_id": expansion,
            "formula_name": formula["gc.formula_name"], "formula_hash": formula["gc.formula_hash"],
            "formula_source": formula["gc.formula_source"], "steps": [{"bead_id": claim_id,
                "step_id": metadata["gc.step_id"], "step_ref": metadata["gc.step_ref"],
                "dependencies": [], "record_kinds": ["source-plan"]}]}))

    def prepare(self, *, nonce="1" * 64, attempt=None, implementation_convoy_id=None, writer_rows=None):
        return self.helper.declare_plan(self.store, attempt or self.attempt, self.plan,
                                        run_record_id="run-record", record_bead_id="plan-record",
                                        authority_id="authority-1", implementation_convoy_id=implementation_convoy_id,
                                        operation_nonce=nonce, writer_map=self.writer_map(), writer_rows=writer_rows)

    def test_first_publication_joins_grant_payload_reference_and_membership_in_one_native_batch(self):
        prepared = self.prepare()
        request = prepared.request
        ids = [patch["id"] for patch in request["rows"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(self.rows))
        self.assertTrue(all(patch["require_change"] for patch in request["rows"]))
        self.assertEqual(self.requests, [])
        result = self.store.execute(prepared)
        self.assertEqual(result["outcome"], "committed")
        self.assertEqual(len(self.requests), 1)
        payload = self.store.read_record("source-plan", "plan-record")
        self.assertEqual(payload, self.plan)
        ref = json.loads(self.rows["convoy-1"]["metadata"]["gc.source_plan_ref"])
        self.assertEqual(ref, {"kind": "source-plan", "identity": list(self.helper.record_identity("source-plan", self.plan)),
                               "bead_id": "plan-record"})

    def test_publication_requires_exact_readback_and_receipt_excludes_native_grant_tokens(self):
        receipt = self.helper.publish_plan(self.store, self.prepare())
        self.assertEqual(receipt["outcome"], "committed")
        self.assertEqual(receipt["submission_outcome"], "committed")
        self.assertNotIn("instance-1", json.dumps(receipt))
        self.assertNotIn("gc.workspace_write_grant", json.dumps(receipt))
        self.assertEqual(len(self.requests), 1)

    def test_lost_reply_uses_readonly_intent_resolution_without_second_submission(self):
        original = self.command
        def lose_reply(arguments, attempt=None):
            result = original(arguments, attempt)
            if arguments[0].startswith("--request="):
                result["rows"] = []
            return result
        self.store._command = lose_reply
        receipt = self.helper.publish_plan(self.store, self.prepare())
        self.assertEqual(receipt["submission_outcome"], "unknown")
        self.assertEqual(receipt["outcome"], "committed")
        self.assertFalse(receipt["retry_allowed"])
        self.assertEqual(len(self.requests), 1)

    def test_exact_replay_still_requires_current_writer_grant(self):
        self.assertEqual(self.store.execute(self.prepare())["outcome"], "committed")
        self.assertEqual(self.store.execute(self.prepare(nonce="2" * 64))["outcome"], "replayed")
        changed_attempt = self.adapter.Attempt("session-1", "replacement-instance", "declare-1")
        with self.assertRaisesRegex(self.adapter.StoreError, "writer attempt"):
            self.prepare(nonce="3" * 64, attempt=changed_attempt)
        self.assertEqual(len(self.requests), 2)

    def test_current_native_step_source_membership_publishes_with_the_plan(self):
        self.plan["source_plan_owner_id"] = "declare-1"
        prepared = self.prepare()
        before = self.rows["declare-1"]["metadata"]
        self.assertNotIn("gc.source_root_id", before)
        self.assertNotIn("gc.source_generation", before)
        self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
        metadata = self.rows["declare-1"]["metadata"]
        self.assertEqual(metadata["gc.source_root_id"], "root-1")
        self.assertEqual(metadata["gc.source_generation"], "1")
        self.assertIn("gc.source_plan_ref", metadata)
        self.assertEqual(len(self.requests), 1)

    def test_source_membership_projection_cannot_adopt_a_foreign_or_conflicting_native_owner(self):
        self.plan["source_plan_owner_id"] = "declare-1"
        original = copy.deepcopy(self.rows["declare-1"]["metadata"])
        for key, value in [("gc.root_bead_id", "foreign-root"), ("gc.root_store_ref", "rig:elsewhere"),
                           ("gc.source_root_id", "foreign-root"), ("gc.source_generation", "2"),
                           ("gc.source_generation", None)]:
            self.rows["declare-1"]["metadata"] = dict(original, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(self.helper.RecordError):
                self.prepare()
        self.assertEqual(self.requests, [])

    def test_source_membership_change_after_prepare_cannot_partially_publish(self):
        self.plan["source_plan_owner_id"] = "declare-1"
        prepared = self.prepare()
        self.rows["declare-1"]["metadata"]["gc.source_generation"] = "2"
        self.rows["declare-1"]["revision"] = "18"
        self.assertEqual(self.store.execute(prepared)["outcome"], "unknown")
        self.assertNotIn("gc.source_plan", self.rows["plan-record"]["metadata"])
        self.assertNotIn("gc.source_root_id", self.rows["declare-1"]["metadata"])
        self.assertNotIn("gc.source_plan_ref", self.rows["declare-1"]["metadata"])

    def implementation_convoy(self):
        self.rows["root-1"]["metadata"]["gc.input_convoy_id"] = "convoy-1"
        self.rows["implementation-convoy"] = self.row("implementation-convoy", "open", {
            "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:project",
            "gc.source_root_id": "root-1", "gc.source_generation": "1",
        })
        self.rows["implementation-convoy"]["type"] = "convoy"

    def test_native_implementation_convoy_binds_with_plan_and_preserves_original_run_tuple(self):
        self.implementation_convoy()
        before = self.store.read_record("run", "run-record")
        prepared = self.prepare(implementation_convoy_id="implementation-convoy")
        self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
        self.assertEqual(self.store.read_record("run", "run-record"), before)
        metadata = self.rows["root-1"]["metadata"]
        self.assertEqual(metadata["gc.input_convoy_id"], "implementation-convoy")
        self.assertEqual(metadata["gc.build.implementation_convoy_id"], "implementation-convoy")
        convoy = self.rows["implementation-convoy"]["metadata"]
        self.assertEqual(convoy["gc.source_plan_owner_id"], self.plan["source_plan_owner_id"])
        self.assertEqual(convoy["gc.source_plan_sha256"], self.helper.record_sha256(self.plan))
        self.assertEqual(len(self.requests), 1)

    def test_foreign_implementation_convoy_or_changed_intake_cannot_partially_publish(self):
        self.implementation_convoy()
        self.rows["implementation-convoy"]["metadata"]["gc.root_store_ref"] = "rig:foreign"
        with self.assertRaisesRegex(self.adapter.StoreError, "exact native convoy"):
            self.prepare(implementation_convoy_id="implementation-convoy")
        self.assertEqual(self.requests, [])
        self.rows["implementation-convoy"]["metadata"]["gc.root_store_ref"] = "rig:project"
        prepared = self.prepare(implementation_convoy_id="implementation-convoy")
        self.rows["root-1"]["metadata"]["gc.input_convoy_id"] = "replacement-convoy"
        self.rows["root-1"]["revision"] = "18"
        self.assertEqual(self.store.execute(prepared)["outcome"], "unknown")
        self.assertNotIn("gc.source_plan", self.rows["plan-record"]["metadata"])
        self.assertNotIn("gc.source_plan_sha256", self.rows["implementation-convoy"]["metadata"])

    def prepare_fix_with_prior_convoy(self):
        self.implementation_convoy()
        self.assertEqual(self.helper.publish_plan(self.store, self.prepare(
            implementation_convoy_id="implementation-convoy"))["outcome"], "committed")
        self.plan = plan_record()
        self.plan.update(generation=2, writer_step_id="declare-fix", source_plan_owner_id="declare-fix",
                         parent_canonical_generation=1, parent_canonical_oid="b" * 40, base_oid="b" * 40)
        for node in self.plan["nodes"]:
            node["owner_id"] += "-fix"
            node["member_ids"] = [member + "-fix" for member in node["member_ids"]]
            node["source_predecessor_owner_ids"] = [owner + "-fix" for owner in node["source_predecessor_owner_ids"]]
        self.plan["terminal_owner_id"] = "D-fix"
        for bead_id, row in native_nodes(self.plan).items():
            self.rows[bead_id] = dict(row, type="task", labels=[])
        self.rows["declare-fix"] = self.row("declare-fix", "in_progress", {
            "gc.session_id": "session-fix", "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:project",
            "gc.step_ref": "declare-fix-source-plan", "gc.step_id": "decompose",
            "gc.build.artifact_schema": "gc.build.decomposition.v1", "gc.native_step_dependencies.v1": "[]",
            "gc.attach_root_id": "fix-expansion"}, assignee="worker")
        self.rows["fix-expansion"] = self.row("fix-expansion", "open", {
            key: value for key, value in self.rows["root-1"]["metadata"].items()
            if key.startswith("gc.formula_") or key == "gc.root_store_ref"})
        self.rows["fix-expansion"]["metadata"]["gc.root_bead_id"] = "root-1"
        self.attempt = self.adapter.Attempt("session-fix", "instance-fix", "declare-fix")
        for bead_id in ("plan-record-fix", "authority-fix"):
            self.rows[bead_id] = self.row(bead_id, "closed", {})
        self.rows["implementation-convoy-fix"] = self.row("implementation-convoy-fix", "open", {
            "gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:project",
            "gc.source_root_id": "root-1", "gc.source_generation": "2"})
        self.rows["implementation-convoy-fix"]["type"] = "convoy"
        canonical = canonical_record()
        self.rows["canonical-record"] = self.row("canonical-record", "closed", {"gc.canonical": json.dumps(canonical)})
        self.rows["root-1"]["metadata"]["gc.canonical_ref"] = json.dumps({
            "kind": "canonical", "identity": list(self.helper.record_identity("canonical", canonical)),
            "bead_id": "canonical-record"})

    def prepare_fix(self):
        return self.helper.declare_plan(self.store, self.attempt, self.plan, run_record_id="run-record",
            record_bead_id="plan-record-fix", authority_id="authority-fix",
            implementation_convoy_id="implementation-convoy-fix", operation_nonce="4" * 64,
            writer_map=self.writer_map())

    def test_fix_convoy_replacement_fences_the_preceding_native_generation(self):
        self.prepare_fix_with_prior_convoy()
        original_run = self.store.read_record("run", "run-record")
        original_convoy = copy.deepcopy(self.rows["implementation-convoy"]["metadata"])
        original_plan = self.store.read_record("source-plan", "plan-record")
        prepared = self.prepare_fix()
        rows = {row["id"]: row for row in prepared.request["rows"]}
        self.assertEqual(rows["implementation-convoy"]["expected_revision"], self.rows["implementation-convoy"]["revision"])
        self.assertEqual(rows["implementation-convoy"]["set"], {"gc.workspace_transition_nonce": "4" * 64})
        self.assertLessEqual(len(rows), 100)
        self.assertEqual(self.helper.publish_plan(self.store, prepared)["outcome"], "committed")
        self.assertEqual(self.rows["root-1"]["metadata"]["gc.input_convoy_id"], "implementation-convoy-fix")
        self.assertEqual(self.rows["root-1"]["metadata"]["gc.build.implementation_convoy_id"], "implementation-convoy-fix")
        self.assertEqual(self.store.read_record("run", "run-record"), original_run)
        self.assertEqual(self.store.read_record("source-plan", "plan-record"), original_plan)
        previous = self.rows["implementation-convoy"]["metadata"]
        self.assertEqual(previous["gc.workspace_transition_nonce"], "4" * 64)
        self.assertEqual({key: value for key, value in previous.items() if key != "gc.workspace_transition_nonce"},
                         {key: value for key, value in original_convoy.items() if key != "gc.workspace_transition_nonce"})

    def test_original_cooked_rows_are_not_refreshed_before_plan_publication(self):
        original = {bead_id: copy.deepcopy(self.rows[bead_id]) for bead_id in ("root-1", "declare-1")}
        self.rows["declare-1"]["revision"] = "18"
        prepared = self.prepare(writer_rows=original)
        request = {row["id"]: row for row in prepared.request["rows"]}
        self.assertEqual(request["declare-1"]["expected_revision"], "17")
        self.assertEqual(self.helper.publish_plan(self.store, prepared)["outcome"], "unknown")
        self.assertNotIn("gc.source_plan", self.rows["plan-record"]["metadata"])

    def test_prior_convoy_race_cannot_partially_replace_the_generation(self):
        self.prepare_fix_with_prior_convoy()
        prepared = self.prepare_fix()
        self.rows["implementation-convoy"]["metadata"]["gc.source_generation"] = "2"
        self.rows["implementation-convoy"]["revision"] = "19"
        receipt = self.helper.publish_plan(self.store, prepared)
        self.assertEqual(receipt["outcome"], "unknown")
        self.assertFalse(receipt["retry_allowed"])
        self.assertEqual(self.rows["root-1"]["metadata"]["gc.input_convoy_id"], "implementation-convoy")
        self.assertNotIn("gc.source_plan", self.rows["plan-record-fix"]["metadata"])
        self.assertNotIn("gc.source_plan_sha256", self.rows["implementation-convoy-fix"]["metadata"])
        self.assertNotIn("gc.workspace_write_grant", self.rows["authority-fix"]["metadata"])

    def test_prior_convoy_foreign_scope_or_wrong_generation_refuses_before_submission(self):
        self.prepare_fix_with_prior_convoy()
        before = len(self.requests)
        original = copy.deepcopy(self.rows["implementation-convoy"]["metadata"])
        for key, value in [("gc.root_bead_id", "foreign-root"), ("gc.root_store_ref", "rig:foreign"),
                           ("gc.source_root_id", "foreign-root"), ("gc.source_generation", "0"),
                           ("gc.source_generation", "2")]:
            self.rows["implementation-convoy"]["metadata"] = dict(original, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(self.helper.RecordError):
                self.prepare_fix()
        self.assertEqual(len(self.requests), before)
        self.assertNotIn("gc.source_plan", self.rows["plan-record-fix"]["metadata"])

    def test_canonical_pointer_change_after_prepare_refuses_without_partial_publication(self):
        prepared = self.prepare()
        self.rows["root-1"]["metadata"]["gc.canonical_ref"] = "new-pointer"
        self.rows["root-1"]["revision"] = "18"
        result = self.store.execute(prepared)
        self.assertEqual(result["outcome"], "unknown")
        self.assertFalse(result["retry_allowed"])
        self.assertNotIn("gc.source_plan", self.rows["plan-record"]["metadata"])
        self.assertNotIn("gc.source_plan_ref", self.rows["convoy-1"]["metadata"])
        self.assertNotIn("gc.workspace_write_grant", self.rows["authority-1"]["metadata"])

    def test_changed_predecessor_scope_before_commit_cannot_publish_the_plan(self):
        prepared = self.prepare()
        self.rows["B"]["metadata"]["gc.source_generation"] = "2"
        self.rows["B"]["revision"] = "18"
        self.assertEqual(self.store.execute(prepared)["outcome"], "unknown")
        self.assertNotIn("gc.source_plan", self.rows["plan-record"]["metadata"])

    def test_null_canonical_and_partial_existing_plan_reference_fail_before_native_write(self):
        self.rows["root-1"]["metadata"]["gc.canonical_ref"] = None
        with self.assertRaises(self.helper.RecordError):
            self.prepare()
        del self.rows["root-1"]["metadata"]["gc.canonical_ref"]
        self.rows["convoy-1"]["metadata"]["gc.source_plan_ref"] = json.dumps({
            "kind": "source-plan", "identity": list(self.helper.record_identity("source-plan", self.plan)), "bead_id": "plan-record"})
        with self.assertRaisesRegex(self.helper.RecordError, "reference has no record"):
            self.prepare()
        self.assertEqual(self.requests, [])

    def test_fix_generation_fences_the_exact_parent_canonical_payload(self):
        self.plan.update(generation=2, parent_canonical_generation=1, parent_canonical_oid="b" * 40, base_oid="b" * 40)
        for bead_id, row in native_nodes(self.plan).items():
            row.update(type="task", labels=[])
            self.rows[bead_id] = row
        canonical = canonical_record()
        self.rows["canonical-record"] = self.row("canonical-record", "closed", {"gc.canonical": json.dumps(canonical)})
        self.rows["root-1"]["metadata"]["gc.canonical_ref"] = json.dumps({
            "kind": "canonical", "identity": list(self.helper.record_identity("canonical", canonical)), "bead_id": "canonical-record"})
        prepared = self.prepare()
        self.assertEqual(self.store.execute(prepared)["outcome"], "committed")
        self.assertEqual(self.store.read_record("source-plan", "plan-record")["base_oid"], canonical["output_oid"])


if __name__ == "__main__":
    unittest.main()
