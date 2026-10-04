"""Real native init/worktrees/formula/check plumbing with deterministic stand-ins.

Ordinary work-store `gc bd` does not support the native file provider.  Only
that CLI door is adapted by native_file_store_bridge.go using the pinned
engine's real FileStore. Init, formula cook, claims readback, control execution,
and managed worktree commands run the unmodified native gc binary.

No model, Git merge, service, deployment, installed config, or PM intake runs.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest


PACK = Path(__file__).resolve().parents[1]
HELPER = PACK / "assets" / "scripts" / "managed_do_work.py"

GC_WRAPPER = r"""#!/usr/bin/env python3
import json, os, subprocess, sys
config = __FIXTURE_CONFIG__
args = sys.argv[1:]
with open(config["GC_NATIVE_COMMAND_LOG"], "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] != ["bd"]:
    os.execve(config["GC_REAL_NATIVE_BIN"], [config["GC_REAL_NATIVE_BIN"], *args],
              {**os.environ, "GC_BEADS": "file", "GC_SESSION": "fake", "GC_DOLT": "skip"})
if args[1:2] == ["show"] and len(args) == 4 and args[-1] == "--json":
    req = {"operation": "show", "id": args[2]}
elif args[1:2] == ["update"]:
    req = {"operation": "update", "id": args[2], "metadata": {}}
    pos = 3
    while pos < len(args):
        flag = args[pos]
        if flag == "--set-metadata":
            key, value = args[pos + 1].split("=", 1)
            req["metadata"][key] = value
            pos += 2
        elif flag == "--status":
            req["status"] = args[pos + 1]
            pos += 2
        elif flag.startswith("--status="):
            req["status"] = flag.split("=", 1)[1]
            pos += 1
        elif flag == "--json":
            pos += 1
        else:
            raise SystemExit("unsupported fixture bd update argument " + flag)
elif args[1:3] == ["dep", "list"]:
    req = {"operation": "dep-list", "id": args[3]}
else:
    raise SystemExit("unsupported fixture bd command " + repr(args))
result = subprocess.run(
    [config["GC_NATIVE_FILE_BRIDGE"], config["GC_NATIVE_FILE_STORE"]],
    input=json.dumps(req), text=True, capture_output=True,
)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
raise SystemExit(result.returncode)
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManagedDoWorkNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.native = os.environ.get("GC_MANAGED_DO_WORK_NATIVE_BIN", "")
        cls.bridge_binary = os.environ.get("GC_MANAGED_DO_WORK_FILE_BRIDGE", "")
        if not cls.native and not cls.bridge_binary:
            raise unittest.SkipTest("explicit native binary and FileStore fixture bridge required")
        for name, value in (
            ("GC_MANAGED_DO_WORK_NATIVE_BIN", cls.native),
            ("GC_MANAGED_DO_WORK_FILE_BRIDGE", cls.bridge_binary),
        ):
            if not value or not Path(value).is_file():
                raise AssertionError(name + " must identify a built executable")

    def setUp(self) -> None:
        if os.environ.get("GC_MANAGED_DO_WORK_KEEP_FIXTURES"):
            self.home = Path(tempfile.mkdtemp(prefix="managed-do-work-native-"))
            print("preserved native fixture " + str(self.home), flush=True)
        else:
            self.tmp = tempfile.TemporaryDirectory(prefix="managed-do-work-native-")
            self.addCleanup(self.tmp.cleanup)
            self.home = Path(self.tmp.name)
        self.city = self.home / "city"
        config = self.home / "config.toml"
        config.write_text('[workspace]\nname = "offline-contract"\n')
        self.env = {
            **os.environ,
            "GC_SESSION": "fake", "GC_BEADS": "file", "GC_DOLT": "skip",
            "GC_NATIVE_FILE_PREFIX": "ci",
            "GC_CITY": str(self.city),
            "GC_REAL_NATIVE_BIN": self.native,
            "GC_NATIVE_FILE_BRIDGE": self.bridge_binary,
            "GC_NATIVE_FILE_STORE": str(self.city / ".gc" / "beads.json"),
            "GC_NATIVE_COMMAND_LOG": str(self.home / "commands.jsonl"),
        }
        self.command([self.native, "init", "--file", str(config), "--no-start",
                      "--skip-provider-readiness", str(self.city)], cwd=self.home)
        roles = self.home / "fixture-roles"
        roles.mkdir()
        (roles / "pack.toml").write_text('[pack]\nname = "fixture-roles"\nschema = 2\n')
        for role in ("run-operator", "implementation-worker", "implementation-reviewer"):
            folder = roles / "agents" / role
            folder.mkdir(parents=True)
            (folder / "agent.toml").write_text('scope = "city"\nfallback = true\n')
            (folder / "prompt.template.md").write_text("Offline deterministic stand-in.\n")
        city_pack = self.city / "pack.toml"
        city_pack.write_text(
            city_pack.read_text()
            + '\n[imports.workflows]\nsource = ' + json.dumps(str(PACK))
            + '\n\n[imports.gc]\nsource = ' + json.dumps(str(roles)) + '\n'
        )
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "gc"
        # Native exec checks rebuild PATH with the resolved bd directory first
        # and export a deliberate environment whitelist. Keep the test bridge
        # first without extending either production rule: resolve a fixture-only
        # bd here and freeze paths/provider choice in this generated wrapper.
        # Production PATH and environment whitelist remain unmodified.
        wrapper_config = {key: self.env[key] for key in (
            "GC_NATIVE_COMMAND_LOG", "GC_REAL_NATIVE_BIN",
            "GC_NATIVE_FILE_BRIDGE", "GC_NATIVE_FILE_STORE",
        )}
        wrapper.write_text(GC_WRAPPER.replace("__FIXTURE_CONFIG__", repr(wrapper_config)))
        wrapper.chmod(0o755)
        bd = bin_dir / "bd"
        bd.write_text(chr(10).join((
            "#!/bin/sh", "echo 'fixture bd is resolved only; use gc bd bridge' >&2",
            "exit 97", "",
        )))
        bd.chmod(0o755)
        self.env["PATH"] = str(bin_dir) + os.pathsep + self.env["PATH"]
        self.repo = self.home / "generic-product-fixture"
        self.repo.mkdir()
        self.git("init", "-b", "fixture-base")
        self.git("config", "user.name", "Native contract fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.hooksPath", "/dev/null")
        (self.repo / "README").write_text("Generic deterministic dependency fixture.\n")
        self.git("add", "README")
        self.git("commit", "-m", "fixture base")
        self.base = self.git("rev-parse", "HEAD")
        self.worktree_root = self.home / "managed-worktrees"
        self.store_ref = "city:city"

    def command(self, args, *, cwd=None, env=None, check=True, stdin=None):
        result = subprocess.run(
            args, cwd=cwd or self.city, env=env or self.env,
            text=True, input=stdin, capture_output=True, timeout=60,
        )
        if hasattr(self, "home"):
            with (self.home / "runtime-results.jsonl").open("a") as log:
                log.write(json.dumps({"argv": list(map(str, args)), "exit": result.returncode,
                                      "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if check and result.returncode:
            self.fail(f"{args!r}: {result.stdout}\n{result.stderr}")
        return result

    def bridge(self, operation, **fields):
        result = self.command(
            [self.bridge_binary, self.env["GC_NATIVE_FILE_STORE"]],
            stdin=json.dumps({"operation": operation, **fields}),
        )
        return json.loads(result.stdout)

    def git(self, *args, cwd=None, env=None, stdin=None):
        return self.command(
            ["git", *args], cwd=cwd or self.repo, env=env, stdin=stdin,
        ).stdout.strip()

    def bead(self, title, *, kind="task", metadata=None, labels=None):
        return self.bridge("create", bead={
            "title": title, "issue_type": kind,
            "metadata": metadata or {}, "labels": labels or [],
        })["id"]

    def show(self, bead):
        return self.bridge("show", id=bead)

    def update(self, bead, **metadata):
        return self.bridge("update", id=bead, metadata=metadata)

    def workflow(self, name, base=None, parents=(), *, source_handoff=False):
        source = self.bead(name)
        input_path = self.home / (source + ".input.json")
        parent_entries = []
        for parent in parents:
            self.bridge("dep-add", id=source, target=parent["source"], dep_type="blocks")
            anchor = self.show(parent["source"])["metadata"]
            parent_entries.append({
                "source_anchor_id": parent["source"], "source_store_ref": self.store_ref,
                "accepted_commit": anchor["gc.work_commit"],
                "acceptance_path": anchor["gc.implementation.acceptance_path"],
                "acceptance_sha256": anchor["gc.implementation.acceptance_sha256"],
            })
        input_path.write_text(json.dumps({
            "schema_version": 1, "source_anchor_id": source,
            "source_store_ref": self.store_ref, "repo_dir": str(self.repo),
            "worktree_root": str(self.worktree_root), "base_sha": base or self.base,
            "branch": "work/" + source, "generation": "fixture-generation-1",
            "verification_command": "fixture oracle: read exact committed content",
            "parents": parent_entries,
        }, sort_keys=True, indent=2) + "\n")
        cook_args = [self.native, "formula", "cook", "do-work", "--attach", source,
                     "--json"]
        if source_handoff:
            self.update(source, **{"gc.implementation.input_path": str(input_path),
                                   "gc.implementation.input_sha256": sha(input_path)})
        else:
            cook_args += ["--var", "input_path=" + str(input_path)]
        cooked = json.loads(self.command(cook_args).stdout)
        root = cooked["workflow_root_id"]
        # This is the explicit PM/native source-link contract in a stand-in
        # fixture. The native cook/intake singleton relationship is also checked.
        self.update(root, **{"gc.source_bead_id": source,
                             "gc.source_store_ref": self.store_ref})
        self.update(source, **{"workflow_id": root})
        return {
            "source": source, "root": root, "input": input_path,
            "mapping": cooked["id_mapping"],
            "path": self.worktree_root / source,
        }

    def step(self, flow, logical, *, control=False):
        key = "do-work." + logical
        if not control and key + ".iteration.1" in flow["mapping"]:
            key += ".iteration.1"
        return flow["mapping"][key]

    def worker_env(self, flow, stage):
        bead = self.step(flow, stage)
        session = self.bead(
            "stand-in-" + stage, kind="session", labels=["gc:session"],
            metadata={"current_claim_bead_id": bead, "state": "active",
                      "session_name": "stand-in-" + bead,
                      "template": "gc.implementation-worker"},
        )
        self.bridge("update", id=bead, status="in_progress",
                    metadata={"gc.session_id": session})
        return {**self.env, "GC_SESSION_ID": session}, bead

    def helper(self, mode, bead, *args, env=None, check=True):
        return self.command(
            ["python3", str(HELPER), mode, "--bead", bead, *map(str, args)],
            env=env, check=check,
        )

    def gate(self, flow, stage, phase, *, check=True):
        bead = self.step(flow, stage)
        return self.helper("check", bead, "--phase", phase, check=check)

    def finish(self, flow, stage, *, run_control=True):
        bead = self.step(flow, stage)
        self.bridge("update", id=bead, status="closed", metadata={"gc.outcome": "pass"})
        if run_control and "do-work." + stage + ".iteration.1" in flow["mapping"]:
            self.command([self.native, "convoy", "control",
                          self.step(flow, stage, control=True)])

    def ready_ids(self):
        return {row["id"] for row in json.loads(self.command([
            self.native, "ready", "--limit", "0", "--json",
        ]).stdout)}

    def prepare(self, flow):
        self.assertNotIn(self.step(flow, "implement"), self.ready_ids())
        env, bead = self.worker_env(flow, "prepare-worktree")
        self.helper("prepare", bead, "--input", flow["input"], env=env)
        self.finish(flow, "prepare-worktree")
        self.gate(flow, "prepare-worktree", "prepare")
        self.assertIn(self.step(flow, "implement"), self.ready_ids())

    def artifact(self, flow, stage, schema, upstream):
        headings = (
            ["Summary", "Intended Behavior", "Changed Files", "Verification", "Remaining Risks"]
            if schema.endswith("implementation-summary.v1")
            else ["Verdict", "Findings", "Verification"]
        )
        path = self.home / (flow["source"] + "." + stage + ".md")
        text = (
            "---\n"
            f"schema: {schema}\n"
            f"workflow:\n  id: {flow['root']}\n  formula: do-work\n"
            "methodology:\n  pack: gascity\n  name: do-work\n"
            f"producer:\n  formula: do-work\n  stage: {stage}\n  attempt: 1\n"
            "status: approved\ntrace:\n  upstream:\n"
            f"    - path: {upstream}\n      hash: sha256:{sha(upstream)}\n"
            "  coverage:\n    - id: FIXTURE-1\n      status: covered\n---\n\n"
        )
        for index, heading in enumerate(headings):
            text += f"## {heading}\n\nDeterministic fixture pass.\n"
            if index == 0:
                text += "\n| ID | Status |\n| --- | --- |\n| FIXTURE-1 | covered |\n"
            text += "\n"
        path.write_text(text)
        return path

    def produce(self, flow, filename, contents, barrier=None):
        env, producer = self.worker_env(flow, "implement")
        self.helper("verify", producer, env=env)
        if barrier:
            barrier.wait(timeout=20)
        path = flow["path"]
        (path / filename).write_text(contents)
        self.git("add", filename, cwd=path)
        self.git("commit", "-m", "fixture " + filename, cwd=path)
        head = self.git("rev-parse", "HEAD", cwd=path)
        evidence = self.home / (flow["source"] + ".verification.json")
        evidence.write_text(json.dumps({
            "tested_commit": head, "result": "pass",
            "command": "fixture oracle: read exact committed content",
            "observed": self.git("show", head + ":" + filename),
        }) + "\n")
        summary = self.artifact(
            flow, "implement", "gc.build.implementation-summary.v1", flow["input"],
        )
        self.helper("publish-output", producer, "--summary", summary,
                    "--verification", evidence, env=env)
        self.finish(flow, "implement")
        self.gate(flow, "implement", "output")
        return head

    def accept(self, flow, filename, contents, barrier=None):
        head = self.produce(flow, filename, contents, barrier)
        env, reviewer = self.worker_env(flow, "independent-acceptance")
        root = self.show(flow["root"])["metadata"]
        review_path = self.worktree_root / ("review-" + reviewer)
        review_report = json.loads(self.command([
            self.native, "worktree", "ensure", "--repo", str(self.repo),
            "--root", str(self.worktree_root), "--path", str(review_path),
            "--branch", "review/" + reviewer, "--base", head, "--base-sha", head,
            "--bead", reviewer, "--store-ref", self.store_ref,
            "--creator", "fixture-independent-review", "--owner", env["GC_SESSION_ID"],
            "--generation", "fixture-review-1", "--json",
        ]).stdout)
        self.assertEqual(review_report["head"], head)
        self.assertEqual((review_path / filename).read_text(), contents)
        self.assertEqual(self.git("status", "--porcelain", cwd=review_path), "")
        if filename == "sum.txt":
            alpha = int((review_path / "a.txt").read_text().strip().split("=")[1])
            beta = int((review_path / "b.txt").read_text().strip().split("=")[1])
            self.assertEqual(int(contents.strip().split("=")[1]), alpha + beta)
        report = self.artifact(
            flow, "independent-acceptance", "gc.build.review.v1",
            Path(root["gc.implementation.output_path"]),
        )
        self.helper("record-acceptance", reviewer, "--report", report, env=env)
        self.finish(flow, "independent-acceptance")
        self.gate(flow, "independent-acceptance", "acceptance")
        env, closer = self.worker_env(flow, "close-source-anchor")
        self.helper("close-source", closer, env=env)
        self.finish(flow, "close-source-anchor")
        self.gate(flow, "close-source-anchor", "close")
        self.command([self.native, "convoy", "control",
                      flow["mapping"]["do-work.workflow-finalize"]])
        accepted = self.show(flow["source"])
        self.assertEqual(accepted["status"], "closed")
        self.assertEqual(accepted["metadata"]["gc.work_commit"], head)
        self.assertEqual(accepted["metadata"]["gc.work_outcome"], "shipped")
        receipt = json.loads(Path(accepted["metadata"]["gc.implementation.acceptance_path"]).read_text())
        self.assertNotEqual(receipt["producer"]["session_id"], receipt["reviewer"]["session_id"])
        self.assertNotEqual(receipt["producer"]["bead_id"], receipt["reviewer"]["bead_id"])
        self.assertEqual(receipt["output_commit"], head)
        return head

    def test_concurrent_accepted_parents_feed_exact_combined_input(self):
        a, b = (self.workflow(name) for name in ("A", "B"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(self.prepare, (a, b)))
        barrier = threading.Barrier(2)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fa = executor.submit(self.accept, a, "a.txt", "alpha=17\n", barrier)
            fb = executor.submit(self.accept, b, "b.txt", "beta=29\n", barrier)
            outputs = (fa.result(timeout=60), fb.result(timeout=60))
        for output in outputs:
            self.assertEqual(self.git("rev-parse", output + "^"), self.base)

        # Construct fixture-only combined tree and explicit parent edges.
        # There is no Git merge and no protected integration branch mutation.
        index = self.home / "combined.index"
        git_env = {**self.env, "GIT_INDEX_FILE": str(index)}
        self.git("read-tree", outputs[0], env=git_env)
        blob = self.git("hash-object", "-w", "--stdin", stdin="beta=29\n")
        self.git("update-index", "--add", "--cacheinfo", "100644," + blob + ",b.txt",
                 env=git_env)
        tree = self.git("write-tree", env=git_env)
        combined = self.git("commit-tree", tree, "-p", outputs[0], "-p", outputs[1],
                            stdin="synthetic combined fixture input\n")
        c = self.workflow("C", combined, (a, b))
        self.prepare(c)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=c["path"]), combined)
        self.assertEqual((c["path"] / "a.txt").read_text(), "alpha=17\n")
        self.assertEqual((c["path"] / "b.txt").read_text(), "beta=29\n")
        c_head = self.accept(c, "sum.txt", "sum=46\n")
        self.assertEqual(self.git("rev-parse", c_head + "^"), combined)
        commands = [json.loads(line) for line in (self.home / "commands.jsonl").read_text().splitlines()]
        ensures = [x for x in commands if x[:2] == ["worktree", "ensure"]]
        for flow, expected in ((a, self.base), (b, self.base), (c, combined)):
            args = next(x for x in ensures if x[x.index("--bead") + 1] == flow["source"])
            self.assertEqual(args[args.index("--base") + 1], expected)
            self.assertEqual(args[args.index("--base-sha") + 1], expected)
            self.assertEqual(args[args.index("--store-ref") + 1], self.store_ref)
        self.assertEqual(self.git("rev-parse", "HEAD"), self.base)

    def test_source_pinned_handoff_without_formula_input_var(self):
        flow = self.workflow("source-pinned-handoff", source_handoff=True)
        env, bead = self.worker_env(flow, "prepare-worktree")
        self.helper("prepare", bead, "--input", "", env=env)
        self.finish(flow, "prepare-worktree")
        self.gate(flow, "prepare-worktree", "prepare")
        self.assertEqual(self.show(flow["root"])["metadata"]["gc.implementation.input_sha256"],
                         sha(flow["input"]))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=flow["path"]), self.base)

    def test_prepare_repeat_keeps_provenance_and_freeze(self):
        flow = self.workflow("repeat")
        env, bead = self.worker_env(flow, "prepare-worktree")
        self.helper("prepare", bead, "--input", flow["input"], env=env)
        before = self.show(flow["source"])["metadata"].copy()
        self.helper("prepare", bead, "--input", flow["input"], env=env)
        self.assertEqual(self.show(flow["source"])["metadata"], before)
        attempt_id = before["gc.implementation.worktree_attempt_id"]
        self.assertTrue(attempt_id)
        frozen = flow["input"].read_bytes()
        changed = json.loads(frozen)
        changed["generation"] = "changed"
        flow["input"].write_text(json.dumps(changed))
        refused = self.helper("prepare", bead, "--input", flow["input"], env=env, check=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.show(flow["source"])["metadata"], before)
        self.assertEqual(self.show(bead)["metadata"].get("gc.attempt"), "1")

    def test_unreviewed_missing_and_stale_parent_inputs_refuse_before_provision(self):
        a = self.workflow("accepted-parent")
        self.prepare(a)
        accepted = self.accept(a, "parent.txt", "accepted\n")
        for case in ("missing", "unreviewed", "stale"):
            flow = self.workflow(case, accepted, (a,))
            payload = json.loads(flow["input"].read_text())
            if case == "missing":
                payload["parents"][0]["acceptance_path"] = str(self.home / "missing.json")
            elif case == "unreviewed":
                pending = self.bead("open-unreviewed-parent")
                self.bridge("dep-add", id=flow["source"], target=pending, dep_type="blocks")
                payload["parents"].append({
                    "source_anchor_id": pending, "source_store_ref": self.store_ref,
                    "accepted_commit": accepted,
                    "acceptance_path": payload["parents"][0]["acceptance_path"],
                    "acceptance_sha256": payload["parents"][0]["acceptance_sha256"],
                })
            else:
                path = a["path"]
                (path / "later.txt").write_text("later unaccepted parent output\n")
                self.git("add", "later.txt", cwd=path)
                self.git("commit", "-m", "unaccepted later parent output", cwd=path)
            flow["input"].write_text(json.dumps(payload) + "\n")
            if case == "unreviewed":
                self.assertNotIn(flow["source"], self.ready_ids())
            self.assertNotIn(self.step(flow, "implement"), self.ready_ids())
            env, bead = self.worker_env(flow, "prepare-worktree")
            before = self.show(bead)["metadata"].copy()
            result = self.helper("prepare", bead, "--input", flow["input"], env=env, check=False)
            self.assertNotEqual(result.returncode, 0, case)
            self.assertFalse(flow["path"].exists(), case)
            self.assertEqual(self.show(bead)["metadata"], before, case)
            self.assertNotIn(self.step(flow, "implement"), self.ready_ids())

    def test_partial_frozen_handoff_never_calls_ensure(self):
        for location, key, value in (
            ("source", "gc.implementation.input_path", "path"),
            ("source", "gc.implementation.input_sha256", "hash"),
            ("root", "gc.implementation.input_path", "path"),
            ("root", "gc.implementation.input_sha256", "hash"),
            ("root", "gc.implementation.worktree_attempt_id", "held-attempt"),
        ):
            flow = self.workflow("partial-" + location + "-" + value)
            actual = str(flow["input"]) if value == "path" else sha(flow["input"]) if value == "hash" else value
            self.update(flow[location], **{key: actual})
            env, bead = self.worker_env(flow, "prepare-worktree")
            log = self.home / "commands.jsonl"
            before = log.read_text() if log.exists() else ""
            result = self.helper("prepare", bead, "--input", flow["input"], env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            commands = [json.loads(line) for line in log.read_text()[len(before):].splitlines()]
            self.assertFalse(any(x[:2] == ["worktree", "ensure"] for x in commands))
            self.assertFalse(flow["path"].exists())

    def test_rejected_and_stale_review_reports_cannot_publish_acceptance(self):
        flow = self.workflow("report-binding")
        self.prepare(flow)
        self.produce(flow, "output.txt", "verified output\n")
        env, reviewer = self.worker_env(flow, "independent-acceptance")
        root = self.show(flow["root"])["metadata"]
        output = Path(root["gc.implementation.output_path"])
        report = self.artifact(flow, "independent-acceptance", "gc.build.review.v1", output)
        approved = report.read_text()
        before = self.show(reviewer)["metadata"].copy()
        for text in (approved.replace("status: approved", "status: changes_required"),
                     approved.replace("hash: sha256:" + sha(output), "hash: sha256:" + "0" * 64)):
            report.write_text(text)
            result = self.helper("record-acceptance", reviewer, "--report", report,
                                 env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.show(reviewer)["metadata"], before)
            self.assertNotIn("gc.implementation.acceptance_path", self.show(flow["root"])["metadata"])
            self.assertEqual(self.show(flow["source"])["status"], "open")

    def test_cleared_source_workflow_link_refuses_replay(self):
        flow = self.workflow("cleared-source-owner")
        self.prepare(flow)
        env, bead = self.worker_env(flow, "implement")
        self.update(flow["source"], **{"workflow_id": ""})
        source_before = self.show(flow["source"])["metadata"].copy()
        worker_before = self.show(bead)["metadata"].copy()
        log = self.home / "commands.jsonl"
        before = log.read_text()
        result = self.helper("verify", bead, env=env, check=False)
        self.assertNotEqual(result.returncode, 0)
        commands = [json.loads(line) for line in log.read_text()[len(before):].splitlines()]
        self.assertFalse(any(x[:2] == ["worktree", "ensure"] for x in commands))
        self.assertEqual(self.show(flow["source"])["metadata"], source_before)
        self.assertEqual(self.show(bead)["metadata"], worker_before)

    def test_native_ralph_failure_preserves_bound_and_frozen_input(self):
        flow = self.workflow("native-bounded-failure")
        self.prepare(flow)
        _, producer = self.worker_env(flow, "implement")
        source_before = self.show(flow["source"])["metadata"].copy()
        self.bridge("update", id=producer, status="closed", metadata={"gc.outcome": "pass"})
        # Missing output is rejected by the real native exec check. Ralph,
        # rather than the pack helper, owns the next bounded repair attempt.
        control = self.step(flow, "implement", control=True)
        dispatched = self.command([self.native, "convoy", "control", control])
        self.assertIn("action=retry created=1", dispatched.stdout)
        rows = json.loads(self.command([
            self.native, "ready", "--status", "open", "--limit", "0", "--json",
        ]).stdout)
        repairs = [row for row in rows
                   if row.get("metadata", {}).get("gc.root_bead_id") == flow["root"]
                   and row.get("metadata", {}).get("gc.step_id") == "implement"
                   and row.get("metadata", {}).get("gc.logical_bead_id") == control
                   and row.get("metadata", {}).get("gc.control_for") == control
                   and row.get("metadata", {}).get("gc.attempt") == "2"]
        self.assertEqual(len(repairs), 1)
        repair = repairs[0]["id"]
        control = self.step(flow, "implement", control=True)
        self.assertEqual(self.show(control)["metadata"]["gc.max_attempts"], "3")
        session = self.bead("repair-session", kind="session", labels=["gc:session"],
                            metadata={"current_claim_bead_id": repair})
        self.bridge("update", id=repair, status="in_progress",
                    metadata={"gc.session_id": session})
        before = self.show(repair)["metadata"].copy()
        flow["input"].write_text(flow["input"].read_text() + " ")
        result = self.helper("verify", repair,
                             env={**self.env, "GC_SESSION_ID": session}, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.show(repair)["metadata"], before)
        self.assertEqual(self.show(control)["metadata"]["gc.max_attempts"], "3")
        self.assertEqual(self.show(flow["source"])["metadata"], source_before)

    def test_cancelled_and_failed_roots_never_provision_or_reset_attempts(self):
        for outcome in ("cancelled", "fail", "pass", "open-molecule-failed", "open-cancel-requested"):
            flow = self.workflow(outcome)
            env, bead = self.worker_env(flow, "prepare-worktree")
            self.update(bead, **{"gc.attempt": "2", "gc.attempt_log": "held failed attempt"})
            if outcome.startswith("open-"):
                key = "molecule_failed" if outcome == "open-molecule-failed" else "gc.cancel_requested"
                self.update(flow["root"], **{key: "operator hold" if key == "gc.cancel_requested" else "true"})
            else:
                self.bridge("update", id=flow["root"], status="closed",
                            metadata={"gc.outcome": outcome})
            before = self.show(bead)["metadata"].copy()
            result = self.helper("prepare", bead, "--input", flow["input"], env=env, check=False)
            self.assertNotEqual(result.returncode, 0, outcome)
            self.assertFalse(flow["path"].exists(), outcome)
            self.assertEqual(self.show(bead)["metadata"], before, outcome)


if __name__ == "__main__":
    unittest.main()
