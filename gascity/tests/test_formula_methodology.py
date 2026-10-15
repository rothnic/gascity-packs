from __future__ import annotations

import contextlib
import copy
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "assets" / "scripts"
sys.path.insert(0, str(SCRIPTS))


class FormulaMethodologyTests(unittest.TestCase):
    def setUp(self):
        self.reader = importlib.import_module("formula_methodology")
        self.policy = {
            "allowed_drain_policies": ["separate", "same-session"],
            "implementation_strategy": "drain",
            "interaction_modes": ["interactive", "autonomous", "headless"],
            "review_modes": ["report", "agent", "interactive"],
        }
        self.recipe = {"schema_version": "1", "ok": True, "name": "build-basic",
                       "metadata": {"gc": {"methodology": self.policy}}, "steps": []}

    def invoke(self, output=None, *, returncode=0, error=None, formula="build-basic", selection=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess([], returncode,
            json.dumps(self.recipe) if output is None else output, "native read failed")
        with patch("workspace_run.subprocess.run", return_value=result, side_effect=error) as command, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            argv = ["--gc", "/selected/gc", "--city-root", "/selected/city",
                    "--rig", "selected-rig", "--formula", formula]
            if selection is not None:
                for flag, value in zip(("--interaction-mode", "--review-mode", "--drain-policy"), selection):
                    argv.extend((flag, value))
            code = self.reader.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), command

    def test_large_native_graph_is_projected_before_tool_output(self):
        self.recipe["steps"] = [{"id": "prepare", "description": "unrelated stage text " * 10000}]
        self.recipe["metadata"]["large_unrelated_metadata"] = "x" * 100000
        raw = json.dumps(self.recipe)
        self.assertGreater(len(raw), 50000)
        self.assertNotIn('"interaction_modes"', raw[-50000:])
        code, stdout, stderr, command = self.invoke(raw)
        self.assertEqual((code, stderr), (0, ""))
        self.assertLess(len(stdout.encode()), 1000)
        projected = json.loads(stdout)
        self.assertEqual(projected, {"name": "build-basic", "declared": True,
                                     "methodology": self.policy})
        self.assertEqual(command.call_args.args[0], ["/selected/gc", "--city", "/selected/city",
            "--rig", "selected-rig", "formula", "show", "build-basic", "--json"])
        self.assertTrue(command.call_args.kwargs["capture_output"])

    def test_projection_preserves_supported_and_unsupported_mode_subsets(self):
        for modes, expected in ((["headless"], True), (["interactive"], False)):
            with self.subTest(modes=modes):
                self.policy["interaction_modes"] = modes
                code, stdout, stderr, _ = self.invoke()
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual("headless" in json.loads(stdout)["methodology"]["interaction_modes"], expected)
        self.policy["implementation_strategy"] = "convoy-step"
        self.policy["allowed_drain_policies"] = []
        self.assertEqual(json.loads(self.invoke()[1])["methodology"], self.policy)
        self.policy["interaction_modes"] = ["headless"] * 10000
        code, stdout, stderr, _ = self.invoke()
        self.assertEqual((code, stderr), (0, ""))
        self.assertLess(len(stdout.encode()), 1000)
        self.assertEqual(json.loads(stdout)["methodology"]["interaction_modes"], ["headless"])

    def test_verified_absence_is_explicit_without_inventing_compatibility(self):
        for metadata in (None, {}, {"gc": {}}, {"other": "metadata"}):
            with self.subTest(metadata=metadata):
                value = copy.deepcopy(self.recipe)
                if metadata is None:
                    value.pop("metadata")
                else:
                    value["metadata"] = metadata
                code, stdout, stderr, _ = self.invoke(json.dumps(value))
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout), {"name": "build-basic", "declared": False})

    def test_malformed_or_unbound_native_result_is_unreadable(self):
        outputs = ["", "{}", "[]", json.dumps(self.recipe)[:-1],
                   json.dumps(self.recipe)[-50000:-1],
                   '{"schema_version":"1","ok":true,"name":"build-basic","name":"other"}',
                   json.dumps(dict(self.recipe, ok=False)),
                   json.dumps(dict(self.recipe, name="other")),
                   json.dumps(dict(self.recipe, schema_version="unknown"))]
        for raw in outputs:
            with self.subTest(raw=raw[:70]):
                code, stdout, stderr, _ = self.invoke(raw)
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("UNREADABLE", stderr)

    def test_present_invalid_metadata_cannot_be_reported_as_absent(self):
        metadata_values = [None, [], {"gc": None}, {"gc": []},
                           {"gc": {"methodology": None}}, {"gc": {"methodology": []}},
                           {"gc": {"methodology": {}}}]
        for field, malformed in (("interaction_modes", "headless"), ("review_modes", [True]),
                                  ("allowed_drain_policies", None), ("implementation_strategy", []),
                                  ("interaction_modes", ["unknown"])):
            policy = dict(self.policy, **{field: malformed})
            metadata_values.append({"gc": {"methodology": policy}})
        for metadata in metadata_values:
            with self.subTest(metadata=metadata):
                code, stdout, stderr, _ = self.invoke(json.dumps(dict(self.recipe, metadata=metadata)))
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("UNREADABLE", stderr)

    def test_cli_failure_missing_binary_and_timeout_are_unreadable(self):
        for kwargs in ({"returncode": 1}, {"error": OSError("missing gc")},
                       {"error": subprocess.TimeoutExpired("gc", 30)}):
            with self.subTest(kwargs=kwargs):
                code, stdout, stderr, _ = self.invoke(**kwargs)
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("UNREADABLE", stderr)

    def test_selected_supported_modes_are_decided_before_large_output_is_projected(self):
        self.recipe["steps"] = [{"id": "prepare", "description": "unrelated stage text " * 10000}]
        raw = json.dumps(self.recipe)
        self.assertNotIn('"interaction_modes"', raw[-50000:])
        for interaction in self.policy["interaction_modes"]:
            for review in self.policy["review_modes"]:
                for drain in self.policy["allowed_drain_policies"]:
                    with self.subTest(interaction=interaction, review=review, drain=drain):
                        code, stdout, stderr, command = self.invoke(raw, selection=(interaction, review, drain))
                        self.assertEqual((code, stderr), (0, ""))
                        self.assertEqual(json.loads(stdout)["selection"], {
                            "interaction_mode": interaction, "review_mode": review,
                            "drain_policy": drain, "supported": True})
                        self.assertLess(len(stdout.encode()), 1000)
                        self.assertEqual(command.call_count, 1)

    def test_selected_unsupported_modes_refuse_with_exact_native_subset_reason(self):
        for field, allowed, reason in (("interaction_modes", ["interactive"],
                                        "unsupported-interaction-mode:headless"),
                                       ("review_modes", ["report"], "unsupported-review-mode:agent"),
                                       ("allowed_drain_policies", [], "unsupported-drain-policy:separate")):
            with self.subTest(field=field):
                recipe = copy.deepcopy(self.recipe)
                recipe["metadata"]["gc"]["methodology"][field] = allowed
                code, stdout, stderr, command = self.invoke(json.dumps(recipe),
                                                          selection=("headless", "agent", "separate"))
                self.assertEqual((code, stderr), (2, ""))
                selection = json.loads(stdout)["selection"]
                self.assertIs(selection["supported"], False)
                self.assertEqual(selection["blocked_reason"], reason)
                self.assertEqual(command.call_count, 1)

    def test_selected_invalid_vocabulary_refuses_without_inventing_support(self):
        for selection, reason in ((("unknown", "agent", "separate"), "invalid-interaction-mode:unknown"),
                                  (("headless", "unknown", "separate"), "invalid-review-mode:unknown"),
                                  (("headless", "agent", ""), "invalid-drain-policy:")):
            with self.subTest(selection=selection):
                code, stdout, stderr, _ = self.invoke(selection=selection)
                self.assertEqual((code, stderr), (2, ""))
                self.assertEqual(json.loads(stdout)["selection"]["blocked_reason"], reason)
                self.assertIs(json.loads(stdout)["selection"]["supported"], False)

    def test_selected_absent_or_unreadable_declaration_cannot_invent_incompatibility(self):
        for output in (json.dumps(dict(self.recipe, metadata={})), "", json.dumps(self.recipe)[:-1]):
            with self.subTest(output=output[:60]):
                code, stdout, stderr, _ = self.invoke(output, selection=("headless", "agent", "separate"))
                self.assertEqual((code, stdout), (1, ""))
                self.assertIn("UNREADABLE", stderr)

    def test_selected_modes_must_be_supplied_together_before_native_read(self):
        for flags in (("--interaction-mode", "headless"), ("--review-mode", "agent"),
                      ("--drain-policy", "separate")):
            with self.subTest(flags=flags), patch.object(self.reader, "read_methodology") as read, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.reader.main(["--formula", "build-basic", "--city-root", "/selected/city", *flags])
            self.assertEqual(error.exception.code, 2)
            read.assert_not_called()

    def test_build_prepare_requires_the_selected_mode_decision(self):
        prepare = (SCRIPTS.parent / "workflows/build-base/prepare.md").read_text()
        command = prepare.split('formula_methodology.py" --formula "$RUNNING_FORMULA"', 1)[1].split("```", 1)[0]
        for flag, variable in (("--interaction-mode", "interaction_mode"),
                               ("--review-mode", "review_mode"), ("--drain-policy", "drain_policy")):
            self.assertIn(flag + ' "{{' + variable + '}}"', command)
        self.assertIn("selection.supported: true", prepare)
        self.assertIn("do not substitute a raw `gc formula show` call", prepare)
        self.assertNotIn("unsupported-interaction-mode:headless", prepare)


if __name__ == "__main__":
    unittest.main()
