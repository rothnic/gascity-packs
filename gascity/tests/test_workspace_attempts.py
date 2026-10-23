"""Native-shaped controller attachments; these doubles are not backend proof."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assets" / "scripts"))
import workspace_cooked as cooked
from workspace_records import RecordError, canonical_bytes
from workspace_store import Attempt, CookedWriterMap, RecordWrite, WorkspaceStore, validate_cooked_writer_map


class NativeAttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "build-basic.formula.toml"
        self.path.write_text('formula = "build-basic"\n')
        self.configure()

    def row(self, bead_id, metadata=None, status="closed"):
        return dict(id=bead_id, revision="9007199254740993", status=status,
                    assignee="worker" if status == "in_progress" else "", type="task", labels=[],
                    metadata={"gc.root_bead_id": "root-1", "gc.root_store_ref": "rig:fixture", **(metadata or {})})

    def configure(self, latest=2, kind="ralph", scoped=False, attached=False, authored_suffix=False):
        self.latest, self.kind, self.scoped = latest, kind, scoped
        self.scope_details = {}
        child_id = "checkpoint-scope-check" if authored_suffix else "apply-story-findings"
        logical = "implement" if scoped else "decompose"
        self.logical = logical
        control_ref = "build-basic." + logical
        suffix = "iteration" if kind == "ralph" else "attempt"
        seed_ref = logical + ".iteration.1" if kind == "ralph" else control_ref + ".attempt.1"
        designation = {"gc.run_target": "gc.implementation-worker" if scoped else "gc.task-decomposer",
                       "gc.build.artifact_schema": "gc.build.implementation-summary.v1" if scoped else "gc.build.decomposition.v1"}
        source = dict(id=logical, title="Native task", description="Checks: {{checks}}", metadata=designation,
                      needs=["plan-review"], **{kind: dict(max_attempts=3)})
        if kind == "ralph":
            source[kind]["check"] = dict(mode="exec", path="/owned/check.sh", timeout="1m")
        if scoped:
            source["children"] = [dict(id=child_id, title="Apply findings", metadata=designation)]
            if authored_suffix:
                source["children"].append(dict(id="checkpoint", title="Exempt checkpoint", metadata={"gc.kind": "check"}))
        self.source = source
        self.formula = dict(ok=True, name="build-basic", vars=[], steps=[], deps=[])
        self.rows = {"root-1": self.row("root-1")}
        self.expansion_id = "expansion-1" if attached else "root-1"
        self.rows.setdefault(self.expansion_id, self.row(self.expansion_id))
        self.rows[self.expansion_id]["metadata"].update({"gc.formula_name": "build-basic",
            "gc.formula_hash": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "gc.formula_source": str(self.path), "gc.var.checks": '[{"id":"test","argv":["true"]}]'})
        def initial(metadata):
            if attached:
                metadata = dict(metadata, **{"gc.attach_root_id": self.expansion_id})
            return metadata
        def template(ref, metadata, dependencies=()):
            self.formula["steps"].append(dict(id=ref, metadata=copy.deepcopy(metadata)))
            for need in dependencies:
                self.formula["deps"].append(dict(step_id=ref, depends_on_id=need, type="blocks"))
        prior = "build-basic.plan-review"
        native_dependencies = json.dumps(sorted([prior] + ([child_id] if scoped else [])
            + (["checkpoint"] if scoped and authored_suffix else [])), separators=(",", ":"))
        template(prior, {"gc.step_id": prior})
        self.rows["prior-1"] = self.row("prior-1", initial({"gc.step_id": prior, "gc.step_ref": prior, cooked.TOPOLOGY: "[]"}))
        control = {**designation, "gc.kind": kind, "gc.step_id": logical, "gc.step_ref": control_ref,
                   "gc.max_attempts": "3", "gc.control_epoch": str(latest), cooked.TOPOLOGY: native_dependencies}
        self.rows["control-1"] = self.row("control-1", initial(control), "open")
        template(control_ref, {key: value for key, value in control.items() if key != cooked.TOPOLOGY}, (prior,))
        spec_ref = control_ref + ".spec"
        spec_meta = {"gc.kind": "spec", "gc.spec_for": logical, "gc.spec_for_ref": logical,
                     "gc.step_id": spec_ref, "gc.step_ref": spec_ref}
        template(spec_ref, spec_meta)
        self.formula["steps"][-1]["description"] = json.dumps(source)
        self.rows["spec-1"] = self.row("spec-1", initial(dict(spec_meta, **{cooked.TOPOLOGY: "[]"})))
        seed_meta = {**designation, "gc.step_id": logical, "gc.step_ref": seed_ref,
                     "gc.control_for": logical, "gc.attempt": "1"}
        if kind == "ralph":
            seed_meta.update({"gc.ralph_step_id": logical, "gc.iteration": "1"})
        else:
            seed_meta["gc.retry_attempt"] = "1"
        if scoped:
            seed_meta.update({"gc.kind": "scope", "gc.scope_role": "body", "gc.scope_name": logical})
        template("build-basic." + logical + "." + suffix + ".1", seed_meta, (prior,))
        self.formula["deps"].append(dict(step_id=control_ref,
            depends_on_id="build-basic." + logical + "." + suffix + ".1", type="blocks"))
        child_seed = seed_ref + "." + child_id
        if scoped:
            child_meta = {**designation, "gc.step_id": child_id, "gc.step_ref": child_seed,
                "gc.scope_ref": seed_ref, "gc.scope_role": "member", "gc.ralph_step_id": logical,
                "gc.attempt": "1", "gc.iteration": "1", "gc.on_fail": "abort_scope"}
            template(child_seed, child_meta)
            check_meta = {key: value for key, value in child_meta.items()
                          if key in ("gc.step_id", "gc.scope_ref", "gc.ralph_step_id", "gc.attempt", "gc.on_fail")}
            check_meta.update({"gc.kind": "scope-check", "gc.scope_role": "control",
                               "gc.step_ref": child_seed + "-scope-check", "gc.control_for": child_seed})
            template(child_seed + "-scope-check", check_meta)
            self.formula["deps"].extend([
                dict(step_id="build-basic." + logical + "." + suffix + ".1", depends_on_id=child_seed, type="blocks"),
                dict(step_id=child_seed + "-scope-check", depends_on_id=child_seed, type="blocks")])
            if authored_suffix:
                checkpoint_meta = {key: value for key, value in child_meta.items()
                                   if key not in designation}
                checkpoint_meta.update({"gc.kind": "check", "gc.step_id": "checkpoint",
                                        "gc.step_ref": seed_ref + ".checkpoint"})
                template(seed_ref + ".checkpoint", checkpoint_meta)
                self.formula["deps"].append(dict(step_id="build-basic." + logical + "." + suffix + ".1",
                    depends_on_id=seed_ref + ".checkpoint", type="blocks"))
        for number in range(1, latest+1):
            root_id = "attempt-" + str(number)
            prefix = seed_ref if number == 1 else control_ref + "." + suffix + "." + str(number)
            metadata = copy.deepcopy(seed_meta)
            if number > 1:
                metadata.update({"gc.kind": "scope" if scoped else "task", "gc.step_ref": prefix,
                    "gc.control_for": "control-1", "gc.logical_bead_id": "control-1",
                    "gc.attempt": str(number), "gc.idempotency_key": "control-1:attempt:" + str(number)})
                if kind == "ralph":
                    metadata["gc.iteration"] = str(number)
                    if not scoped:
                        metadata.pop("gc.ralph_step_id")
                else:
                    metadata["gc.retry_attempt"] = str(number)
            else:
                metadata["gc.logical_bead_id"] = "control-1"
            metadata[cooked.TOPOLOGY] = native_dependencies
            self.rows[root_id] = self.row(root_id, initial(metadata), "in_progress" if number == latest and not scoped else "closed")
            if scoped:
                child = copy.deepcopy(child_meta)
                child.update({"gc.step_ref": prefix + "." + child_id, "gc.scope_ref": prefix,
                              "gc.attempt": str(number), "gc.iteration": str(number), cooked.TOPOLOGY: "[]"})
                check = copy.deepcopy(check_meta)
                check.update({"gc.step_ref": child["gc.step_ref"] + "-scope-check", "gc.scope_ref": prefix,
                              "gc.control_for": child["gc.step_ref"], "gc.attempt": str(number), cooked.TOPOLOGY: "[]"})
                if number > 1:
                    child["gc.kind"] = "task"
                    child["gc.attach_root_id"] = check["gc.attach_root_id"] = root_id
                self.rows["child-"+str(number)] = self.row("child-"+str(number), initial(child) if number == 1 else child,
                    "in_progress" if number == latest else "closed")
                self.rows["check-"+str(number)] = self.row("check-"+str(number), initial(check) if number == 1 else check)
                if authored_suffix:
                    checkpoint = copy.deepcopy(checkpoint_meta)
                    checkpoint.update({"gc.step_ref": prefix + ".checkpoint", "gc.scope_ref": prefix,
                        "gc.attempt": str(number), "gc.iteration": str(number), cooked.TOPOLOGY: "[]"})
                    if number > 1:
                        checkpoint["gc.attach_root_id"] = root_id
                    self.rows["checkpoint-"+str(number)] = self.row("checkpoint-"+str(number),
                        initial(checkpoint) if number == 1 else checkpoint)
        physical_blocks = {"control-1": ["prior-1", *("attempt-" + str(number) for number in range(1, latest+1))]}
        for number in range(1, latest+1):
            physical_blocks["attempt-"+str(number)] = (["prior-1"] if number == 1 else []) + (
                ["child-"+str(number)] + (["checkpoint-"+str(number)] if authored_suffix else []) if scoped else [])
            if scoped:
                physical_blocks["child-"+str(number)] = []
                physical_blocks["check-"+str(number)] = ["child-"+str(number)]
                if authored_suffix:
                    physical_blocks["checkpoint-"+str(number)] = []
        self.scope_details = {bead_id: dict(copy.deepcopy(self.rows[bead_id]), dependencies=[
            dict(id=need, dependency_type="blocks") for need in needs]) for bead_id, needs in physical_blocks.items()}
        self.claim = "child-"+str(latest) if scoped else "attempt-"+str(latest)
        self.detail = dict(id="spec-1", revision=self.rows["spec-1"]["revision"], status="closed",
            updated_at="2026-10-15T00:00:00Z", description=json.dumps(source).replace("{{checks}}", '[{\\"id\\":\\"test\\",\\"argv\\":[\\"true\\"]}]'))
        outer = self
        class Store:
            gc = "gc"
            cwd = outer.tmp.name
            store_ref = "rig:fixture"
            def snapshot(self, ids):
                return {bead_id: copy.deepcopy(outer.rows[bead_id]) for bead_id in ids}
        self.store = Store()

    def read(self, claimed=None, read_only=False):
        def native(gc, cwd, argv, rig, **options):
            if argv[:2] == ["bd", "show"]:
                if argv[2:5] == ["--exact-store", "--json", "--"]:
                    self.assertTrue(options["require_array"])
                    self.assertFalse(options.get("unwrap_singleton", False))
                    return [copy.deepcopy(self.scope_details[bead_id]) for bead_id in argv[5:]]
                self.assertTrue(options["unwrap_singleton"] and options["require_array"])
                if argv[2] in self.scope_details:
                    return copy.deepcopy(self.scope_details[argv[2]])
                return copy.deepcopy(self.detail)
            return copy.deepcopy(self.formula)
        with patch.object(cooked, "_native_list", return_value=list(self.rows)), patch.object(cooked, "native_json", side_effect=native):
            return cooked.read_cooked_writer_map(self.store, workflow_root_id="root-1", claimed_step_id=claimed or self.claim,
                                                  read_only=read_only)

    def configure_outer_scope(self, latest=3, kind="ralph", role="member", scoped=False):
        self.configure(latest=latest, kind=kind, scoped=scoped)
        scope = {"gc.scope_ref": "build-body", "gc.scope_role": role, "gc.on_fail": "abort_scope"}
        self.source["metadata"].update(scope)
        spec = next(step for step in self.formula["steps"] if step["metadata"].get("gc.kind") == "spec")
        spec["description"] = json.dumps(self.source)
        description = json.loads(self.detail["description"])
        description["metadata"].update(scope)
        self.detail["description"] = json.dumps(description)
        self.rows["control-1"]["metadata"].update(scope)
        self.scope_details["control-1"]["metadata"].update(scope)
        control = next(step for step in self.formula["steps"] if step["metadata"].get("gc.kind") == kind)
        control["metadata"].update(scope)
        check_meta = {"gc.kind": "scope-check", "gc.step_id": self.logical,
            "gc.step_ref": control["id"] + "-scope-check", "gc.control_for": self.logical,
            "gc.scope_ref": "build-body", "gc.scope_role": "control", "gc.on_fail": "abort_scope",
            cooked.TOPOLOGY: self.rows["control-1"]["metadata"][cooked.TOPOLOGY]}
        self.rows["outer-check"] = self.row("outer-check", check_meta, "open")
        self.formula["steps"].append(dict(id=check_meta["gc.step_ref"],
            metadata={key: value for key, value in check_meta.items() if key != cooked.TOPOLOGY}))
        self.formula["deps"].append(dict(step_id=check_meta["gc.step_ref"], depends_on_id=control["id"], type="blocks"))
        self.scope_details["outer-check"] = dict(copy.deepcopy(self.rows["outer-check"]), dependencies=[
            dict(id="control-1", dependency_type="blocks")])
        for number in range(2, latest+1):
            root_id = "attempt-" + str(number)
            inherited = dict(scope, **({"gc.scope_role": "body"} if scoped else {}))
            self.rows[root_id]["metadata"].update(inherited)
            self.scope_details[root_id]["metadata"].update(inherited)
            if not scoped:
                prefix = self.rows[root_id]["metadata"]["gc.step_ref"]
                check = {"gc.kind": "scope-check", "gc.step_id": self.logical,
                         "gc.step_ref": prefix+"-scope-check", "gc.control_for": prefix,
                         "gc.scope_ref": "build-body", "gc.scope_role": "control",
                         "gc.on_fail": "abort_scope", "gc.attempt": str(number), cooked.TOPOLOGY: "[]"}
                bead_id = "attempt-check-" + str(number)
                self.rows[bead_id] = self.row(bead_id, dict(check, **{"gc.attach_root_id": root_id}),
                    "open" if number == latest else "closed")
                self.scope_details[bead_id] = dict(copy.deepcopy(self.rows[bead_id]), dependencies=[
                    dict(id=root_id, dependency_type="blocks")])

    def test_outer_scope_check_composes_with_current_native_attempt_history(self):
        for latest in (2, 3):
            for kind in ("ralph", "retry"):
                for role in ("setup", "member"):
                    with self.subTest(latest=latest, kind=kind, role=role):
                        self.configure_outer_scope(latest=latest, kind=kind, role=role)
                        writer_map, rows = self.read()
                        self.assertIsNotNone(writer_map.lineage_bytes)
                        entry = next(item for item in writer_map.declaration["steps"] if item["bead_id"] == "outer-check")
                        self.assertEqual(entry["record_kinds"], [])
                        validate_cooked_writer_map(writer_map, rows, store_ref="rig:fixture",
                            workflow_root_id="root-1", record_kind="source-plan", claimed_step_id=self.claim)
                        with self.assertRaises(RecordError):
                            self.read("attempt-1")
                        with self.assertRaises(RecordError):
                            self.read("outer-check")

    def test_real_shaped_second_and_third_iterations_keep_exact_history(self):
        for number in (2, 3):
            with self.subTest(number=number):
                self.configure(latest=number)
                writer_map, rows = self.read()
                self.assertIsNotNone(writer_map.lineage_bytes)
                self.assertEqual(rows, self.rows)
                self.assertEqual(len([step for step in writer_map.declaration["steps"] if step["step_id"] == "decompose"]), number+1)
                self.assertEqual(next(step["record_kinds"] for step in writer_map.declaration["steps"] if step["bead_id"] == self.claim), ["source-plan"])

    def test_retry_second_and_third_attempts_keep_their_own_counter(self):
        for number in (2, 3):
            with self.subTest(number=number):
                self.configure(latest=number, kind="retry")
                writer_map, _ = self.read()
                self.assertIn(b'"kind":"retry"', writer_map.lineage_bytes)

    def test_native_integer_control_epochs_keep_exact_second_and_third_history(self):
        for number in (2, 3):
            for kind in ("ralph", "retry"):
                for epoch in (str(number), number - 1, number):
                    with self.subTest(number=number, kind=kind, epoch=epoch):
                        self.configure(latest=number, kind=kind)
                        self.rows["control-1"]["metadata"]["gc.control_epoch"] = epoch
                        self.scope_details["control-1"]["metadata"]["gc.control_epoch"] = epoch
                        writer_map, rows = self.read()
                        self.assertEqual(rows, self.rows)
                        self.assertIs(type(rows["control-1"]["metadata"]["gc.control_epoch"]), type(epoch))
                        validate_cooked_writer_map(writer_map, rows, store_ref="rig:fixture",
                            workflow_root_id="root-1", record_kind="source-plan", claimed_step_id=self.claim)

    def test_invalid_control_epochs_refuse_discovery_and_retained_maps(self):
        for epoch in (True, False, 2.0, None, [], {}, 0, -2, 9,
                      "", "0", "-2", "02", "+2", " 2", "2 ", "2.0"):
            with self.subTest(epoch=epoch):
                self.configure(latest=2)
                writer_map, rows = self.read()
                self.rows["control-1"]["metadata"]["gc.control_epoch"] = epoch
                rows["control-1"]["metadata"]["gc.control_epoch"] = epoch
                with self.assertRaises(RecordError):
                    self.read()
                with self.assertRaises(RecordError):
                    validate_cooked_writer_map(writer_map, rows, store_ref="rig:fixture",
                        workflow_root_id="root-1", record_kind="source-plan", claimed_step_id=self.claim)

    def test_native_integer_epoch_does_not_loosen_attempt_or_maximum_counters(self):
        for kind, bead_id, key, value in (("ralph", "attempt-2", "gc.attempt", 2),
                ("retry", "attempt-2", "gc.retry_attempt", 2),
                ("ralph", "control-1", "gc.max_attempts", 3)):
            with self.subTest(kind=kind, key=key):
                self.configure(latest=2, kind=kind)
                self.rows["control-1"]["metadata"]["gc.control_epoch"] = 2
                self.rows[bead_id]["metadata"][key] = value
                with self.assertRaises(RecordError):
                    self.read()

    def test_scoped_native_body_follows_original_expansion_and_checks(self):
        for attached in (False, True):
            with self.subTest(attached=attached):
                self.configure(latest=3, scoped=True, attached=attached)
                writer_map, _ = self.read()
                self.assertEqual(writer_map.declaration["expansion_root_id"], self.expansion_id)
                self.assertEqual(next(step["record_kinds"] for step in writer_map.declaration["steps"] if step["bead_id"] == self.claim), ["workspace"])

    def test_authored_scope_check_suffix_keeps_writer_and_exempt_sibling(self):
        # Native applyAttemptRecipeScopeChecks reserves every authored ID before
        # minting checks; a suffix alone does not identify a generated control.
        for latest in (2, 3):
            for attached in (False, True):
                with self.subTest(latest=latest, attached=attached):
                    self.configure(latest=latest, scoped=True, attached=attached, authored_suffix=True)
                    writer_map, rows = self.read(read_only=True)
                    entries = {step["bead_id"]: step for step in writer_map.declaration["steps"]}
                    self.assertEqual(entries[self.claim]["record_kinds"], [])
                    with self.assertRaises(RecordError):
                        self.read()
                    for number in range(1, latest + 1):
                        writer, checkpoint, control = (name + "-" + str(number)
                                                       for name in ("child", "checkpoint", "check"))
                        writer_ref = rows[writer]["metadata"]["gc.step_ref"]
                        self.assertTrue(writer_ref.endswith(".checkpoint-scope-check"))
                        self.assertEqual(rows[checkpoint]["metadata"]["gc.kind"], "check")
                        self.assertEqual(entries[checkpoint]["record_kinds"], [])
                        self.assertEqual(entries[control]["record_kinds"], [])
                        self.assertEqual(rows[control]["metadata"]["gc.control_for"], writer_ref)
                        self.assertEqual(rows[control]["metadata"]["gc.step_ref"], writer_ref + "-scope-check")
                        self.assertEqual([edge["id"] for edge in self.scope_details[control]["dependencies"]], [writer])
                        self.assertEqual([edge["id"] for edge in self.scope_details["attempt-" + str(number)]["dependencies"]],
                                         (["prior-1"] if number == 1 else []) + [writer, checkpoint])
                    validate_cooked_writer_map(writer_map, rows, store_ref="rig:fixture",
                        workflow_root_id="root-1", record_kind=None, claimed_step_id=self.claim, read_only=True)
                    for bead_id in ("checkpoint-" + str(latest), "check-" + str(latest)):
                        self.read(bead_id, read_only=True)
                        with self.assertRaises(RecordError):
                            self.read(bead_id)
                    self.rows["check-" + str(latest)]["metadata"]["gc.control_for"] = rows["checkpoint-" + str(latest)]["metadata"]["gc.step_ref"]
                    with self.assertRaises(RecordError):
                        self.read(read_only=True)

    def test_same_named_sibling_expansion_is_not_adopted(self):
        self.configure(latest=3, scoped=True, attached=True)
        for bead_id in ("control-1", "spec-1", "attempt-1", "child-1", "check-1"):
            sibling = copy.deepcopy(self.rows[bead_id])
            sibling["id"] = "sibling-" + bead_id
            sibling["metadata"]["gc.attach_root_id"] = "sibling-expansion"
            self.rows[sibling["id"]] = sibling
        writer_map, _ = self.read()
        self.assertFalse(any(step["bead_id"].startswith("sibling-") for step in writer_map.declaration["steps"]))

    def test_explicit_read_only_history_and_scope_check_do_not_authorize_writes(self):
        self.read("attempt-1", read_only=True)
        with self.assertRaises(RecordError):
            self.read("attempt-1")
        self.configure(latest=3, scoped=True)
        self.read("check-3", read_only=True)
        with self.assertRaises(RecordError):
            self.read("check-3")

    def prepare_grant(self, outer_scope=False):
        if outer_scope:
            self.configure_outer_scope(latest=3)
        else:
            self.configure(latest=3)
        self.rows[self.claim]["metadata"]["gc.session_id"] = "session-current"
        self.scope_details[self.claim]["metadata"]["gc.session_id"] = "session-current"
        writer_map, rows = self.read()
        for bead_id in ("grant-1", "payload-1"):
            rows[bead_id] = dict(id=bead_id, revision="1", status="closed", assignee="", type="task", labels=[], metadata={})
        payload = json.loads((Path(__file__).parent / "fixtures/workspace-records/valid.json").read_text())["source-plan"]
        payload.update(workflow_root_id="root-1", writer_step_id=self.claim)
        common_git = Path(self.tmp.name) / ".git"
        common_git.mkdir(exist_ok=True)
        store = WorkspaceStore("rig:fixture", cwd=self.tmp.name, common_git_dir=common_git)
        attempt = Attempt("session-current", "instance-current", self.claim)
        scope = dict(workflow_root_id="root-1", generation=1,
                     writer_scope_id=payload["source_plan_owner_id"], record_kind="source-plan")
        writes = [RecordWrite("source-plan", "payload-1", payload)]
        return store, writer_map, rows, attempt, scope, writes

    def test_selected_control_and_specification_join_the_atomic_request(self):
        store, writer_map, rows, attempt, scope, writes = self.prepare_grant()
        prepared = store.install_grant(attempt, scope, "grant-1", writes, writer_map=writer_map, expected_rows=rows)
        guarded = {row["id"] for row in prepared.request["rows"]}
        self.assertTrue({"control-1", "spec-1", self.claim}.issubset(guarded))
        self.assertNotIn("prior-1", guarded)
        self.assertLessEqual(len(guarded), 100)

    def test_retained_map_rejects_external_spec_revision_even_with_fresh_snapshot(self):
        store, writer_map, rows, attempt, scope, writes = self.prepare_grant()
        rows["spec-1"]["revision"] = "9007199254740994"
        with patch.object(store, "snapshot", side_effect=lambda ids: {key: copy.deepcopy(rows[key]) for key in ids}):
            with self.assertRaisesRegex(RecordError, "specification revision changed after discovery"):
                store.install_grant(attempt, scope, "grant-1", writes, writer_map=writer_map)

    def test_only_matching_native_cas_advances_spec_revision_without_changing_map_identity(self):
        for outer_scope, native_receipt in ((outer, receipt) for outer in (False, True)
                                           for receipt in ("matched", "incomplete", "resolve-only")):
            with self.subTest(outer_scope=outer_scope, native_receipt=native_receipt):
                store, writer_map, rows, attempt, scope, writes = self.prepare_grant(outer_scope)
                initial_hash = writer_map.sha256
                prepared = store.install_grant(attempt, scope, "grant-1", writes,
                                               writer_map=writer_map, expected_rows=rows)
                if outer_scope:
                    self.assertTrue({"outer-check", "control-1", self.claim}.issubset(
                        row["id"] for row in prepared.request["rows"]))
                actual = json.loads(prepared.after_bytes)
                response = []
                for patch_row in prepared.request["rows"]:
                    bead_id = patch_row["id"]
                    revision = str(int(patch_row["expected_revision"]) + 1)
                    actual[bead_id]["revision"] = revision
                    response.append(dict(id=bead_id, revision=revision, changed=True))
                reply = dict(schema_version="1", ok=True, store_ref="rig:fixture", rows=response)
                if native_receipt == "incomplete":
                    reply["rows"] = response[:-1]
                if native_receipt != "resolve-only":
                    with patch.object(store, "_command", return_value=reply):
                        result = store.execute(prepared)
                    self.assertEqual(result["outcome"], "committed" if native_receipt == "matched" else "unknown")
                with patch.object(store, "snapshot", return_value=actual):
                    self.assertEqual(store.resolve(prepared)["outcome"], "committed")
                self.assertEqual(writer_map.sha256, initial_hash)
                rows.update(actual)
                if native_receipt == "matched":
                    next_write = store.write_records(attempt, scope, "grant-1", writes,
                                                     writer_map=writer_map, expected_rows=rows)
                    self.assertEqual(next(row["expected_revision"] for row in next_write.request["rows"]
                                          if row["id"] == "spec-1"), rows["spec-1"]["revision"])
                    rows["outer-check" if outer_scope else "spec-1"]["revision"] = "9007199254740995"
                with self.assertRaisesRegex(RecordError, "scope check revision changed after discovery" if outer_scope and native_receipt == "matched"
                                            else "specification revision changed after discovery"):
                    store.write_records(attempt, scope, "grant-1", writes, writer_map=writer_map, expected_rows=rows)

    def test_native_forgery_foreign_stale_and_policy_changes_refuse(self):
        for mutation in ("root", "store", "counter", "epoch", "maximum", "policy", "idempotency", "control", "role", "dependency", "spec", "spec-revision", "ambiguous", "old-live", "closed-current"):
            with self.subTest(mutation=mutation):
                self.configure(latest=3)
                current = self.rows[self.claim]
                if mutation == "root": current["metadata"]["gc.root_bead_id"] = "foreign-root"
                elif mutation == "store": current["metadata"]["gc.root_store_ref"] = "rig:other"
                elif mutation == "counter": current["metadata"]["gc.attempt"] = "2"
                elif mutation == "epoch": self.rows["control-1"]["metadata"]["gc.control_epoch"] = "9"
                elif mutation == "maximum": self.rows["control-1"]["metadata"]["gc.max_attempts"] = "2"
                elif mutation == "policy": self.rows["control-1"]["metadata"]["gc.check_path"] = "/foreign/check.sh"
                elif mutation == "idempotency": current["metadata"]["gc.idempotency_key"] = "other:attempt:3"
                elif mutation == "control": current["metadata"]["gc.control_for"] = "other-control"
                elif mutation == "role": current["metadata"]["gc.run_target"] = "gc.publisher"
                elif mutation == "dependency": current["metadata"][cooked.TOPOLOGY] = "[]"
                elif mutation == "spec": self.detail["description"] = self.detail["description"].replace("Native task", "Foreign task")
                elif mutation == "spec-revision": self.detail["revision"] = "9007199254740992"
                elif mutation == "ambiguous":
                    duplicate = copy.deepcopy(current); duplicate["id"] = "duplicate-1"; self.rows["duplicate-1"] = duplicate
                elif mutation == "old-live": self.rows["attempt-1"]["status"] = "in_progress"
                elif mutation == "closed-current": current["status"] = "closed"
                with self.assertRaises(RecordError):
                    self.read()

    def test_retained_map_refuses_changed_control_spec_and_old_claim(self):
        writer_map, original = self.read()
        for bead_id, key, value in (("control-1", "gc.max_attempts", "9"), ("spec-1", "gc.spec_for", "other"),
                                    ("control-1", "gc.root_bead_id", "foreign-root"), ("spec-1", "gc.root_store_ref", "rig:other"),
                                    (self.claim, "gc.control_for", "other")):
            rows = copy.deepcopy(original); rows[bead_id]["metadata"][key] = value
            with self.subTest(key=key), self.assertRaises(RecordError):
                validate_cooked_writer_map(writer_map, rows, store_ref="rig:fixture", workflow_root_id="root-1",
                                          record_kind="source-plan", claimed_step_id=self.claim)
        with self.assertRaises(RecordError):
            self.read("attempt-1")

    def test_immediate_native_successor_requires_closed_previous_and_same_designation(self):
        for scoped in (False, True):
            with self.subTest(scoped=scoped):
                self.configure(latest=2, scoped=scoped, attached=scoped)
                writer_map, rows = self.read()
                data = writer_map.declaration
                previous = "child-1" if scoped else "attempt-1"
                entry = next(step for step in data["steps"] if step["bead_id"] == previous)
                grant = dict(attempt=Attempt("session-old", "instance-old", previous).admission,
                    writer_map_sha256="old-map", writer_occurrence={key: data[key] for key in
                        ("source_member_id", "expansion_root_id", "formula_name", "formula_hash", "formula_source")})
                grant["writer_occurrence"].update(step_id=entry["step_id"], step_ref=entry["step_ref"])
                scope = dict(workflow_root_id="root-1", record_kind="workspace" if scoped else "source-plan")
                successor = Attempt("session-current", "instance-current", self.claim)
                result = WorkspaceStore._successor(grant, successor, scope, None, rows, data, writer_map.sha256, writer_map=writer_map)
                self.assertEqual(result, [previous, "control-1"])
                rows[previous]["status"] = "in_progress"
                with self.assertRaises(RecordError):
                    WorkspaceStore._successor(grant, successor, scope, None, rows, data, writer_map.sha256, writer_map=writer_map)


class NativeScopeHistoryTests(unittest.TestCase):
    """Portable native-generated graph; no original cohort identities or prose."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "build-basic.formula.toml"
        self.path.write_text('formula = "build-basic"\n')
        self.fixture = json.loads((Path(__file__).parent /
            "fixtures/workspace-records/native-attempt-scope-history.json").read_text())
        self.configure()

    def configure(self):
        self.formula = copy.deepcopy(self.fixture["formula"])
        self.root, self.claim = self.fixture["root_id"], self.fixture["claimed_id"]
        self.rows = {row["id"]: {key: copy.deepcopy(row[key]) for key in
            ("id", "revision", "status", "assignee", "type", "labels", "metadata")} for row in self.fixture["rows"]}
        self.rows[self.root]["metadata"].update({"gc.formula_source": str(self.path),
            "gc.formula_hash": hashlib.sha256(self.path.read_bytes()).hexdigest()})
        # Model the same native third-attempt graph while its writer is claimed.
        self.rows[self.claim].update(status="in_progress", assignee="worker")
        logical = self.rows[self.claim]["metadata"]["gc.control_for"]
        self.rows[logical]["status"] = "open"
        self.details = {row["id"]: dict(copy.deepcopy(row), **copy.deepcopy(self.rows[row["id"]]))
                        for row in self.fixture["rows"]}
        outer = self
        class Store:
            gc = "gc"
            cwd = outer.tmp.name
            store_ref = "rig:fixture"
            def snapshot(self, ids):
                return {bead_id: copy.deepcopy(outer.rows[bead_id]) for bead_id in ids}
        self.store = Store()

    def by_ref(self, ref):
        return next(row for row in self.rows.values() if row["metadata"].get("gc.step_ref") == ref)

    def read(self, claim=None, read_only=False):
        def native(gc, cwd, argv, rig, **options):
            if argv[:2] == ["bd", "show"]:
                if argv[2:5] == ["--exact-store", "--json", "--"]:
                    self.assertTrue(options["require_array"])
                    self.assertFalse(options.get("unwrap_singleton", False))
                    return [copy.deepcopy(self.details[bead_id]) for bead_id in argv[5:]]
                self.assertTrue(options["unwrap_singleton"] and options["require_array"])
                return copy.deepcopy(self.details[argv[2]])
            return copy.deepcopy(self.formula)
        with patch.object(cooked, "_native_list", return_value=list(self.rows)), \
             patch.object(cooked, "native_json", side_effect=native):
            return cooked.read_cooked_writer_map(self.store, workflow_root_id=self.root,
                claimed_step_id=claim or self.claim, read_only=read_only)

    def test_complete_native_graph_reconstructs_scoped_attempts_and_generated_checks(self):
        writer_map, rows = self.read()
        self.assertEqual((len(rows), len(self.formula["steps"])), (72, 61))
        controls = json.loads(writer_map.lineage_bytes)["controls"]
        self.assertEqual({d["step_id"]: len(d["attempts"]) for d in controls}, {"decompose": 3, "plan-review": 2})
        steps = {item["bead_id"]: item for item in writer_map.declaration["steps"]}
        checks = ["build-basic.decompose.iteration.2-scope-check", "build-basic.decompose.iteration.3-scope-check",
                  "build-basic.plan-review.iteration.2.author-repair-scope-check",
                  "build-basic.plan-review.iteration.2.plan-review-verdict-scope-check"]
        for ref in checks:
            row = self.by_ref(ref)
            self.assertEqual(steps[row["id"]]["record_kinds"], [])
            self.read(row["id"], read_only=True)
            with self.assertRaises(RecordError):
                self.read(row["id"])
        self.assertEqual(steps[self.claim]["record_kinds"], ["source-plan"])
        control = next(item for item in controls if item["step_id"] == "decompose")
        self.assertEqual({item["root_id"] for item in control["attempts"]},
            {edge["id"] for edge in self.details[control["control_id"]]["dependencies"] if edge["dependency_type"] == "blocks"}
            - {self.by_ref("build-basic.plan-review-scope-check")["id"]})

    def test_inherited_scope_and_generated_control_metadata_remain_exact(self):
        changes = [
            ("build-basic.decompose.iteration.3", "gc.scope_ref", None),
            ("build-basic.decompose.iteration.2", "gc.scope_role", "setup"),
            ("build-basic.plan-review.iteration.2", "gc.scope_ref", "foreign"),
            ("build-basic.plan-review.iteration.2", "gc.on_fail", None),
            ("build-basic.decompose.iteration.3", "gc.run_target", "gc.publisher"),
            ("build-basic.decompose.iteration.3", "gc.build.artifact_schema", "gc.build.implementation-summary.v1"),
        ]
        for ref in ("build-basic.decompose.iteration.3-scope-check",
                    "build-basic.plan-review.iteration.2.author-repair-scope-check",
                    "build-basic.plan-review.iteration.2.plan-review-verdict-scope-check"):
            changes.extend((ref, key, value) for key, value in (
                ("gc.control_for", "foreign"), ("gc.scope_ref", "foreign"), ("gc.scope_role", "member"),
                ("gc.run_target", "gc.task-decomposer"), ("gc.iteration", "2"),
                ("gc.attach_root_id", "foreign"), ("gc.root_store_ref", "rig:other"),
                ("gc.native_step_dependencies.v1", '["foreign"]')))
        for ref, key, value in changes:
            with self.subTest(ref=ref, key=key):
                self.configure()
                writer_map, rows = self.read()
                bead_id = self.by_ref(ref)["id"]
                for metadata in (self.rows[bead_id]["metadata"], rows[bead_id]["metadata"]):
                    if value is None: metadata.pop(key, None)
                    else: metadata[key] = value
                with self.assertRaises(RecordError):
                    self.read()
                with self.assertRaises(RecordError):
                    validate_cooked_writer_map(writer_map, rows, store_ref=self.store.store_ref,
                        workflow_root_id=self.root, record_kind="source-plan", claimed_step_id=self.claim)

    def test_native_physical_blocks_cannot_omit_history_or_bypass_minted_controls(self):
        cases = [("build-basic.decompose", action) for action in ("first", "middle", "duplicate", "extra")]
        cases += [("build-basic.plan-review.iteration.2", "child-check"),
                  ("build-basic.plan-review.iteration.2.plan-review-verdict", "raw-author"),
                  ("build-basic.decompose.iteration.3-scope-check", "missing"),
                  ("build-basic.plan-review.iteration.2.author-repair-scope-check", "foreign-subject")]
        for ref, action in cases:
            with self.subTest(ref=ref, action=action):
                self.configure()
                row = self.by_ref(ref)
                edges = self.details[row["id"]]["dependencies"]
                if action in ("first", "middle"):
                    suffix = "decompose.iteration.1" if action == "first" else "build-basic.decompose.iteration.2"
                    removed = self.by_ref(suffix)["id"]
                    self.assertTrue(any(edge["id"] == removed and edge["dependency_type"] == "blocks" for edge in edges))
                    edges[:] = [edge for edge in edges if edge["id"] != removed]
                elif action == "duplicate": edges.append(copy.deepcopy(next(edge for edge in edges if edge["dependency_type"] == "blocks")))
                elif action == "extra": edges.append(dict(id=self.root, dependency_type="blocks"))
                elif action == "child-check":
                    child = self.by_ref("build-basic.plan-review.iteration.2.author-repair")["id"]
                    next(edge for edge in edges if edge["id"] == child)["id"] = self.by_ref(
                        "build-basic.plan-review.iteration.2.author-repair-scope-check")["id"]
                elif action == "raw-author": next(edge for edge in edges if edge["dependency_type"] == "blocks")["id"] = self.by_ref("build-basic.plan-review.iteration.2.author-repair")["id"]
                elif action == "missing": edges.clear()
                else: next(edge for edge in edges if edge["dependency_type"] == "blocks")["id"] = self.claim
                with self.assertRaisesRegex(RecordError, "physical blocks"):
                    self.read()

    def test_missing_or_duplicate_runtime_check_cannot_enter_an_occurrence_map(self):
        for action in ("missing", "duplicate"):
            with self.subTest(action=action):
                self.configure()
                row = self.by_ref("build-basic.plan-review.iteration.2.author-repair-scope-check")
                if action == "missing": del self.rows[row["id"]]
                else:
                    duplicate = copy.deepcopy(row)
                    duplicate["id"] = "duplicate-check"
                    self.rows[duplicate["id"]] = duplicate
                with self.assertRaises(RecordError):
                    self.read()

    def test_retained_map_pins_physical_edge_revisions_even_with_a_fresh_snapshot(self):
        for ref in ("build-basic.decompose", "decompose.iteration.1", "build-basic.decompose.iteration.3-scope-check",
                    "build-basic.plan-review.iteration.2.plan-review-verdict"):
            with self.subTest(ref=ref):
                self.configure()
                writer_map, rows = self.read()
                rows[self.by_ref(ref)["id"]]["revision"] = "9007199254740994"
                with self.assertRaisesRegex(RecordError, "physical dependency revision changed"):
                    validate_cooked_writer_map(writer_map, rows, store_ref=self.store.store_ref,
                        workflow_root_id=self.root, record_kind="source-plan", claimed_step_id=self.claim)


if __name__ == "__main__":
    unittest.main()
