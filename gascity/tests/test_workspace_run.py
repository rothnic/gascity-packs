from __future__ import annotations

import importlib.util
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from workspace_records import RecordError


SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("workspace_run", SCRIPTS / "workspace_run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class RunCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="run-capture-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "registered rig with spaces"
        self.git("init", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "file").write_text("base\n")
        self.git("add", "file")
        self.git("commit", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *argv, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.repo), *argv],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def args(self, **changes):
        value = dict(workflow_root_id="root-1", input_convoy_id="convoy-1",
                     source_anchor_id="source-1", rig_root=str(self.repo),
                     writer_step_id="writer-1", worktree_lifecycle="new", base_ref="@default")
        value.update(changes)
        return value

    def test_real_default_capture_and_moving_reference_replay(self):
        captured = run.capture_payload(**self.args())
        self.assertEqual(captured["base_oid"], self.base)
        self.assertEqual(captured["common_git_dir"], str(self.repo / ".git"))
        (self.repo / "file").write_text("later\n")
        self.git("commit", "-am", "later")
        later = self.git("rev-parse", "HEAD")
        self.assertNotEqual(self.base, later)
        replay = run.capture_payload(stored=captured, **self.args(writer_step_id="replacement-1"))
        self.assertEqual(replay, captured)
        self.assertEqual(replay["writer_step_id"], "writer-1")

    def test_linked_registered_checkout_selects_its_own_head(self):
        self.git("branch", "linked", self.base)
        (self.repo / "file").write_text("primary later\n")
        self.git("commit", "-am", "primary later")
        linked = self.root / "linked rig"
        self.git("worktree", "add", str(linked), "linked")
        capture = run.capture_payload(**self.args(rig_root=str(linked)))
        self.assertEqual(capture["base_oid"], self.base)
        self.assertEqual(capture["rig_root"], str(linked))
        self.assertEqual(capture["common_git_dir"], str(self.repo / ".git"))

    def test_bare_control_and_bare_root_select_bare_head(self):
        for layout in ("bare-control", "bare-root"):
            with self.subTest(layout=layout):
                rig = self.root / layout
                clone = rig / ".git" if layout == "bare-control" else rig
                self.git("clone", "--bare", str(self.repo), str(clone))
                capture = run.capture_payload(**self.args(rig_root=str(rig)))
                self.assertEqual(capture["base_oid"], self.base)
                self.assertEqual(capture["common_git_dir"], str(clone))

    def test_unrelated_cwd_and_hostile_git_environment_cannot_redirect(self):
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        environment = {"GIT_DIR": str(unrelated), "GIT_WORK_TREE": str(unrelated),
                       "GIT_COMMON_DIR": str(unrelated), "GIT_OBJECT_DIRECTORY": str(unrelated),
                       "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.worktree",
                       "GIT_CONFIG_VALUE_0": str(unrelated)}
        before = Path.cwd()
        try:
            os.chdir(unrelated)
            with patch.dict(os.environ, environment):
                self.assertEqual(run.capture_payload(**self.args())["base_oid"], self.base)
        finally:
            os.chdir(before)

    def test_explicit_commit_and_qualified_refs_are_unambiguous(self):
        self.git("tag", "main")
        for selector in (self.base, "refs/heads/main", "refs/tags/main"):
            with self.subTest(selector=selector):
                self.assertEqual(run.capture_payload(**self.args(base_ref=selector))["base_oid"], self.base)
        with self.assertRaisesRegex(run.RunError, "ambiguous"):
            run.capture_payload(**self.args(base_ref="main"))

    def test_empty_missing_noncommit_and_unborn_refs_refuse(self):
        blob = self.git("hash-object", "-w", "file")
        self.git("update-ref", "refs/tags/blob", blob)
        for selector in ("", "missing", "refs/tags/blob", "-q", "main\n"):
            with self.subTest(selector=selector):
                with self.assertRaises(run.RunError):
                    run.capture_payload(**self.args(base_ref=selector))
        unborn = self.root / "unborn"
        self.git("init", str(unborn))
        with self.assertRaises(run.RunError):
            run.capture_payload(**self.args(rig_root=str(unborn)))

    def test_replay_refuses_changed_root_source_mode_and_repository(self):
        capture = run.capture_payload(**self.args())
        other = self.root / "other"
        self.git("clone", str(self.repo), str(other))
        for changes in ({"workflow_root_id": "other-root"}, {"input_convoy_id": "other-convoy"},
                        {"source_anchor_id": "other-source"}, {"worktree_lifecycle": "legacy"},
                        {"rig_root": str(other)}):
            with self.subTest(changes=changes):
                with self.assertRaises(run.RunError):
                    run.capture_payload(stored=capture, **self.args(**changes))

    def test_replay_requires_saved_commit_and_never_resolves_selector_again(self):
        capture = run.capture_payload(**self.args())
        self.assertEqual(run.capture_payload(stored=capture, **self.args(base_ref="now-missing")), capture)
        changed = dict(capture, base_oid="0" * 40)
        with self.assertRaises(run.RunError):
            run.capture_payload(stored=changed, **self.args())

    def test_symlink_registration_is_canonical_and_nested_path_refuses(self):
        alias = self.root / "rig alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        self.assertEqual(run.capture_payload(**self.args(rig_root=str(alias)))["rig_root"], str(self.repo))
        nested = self.repo / "nested"
        nested.mkdir()
        with self.assertRaisesRegex(run.RunError, "registered rig"):
            run.capture_payload(**self.args(rig_root=str(nested)))

    def source_store(self, *, synthetic=None):
        class Store:
            store_ref = "rig:example"

            def snapshot(self, ids):
                self.reads.extend(ids)
                return {key: copy.deepcopy(self.rows[key]) for key in ids}

            def read_record(self, kind, bead_id, identity=None):
                self.record_reads.append((kind, bead_id, identity))
                return copy.deepcopy(self.record)

        store = Store()
        store.reads, store.record_reads, store.record = [], [], None
        store.rows = {
            "writer-1": {"id": "writer-1", "type": "task", "status": "in_progress",
                         "metadata": {"gc.root_bead_id": "root-1"}},
            "root-1": {"id": "root-1", "type": "task", "status": "open",
                       "metadata": {"gc.kind": "workflow", "gc.input_convoy_id": "convoy-1",
                                    "gc.root_store_ref": "rig:example"}},
            "convoy-1": {"id": "convoy-1", "type": "convoy", "status": "open", "metadata": {}},
            "source-1": {"id": "source-1", "type": "task", "status": "open",
                         "metadata": {"workflow_id": "root-1"}},
        }
        if synthetic == "drain":
            store.rows["convoy-1"]["metadata"] = {"gc.synthetic": "true",
                "gc.synthetic_kind": "drain-unit-convoy", "gc.drain_member_id": "source-1"}
        elif synthetic == "wrapper":
            store.rows["convoy-1"]["metadata"] = {"gc.synthetic": "true", "gc.source_bead_id": "source-1"}
        return store

    def context(self, store, **changes):
        args = dict(gc="gc", city_root=str(self.root), workflow_root_id="root-1",
                    input_convoy_id="convoy-1", claimed_step_id="writer-1")
        args.update(changes)
        return run.source_context(store, **args)

    def test_native_source_cases_use_exact_selected_store_rows(self):
        ordinary = self.source_store()
        ordinary.rows["convoy-1"]["labels"] = None
        self.assertEqual(self.context(ordinary)[0], "convoy-1")
        drain = self.source_store(synthetic="drain")
        self.assertEqual(self.context(drain)[0], "source-1")
        wrapper = self.source_store(synthetic="wrapper")
        status = {"convoy": {"id": "convoy-1"}, "children": [{"id": "source-1"}]}
        with patch.object(run, "native_json", return_value=status) as native:
            self.assertEqual(self.context(wrapper)[0], "source-1")
            native.assert_not_called()
        self.assertEqual(wrapper.reads, ["writer-1", "root-1", "convoy-1", "source-1"])

    def test_preserved_root_and_claim_source_pins_select_original_task(self):
        for bead in ("root-1", "writer-1"):
            with self.subTest(bead=bead):
                store = self.source_store()
                store.rows[bead]["metadata"]["gc.source_bead_id"] = "source-1"
                self.assertEqual(self.context(store)[0], "source-1")

    def test_wrapper_source_selection_is_independent_of_moving_tracks(self):
        store = self.source_store(synthetic="wrapper")
        original_revision = store.rows["convoy-1"].setdefault("revision", "1")
        with patch.object(run, "native_json", return_value={"convoy": {"id": "convoy-1"},
                "children": [{"id": "wrong-source"}]}) as native:
            anchor, rows = self.context(store)
        self.assertEqual(anchor, "source-1")
        self.assertEqual(rows["convoy-1"]["revision"], original_revision)
        self.assertEqual(rows["convoy-1"]["metadata"]["gc.source_bead_id"], "source-1")
        native.assert_not_called()

    def test_conflicting_and_empty_root_claim_wrapper_pins_refuse(self):
        for bead, key, value in (("root-1", "gc.source_bead_id", "other-source"),
                ("writer-1", "gc.drain_member_id", "other-source"),
                ("writer-1", "gc.source_bead_id", ""),
                ("convoy-1", "gc.source_bead_id", "")):
            with self.subTest(bead=bead, key=key), self.assertRaises(run.RunError), \
                 patch.object(run, "native_json", return_value={"convoy": {"id": "convoy-1"},
                     "children": [{"id": "source-1"}]}):
                store = self.source_store(synthetic="wrapper")
                store.rows[bead]["metadata"][key] = value
                self.context(store)

    def test_missing_empty_foreign_and_changed_source_pins_refuse(self):
        cases = (("writer-1", "gc.root_bead_id", "other-root"),
                 ("root-1", "gc.input_convoy_id", "other-convoy"),
                 ("root-1", "gc.source_anchor_id", "other-source"),
                 ("root-1", "gc.drain_member_id", ""),
                 ("root-1", "gc.root_store_ref", "rig:foreign"),
                 ("convoy-1", "gc.source_store_ref", ""),
                 ("source-1", "workflow_id", "other-root"))
        for bead, key, value in cases:
            with self.subTest(bead=bead, key=key):
                store = self.source_store(synthetic="drain")
                store.rows[bead]["metadata"][key] = value
                with self.assertRaises(run.RunError):
                    self.context(store)
        missing = self.source_store(synthetic="drain")
        del missing.rows["root-1"]["metadata"]["gc.root_store_ref"]
        with self.assertRaises(run.RunError):
            self.context(missing)

    def test_unstamped_synthetic_wrapper_refuses_even_with_plausible_tracks(self):
        for children in ([], [{"id": "source-1"}], [{"id": "source-1"}, {"id": "source-2"}],
                         [{"id": "source-1", "dangling_track": True}], [{"id": "convoy-1"}]):
            with self.subTest(children=children):
                store = self.source_store(synthetic="wrapper")
                store.rows["convoy-1"]["metadata"].pop("gc.source_bead_id")
                with patch.object(run, "native_json", return_value={"convoy": {"id": "convoy-1"}, "children": children}):
                    with self.assertRaises(run.RunError):
                        self.context(store)

    def test_failed_canceled_held_and_closed_without_pass_sources_refuse(self):
        for failure in ("outcome", "cancel", "failed", "held", "closed"):
            with self.subTest(failure=failure):
                store = self.source_store(synthetic="drain")
                source = store.rows["source-1"]
                if failure == "outcome":
                    source["metadata"]["gc.outcome"] = "fail"
                elif failure == "cancel":
                    source["metadata"]["gc.cancel_requested"] = "requested"
                elif failure == "failed":
                    source["metadata"]["molecule_failed"] = True
                elif failure == "held":
                    source["labels"] = ["hold:review"]
                else:
                    source["status"] = "closed"
                with self.assertRaises(run.RunError):
                    self.context(store)

    def test_native_physical_row_read_accepts_singleton_and_refuses_ambiguous_or_duplicate_json(self):
        details = {"id": "native-1", "title": "Run", "description": "retained intent"}
        for output in (json.dumps(details), json.dumps([details])):
            with self.subTest(output=output), patch.object(run.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, output, "")) as command:
                self.assertEqual(run.native_json("gc", str(self.root), ["bd", "show", "native-1", "--json"],
                    "example", unwrap_singleton=True), details)
                self.assertEqual(command.call_args.args[0],
                    ["gc", "--city", str(self.root), "--rig", "example", "bd", "show", "native-1", "--json"])
        for output in ('[]', '[{"id":"one"},{"id":"two"}]', '[{"id":"one","id":"two"}]'):
            with self.subTest(output=output), patch.object(run.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, output, "")), self.assertRaises(RecordError):
                run.native_json("gc", str(self.root), ["bd", "show", "native-1", "--json"],
                    "example", unwrap_singleton=True)

    def test_registered_rig_refuses_wrong_city_store_and_ambiguous_name(self):
        data = {"city_path": str(self.root), "city_name": "fixture",
                "rigs": [{"name": "example", "path": str(self.repo)}]}
        with patch.object(run, "native_json", return_value=data):
            self.assertEqual(run.registered_rig("gc", str(self.root), "example", "rig:example"), str(self.repo))
            self.assertEqual(run.registered_rig("gc", str(self.root), "example", "city:fixture"), str(self.repo))
            for store_ref in ("rig:foreign", "city:foreign", "", "remote:fixture"):
                with self.subTest(store_ref=store_ref):
                    with self.assertRaises(run.RunError):
                        run.registered_rig("gc", str(self.root), "example", store_ref)
            data["rigs"].append(dict(data["rigs"][0]))
            with self.assertRaises(run.RunError):
                run.registered_rig("gc", str(self.root), "example", "rig:example")

    def test_read_requires_selected_native_reference_and_mode(self):
        store = self.source_store(synthetic="drain")
        store.record = run.capture_payload(**self.args())
        identity = list(run.record_identity("run", store.record))
        store.rows["root-1"]["metadata"][run.RUN_REFERENCE_KEY] = json.dumps(
            {"kind": "run", "identity": identity, "bead_id": "record-1"})
        kwargs = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
                      input_convoy_id="convoy-1", record_bead_id="record-1", worktree_lifecycle="new")
        with patch.object(run, "registered_rig", return_value=str(self.repo)):
            self.assertEqual(run.read_run(store, **kwargs), store.record)
            self.assertEqual(store.record_reads[-1], ("run", "record-1", identity))
            with self.assertRaises(run.RunError):
                run.read_run(store, **dict(kwargs, worktree_lifecycle="legacy"))
            del store.rows["root-1"]["metadata"][run.RUN_REFERENCE_KEY]
            with self.assertRaises(run.RunError):
                run.read_run(store, **kwargs)


