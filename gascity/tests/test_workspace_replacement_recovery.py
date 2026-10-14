"""Replacement recovery over real Git and the native command protocol doubles."""
from __future__ import annotations

import copy
import json
import os
import hashlib
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workspace_composition as composition
import test_workspace_run as run_fixtures
from workspace_records import RecordError, canonical_bytes
from workspace_store import Attempt, CookedWriterMap, GRANT_KEY
import workspace_entry as entry
import workspace_flow as flow_module
from workspace_requests import allocation_directory, journal_directory, resolve_request


class FlowReplacementTests(unittest.TestCase):
    def setUp(self):
        self.original = composition.ComposedFlowTests("runTest")
        self.original.setUp()
        self.addCleanup(self.original.doCleanups)
        self.fixture = self.original.fixture

    def rotate(self):
        f = self.fixture
        state = json.loads((f.root / "port.json").read_text())
        f.rows.update(copy.deepcopy(state["stores"]["rig:fixture"]))
        old = f.attempts["recorder"]
        current = Attempt(old.session_id, "replacement-recorder-instance", old.claimed_bead_id)
        f.attempts["recorder"] = current
        f.sessions[old.session_id]["metadata"]["instance_token"] = current.instance_token
        f.rows[old.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
        f.rows[old.claimed_bead_id]["revision"] = str(int(f.rows[old.claimed_bead_id]["revision"]) + 1)
        f.select_role("recorder")
        return current

    def test_ready_native_ids_survive_actual_recorder_replacement_without_new_creation(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocated = original._allocation("member-result", "member", "member")
        before = json.loads((f.root / "port.json").read_text())
        self.rotate()
        recovered = flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(recovered, allocated)
        after = json.loads((f.root / "port.json").read_text())
        self.assertEqual(set(after["stores"]["rig:fixture"]), set(before["stores"]["rig:fixture"]))
        self.assertEqual(after["stores"]["rig:fixture"][allocated["record_id"]],
                         before["stores"]["rig:fixture"][allocated["record_id"]])
        with self.assertRaises(RecordError):
            original._allocation("member-result", "member", "member")

    def commands(self):
        return [json.loads(line) for line in (self.fixture.root / "port.commands").read_text().splitlines()]

    def creates(self):
        return sum("create" in command and "bd" in command for command in self.commands())

    def lose_next_reply(self, index=1):
        f = self.fixture
        port = f.port.read_text()
        port = port.replace("    emit(dict(id=key))", "    if data.get('lose_allocation_ack_at') == data['allocation_counter']:\n"
                            "        sys.exit('native create committed; acknowledgement lost')\n    emit(dict(id=key))")
        port = port.replace("    value=option('desc-contains')", "    value=option('desc-contains')\n"
            "    if 'allocation_lookup_response' in data: emit(data['allocation_lookup_response'])")
        f.port.write_text(port)
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        state["lose_allocation_ack_at"] = index
        path.write_text(json.dumps(state))

    def fresh_allocation(self, *, expected_success=True):
        f = self.fixture
        script = """import json,sys
from pathlib import Path
from workspace_store import WorkspaceStore
from workspace_runtime import NativeSourceRuntime
from workspace_flow import WorkspaceFlow
p,city,common,artifacts,evidence=sys.argv[1:]
state=json.loads(Path(p).with_name('port.json').read_text());rows=state['stores']['rig:fixture']
run=json.loads(rows['run-record']['metadata']['gc.implementation_run'])
plan=json.loads(rows['plan-record']['metadata']['gc.source_plan'])
store=WorkspaceStore('rig:fixture',gc=p,cwd=city,common_git_dir=common)
runtime=NativeSourceRuntime(store,gc=p,city_root=city,rig_name='fixture',run=run,plan=plan,
 artifact_root=artifacts,evidence_dir=evidence,claimed_step_id='recorder')
print(json.dumps(WorkspaceFlow(runtime)._allocation('member-result','member','member')))
"""
        environment = dict(os.environ, PYTHONPATH=str(Path(flow_module.__file__).parent))
        result = subprocess.run([sys.executable, "-B", "-c", script, str(f.port), str(f.city),
            str(f.repo / ".git"), str(f.artifacts), str(f.diagnostics)], text=True,
            capture_output=True, env=environment, timeout=60)
        if expected_success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result

    def test_unknown_created_role_is_found_readonly_by_original_description_in_new_process(self):
        f = self.fixture
        self.lose_next_reply(index=2)
        original = flow_module.WorkspaceFlow(f.adapter())
        with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
            original._allocation("member-result", "member", "member")
        intent = next(allocation_directory(f.store).glob("*.intent.json"))
        before = intent.read_bytes()
        self.rotate()
        recovered = self.fresh_allocation()
        self.assertEqual(recovered["record_id"], "allocated-1")
        self.assertEqual(recovered["authority_id"], "allocated-2")
        self.assertEqual(self.creates(), 2)
        self.assertEqual(intent.read_bytes(), before)
        query = [command for command in self.commands() if "--desc-contains" in command]
        self.assertEqual(len(query), 1)
        self.assertTrue(all(flag in query[0] for flag in ("--all", "--limit", "--json", "--readonly")))
        self.assertEqual(query[0][query[0].index("--limit") + 1], "2")
        self.assertFalse(any("sling" in command or "start" in command for command in self.commands()))

    def test_zero_duplicate_object_or_wrong_identity_lookup_blocks_without_another_create(self):
        f = self.fixture
        self.lose_next_reply()
        with self.assertRaises(RecordError):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.rotate()
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        row = copy.deepcopy(state["stores"]["rig:fixture"]["allocated-1"])
        for value in ([], [row, row], row, None, [dict(row, title="wrong")],
                      [dict(row, description="wrong")], [dict(row, id="")]):
            with self.subTest(response=value):
                current = json.loads(path.read_text())
                current["allocation_lookup_response"] = value
                path.write_text(json.dumps(current))
                refused = self.fresh_allocation(expected_success=False)
                self.assertIn("no known physical ID", refused.stderr)
                self.assertEqual(self.creates(), 1)

    def test_ready_receipt_keeps_original_revision_across_replacement(self):
        f = self.fixture
        flow = flow_module.WorkspaceFlow(f.adapter())
        allocated = flow._allocation("member-result", "member", "member")
        self.rotate()
        path = f.root / "port.json"
        state = json.loads(path.read_text())
        state["stores"]["rig:fixture"][allocated["record_id"]]["revision"] = "2"
        path.write_text(json.dumps(state))
        with self.assertRaisesRegex(RecordError, "changed since its original receipt"):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(self.creates(), 2)

    def test_null_origin_or_invalid_attempt_or_nonce_refuses_before_native_allocation_reads(self):
        f = self.fixture
        flow = flow_module.WorkspaceFlow(f.adapter())
        flow._allocation("member-result", "member", "member")
        intent = next(allocation_directory(f.store).glob("*.intent.json"))
        original = json.loads(intent.read_text())
        for change in ({"origin": None}, {"origin": dict(original["origin"], attempt={"session_id": None,
                       "instance_token": "token", "claimed_bead_id": "recorder"})}, {"nonce": "g" * 64}):
            with self.subTest(change=change):
                intent.write_bytes(canonical_bytes(dict(original, **change)))
                before = len(self.commands())
                with self.assertRaises(RecordError):
                    flow._allocation("member-result", "member", "member")
                added = self.commands()[before:]
                self.assertFalse(any("create" in command or "show" in command or "--desc-contains" in command
                                     for command in added))
        intent.write_bytes(canonical_bytes(original))

    def test_installed_result_replay_replaces_only_current_native_writer_in_same_batch(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocation = original._allocation("member-result", "member", "member")
        prepared = original.runtime.prepare_member_result(f.result, **allocation)
        original._commit(prepared, f.result)
        state = json.loads((f.root / "port.json").read_text())
        payload = state["stores"]["rig:fixture"][allocation["record_id"]]["metadata"]["gc.workspace_result"]
        current = self.rotate()
        replacement = flow_module.WorkspaceFlow(f.adapter())
        existing = replacement._allocation("member-result", "member", "member")
        self.assertFalse(existing["initial_write"])
        prepared = replacement.runtime.prepare_member_result(f.result, **existing)
        request = json.loads(prepared.request_bytes)
        authority = next(row for row in request["rows"] if row["id"] == allocation["authority_id"])
        self.assertEqual(json.loads(authority["set"][GRANT_KEY])["attempt"], current.admission)
        self.assertIn(allocation["record_id"], {row["id"] for row in request["rows"]})
        self.assertIn("member", {row["id"] for row in request["rows"]})
        receipt = replacement._commit(prepared, f.result)
        self.assertEqual(receipt["outcome"], "replayed")
        state = json.loads((f.root / "port.json").read_text())
        self.assertEqual(state["stores"]["rig:fixture"][allocation["record_id"]]["metadata"]["gc.workspace_result"], payload)
        self.assertEqual(self.creates(), 2)
        with self.assertRaises(RecordError):
            original._allocation("member-result", "member", "member")


    def test_pending_original_write_blocks_replacement_before_new_effects(self):
        f = self.fixture
        original = flow_module.WorkspaceFlow(f.adapter())
        allocated = original._allocation("member-result", "member", "member")
        prepared = original.runtime.prepare_member_result(f.result, **allocated)
        state_path = f.root / "port.json"
        state = json.loads(state_path.read_text())
        state["lose_write_ack"] = True
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(RecordError, "original request"):
            original._commit(prepared, f.result)
        pending = next(journal_directory(f.store).glob("*.pending"))
        request = Path(pending.read_text())
        retained = request.read_bytes()
        state = json.loads(state_path.read_text())
        state.pop("lose_write_ack"); state.pop("block_readback")
        state_path.write_text(json.dumps(state))
        self.rotate()
        other = f.root / "other-diagnostics"
        other.mkdir()
        f.diagnostics = other
        with self.assertRaisesRegex(RecordError, "original retained request"):
            flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
        self.assertEqual(self.creates(), 2)
        # A changed native claim cannot be guessed into the original after-state.
        resolved = resolve_request(f.store, request)
        self.assertEqual(resolved["outcome"], "unknown")
        self.assertTrue(pending.exists())
        self.assertEqual(request.read_bytes(), retained)
        writes = [command for command in self.commands() if "guarded-metadata-batch" in command
                  and any(arg == "--request" or arg.startswith("--request=") for arg in command)]
        self.assertEqual(len(writes), 1)


    def test_malformed_existing_record_or_grant_reference_refuses_before_creation(self):
        from workspace_store import GRANT_REFS_KEY
        f = self.fixture
        path = f.root / "port.json"
        original = json.loads(path.read_text())
        scope = dict(workflow_root_id="root", generation=1, writer_scope_id="member", record_kind="member-result")
        scope_hash = hashlib.sha256(canonical_bytes(scope)).hexdigest()
        sibling = dict(scope, writer_scope_id="plan-owner", record_kind="canonical")
        sibling_hash = hashlib.sha256(canonical_bytes(sibling)).hexdigest()
        malformed_indices = [dict(version=1, scopes={scope_hash: value}) for value in (None, "", {})]
        malformed_indices += [dict(version=1, scopes={"sibling": None}),
            dict(version=1, scopes={scope_hash: dict(scope=scope, authority_id="same-authority"),
                sibling_hash: dict(scope=sibling, authority_id="same-authority")}),
            dict(version=1, scopes={scope_hash: dict(scope=dict(scope, workflow_root_id="wrong-root"), authority_id="record")})]
        changes = [("member", "gc.workspace_result_ref", None), ("member", "gc.workspace_result_ref", ""),
            ("root", GRANT_REFS_KEY, None), ("root", GRANT_REFS_KEY, ""), ("root", GRANT_REFS_KEY, "{}")]
        changes += [("root", GRANT_REFS_KEY, canonical_bytes(value).decode()) for value in malformed_indices]
        for owner, key, value in changes:
            with self.subTest(owner=owner, value=value):
                current = copy.deepcopy(original)
                current["stores"]["rig:fixture"][owner]["metadata"][key] = value
                path.write_text(json.dumps(current))
                with self.assertRaises(RecordError):
                    flow_module.WorkspaceFlow(f.adapter())._allocation("member-result", "member", "member")
                self.assertEqual(self.creates(), 0)
        path.write_text(json.dumps(original))



class RunReplacementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = run_fixtures.RunStoreTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_known_initial_ids_survive_replacement_with_original_base_and_source_intent(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=2)
        args = f.allocation_args()
        with patch.object(module, "native_json", side_effect=native):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                module.allocate_run_placeholders(f.store, f.attempt, **args)
            intent = next((f.repo / ".git" / "gc-workspace-locks").rglob("*.intent.json"))
            original = intent.read_bytes()
            (f.repo / "file").write_text("later default\n")
            f.git("commit", "-am", "later default")
            current = Attempt(f.attempt.session_id, "replacement-native-instance", f.attempt.claimed_bead_id)
            f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
            f.port.rows[current.claimed_bead_id]["revision"] = "2"
            recovered = module.allocate_run_placeholders(f.store, current,
                authority_id=list(created)[1], **args)
        self.assertEqual(recovered["captured_run"]["base_oid"], f.base)
        self.assertEqual(intent.read_bytes(), original)
        self.assertEqual(len(created), 2)
        self.assertEqual(f.port.requests, [])


    def test_published_run_replay_accepts_native_replacement_but_rejects_stale_original(self):
        f = self.fixture
        captured = run_fixtures.run.capture_run(f.store, f.attempt, **f.kwargs)
        current = Attempt(f.attempt.session_id, "current-native-instance", f.attempt.claimed_bead_id)
        f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
        f.port.rows[current.claimed_bead_id]["revision"] = str(int(f.port.rows[current.claimed_bead_id]["revision"]) + 1)
        replay = run_fixtures.run.capture_run(f.store, current, **f.kwargs)
        self.assertEqual(replay["record"], captured["record"])
        self.assertEqual(replay["receipt"]["outcome"], "replayed")
        self.assertEqual(json.loads(f.port.rows["authority-1"]["metadata"][GRANT_KEY])["attempt"], current.admission)
        with self.assertRaisesRegex(RecordError, "stale native claim"):
            run_fixtures.run.capture_run(f.store, f.attempt, **f.kwargs)
        self.assertEqual(len(f.port.requests), 2)

    def test_null_run_origin_refuses_without_native_create_or_lookup(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=1)
        with patch.object(module, "native_json", side_effect=native):
            with self.assertRaises(RecordError):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
            path = next(allocation_directory(f.store).glob("*.intent.json"))
            value = json.loads(path.read_text())
            value["origin"] = None
            path.write_bytes(canonical_bytes(value))
            before = list(calls)
            with self.assertRaisesRegex(RecordError, "no original cooked writer"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
        self.assertEqual(calls, before)
        self.assertEqual(len(created), 1)


    def test_claim_change_after_first_role_prevents_second_native_create(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator()
        def changed(gc, city, args, rig=None, **kwargs):
            value = native(gc, city, args, rig, **kwargs)
            if args[:2] == ["bd", "show"]:
                claim = f.port.rows[f.attempt.claimed_bead_id]
                claim["metadata"]["gc.session_attempt_id"] = Attempt(f.attempt.session_id,
                    "new-owner", f.attempt.claimed_bead_id).writer_attempt_id
                claim["revision"] = "2"
            return value
        with patch.object(module, "native_json", side_effect=changed):
            with self.assertRaisesRegex(RecordError, "changed after admission"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
        self.assertEqual(len(created), 1)
        self.assertEqual(sum(call[:2] == ["bd", "create"] for call in calls), 1)
        self.assertEqual(f.port.requests, [])

    def test_unacknowledged_authority_query_survives_replacement_and_first_publication(self):
        f = self.fixture
        module, created, calls, native = f.native_allocator(lose_reply_at=2)
        def lookup(gc, city, args, rig=None, **kwargs):
            if args[:2] == ["bd", "list"]:
                calls.append(list(args))
                self.assertTrue(kwargs["require_array"])
                value = args[args.index("--desc-contains") + 1]
                matches = [row for row in created.values() if row["description"] == value]
                self.assertEqual(len(matches), 1)
                return copy.deepcopy(matches[0])
            return native(gc, city, args, rig, **kwargs)
        with patch.object(module, "native_json", side_effect=lookup):
            with self.assertRaisesRegex(RecordError, "authority allocation unresolved"):
                module.allocate_run_placeholders(f.store, f.attempt, **f.allocation_args())
            intent = next(allocation_directory(f.store).glob("*.intent.json"))
            retained = intent.read_bytes()
            (f.repo / "file").write_text("new default after lost acknowledgement\n")
            f.git("commit", "-am", "new default")
            current = Attempt(f.attempt.session_id, "actual-replacement", f.attempt.claimed_bead_id)
            f.port.rows[current.claimed_bead_id]["metadata"]["gc.session_attempt_id"] = current.writer_attempt_id
            f.port.rows[current.claimed_bead_id]["revision"] = "2"
            allocated = module.allocate_run_placeholders(f.store, current, **f.allocation_args())
        captured = run_fixtures.run.capture_run(f.store, current, **dict(f.kwargs,
            record_bead_id=allocated["run_record_id"], authority_id=allocated["authority_id"],
            captured_run=allocated["captured_run"], allocation_rows=allocated["allocation_rows"],
            captured_checks_config=f.allocation_args()["checks_config"]))
        self.assertEqual(captured["receipt"]["outcome"], "committed")
        self.assertEqual(captured["record"]["base_oid"], f.base)
        self.assertEqual(captured["record"]["writer_step_id"], f.attempt.claimed_bead_id)
        self.assertEqual(intent.read_bytes(), retained)
        self.assertEqual(len(created), 2)
        self.assertEqual(sum(call[:2] == ["bd", "create"] for call in calls), 2)
        self.assertEqual(len(f.port.requests), 1)
