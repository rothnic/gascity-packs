"""Tests for resolving helper scripts from an imported Gas City pack."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
COMMAND = REPO / "gascity/commands/workspace/run.sh"


class WorkspaceScriptsPathTests(unittest.TestCase):
    def test_help_documents_scripts_path_lookup(self) -> None:
        result = subprocess.run(
            [str(COMMAND), "--help"], text=True, capture_output=True,
            env=dict(os.environ, GC_PACK_DIR=str(REPO / "gascity")), timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scripts-path", result.stdout)
        self.assertIn("PACK_SCRIPTS=$(gc gc workspace scripts-path)", result.stdout)

    def test_returns_scripts_path_for_checkout_and_cached_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for layout in ("checkout with spaces/gascity", "city/.gc/cache/repos/pinned/gascity"):
                pack = root / layout
                scripts = pack / "assets/scripts"
                scripts.mkdir(parents=True)
                schema = pack / "schemas/workspace/records.v1.json"
                schema.parent.mkdir(parents=True)
                shutil.copy2(REPO / "gascity/schemas/workspace/records.v1.json", schema)
                shutil.copy2(REPO / "gascity/assets/scripts/workspace_entry.py", scripts)
                helper = scripts / "validate_context_bundle.py"
                shutil.copy2(REPO / "gascity/assets/scripts/validate_context_bundle.py", helper)
                env = dict(os.environ, GC_PACK_DIR=str(pack))

                with self.subTest(layout=layout):
                    result = subprocess.run(
                        [str(COMMAND), "scripts-path"], cwd=root, text=True,
                        capture_output=True, env=env, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, str(scripts) + "\n")
                    invoked = subprocess.run(
                        [sys.executable, "-B", str(Path(result.stdout.strip()) / helper.name), "--help"],
                        cwd=root, text=True, capture_output=True, env=env, timeout=10,
                    )
                    self.assertEqual(invoked.returncode, 0, invoked.stderr)
                    self.assertIn("Validate a gc context bundle", invoked.stdout)

    def test_scripts_path_requires_an_absolute_complete_pack_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command_cases = (None, "relative", str(root / "missing"))
            for binding in command_cases:
                env = dict(os.environ)
                env.pop("GC_PACK_DIR", None)
                if binding is not None:
                    env["GC_PACK_DIR"] = binding
                with self.subTest(binding=binding):
                    result = subprocess.run(
                        [str(COMMAND), "scripts-path"], cwd=root, text=True,
                        capture_output=True, env=env, timeout=10,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")

            pack = root / "incomplete/gascity"
            (pack / "assets/scripts").mkdir(parents=True)
            env = dict(os.environ, GC_PACK_DIR=str(pack))
            result = subprocess.run(
                [str(COMMAND), "scripts-path"], cwd=root, text=True,
                capture_output=True, env=env, timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_scripts_path_rejects_unexpected_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "gascity"
            scripts = pack / "assets/scripts"
            scripts.mkdir(parents=True)
            schema = pack / "schemas/workspace/records.v1.json"
            schema.parent.mkdir(parents=True)
            shutil.copy2(REPO / "gascity/schemas/workspace/records.v1.json", schema)
            shutil.copy2(REPO / "gascity/assets/scripts/workspace_entry.py", scripts)
            env = dict(os.environ, GC_PACK_DIR=str(pack))
            for extra in ("extra", "--help", "../foreign"):
                with self.subTest(extra=extra):
                    result = subprocess.run(
                        [str(COMMAND), "scripts-path", extra], cwd=root, text=True,
                        capture_output=True, env=env, timeout=10,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
