"""Exact-intent recovery controls; command doubles are not backend acceptance."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_workspace_store as store_fixtures
from workspace_records import RecordError
from workspace_requests import retain_request, require_resolved_scope, resolve_request, journal_directory


class RequestRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = store_fixtures.WorkspaceStoreTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.port = self.fixture.store, self.fixture.port
        self.directory = Path(self.fixture.tmp.name) / "evidence"
        self.directory.mkdir(mode=0o700)

    def test_pending_original_intent_blocks_scope_in_a_new_process(self):
        prepared = self.fixture.prepare()
        path, pending = retain_request(self.store, prepared)
        before = copy.deepcopy(self.port.rows)
        script = "from workspace_requests import require_resolved_scope; from workspace_store import WorkspaceStore; import json,sys; require_resolved_scope(WorkspaceStore('rig:example',cwd=sys.argv[1],common_git_dir=sys.argv[2]),json.loads(sys.argv[3]))"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "assets/scripts"),
                   PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-B", "-c", script, self.store.cwd, str(self.store.common_git_dir), prepared.scope_bytes.decode()],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(path), result.stderr)
        self.assertEqual(pending.read_text(), str(path))
        self.assertEqual(self.port.rows, before)
        self.assertEqual(self.port.requests, [])

    def test_lost_reply_resolves_original_request_without_resubmission(self):
        prepared = self.fixture.prepare()
        path, pending = retain_request(self.store, prepared)
        original = path.read_bytes()
        self.port.lose_ack = True
        self.assertEqual(self.store.execute(prepared)["outcome"], "unknown")
        receipt = resolve_request(self.store, path)
        self.assertEqual(receipt["outcome"], "committed")
        self.assertEqual(receipt["request_sha256"], prepared.sha256)
        self.assertNotIn("rows", receipt)
        self.assertEqual(len(self.port.requests), 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(pending.exists())
        require_resolved_scope(self.store, json.loads(prepared.scope_bytes))

    def test_uncommitted_request_stays_pending_and_rejects_new_intent(self):
        prepared = self.fixture.prepare()
        path, pending = retain_request(self.store, prepared)
        before = copy.deepcopy(self.port.rows)
        self.assertEqual(resolve_request(self.store, path)["outcome"], "not_committed")
        with self.assertRaises(RecordError):
            require_resolved_scope(self.store, json.loads(prepared.scope_bytes))
        with self.assertRaises(RecordError):
            retain_request(self.store, prepared)
        self.assertTrue(pending.exists())
        self.assertEqual(self.port.rows, before)
        self.assertEqual(self.port.requests, [])

    def test_pending_scope_is_shared_across_attempts_but_not_record_kinds(self):
        prepared = self.fixture.prepare()
        retain_request(self.store, prepared)
        scope = json.loads(prepared.scope_bytes)
        with self.assertRaises(RecordError):
            require_resolved_scope(self.store, scope)
        require_resolved_scope(self.store, dict(scope, record_kind="source-plan"))

    def test_changing_diagnostics_or_attempt_cannot_change_authoritative_intent_root(self):
        from workspace_store import WorkspaceStore
        prepared = self.fixture.prepare()
        path, pending = retain_request(self.store, prepared)
        alternative = Path(self.fixture.tmp.name) / "different-diagnostics"
        alternative.mkdir(mode=0o700)
        reopened = WorkspaceStore(self.store.store_ref, cwd=self.store.cwd, common_git_dir=self.store.common_git_dir)
        self.assertEqual(journal_directory(self.store), journal_directory(reopened))
        self.assertNotIn(str(self.directory), str(path))
        self.assertNotIn(str(alternative), str(path))
        with self.assertRaises(RecordError):
            require_resolved_scope(reopened, json.loads(prepared.scope_bytes))
        self.assertTrue(pending.exists())
        self.assertEqual(self.port.requests, [])


if __name__ == "__main__":
    unittest.main()
