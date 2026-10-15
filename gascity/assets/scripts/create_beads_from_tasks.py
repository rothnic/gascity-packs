#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workspace_records import RecordError

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


PAYLOAD_RE = re.compile(
    r"^## Bead Creation Payload\s*?\n```ya?ml\s*\n(?P<body>.*?)\n```",
    re.MULTILINE | re.DOTALL,
)
CREATED_RE = re.compile(r"^## Created Beads\s*?\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
FRONT_MATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
VALID_TYPES = {"feature", "bug", "task", "chore", "docs"}
VALID_PRIORITIES = {"0", "1", "2", "3", "4", "P0", "P1", "P2", "P3", "P4"}
LEGACY_WORK_OPTION_METADATA = {
    "gc.model": "opt_model",
    "gc.reasoning": "opt_effort",
    "gc.effort": "opt_effort",
}


class PlanError(Exception):
    pass


@dataclass
class Runnable:
    key: str
    title: str
    type: str
    priority: str
    description: str
    acceptance_criteria: list[str]
    parent_convoy: str
    dependencies: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Convoy:
    key: str
    title: str
    description: str
    parent_convoy: str = ""
    dependencies: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    target: str = ""
    convoy_keys: list[str] = field(default_factory=list)
    bead_keys: list[str] = field(default_factory=list)


@dataclass
class Plan:
    target_rig: str
    labels: list[str]
    convoys: list[Convoy]
    runnables: list[Runnable]
    sources: dict[str, Any] | None = None

    @property
    def items(self) -> list[Convoy | Runnable]:
        return [*self.convoys, *self.runnables]


class Runner:
    def __init__(self, city: str | None, rig: str, dry_run: bool) -> None:
        self.city = city
        self.rig = rig
        self.dry_run = dry_run
        self.seeded_convoy_members: dict[str, str] = {}

    def bd_base(self) -> list[str]:
        cmd = ["gc", "bd"]
        if self.city:
            cmd.extend(["--city", self.city])
        cmd.extend(["--rig", self.rig])
        return cmd

    def convoy_base(self) -> list[str]:
        cmd = ["gc", "convoy"]
        if self.city:
            cmd.extend(["--city", self.city])
        cmd.extend(["--rig", self.rig])
        return cmd

    def run_bd(self, args: list[str]) -> str:
        return self.run([*self.bd_base(), *args])

    def run_convoy(self, args: list[str]) -> str:
        return self.run([*self.convoy_base(), *args])

    def run(self, cmd: list[str]) -> str:
        if self.dry_run:
            print(shell_join(cmd))
            return ""
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise PlanError(f"command failed ({proc.returncode}): {shell_join(cmd)}\n{stderr}")
        return proc.stdout


class WorkspaceRunner(Runner):
    """Explicit native allocation route for a previously captured build run."""
    def __init__(self, store, state: dict, claimed_step_id: str, dry_run: bool):
        super().__init__(store.cwd, state["rig_name"], dry_run)
        self.store, self.state, self.claimed_step_id = store, state, claimed_step_id
        self.created_convoys: set[str] = set()
        self.creation_edges: set[tuple[str, str]] = set()
        self.checkpoint = lambda key, mappings: None

    def bd_base(self) -> list[str]:
        command = [self.store.gc, "--city", self.store.cwd]
        if self.store.store_ref.startswith("rig:"):
            command += ["--rig", self.store.store_ref.split(":", 1)[1]]
        return [*command, "bd"]

    def convoy_base(self) -> list[str]:
        return [*self.bd_base()[:-1], "convoy"]

    def run(self, cmd: list[str]) -> str:
        if self.dry_run:
            print(shell_join(cmd))
            return ""
        from workspace_store import ROUTING_ENV
        import os
        environment = {key: value for key, value in os.environ.items() if key not in ROUTING_ENV}
        try:
            result = subprocess.run(cmd, text=True, encoding="utf-8", errors="strict",
                capture_output=True, check=False, timeout=30, cwd=self.store.cwd, env=environment)
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            raise PlanError("native operation outcome is uncertain; inspect the original response before retrying creation") from exc
        if result.returncode:
            raise PlanError(f"native operation failed ({result.returncode}): {result.stderr.strip()[-1000:]}")
        return result.stdout

    def membership(self) -> dict[str, str]:
        return {"gc.root_bead_id": self.state["workflow_root_id"], "gc.root_store_ref": self.store.store_ref,
            "gc.source_root_id": self.state["workflow_root_id"], "gc.source_generation": str(self.state["generation"]),
            "gc.source_plan_owner_id": self.claimed_step_id}

    def verify_existing(self, bead_id: str, *, key: str, kind: str) -> None:
        if self.dry_run:
            return
        row = self.store.snapshot([bead_id])[bead_id]
        expected = {**self.membership(), "gc.plan.key": key, "gc.plan.kind": kind}
        if any(row["metadata"].get(name) != value for name, value in expected.items()):
            raise PlanError(f"{bead_id}: artifact mapping has no matching native run/generation binding; migrate explicitly")
        if kind == "convoy" and row["type"] != "convoy":
            raise PlanError(f"{bead_id}: native allocation is not a convoy")
        if kind == "bead" and (row["status"] not in ("deferred", "open") or row["assignee"]):
            raise PlanError(f"{bead_id}: reused expansion member has already started or completed")


def shell_join(args: list[str]) -> str:
    import shlex

    return " ".join(shlex.quote(arg) for arg in args)


def require_yaml() -> None:
    if yaml is None:
        raise PlanError("PyYAML is required to parse tasks.md")


def extract_payload(markdown: str) -> dict[str, Any]:
    require_yaml()
    match = PAYLOAD_RE.search(markdown)
    if not match:
        raise PlanError("missing ## Bead Creation Payload fenced yaml block")
    try:
        payload = yaml.safe_load(match.group("body"))
    except Exception as exc:
        raise PlanError(f"invalid YAML payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanError("bead creation payload must be a YAML mapping")
    return payload


def string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlanError(f"{field_name} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PlanError(f"{field_name} must contain only non-empty strings")
        out.append(item.strip())
    return out


def metadata_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PlanError(f"{field_name} must be a mapping")
    out: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(key, str) or not key.strip():
            raise PlanError(f"{field_name} keys must be non-empty strings")
        raw_key = key.strip()
        normalized_key = LEGACY_WORK_OPTION_METADATA.get(raw_key, raw_key)
        if raw_key in LEGACY_WORK_OPTION_METADATA and normalized_key in out:
            continue
        out[normalized_key] = str(val)
    return out


def required_string(raw: dict[str, Any], field_name: str, item_name: str) -> str:
    value = raw.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{item_name}: missing required string field {field_name}")
    return value.strip()


def parse_runnable(
    raw: Any,
    index: int,
    *,
    parent_convoy: str,
    inherited_labels: list[str],
    inherited_metadata: dict[str, str],
) -> Runnable:
    name = f"beads[{index}]"
    if not isinstance(raw, dict):
        raise PlanError(f"{name} must be a mapping")
    key = required_string(raw, "key", name)
    item_type = str(raw.get("type", "")).strip()
    if item_type not in VALID_TYPES:
        raise PlanError(f"{key}: unsupported type {item_type!r}")
    priority = str(raw.get("priority", "2")).strip()
    if priority not in VALID_PRIORITIES:
        raise PlanError(f"{key}: priority must be 0-4 or P0-P4")
    metadata = {**inherited_metadata, **metadata_map(raw.get("metadata"), f"{key}.metadata")}
    return Runnable(
        key=key,
        title=required_string(raw, "title", key),
        type=item_type,
        priority=priority,
        description=required_string(raw, "description", key),
        acceptance_criteria=string_list(raw.get("acceptance_criteria"), f"{key}.acceptance_criteria"),
        parent_convoy=parent_convoy,
        dependencies=string_list(raw.get("dependencies"), f"{key}.dependencies"),
        labels=[*inherited_labels, *string_list(raw.get("labels"), f"{key}.labels")],
        files=string_list(raw.get("files"), f"{key}.files"),
        verification=string_list(raw.get("verification"), f"{key}.verification"),
        metadata=metadata,
    )


def parse_convoy(
    raw: Any,
    index: int,
    *,
    parent_convoy: str,
    plan: Plan,
    inherited_labels: list[str],
    inherited_metadata: dict[str, str],
    inherited_target: str,
) -> None:
    name = f"convoys[{index}]"
    if not isinstance(raw, dict):
        raise PlanError(f"{name} must be a mapping")
    key = required_string(raw, "key", name)
    labels = [*inherited_labels, *string_list(raw.get("labels"), f"{key}.labels")]
    metadata = {**inherited_metadata, **metadata_map(raw.get("metadata"), f"{key}.metadata")}
    target = str(raw.get("target", inherited_target)).strip()
    convoy = Convoy(
        key=key,
        title=required_string(raw, "title", key),
        description=required_string(raw, "description", key),
        parent_convoy=parent_convoy,
        dependencies=string_list(raw.get("dependencies"), f"{key}.dependencies"),
        labels=labels,
        metadata=metadata,
        target=target,
    )
    plan.convoys.append(convoy)

    for child_index, child in enumerate(raw.get("convoys") or []):
        if not isinstance(child, dict):
            raise PlanError(f"{key}.convoys[{child_index}] must be a mapping")
        child_key = required_string(child, "key", f"{key}.convoys[{child_index}]")
        parse_convoy(
            child,
            child_index,
            parent_convoy=key,
            plan=plan,
            inherited_labels=labels,
            inherited_metadata=metadata,
            inherited_target=target,
        )
        convoy.convoy_keys.append(child_key)

    raw_beads = raw.get("beads") or []
    if not isinstance(raw_beads, list):
        raise PlanError(f"{key}.beads must be a list")
    for bead_index, bead in enumerate(raw_beads):
        runnable = parse_runnable(
            bead,
            bead_index,
            parent_convoy=key,
            inherited_labels=labels,
            inherited_metadata=metadata,
        )
        plan.runnables.append(runnable)
        convoy.bead_keys.append(runnable.key)


def parse_plan(payload: dict[str, Any]) -> Plan:
    target_rig = str(payload.get("target_rig", "")).strip()
    if not target_rig:
        raise PlanError("target_rig is required")
    if "epics" in payload:
        raise PlanError("epics[] is not supported; use nested convoys[]")
    raw_convoys = payload.get("convoys") or []
    raw_beads = payload.get("beads") or []
    if not isinstance(raw_convoys, list):
        raise PlanError("convoys must be a list")
    if not isinstance(raw_beads, list):
        raise PlanError("beads must be a list")
    plan = Plan(target_rig=target_rig, labels=string_list(payload.get("labels"), "labels"), convoys=[], runnables=[])
    for index, raw in enumerate(raw_convoys):
        parse_convoy(
            raw,
            index,
            parent_convoy="",
            plan=plan,
            inherited_labels=plan.labels,
            inherited_metadata={},
            inherited_target="",
        )
    for index, raw in enumerate(raw_beads):
        plan.runnables.append(
            parse_runnable(
                raw,
                index,
                parent_convoy="",
                inherited_labels=plan.labels,
                inherited_metadata={},
            )
        )
    if not plan.runnables:
        raise PlanError("beads must contain at least one runnable item, directly or inside convoys")
    validate_plan(plan)
    if "sources" in payload:
        expand_sources(plan, payload["sources"])
        validate_plan(plan)
    return plan


def expand_sources(plan: Plan, raw: Any) -> None:
    """Expand explicit ordered source edges; scheduler edges remain independent."""
    if not isinstance(raw, dict) or set(raw) != {"nodes", "terminal"} or not isinstance(raw["nodes"], list) or not raw["nodes"]:
        raise PlanError("sources requires nonempty nodes and one terminal")
    by_key = {item.key: item for item in plan.runnables}
    all_keys = {item.key for item in plan.items}
    owners, members, expanded = {}, {}, []
    for original in raw["nodes"]:
        if not isinstance(original, dict) or set(original) - {"owner", "strategy", "members", "predecessors", "single_lane"}:
            raise PlanError("source nodes require explicit owner, strategy, members and ordered predecessors")
        owner = required_string(original, "owner", "source node")
        strategy = required_string(original, "strategy", owner)
        node_members = string_list(original.get("members"), owner + ".members")
        predecessors = string_list(original.get("predecessors"), owner + ".predecessors")
        single_lane = original.get("single_lane", strategy == "shared-chain")
        if owner in owners or not node_members or len(set(node_members)) != len(node_members) or len(set(predecessors)) != len(predecessors):
            raise PlanError(f"{owner}: source owner, members and predecessors must be unique")
        if owner not in all_keys or any(key not in by_key or key in members for key in node_members):
            raise PlanError(f"{owner}: source owner/member is missing or belongs to multiple owners")
        if strategy not in {"isolated", "dependent", "shared-chain", "integration"} or type(single_lane) is not bool:
            raise PlanError(f"{owner}: unsupported source strategy or single_lane")
        if strategy == "isolated" and (len(node_members) != 1 or predecessors):
            raise PlanError(f"{owner}: isolated source has one member and no predecessors")
        if strategy in {"dependent", "integration"} and len(node_members) != 1:
            raise PlanError(f"{owner}: {strategy} source requires one member")
        if strategy == "dependent" and not predecessors or strategy == "integration" and len(predecessors) < 2:
            raise PlanError(f"{owner}: source strategy has the wrong number of predecessors")
        if strategy == "shared-chain" and single_lane is not True:
            raise PlanError(f"{owner}: shared-chain requires one native execution lane")
        node = {"owner": owner, "strategy": strategy, "members": node_members,
                "predecessors": predecessors, "single_lane": single_lane}
        owners[owner] = node
        members.update({key: owner for key in node_members})
        expanded.append(node)
    if any(owner in members and members[owner] != owner for owner in owners):
        raise PlanError("a source owner cannot be another owner's member")
    for node in expanded:
        if any(key not in owners or key == node["owner"] for key in node["predecessors"]):
            raise PlanError(f"{node['owner']}: unknown or self source predecessor")
    # Check the original graph before creating any task or changing scheduling.
    _validate_source_graph(expanded, raw["terminal"])
    output = []
    for node in expanded:
        if len(node["predecessors"]) > 1 and node["strategy"] != "integration":
            key = node["owner"] + "-inputs"
            if key in all_keys:
                raise PlanError(f"generated integration key already exists: {key}")
            first = by_key[node["members"][0]]
            predecessors = list(node["predecessors"])
            integration = Runnable(key=key, title="Integrate inputs for " + first.title, type="task", priority=first.priority,
                description="Integrate the declared accepted source outputs in their recorded order. Run project checks and independent review against the exact merged commit before accepting it.",
                acceptance_criteria=["Every declared predecessor has a current accepted output.",
                    "The integrated commit includes each accepted input and passes project checks and independent review."],
                parent_convoy=first.parent_convoy, labels=list(first.labels),
                dependencies=[owners[p]["members"][-1] for p in predecessors],
                metadata={"gc.source.role": "integration"})
            plan.runnables.append(integration)
            by_key[key] = integration
            all_keys.add(key)
            if first.parent_convoy:
                next(convoy for convoy in plan.convoys if convoy.key == first.parent_convoy).bead_keys.append(key)
            output.append({"owner": key, "strategy": "integration", "members": [key],
                           "predecessors": predecessors, "single_lane": False})
            node = dict(node, predecessors=[key])
        output.append(node)
    _validate_source_graph(output, raw["terminal"])
    nodes = {node["owner"]: node for node in output}
    # Source dependencies require scheduler waiting. The reverse implication
    # is deliberately absent: ordinary control dependencies transfer no code.
    for node in output:
        first = by_key[node["members"][0]]
        first.dependencies = list(dict.fromkeys([*first.dependencies,
            *(nodes[key]["members"][-1] for key in node["predecessors"])]))
        for prior, current in zip(node["members"], node["members"][1:]):
            by_key[current].dependencies = list(dict.fromkeys([*by_key[current].dependencies, prior]))
    plan.sources = {"nodes": output, "terminal": raw["terminal"]}


def _validate_source_graph(nodes: list[dict], terminal: Any) -> None:
    owners = {node["owner"]: node for node in nodes}
    remaining, successors = {}, {key: [] for key in owners}
    for node in nodes:
        remaining[node["owner"]] = len(node["predecessors"])
        for predecessor in node["predecessors"]:
            if predecessor not in owners or predecessor == node["owner"]:
                raise PlanError("source predecessor is missing or self-referential")
            successors[predecessor].append(node["owner"])
    ready = [key for key in owners if remaining[key] == 0]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for child in successors[key]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    if visited != len(owners):
        raise PlanError("source graph contains a cycle")
    if [key for key in owners if not successors[key]] != [terminal]:
        raise PlanError("all source owners must reach one declared terminal")


def physical_source_plan(plan: Plan, mappings: dict[str, str], run: dict[str, Any], *,
                         writer_step_id: str, generation: int = 1,
                         canonical: dict[str, Any] | None = None) -> dict[str, Any]:
    from workspace_source_plan import source_order
    if plan.sources is None:
        raise PlanError("new lifecycle requires explicit ordered sources; scheduler dependencies are insufficient")
    if generation > 1 and canonical is None:
        raise PlanError("fix generation requires the exact current canonical parent")
    result = {"version": 1, "workflow_root_id": run["workflow_root_id"], "generation": generation,
        "writer_step_id": writer_step_id, "source_plan_owner_id": writer_step_id,
        "base_oid": run["base_oid"] if generation == 1 else canonical["output_oid"],
        "parent_canonical_generation": None if generation == 1 else canonical["generation"],
        "parent_canonical_oid": None if generation == 1 else canonical["output_oid"],
        "nodes": [{"owner_id": mappings[node["owner"]], "strategy": node["strategy"],
            "member_ids": [mappings[key] for key in node["members"]],
            "source_predecessor_owner_ids": [mappings[key] for key in node["predecessors"]],
            "single_lane": node["single_lane"]} for node in plan.sources["nodes"]],
        "terminal_owner_id": mappings[plan.sources["terminal"]]}
    source_order(result)
    return result


def validate_plan(plan: Plan) -> None:
    by_key: dict[str, Convoy | Runnable] = {}
    for item in plan.items:
        if item.key in by_key:
            raise PlanError(f"duplicate key {item.key!r}")
        by_key[item.key] = item
    for item in plan.items:
        for dep in item.dependencies:
            if dep not in by_key:
                raise PlanError(f"{item.key}: unknown dependency {dep!r}")
    for convoy in plan.convoys:
        if not convoy.convoy_keys and not convoy.bead_keys:
            raise PlanError(f"{convoy.key}: convoy must contain at least one bead or nested convoy")
    topo_order(plan.runnables, expanded_dependency_edges(plan))


def descendants(plan: Plan, convoy_key: str) -> set[str]:
    result: set[str] = set()
    for convoy in plan.convoys:
        if convoy.parent_convoy == convoy_key:
            result.add(convoy.key)
            result.update(descendants(plan, convoy.key))
    for runnable in plan.runnables:
        if runnable.parent_convoy == convoy_key:
            result.add(runnable.key)
    return result


def runnable_descendants(plan: Plan, key: str) -> list[str]:
    item = item_map(plan)[key]
    if isinstance(item, Runnable):
        return [key]
    nested = descendants(plan, key)
    return [runnable.key for runnable in plan.runnables if runnable.key in nested]


def root_runnables(plan: Plan, key: str) -> list[str]:
    runnable_keys = set(runnable_descendants(plan, key))
    edges = explicit_runnable_edges(plan)
    blocked = {child for child, dep in edges if child in runnable_keys and dep in runnable_keys}
    return [runnable.key for runnable in plan.runnables if runnable.key in runnable_keys and runnable.key not in blocked]


def terminal_runnables(plan: Plan, key: str) -> list[str]:
    runnable_keys = set(runnable_descendants(plan, key))
    edges = explicit_runnable_edges(plan)
    predecessors = {dep for child, dep in edges if child in runnable_keys and dep in runnable_keys}
    return [runnable.key for runnable in plan.runnables if runnable.key in runnable_keys and runnable.key not in predecessors]


def item_map(plan: Plan) -> dict[str, Convoy | Runnable]:
    return {item.key: item for item in plan.items}


def explicit_runnable_edges(plan: Plan) -> set[tuple[str, str]]:
    by_key = item_map(plan)
    edges: set[tuple[str, str]] = set()
    for runnable in plan.runnables:
        for dep in runnable.dependencies:
            dep_item = by_key[dep]
            if isinstance(dep_item, Runnable):
                edges.add((runnable.key, dep))
    return edges


def expanded_dependency_edges(plan: Plan) -> set[tuple[str, str]]:
    by_key = item_map(plan)
    edges = explicit_runnable_edges(plan)

    def add_expanded(dependent_key: str, dependency_key: str) -> None:
        dependent = by_key[dependent_key]
        dependency = by_key[dependency_key]
        dependent_roots = [dependent.key] if isinstance(dependent, Runnable) else root_runnables(plan, dependent.key)
        dependency_terms = [dependency.key] if isinstance(dependency, Runnable) else terminal_runnables(plan, dependency.key)
        for child in dependent_roots:
            for dep in dependency_terms:
                if child != dep:
                    edges.add((child, dep))

    for item in plan.items:
        for dep in item.dependencies:
            add_expanded(item.key, dep)
    return edges


def topo_order(items: list[Runnable], edges: set[tuple[str, str]] | None = None) -> list[Runnable]:
    by_key = {item.key: item for item in items}
    ordered: list[Runnable] = []
    temporary: set[str] = set()
    permanent: set[str] = set()
    edges = edges or explicit_edges_for_items(items)

    def visit(key: str) -> None:
        if key in permanent:
            return
        if key in temporary:
            raise PlanError(f"dependency cycle involving {key!r}")
        temporary.add(key)
        for child, dep in sorted(edges):
            if child == key and dep in by_key:
                visit(dep)
        temporary.remove(key)
        permanent.add(key)
        ordered.append(by_key[key])

    for item in items:
        visit(item.key)
    return ordered


def explicit_edges_for_items(items: list[Runnable]) -> set[tuple[str, str]]:
    keys = {item.key for item in items}
    return {(item.key, dep) for item in items for dep in item.dependencies if dep in keys}


def front_matter_status(markdown: str) -> str:
    require_yaml()
    match = FRONT_MATTER_RE.match(markdown)
    if not match:
        return ""
    data = yaml.load(match.group("body"), Loader=yaml.BaseLoader) or {}
    if not isinstance(data, dict):
        return ""
    return str(data.get("status", "")).strip()


def update_front_matter(markdown: str, updates: dict[str, str]) -> str:
    require_yaml()
    match = FRONT_MATTER_RE.match(markdown)
    if not match:
        return markdown
    data = yaml.load(match.group("body"), Loader=yaml.BaseLoader) or {}
    if not isinstance(data, dict):
        data = {}
    data.update(updates)
    rendered = yaml.safe_dump(data, sort_keys=False).strip()
    return f"---\n{rendered}\n---\n" + markdown[match.end() :]


def parse_created_mappings(markdown: str) -> dict[str, str]:
    match = CREATED_RE.search(markdown)
    if not match:
        return {}
    mappings: dict[str, str] = {}
    for line in match.group(0).splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"Key", "---"}:
            continue
        if len(cells) >= 4 and cells[0] and cells[2]:
            mappings[cells[0]] = cells[2]
        elif len(cells) >= 2 and cells[0] and cells[1]:
            mappings[cells[0]] = cells[1]
    return mappings


def render_created_section(plan: Plan, mappings: dict[str, str]) -> str:
    titles = {item.key: item.title for item in plan.items}
    kinds = {convoy.key: "convoy" for convoy in plan.convoys}
    kinds.update({runnable.key: "bead" for runnable in plan.runnables})
    ordered_keys = [item.key for item in [*plan.convoys, *plan.runnables] if item.key in mappings]
    lines = [
        "## Created Beads",
        "",
        "| Key | Kind | Bead ID | Title |",
        "|---|---|---|---|",
    ]
    for key in ordered_keys:
        lines.append(f"| {key} | {kinds[key]} | {mappings[key]} | {titles.get(key, '')} |")
    return "\n".join(lines) + "\n"


def update_created_section(markdown: str, plan: Plan, mappings: dict[str, str], status: str) -> str:
    section = render_created_section(plan, mappings)
    if CREATED_RE.search(markdown):
        markdown = CREATED_RE.sub(section, markdown)
    else:
        markdown = markdown.rstrip() + "\n\n" + section
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    updates = {"status": status, "updated_at": now}
    if status == "created":
        updates["created_beads_at"] = now
    return update_front_matter(markdown, updates)


def build_description(item: Runnable) -> str:
    parts = [item.description]
    if item.files:
        parts.append("Suggested files/modules:\n" + "\n".join(f"- {path}" for path in item.files))
    if item.verification:
        parts.append("Verification:\n" + "\n".join(f"- {check}" for check in item.verification))
    return "\n\n".join(parts)


def parse_create_output(output: str) -> str:
    start = output.find("{")
    if start < 0:
        raise PlanError(f"create output did not contain JSON: {output!r}")
    try:
        data, _ = json.JSONDecoder().raw_decode(output[start:])
    except json.JSONDecodeError as exc:
        raise PlanError(f"create output did not contain valid JSON: {output!r}") from exc
    if not isinstance(data, dict):
        raise PlanError(f"create JSON was not an object: {output!r}")
    bead_id = str(data.get("id") or data.get("bead_id") or data.get("convoy_id") or "").strip()
    if not bead_id:
        raise PlanError(f"create JSON missing id: {output!r}")
    return bead_id


def parse_native_create_output(output: str, *, convoy: bool = False) -> str:
    try:
        response = json.loads(output)
    except ValueError as exc:
        raise PlanError("native create acknowledgement is malformed; inspect the original outcome before retrying") from exc
    field = "convoy_id" if convoy else "id"
    if not isinstance(response, dict) or not isinstance(response.get(field), str) \
            or not response[field] or response[field].strip() != response[field]:
        raise PlanError("native create returned no exact physical ID; inspect the original outcome before retrying")
    if convoy and (response.get("schema_version") != "1" or response.get("ok") is not True
                   or response.get("command") != "convoy.create"):
        raise PlanError("native convoy acknowledgement does not confirm creation; inspect the original outcome")
    return response[field]


def create_runnable(runner: Runner, item: Runnable, mappings: dict[str, str]) -> str:
    if item.key in mappings:
        if isinstance(runner, WorkspaceRunner):
            runner.verify_existing(mappings[item.key], key=item.key, kind="bead")
        else:
            runner.run_bd(["show", mappings[item.key], "--json"])
        return mappings[item.key]
    metadata = {"gc.plan.key": item.key, "gc.plan.kind": "bead"}
    if item.parent_convoy:
        metadata["gc.plan.parent_convoy"] = item.parent_convoy
    metadata.update(item.metadata)
    if isinstance(runner, WorkspaceRunner):
        if any(key in item.metadata and item.metadata[key] != value for key, value in runner.membership().items()):
            raise PlanError(f"{item.key}: supplied metadata conflicts with captured source membership")
        metadata.update(runner.membership())
    args = [
        "create",
        "--json",
        item.title,
        "-t",
        item.type,
        "-p",
        item.priority,
        "--description",
        build_description(item),
        "--acceptance",
        "\n".join(f"- {criterion}" for criterion in item.acceptance_criteria),
        "--metadata",
        json.dumps(metadata, sort_keys=True),
    ]
    if item.labels:
        args.extend(["--labels", ",".join(dict.fromkeys(item.labels))])
    if isinstance(runner, WorkspaceRunner):
        args += ["--parent", runner.state["workflow_root_id"], "--no-inherit-labels", "--status", "open", "--assignee", ""]
        dependencies = [mappings[key] for child, key in sorted(runner.creation_edges) if child == item.key]
        if dependencies:
            args += ["--deps", ",".join(dependencies)]
    if isinstance(runner, WorkspaceRunner) and not runner.dry_run:
        runner.checkpoint(item.key, mappings)
    output = runner.run_bd(args)
    if runner.dry_run:
        return f"<{item.key}>"
    bead_id = parse_native_create_output(output) if isinstance(runner, WorkspaceRunner) else parse_create_output(output)
    mappings[item.key] = bead_id
    if isinstance(runner, WorkspaceRunner):
        runner.verify_existing(bead_id, key=item.key, kind="bead")
        runner.checkpoint("", mappings)
    return bead_id


def create_convoy(runner: Runner, convoy: Convoy, mappings: dict[str, str]) -> str:
    member_keys = [*convoy.convoy_keys, *convoy.bead_keys]
    if convoy.key in mappings:
        if isinstance(runner, WorkspaceRunner):
            runner.verify_existing(mappings[convoy.key], key=convoy.key, kind="convoy")
        else:
            runner.run_bd(["show", mappings[convoy.key], "--json"])
        if member_keys:
            runner.seeded_convoy_members[convoy.key] = member_keys[0]
        if not isinstance(runner, WorkspaceRunner):
            update_convoy_metadata(runner, convoy, mappings[convoy.key])
        return mappings[convoy.key]
    if not member_keys:
        raise PlanError(f"{convoy.key}: convoy must contain at least one bead or nested convoy")
    args = ["create", "--json"]
    if convoy.target:
        args.extend(["--target", convoy.target])
    args.append(convoy.title)
    seed_key = member_keys[0]
    if isinstance(runner, WorkspaceRunner):
        args.extend(mappings[key] for key in member_keys)
    else:
        args.append(mappings[seed_key])
    if isinstance(runner, WorkspaceRunner) and not runner.dry_run:
        runner.checkpoint(convoy.key, mappings)
    output = runner.run_convoy(args)
    convoy_id = f"<{convoy.key}>" if runner.dry_run else (parse_native_create_output(output, convoy=True)
        if isinstance(runner, WorkspaceRunner) else parse_create_output(output))
    mappings[convoy.key] = convoy_id
    runner.seeded_convoy_members[convoy.key] = seed_key
    if isinstance(runner, WorkspaceRunner):
        runner.created_convoys.add(convoy.key)
    update_convoy_metadata(runner, convoy, convoy_id)
    if isinstance(runner, WorkspaceRunner) and not runner.dry_run:
        runner.verify_existing(convoy_id, key=convoy.key, kind="convoy")
        runner.checkpoint("", mappings)
    return convoy_id


def update_convoy_metadata(runner: Runner, convoy: Convoy, convoy_id: str) -> None:
    metadata = {
        "gc.plan.key": convoy.key,
        "gc.plan.kind": "convoy",
        **convoy.metadata,
    }
    if convoy.parent_convoy:
        metadata["gc.plan.parent_convoy"] = convoy.parent_convoy
    if isinstance(runner, WorkspaceRunner):
        if any(key in convoy.metadata and convoy.metadata[key] != value for key, value in runner.membership().items()):
            raise PlanError(f"{convoy.key}: convoy metadata conflicts with captured source membership")
        metadata.update(runner.membership())
    runner.run_bd(["update", convoy_id, "--metadata", json.dumps(metadata, sort_keys=True)])


def link_memberships(runner: Runner, plan: Plan, mappings: dict[str, str]) -> None:
    for convoy in plan.convoys:
        if isinstance(runner, WorkspaceRunner) and convoy.key in runner.created_convoys:
            continue  # Native create linked all members in the same command.
        convoy_id = mappings[convoy.key]
        seeded_key = runner.seeded_convoy_members.get(convoy.key)
        existing_member_ids = existing_convoy_members(runner, convoy_id)
        for key in [*convoy.convoy_keys, *convoy.bead_keys]:
            if key == seeded_key:
                continue
            member_id = mappings[key]
            if member_id in existing_member_ids:
                continue
            runner.run_convoy(["add", convoy_id, member_id])
            existing_member_ids.add(member_id)


def existing_convoy_members(runner: Runner, convoy_id: str) -> set[str]:
    if runner.dry_run:
        return set()
    output = runner.run_bd(["dep", "list", convoy_id, "--type", "tracks", "--json"])
    try:
        deps = json.loads(output)
    except json.JSONDecodeError:
        if isinstance(runner, WorkspaceRunner):
            raise PlanError("native convoy membership response is malformed")
        return set()
    if not isinstance(deps, list):
        if isinstance(runner, WorkspaceRunner):
            raise PlanError("native convoy membership response is not a list")
        return set()
    member_ids: set[str] = set()
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        dep_type = str(dep.get("type") or dep.get("dependency_type") or "").strip()
        if dep_type and dep_type != "tracks":
            continue
        dep_id = str(dep.get("depends_on_id") or "").strip()
        if not dep_id:
            dep_id = str(dep.get("target_id") or dep.get("to_id") or dep.get("issue_id") or dep.get("id") or "").strip()
        if dep_id:
            member_ids.add(dep_id)
    return member_ids


def dependency_exists(runner: Runner, issue_id: str, depends_on_id: str) -> bool:
    output = runner.run_bd(["dep", "list", issue_id, "--json"])
    if runner.dry_run:
        return False
    try:
        deps = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(deps, list):
        return False
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        dep_id = str(dep.get("depends_on_id") or dep.get("id") or "").strip()
        dep_type = str(dep.get("type") or dep.get("dependency_type") or "blocks").strip()
        if dep_id == depends_on_id and dep_type == "blocks":
            return True
    return False


def add_dependencies(runner: Runner, plan: Plan, mappings: dict[str, str]) -> None:
    for child_key, dep_key in sorted(expanded_dependency_edges(plan)):
        issue_id = mappings[child_key]
        depends_on_id = mappings[dep_key]
        if dependency_exists(runner, issue_id, depends_on_id):
            continue
        runner.run_bd(["dep", "add", issue_id, depends_on_id])


def create_from_tasks(path: Path, *, city: str | None, dry_run: bool, force: bool,
                      workspace: dict[str, Any] | None = None) -> int:
    markdown = path.read_text(encoding="utf-8")
    if front_matter_status(markdown) == "created" and not force:
        raise PlanError("tasks.md already has status: created; pass --force to rerun")
    plan = parse_plan(extract_payload(markdown))
    if workspace is not None and plan.sources is None:
        raise PlanError("new lifecycle requires explicit ordered sources before native expansion")
    if workspace is not None:
        if not dry_run:
            from workspace_requests import require_resolved_scope
            if not workspace.get("evidence_dir"):
                raise PlanError("new source expansion requires its existing evidence directory")
            require_resolved_scope(workspace["store"], {
                "workflow_root_id": workspace["state"]["workflow_root_id"],
                "generation": workspace["state"]["generation"],
                "writer_scope_id": workspace["attempt"].claimed_bead_id, "record_kind": "source-plan"})
        if any(item.key not in {member for node in plan.sources["nodes"] for member in node["members"]} for item in plan.runnables):
            raise PlanError("every new-mode runnable must belong to a declared source owner; control work belongs in the workflow graph")
        if not plan.convoys:
            convoy = Convoy(key="implementation", title="Implementation work", description="Declared source work for this build.",
                            bead_keys=[item.key for item in plan.runnables])
            if any(item.key == convoy.key for item in plan.items):
                raise PlanError("generated implementation convoy key already exists")
            plan.convoys.append(convoy)
            for item in plan.runnables:
                item.parent_convoy = convoy.key
    ordered_runnables = topo_order(plan.runnables, expanded_dependency_edges(plan))
    mappings = parse_created_mappings(markdown)
    runner = WorkspaceRunner(workspace["store"], workspace["state"], workspace["attempt"].claimed_bead_id, dry_run) if workspace else Runner(city, plan.target_rig, dry_run)
    if workspace:
        if plan.target_rig != workspace["state"]["rig_name"]:
            raise PlanError("task plan target rig differs from captured native rig")
        runner.creation_edges = expanded_dependency_edges(plan)
        if not dry_run:
            from workspace_cooked import read_cooked_writer_map
            writer_map, writer_rows = read_cooked_writer_map(workspace["store"],
                workflow_root_id=workspace["state"]["workflow_root_id"], claimed_step_id=workspace["attempt"].claimed_bead_id)
            workspace["writer_map"], workspace["writer_rows"] = writer_map, writer_rows
        front = FRONT_MATTER_RE.match(markdown)
        data = yaml.safe_load(front.group("body")) if front else {}
        pending = (data or {}).get("native_allocation_pending")
        if pending and pending not in mappings:
            raise PlanError(f"previous native creation for {pending!r} is uncertain; inspect its original response and record the exact native ID before retrying")
        if not dry_run:
            def checkpoint(key, retained):
                text = update_created_section(markdown, plan, retained, "partial")
                path.write_text(update_front_matter(text, {"native_allocation_pending": key}), encoding="utf-8")
            runner.checkpoint = checkpoint

    if dry_run:
        print(f"# target rig: {plan.target_rig}")
    try:
        for item in ordered_runnables:
            mappings.setdefault(item.key, create_runnable(runner, item, mappings))
        for convoy in reversed(plan.convoys):
            mappings.setdefault(convoy.key, create_convoy(runner, convoy, mappings))
        link_memberships(runner, plan, mappings)
        add_dependencies(runner, plan, mappings)
        if workspace and not dry_run:
            publish_source_expansion(runner, plan, mappings, workspace)
    except Exception:
        if not dry_run and mappings:
            # Preserve any pending-create marker written before the command.
            current = path.read_text(encoding="utf-8") if workspace else markdown
            path.write_text(update_created_section(current, plan, mappings, "partial"), encoding="utf-8")
        raise

    if not dry_run:
        current = path.read_text(encoding="utf-8") if workspace else markdown
        text = update_created_section(current, plan, mappings, "created")
        path.write_text(update_front_matter(text, {"native_allocation_pending": ""}) if workspace else text, encoding="utf-8")
    return 0


def publish_source_expansion(runner: WorkspaceRunner, plan: Plan, mappings: dict[str, str], workspace: dict) -> None:
    from workspace_cooked import read_cooked_writer_map
    from workspace_entry import allocate_placeholder, read_entry
    from workspace_outputs import immutable_json
    from workspace_records import canonical_bytes, record_identity
    from workspace_source_plan import declare_plan, publish_plan
    from workspace_store import validate_cooked_writer_map
    state, store, attempt = workspace["state"], workspace["store"], workspace["attempt"]
    source_plan = physical_source_plan(plan, mappings, state["run"], writer_step_id=attempt.claimed_bead_id,
        generation=state["generation"], canonical=workspace.get("canonical"))
    convoy_key = workspace.get("implementation_convoy_key")
    if convoy_key is None:
        roots = [item.key for item in plan.convoys if not item.parent_convoy]
        if len(roots) != 1:
            raise PlanError("choose exactly one implementation convoy key for this source plan")
        convoy_key = roots[0]
    if convoy_key not in {item.key for item in plan.convoys}:
        raise PlanError("implementation convoy key does not name a native convoy in this expansion")
    row = store.snapshot([attempt.claimed_bead_id])[attempt.claimed_bead_id]
    raw_ref = row["metadata"].get("gc.source_plan_ref")
    if raw_ref is not None:
        from workspace_entry import reference
        ref = reference(raw_ref, "source-plan")
        if ref["identity"] != list(record_identity("source-plan", source_plan)):
            raise PlanError("existing source plan differs from this expansion identity")
        record_id = ref["bead_id"]
        if workspace.get("record_id") not in (None, record_id):
            raise PlanError("supplied source-plan record differs from existing native reference")
    else:
        record_id = allocate_placeholder(store, title="Declared build source plan", existing_id=workspace.get("record_id"))
    authority_id = workspace.get("authority_id")
    if authority_id is None:
        import hashlib
        scope = {"workflow_root_id": state["workflow_root_id"], "generation": state["generation"],
                 "writer_scope_id": attempt.claimed_bead_id, "record_kind": "source-plan"}
        index_raw = store.snapshot([state["workflow_root_id"]])[state["workflow_root_id"]]["metadata"].get("gc.workspace_write_grant_refs")
        if index_raw is not None:
            index = json.loads(index_raw)
            key = hashlib.sha256(canonical_bytes(scope)).hexdigest()
            grant_ref = index.get("scopes", {}).get(key)
            if grant_ref is not None:
                if grant_ref.get("scope") != scope:
                    raise PlanError("source-plan authority has a conflicting native scope")
                authority_id = grant_ref["authority_id"]
    if authority_id is None:
        authority_id = allocate_placeholder(store, title="Source-plan writer grant")
    # Native allocations can overlap controller annotations. Re-admit before
    # preparing the first intent, retaining the original map and spec tokens.
    current_map, current_rows = read_cooked_writer_map(store,
        workflow_root_id=state["workflow_root_id"], claimed_step_id=attempt.claimed_bead_id)
    if current_map.sha256 != workspace["writer_map"].sha256:
        raise RecordError("native writer map changed during source allocation")
    validate_cooked_writer_map(workspace["writer_map"], current_rows, store_ref=store.store_ref,
        workflow_root_id=state["workflow_root_id"], record_kind="source-plan", claimed_step_id=attempt.claimed_bead_id)
    current_entry = read_entry(store, gc=store.gc, city_root=store.cwd, rig_name=state["rig_name"],
        workflow_root_id=state["workflow_root_id"], claimed_step_id=attempt.claimed_bead_id,
        worktree_lifecycle="new", generation=state["generation"], expected_run_sha256=state["run_sha256"])
    if ({key: value for key, value in current_entry.items() if key != "_native_rows"}
            != {key: value for key, value in state.items() if key != "_native_rows"}):
        raise RecordError("recorded source expansion entry changed during native allocation")
    prepared = declare_plan(store, attempt, source_plan, run_record_id=state["run_reference"]["bead_id"],
        record_bead_id=record_id, authority_id=authority_id, implementation_convoy_id=mappings[convoy_key],
        writer_map=workspace["writer_map"], writer_rows=current_rows)
    receipt = publish_plan(store, prepared, evidence_dir=workspace["evidence_dir"])
    receipt_ref = immutable_json(Path(workspace["evidence_dir"]) / f"source-plan-publication-{prepared.sha256}.json", receipt)
    if receipt.get("outcome") not in ("committed", "replayed"):
        error = receipt.get("submission_error", receipt.get("error", "exact native readback did not prove publication"))
        raise PlanError(f"source-plan publication is uncertain: {error}; original request: {receipt['request_path']}; "
                        f"publication receipt: {receipt_ref['path']}; resolve the original guarded request before dispatch")
    # Creation assigns no worker or routing target. The existing native build
    # drain starts only after this declaration and successful decomposition.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create Gas City beads and convoys from a gc mayor tasks.md file")
    parser.add_argument("tasks_md", help="Path to tasks.md")
    parser.add_argument("--city", help="Optional city path/name passed through to gc")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print gc commands without creating beads")
    parser.add_argument("--force", action="store_true", help="Allow rerun when tasks.md status is created")
    parser.add_argument("--worktree-lifecycle", choices=("legacy", "new"),
                        help="Inherit the recorded workflow mode, otherwise use new; legacy is deprecated")
    parser.add_argument("--store-ref")
    parser.add_argument("--workflow-root")
    parser.add_argument("--claimed-step")
    parser.add_argument("--generation", type=int, default=1)
    parser.add_argument("--source-plan-record-id")
    parser.add_argument("--authority-id")
    parser.add_argument("--implementation-convoy-key")
    parser.add_argument("--evidence-dir", type=Path, help="Existing directory retaining exact new-mode write requests")
    parser.add_argument("--gc", default="gc")
    args = parser.parse_args(argv)
    try:
        workspace = None
        store = None
        mode = args.worktree_lifecycle or "new"
        if any((args.store_ref, args.workflow_root, args.claimed_step)):
            from workspace_entry import read_entry_mode
            from workspace_store import Attempt, WorkspaceStore
            if not all((args.city, args.store_ref, args.workflow_root, args.claimed_step)):
                raise PlanError("native lifecycle selection requires explicit city, store, workflow root and claimed step")
            store = WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city)
            mode, _ = read_entry_mode(store, workflow_root_id=args.workflow_root,
                claimed_step_id=args.claimed_step, worktree_lifecycle=args.worktree_lifecycle)
        if mode == "new":
            from workspace_entry import read_entry, reference
            from workspace_store import Attempt, WorkspaceStore
            if not all((args.city, args.store_ref, args.workflow_root, args.claimed_step)) or (not args.dry_run and args.evidence_dir is None):
                raise PlanError("new source expansion requires explicit city, store, workflow root, claimed step and evidence directory")
            if args.evidence_dir is not None and (not args.evidence_dir.is_absolute() or not args.evidence_dir.is_dir()
                    or args.evidence_dir.resolve(strict=True) != args.evidence_dir):
                raise PlanError("evidence directory must be an existing canonical absolute directory")
            rig_name = parse_plan(extract_payload(Path(args.tasks_md).read_text(encoding="utf-8"))).target_rig
            store = store or WorkspaceStore(args.store_ref, gc=args.gc, cwd=args.city)
            state = read_entry(store, gc=args.gc, city_root=args.city, rig_name=rig_name,
                workflow_root_id=args.workflow_root, claimed_step_id=args.claimed_step,
                worktree_lifecycle="new", generation=args.generation)
            state["rig_name"] = rig_name
            store.common_git_dir = state["run"]["common_git_dir"]
            canonical = None
            if args.generation > 1:
                raw = store.snapshot([args.workflow_root])[args.workflow_root]["metadata"].get("gc.canonical_ref")
                ref = reference(raw, "canonical")
                canonical = store.read_record("canonical", ref["bead_id"], ref["identity"])
                if canonical is None or canonical["generation"] + 1 != args.generation:
                    raise PlanError("new fix generation must follow the exact current canonical result")
            workspace = {"store": store, "state": state, "attempt": Attempt.from_env(args.claimed_step),
                "record_id": args.source_plan_record_id, "authority_id": args.authority_id,
                "implementation_convoy_key": args.implementation_convoy_key, "canonical": canonical,
                "evidence_dir": args.evidence_dir}
        else:
            if store is not None:
                from workspace_entry import gate_entry
                gate_entry(store, Attempt.from_env(args.claimed_step), gc=args.gc, city_root=args.city,
                    rig_name=parse_plan(extract_payload(Path(args.tasks_md).read_text(encoding="utf-8"))).target_rig,
                    workflow_root_id=args.workflow_root, entrypoint="decompose", worktree_lifecycle=mode)
            print("create_beads_from_tasks: worktree_lifecycle=legacy is deprecated; retain the original mode for legacy work",
                  file=sys.stderr)
        return create_from_tasks(Path(args.tasks_md), city=args.city, dry_run=args.dry_run, force=args.force, workspace=workspace)
    except (PlanError, RecordError, OSError, ValueError) as exc:
        print(f"create_beads_from_tasks: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
