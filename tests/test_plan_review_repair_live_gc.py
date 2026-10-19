"""Compile the actual default author/reviewer route with the native CLI."""
import json
import os
from pathlib import Path

import pytest

from gc_live_city import REPO_ROOT, gc_test_bin, run_gc, write_city  # noqa: F401


@pytest.fixture(scope="module")
def review_city(tmp_path_factory):
    # The shared harness uses a file-backed store and starts no controller.
    return write_city(tmp_path_factory.mktemp("plan-repair-route"), {"gc": REPO_ROOT / "gascity"})


@pytest.mark.parametrize("formula", ("build-base", "build-basic", "build-from-plan-base", "planning-base"))
@pytest.mark.parametrize("lifecycle", ("new", "legacy"))
@pytest.mark.parametrize("drain", ("separate", "same-session"))
def test_native_default_review_joins_distinct_author_and_reviewer(
    gc_test_bin: Path, review_city, formula, lifecycle, drain, record_property  # noqa: F811
):
    result = run_gc(gc_test_bin, review_city, "formula", "show", formula, "--json",
                    "--var", "worktree_lifecycle=" + lifecycle, "--var", "drain_policy=" + drain)
    if lifecycle == "legacy" and formula in ("build-base", "build-basic", "build-from-plan-base"):
        assert result.returncode == 1, result.stdout + result.stderr
        refusal = json.loads(result.stdout)
        assert refusal["schema_version"] == "1" and refusal["ok"] is False
        error = refusal["error"]
        assert error["code"] == "command_failed" and error["exit_code"] == 1
        assert ('variable "worktree_lifecycle": value "legacy" not in allowed values [new]'
                in error["message"])
        assert "steps" not in refusal and "deps" not in refusal
        record_property("native_legacy_refusal", json.dumps(refusal, sort_keys=True))
        return
    assert result.returncode == 0, result.stdout + result.stderr
    recipe = json.loads(result.stdout)
    assert recipe["ok"] is True and recipe["name"] == formula
    record_property("native_recipe", json.dumps(recipe, sort_keys=True))
    steps = {step["id"]: step for step in recipe["steps"]}
    prefix = formula + ".plan-review"
    logical = steps[prefix]
    assert logical["metadata"]["gc.kind"] == "ralph"
    assert logical["metadata"]["gc.max_attempts"] == "3"
    assert logical["metadata"]["gc.build.plan_review_required"] == "true"
    assert Path(logical["metadata"]["gc.check_path"]).resolve() == (
        REPO_ROOT / "gascity/assets/scripts/checks/plan-review-approved.py").resolve()
    scope = steps[prefix + ".iteration.1"]
    assert scope["metadata"]["gc.kind"] == "scope"
    assert scope["metadata"]["gc.control_for"] == "plan-review"
    author = steps[scope["id"] + ".author-repair"]
    reviewer = steps[scope["id"] + ".plan-review-verdict"]
    assert author["metadata"]["gc.run_target"] == "gc.design-author"
    assert reviewer["metadata"]["gc.run_target"] == "gc.review-synthesizer"
    for child in (author, reviewer):
        meta = child["metadata"]
        assert meta["gc.attempt"] == meta["gc.iteration"] == "1"
        assert meta["gc.scope_ref"] == "plan-review.iteration.1"
        assert meta["gc.on_fail"] == "abort_scope"
        assert meta["gc.scope_role"] == "member"
    deps = {}
    for dep in recipe["deps"]:
        if dep["type"] == "blocks":
            deps.setdefault(dep["step_id"], set()).add(dep["depends_on_id"])

    def ancestors(step):
        seen, todo = set(), list(deps.get(step, ()))
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(deps.get(current, ()))
        return seen

    assert author["id"] in ancestors(reviewer["id"])
    assert {author["id"], reviewer["id"]} <= ancestors(scope["id"])
    assert scope["id"] in ancestors(logical["id"])
    assert not any(step["id"].startswith(prefix + ".iteration.2") for step in recipe["steps"])


@pytest.mark.parametrize("formula,expected", (
    ("superpowers-build", {
        "design-review-approved.sh": ("requirements.superpowers-design-approval-loop",
                                      "requirements.superpowers-written-spec-loop",
                                      "plan-review.superpowers-plan-review-loop"),
        "implementation-review-approved.sh": ("review.superpowers-code-review-loop",),
        "build-artifact-valid.sh": ("requirements", "plan", "decompose", "review", "finalize"),
    }),
    ("superpowers-planning", {
        "design-review-approved.sh": ("requirements.superpowers-design-approval-loop",
                                      "requirements.superpowers-written-spec-loop",
                                      "plan-review.superpowers-plan-review-loop"),
        "build-artifact-valid.sh": ("requirements", "plan"),
    }),
    ("superpowers-decomposition", {"build-artifact-valid.sh": ("decompose",)}),
    ("superpowers-development", {
        "build-artifact-valid.sh": ("implement",),
        "implementation-review-approved.sh": ("task-review.superpowers-task-review-loop",),
    }),
    ("superpowers-development-item", {
        "build-artifact-valid.sh": ("implement-item",),
        "implementation-review-approved.sh": ("task-review.superpowers-task-review-loop",),
    }),
    ("superpowers-review", {
        "build-artifact-valid.sh": ("write-report",),
        "implementation-review-approved.sh": ("write-report.superpowers-code-review-loop",),
    }),
))
def test_native_superpowers_checks_resolve_imported_assets_and_control_identity(
    gc_test_bin: Path, tmp_path, formula, expected, record_property  # noqa: F811
):
    city = write_city(tmp_path, {"gc": REPO_ROOT / "gascity",
                                 "superpowers": REPO_ROOT / "superpowers"})
    assert not (city.rig_dir / ".gc/scripts").exists()
    command = run_gc(gc_test_bin, city, "gc", "workspace", "entry", "--help")
    assert command.returncode == 0, command.stdout + command.stderr
    assert "# Managed workspaces" in command.stdout
    assert "gc <binding> workspace <helper> <action> [arguments]" in command.stdout
    result = run_gc(gc_test_bin, city, "formula", "show", formula, "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    recipe = json.loads(result.stdout)
    assert recipe["ok"] is True and recipe["name"] == formula
    record_property("native_recipe", json.dumps(recipe, sort_keys=True))
    steps = {step["id"]: step for step in recipe["steps"]}
    for script, controls in expected.items():
        for control_ref in controls:
            control = steps[formula + "." + control_ref]
            meta = control["metadata"]
            assert meta["gc.kind"] == "ralph"
            check = Path(meta["gc.check_path"])
            assert check.is_absolute()
            assert check == (REPO_ROOT / "gascity/assets/scripts/checks" / script).resolve()
            assert os.access(check, os.X_OK)
            artifact = script == "build-artifact-valid.sh"
            assert meta["gc.max_attempts"] == ("3" if artifact else "6")
            assert meta["gc.check_timeout"] == ("5m" if artifact else "10m")
            iteration = steps[control["id"] + ".iteration.1"]
            assert iteration["id"] != control["id"]
            assert iteration["metadata"]["gc.control_for"] == meta["gc.step_id"] == control_ref
            if artifact:
                assert meta["gc.build.artifact_schema"].startswith("gc.build.")
                assert meta["gc.build.artifact_path_keys"]