class RunStoreTests(unittest.TestCase):
    """Actual adapter composition over its synthetic native command port."""
    git = RunCaptureTests.git
    args = RunCaptureTests.args
    source_store = RunCaptureTests.source_store

    def setUp(self):
        RunCaptureTests.setUp(self)
        from workspace_store import Attempt, CookedWriterMap, WorkspaceStore
        from test_workspace_store import MemoryPort, row
        rows = self.source_store(synthetic="drain").rows
        for value in rows.values():
            value.update(revision="1", assignee="", labels=[])
        rows["writer-1"]["assignee"] = "worker"
        rows["writer-1"]["metadata"].update({"gc.session_id": "session-1", "workflow_id": "root-1",
            "gc.root_store_ref": "rig:example", "gc.step_ref": "build.prepare", "gc.step_id": "build.prepare",
            "gc.lifecycle": "new", "gc.native_step_dependencies.v1": "[]"})
        rows["root-1"]["metadata"].update({"gc.formula_name": "build", "gc.formula_hash": "a" * 64,
            "gc.formula_source": str(self.root / "build.formula.toml"), run.CHECKS_CONFIG_KEY:
            run.canonical_bytes({"required_checks": [{"id": "project-tests", "argv": ["python3", "-m", "unittest"]}]}).decode()})
        self.writer_map = CookedWriterMap(run.canonical_bytes({"version": 1, "workflow_root_id": "root-1",
            "store_ref": "rig:example", "source_member_id": "root-1", "expansion_root_id": "root-1",
            "formula_name": "build", "formula_hash": "a" * 64, "formula_source": str(self.root / "build.formula.toml"),
            "steps": [{"bead_id": "writer-1", "step_id": "build.prepare", "step_ref": "build.prepare",
                       "dependencies": [], "record_kinds": ["run"]}]}))
        rows.update({"record-1": row("record-1"), "authority-1": row("authority-1")})
        self.port = MemoryPort(rows)
        self.store = WorkspaceStore("rig:example", cwd=self.root, common_git_dir=self.repo / ".git")
        self.attempt = Attempt("session-1", "incarnation-1", "writer-1")
        command = patch.object(self.store, "_command", side_effect=self.port)
        command.start()
        self.addCleanup(command.stop)
        registration = patch.object(run, "registered_rig", return_value=str(self.repo))
        registration.start()
        self.addCleanup(registration.stop)
        self.kwargs = dict(gc="gc", city_root=str(self.root), rig_name="example", workflow_root_id="root-1",
            input_convoy_id="convoy-1", record_bead_id="record-1", authority_id="authority-1",
            worktree_lifecycle="new", writer_map=self.writer_map)

    def test_capture_replay_and_read_use_real_adapter_and_one_complete_batch(self):
        captured = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(captured["receipt"]["outcome"], "committed")
        self.assertEqual(set(self.port.rows), {p["id"] for p in self.port.requests[0]["rows"]})
        (self.repo / "file").write_text("new HEAD\n")
        self.git("commit", "-am", "new HEAD")
        replay = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(replay["receipt"]["outcome"], "replayed")
        self.assertEqual(replay["record"], captured["record"])
        kwargs = {key: value for key, value in self.kwargs.items() if key not in ("authority_id", "writer_map")}
        self.assertEqual(run.read_run(self.store, **kwargs), captured["record"])
        with self.assertRaises(run.RunError):
            run.read_run(self.store, **dict(kwargs, worktree_lifecycle="legacy"))
        self.assertNotIn("incarnation-1", json.dumps(replay))

    def test_changed_source_revision_refuses_before_partial_publication(self):
        execute = self.store.execute

        def changed_source(prepared):
            self.port.rows["source-1"]["revision"] = "2"
            self.port.rows["source-1"]["metadata"]["workflow_id"] = "foreign-root"
            return execute(prepared)

        with patch.object(self.store, "execute", side_effect=changed_source):
            result = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(result["receipt"]["outcome"], "unknown")
        self.assertEqual(self.port.rows["record-1"]["metadata"], {})
        self.assertEqual(self.port.rows["authority-1"]["metadata"], {})
        self.assertNotIn(run.RUN_REFERENCE_KEY, self.port.rows["root-1"]["metadata"])

    def test_changed_native_wrapper_pin_cannot_publish_a_run_or_grant(self):
        self.port.rows["convoy-1"]["metadata"] = {"gc.synthetic": "true", "gc.source_bead_id": "source-1"}
        execute = self.store.execute

        def changed_wrapper(prepared):
            wrapper = self.port.rows["convoy-1"]
            wrapper["revision"] = "2"
            wrapper["metadata"]["gc.source_bead_id"] = "different-source"
            return execute(prepared)

        with patch.object(self.store, "execute", side_effect=changed_wrapper):
            result = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(result["receipt"]["outcome"], "unknown")
        self.assertEqual(self.port.rows["record-1"]["metadata"], {})
        self.assertEqual(self.port.rows["authority-1"]["metadata"], {})
        self.assertNotIn(run.RUN_REFERENCE_KEY, self.port.rows["root-1"]["metadata"])

    def test_competing_mode_capture_keeps_one_immutable_payload(self):
        from workspace_store import GuardRead, RecordWrite, ReferenceWrite, RunCheckPolicyProjection
        execute = self.store.execute

        def competing_capture(prepared):
            payload = run.capture_payload(**self.args(worktree_lifecycle="legacy"))
            reference = {"kind": "run", "identity": list(run.record_identity("run", payload)), "bead_id": "record-1"}
            competitor = self.store.install_grant(self.attempt,
                {"workflow_root_id": "root-1", "generation": 1, "writer_scope_id": "root-1", "record_kind": "run"}, "authority-1",
                [RecordWrite("run", "record-1", payload)],
                [ReferenceWrite("root-1", run.RUN_REFERENCE_KEY, reference)], writer_map=self.writer_map,
                guards=[GuardRead("root-1", run.CHECKS_CONFIG_KEY, self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY])],
                projections=[RunCheckPolicyProjection("record-1", run.capture_check_policy(payload, "record-1",
                    self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY]))])
            self.assertEqual(execute(competitor)["outcome"], "committed")
            return execute(prepared)

        with patch.object(self.store, "execute", side_effect=competing_capture):
            result = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(result["receipt"]["outcome"], "unknown")
        self.assertEqual(self.store.read_record("run", "record-1")["worktree_lifecycle"], "legacy")

    def test_replaced_attempt_cannot_replay_an_unchanged_payload(self):
        from workspace_store import Attempt, StoreError
        run.capture_run(self.store, self.attempt, **self.kwargs)
        with self.assertRaises(StoreError):
            run.capture_run(self.store, Attempt("session-1", "replacement-1", "writer-1"), **self.kwargs)
        self.assertEqual(len(self.port.requests), 1)

    def test_lost_acknowledgement_uses_readback_without_a_second_write(self):
        self.port.lose_ack = True
        result = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(result["receipt"]["outcome"], "committed")
        self.assertEqual(result["receipt"]["write_outcome"], "unknown")
        self.assertEqual(len(self.port.requests), 1)
        self.assertNotIn("incarnation-1", json.dumps(result))

    def test_check_policy_is_published_atomically_and_cannot_change_on_replay(self):
        result = run.capture_run(self.store, self.attempt, **self.kwargs)
        policy = run.read_check_policy(self.store, "record-1", result["record"])
        self.assertEqual(policy["base_oid"], self.base)
        record_patch = next(row for row in self.port.requests[0]["rows"] if row["id"] == "record-1")
        self.assertIn(run.CHECKS_POLICY_KEY, record_patch["set"])
        self.assertIn("gc.implementation_run", record_patch["set"])
        self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY] = run.canonical_bytes({
            "required_checks": [{"id": "different", "argv": ["true"]}]}).decode()
        with self.assertRaises(RecordError):
            run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(len(self.port.requests), 1)
        self.assertEqual(run.read_check_policy(self.store, "record-1", result["record"]), policy)

    def test_new_mode_missing_empty_or_noncanonical_checks_refuse_before_publication(self):
        for config in (None, '{"required_checks":[]}', '{ "required_checks": [] }',
                       '{"required_checks":[{"id":"test","argv":[]}]}'):
            with self.subTest(config=config):
                if config is None:
                    self.port.rows["root-1"]["metadata"].pop(run.CHECKS_CONFIG_KEY, None)
                else:
                    self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY] = config
                with self.assertRaises(RecordError):
                    run.capture_run(self.store, self.attempt, **self.kwargs)
                self.assertEqual(self.port.requests, [])

    def test_changed_check_config_revision_cannot_publish_partial_run_or_policy(self):
        execute = self.store.execute
        def changed_policy(prepared):
            self.port.rows["root-1"]["revision"] = "2"
            self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY] = '{"required_checks":[]}'
            return execute(prepared)
        with patch.object(self.store, "execute", side_effect=changed_policy):
            result = run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(result["receipt"]["outcome"], "unknown")
        self.assertEqual(self.port.rows["record-1"]["metadata"], {})
        self.assertNotIn(run.RUN_REFERENCE_KEY, self.port.rows["root-1"]["metadata"])

    def command(self):
        argv = ["capture", "--store-ref", "rig:example", "--claimed-step-id", "writer-1"]
        for key, value in self.kwargs.items():
            if key == "writer_map":
                continue
            argv.extend(["--" + key.replace("_", "-"), str(value)])
        return argv

    def allocation_args(self):
        return dict(workflow_root_id="root-1", input_convoy_id="convoy-1", source_anchor_id="source-1",
            rig_root=str(self.repo), worktree_lifecycle="new", base_ref="@default",
            checks_config=self.port.rows["root-1"]["metadata"][run.CHECKS_CONFIG_KEY])

    def native_allocator(self, *, lose_reply_at=None, change_on_show=False):
        import workspace_entry as entry
        from test_workspace_store import row
        created = {}
        calls = []
        def native(gc, city, args, rig=None, **kwargs):
            self.assertEqual(city, str(self.root))
            self.assertEqual(rig, "example")
            calls.append(list(args))
            if args[:2] == ["bd", "create"]:
                bead_id = "native-allocation-" + str(len(created) + 1)
                created[bead_id] = {"id": bead_id, "title": args[2],
                    "description": args[args.index("--description") + 1]}
                self.port.rows[bead_id] = row(bead_id)
                if len(created) == lose_reply_at:
                    raise run.RunError("native create committed; acknowledgement lost")
                return {"id": bead_id}
            self.assertEqual(args[:2], ["bd", "show"])
            self.assertTrue(kwargs["unwrap_singleton"])
            value = copy.deepcopy(created[args[2]])
            if change_on_show:
                self.port.rows[args[2]]["revision"] = "2"
            return value
        return entry, created, calls, native

    def test_unknown_allocation_blocks_new_process_and_recovers_only_its_native_id_without_recapturing_base(self):
        entry, created, calls, native = self.native_allocator(lose_reply_at=1)
        args = self.allocation_args()
        with patch.object(entry, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "retained intent"):
                entry.allocate_run_placeholders(self.store, self.attempt, **args)
        journal = next((self.repo / ".git" / "gc-workspace-locks").rglob("*.intent.json"))
        original = journal.read_bytes()
        self.assertEqual(json.loads(original)["captured_run"]["base_oid"], self.base)
        (self.repo / "file").write_text("moving default while allocation is unresolved\n")
        self.git("commit", "-am", "move default")
        state = self.root / "allocation-fixture.json"
        state.write_text(json.dumps({"rows": self.port.rows, "cwd": self.store.cwd,
            "common": str(self.store.common_git_dir), "sys_path": sys.path, "args": args,
            "entry_source": entry.__file__, "run_source": run.__file__}))
        script = '''import importlib.util,json,sys
from pathlib import Path
from unittest.mock import patch
data=json.loads(Path(sys.argv[1]).read_text());sys.path[:0]=data['sys_path']
for name,key in [('workspace_run','run_source'),('workspace_entry','entry_source')]:
 spec=importlib.util.spec_from_file_location(name,data[key]);module=importlib.util.module_from_spec(spec)
 sys.modules[name]=module;spec.loader.exec_module(module)
from workspace_store import WorkspaceStore,Attempt
from test_workspace_store import MemoryPort
from workspace_entry import allocate_run_placeholders,EntryError
store=WorkspaceStore('rig:example',cwd=data['cwd'],common_git_dir=data['common'])
port=MemoryPort(data['rows']);store._command=port
with patch('workspace_entry.native_json',side_effect=AssertionError('duplicate native create')):
 try:allocate_run_placeholders(store,Attempt('session-1','incarnation-1','writer-1'),**data['args'])
 except EntryError as exc:
  assert 'no known physical ID' in str(exc), str(exc)
  assert port.requests==[]
  print('refused-original-unknown-allocation')
 else:raise AssertionError('unknown allocation was accepted')
'''
        other = self.root / "other-allocation-diagnostics"
        other.mkdir()
        child = subprocess.run([sys.executable, "-c", script, str(state)], cwd=other,
            text=True, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "refused-original-unknown-allocation")
        with patch.object(entry, "native_json", side_effect=native):
            recovered = entry.allocate_run_placeholders(self.store, self.attempt,
                run_record_id=next(iter(created)), **args)
        self.assertEqual(len(created), 2)
        self.assertEqual(recovered["captured_run"]["base_oid"], self.base)
        self.assertEqual(journal.read_bytes(), original)
        captured = run.capture_run(self.store, self.attempt, **dict(self.kwargs,
            record_bead_id=recovered["run_record_id"], authority_id=recovered["authority_id"]),
            allocation_rows=recovered["allocation_rows"], captured_run=recovered["captured_run"],
            captured_checks_config=args["checks_config"])
        self.assertEqual(captured["receipt"]["outcome"], "committed")
        self.assertEqual(captured["record"]["base_oid"], self.base)
        self.assertEqual(sum(c[:2] == ["bd", "create"] for c in calls), 2)
        self.assertEqual(len(self.port.requests), 1)

    def test_authority_lost_reply_reuses_known_record_and_rejects_foreign_recovery_id(self):
        entry, created, calls, native = self.native_allocator(lose_reply_at=2)
        args = self.allocation_args()
        with patch.object(entry, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                entry.allocate_run_placeholders(self.store, self.attempt, **args)
            with self.assertRaisesRegex(RecordError, "no known physical ID"):
                entry.allocate_run_placeholders(self.store, self.attempt, **args)
            with self.assertRaisesRegex(RecordError, "retained allocation intent"):
                entry.allocate_run_placeholders(self.store, self.attempt,
                    authority_id="native-allocation-1", **args)
            recovered = entry.allocate_run_placeholders(self.store, self.attempt,
                authority_id="native-allocation-2", **args)
        self.assertEqual(recovered["run_record_id"], "native-allocation-1")
        self.assertEqual(recovered["authority_id"], "native-allocation-2")
        self.assertEqual(len(created), 2)
        self.assertEqual(sum(c[:2] == ["bd", "create"] for c in calls), 2)

    def test_changed_native_allocation_or_retained_attempt_configuration_refuses_without_recreation(self):
        from workspace_store import Attempt
        entry, created, calls, native = self.native_allocator(change_on_show=True)
        args = self.allocation_args()
        with patch.object(entry, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "changed while reading"):
                entry.allocate_run_placeholders(self.store, self.attempt, **args)
            for change in ({"base_ref": "refs/heads/main"}, {"source_anchor_id": "foreign-source"},
                           {"worktree_lifecycle": "legacy"}, {"checks_config": '{"required_checks":[]}'}):
                with self.subTest(change=change), self.assertRaises(RecordError):
                    entry.allocate_run_placeholders(self.store, self.attempt, **dict(args, **change))
            with self.assertRaisesRegex(RecordError, "different source configuration or attempt"):
                entry.allocate_run_placeholders(self.store, Attempt("session-1", "different-token", "writer-1"), **args)
        self.assertEqual(len(created), 1)
        self.assertEqual(sum(c[:2] == ["bd", "create"] for c in calls), 1)

    def test_successful_role_receipt_retains_original_revision_across_lost_authority_reply(self):
        entry, created, calls, native = self.native_allocator(lose_reply_at=2)
        args = self.allocation_args()
        with patch.object(entry, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                entry.allocate_run_placeholders(self.store, self.attempt, **args)
            first_id, authority_id = list(created)
            original = copy.deepcopy(self.port.rows[first_id])
            self.port.rows[first_id]["revision"] = "2"
            with self.assertRaisesRegex(RecordError, "changed since its original receipt"):
                entry.allocate_run_placeholders(self.store, self.attempt, authority_id=authority_id, **args)
        self.assertEqual(len(created), 2)
        self.assertEqual(sum(c[:2] == ["bd", "create"] for c in calls), 2)
        self.assertEqual(self.port.requests, [])
        self.assertEqual(original["metadata"], self.port.rows[first_id]["metadata"])

    def test_native_allocation_revision_remains_fenced_through_run_publication(self):
        entry, created, calls, native = self.native_allocator()
        args = self.allocation_args()
        with patch.object(entry, "native_json", side_effect=native):
            allocated = entry.allocate_run_placeholders(self.store, self.attempt, **args)
        self.port.rows[allocated["run_record_id"]]["revision"] = "2"
        with self.assertRaisesRegex(RecordError, "allocation changed"):
            run.capture_run(self.store, self.attempt, **dict(self.kwargs,
                record_bead_id=allocated["run_record_id"], authority_id=allocated["authority_id"]),
                allocation_rows=allocated["allocation_rows"], captured_run=allocated["captured_run"],
                captured_checks_config=args["checks_config"])
        self.assertEqual(self.port.requests, [])

    def test_real_entry_calls_native_allocator_and_publishes_its_captured_base(self):
        entry, created, calls, native = self.native_allocator()
        import workspace_cooked
        with patch.object(entry, "native_json", side_effect=native), \
             patch.object(entry, "registered_rig", return_value=str(self.repo)), \
             patch("workspace_run.registered_rig", return_value=str(self.repo)), \
             patch.object(workspace_cooked, "read_cooked_writer_map", side_effect=lambda *a, **k:
                 (self.writer_map, self.store.snapshot(["root-1", "writer-1"]))):
            result = entry.prepare_entry(self.store, self.attempt, gc="gc", city_root=str(self.root),
                rig_name="example", workflow_root_id="root-1", entrypoint="build", worktree_lifecycle="new")
        self.assertEqual(result["run"]["base_oid"], self.base)
        self.assertEqual(result["receipt"]["outcome"], "committed")
        self.assertEqual(len(created), 2)
        self.assertTrue(Path(result["allocation_journal"]).is_file())

    def test_capture_cli_prints_verified_result_without_retained_token(self):
        import workspace_store
        import workspace_cooked
        stdout = io.StringIO()
        with patch.object(workspace_store, "WorkspaceStore", return_value=self.store), \
             patch.object(workspace_cooked, "read_cooked_writer_map", side_effect=lambda *a, **k: (self.writer_map, self.store.snapshot(["root-1", "writer-1"]))), \
             patch.dict(os.environ, {"GC_SESSION_ID": "session-1", "GC_INSTANCE_TOKEN": "incarnation-1"}), \
             contextlib.redirect_stdout(stdout):
            code = run.main(self.command())
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["receipt"]["outcome"], "committed")
        self.assertEqual(result["record"]["base_oid"], self.base)
        self.assertNotIn("incarnation-1", stdout.getvalue())

    def test_capture_cli_unknown_outcome_cannot_exit_success(self):
        import workspace_store
        import workspace_cooked
        stdout = io.StringIO()
        with patch.object(workspace_store, "WorkspaceStore", return_value=self.store), \
             patch.object(workspace_cooked, "read_cooked_writer_map", side_effect=lambda *a, **k: (self.writer_map, self.store.snapshot(["root-1", "writer-1"]))), \
             patch.dict(os.environ, {"GC_SESSION_ID": "session-1", "GC_INSTANCE_TOKEN": "incarnation-1"}), \
             patch.object(self.store, "resolve", side_effect=lambda prepared: {
                 "outcome": "unknown", "request_sha256": prepared.sha256, "retry_allowed": False}), \
             contextlib.redirect_stdout(stdout):
            code = run.main(self.command())
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["receipt"]["outcome"], "unknown")

    def test_lost_cli_reply_retains_original_request_and_new_process_resolves_without_write(self):
        import workspace_store
        import workspace_cooked
        from workspace_requests import require_resolved_scope
        self.port.lose_ack = True
        stdout = io.StringIO()
        with patch.object(workspace_store, "WorkspaceStore", return_value=self.store), \
             patch.object(workspace_cooked, "read_cooked_writer_map", side_effect=lambda *a, **k: (self.writer_map, self.store.snapshot(["root-1", "writer-1"]))), \
             patch.dict(os.environ, {"GC_SESSION_ID": "session-1", "GC_INSTANCE_TOKEN": "incarnation-1"}), \
             patch.object(self.store, "resolve", side_effect=lambda prepared: {
                 "outcome": "unknown", "request_sha256": prepared.sha256, "retry_allowed": False}), \
             contextlib.redirect_stdout(stdout):
            self.assertEqual(run.main(self.command()), 1)
        result = json.loads(stdout.getvalue())
        packet = Path(result["receipt"]["request_path"])
        self.assertTrue(packet.is_file())
        self.assertEqual(packet.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("incarnation-1", stdout.getvalue())
        diagnostic = self.root / "different diagnostics"
        diagnostic.mkdir()
        with patch.dict(os.environ, {"TMPDIR": str(diagnostic)}), \
             self.assertRaisesRegex(RecordError, "original retained request"):
            run.capture_run(self.store, self.attempt, **self.kwargs)
        self.assertEqual(len(self.port.requests), 1)
        state = self.root / "resolution-fixture.json"
        state.write_text(json.dumps({"rows": self.port.rows, "cwd": self.store.cwd,
            "common": str(self.store.common_git_dir), "path": str(packet), "sys_path": sys.path}))
        script = '''import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text());sys.path[:0]=data['sys_path']
from workspace_store import WorkspaceStore
from workspace_requests import resolve_request
from test_workspace_store import MemoryPort
store=WorkspaceStore('rig:example',cwd=data['cwd'],common_git_dir=data['common'])
port=MemoryPort(data['rows']);store._command=port
receipt=resolve_request(store,data['path'])
assert port.requests==[], 'resolution submitted another write'
print(json.dumps(receipt))
'''
        child = subprocess.run([sys.executable, "-c", script, str(state)], cwd=diagnostic,
            text=True, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout)["outcome"], "committed")
        require_resolved_scope(self.store, run.run_scope("root-1"))
        self.assertTrue(packet.is_file())
        self.assertEqual(len(self.port.requests), 1)


if __name__ == "__main__":
    unittest.main()
