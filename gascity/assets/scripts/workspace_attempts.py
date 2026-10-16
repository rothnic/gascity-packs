"""Join native controller attachments to their original compiled attempt seed."""
from __future__ import annotations

import copy
import hashlib
import json
import re

from workspace_records import canonical_bytes, parse_record


FACTS = ("gc.kind", "gc.step_id", "gc.step_ref", "gc.control_for",
         "gc.build.artifact_schema", "gc.build.plan_review_required", "gc.lifecycle", "gc.run_target", "gc.scope_role",
         "gc.scope_ref", "gc.scope_name", "gc.ralph_step_id", "gc.attempt", "gc.retry_attempt",
         "gc.iteration", "gc.on_fail")
POLICY = ("gc.max_attempts", "gc.check_mode", "gc.check_path", "gc.check_timeout",
          "gc.on_exhausted", "gc.step_timeout", "gc.original_kind")


def _require(condition, message):
    from workspace_store import require
    require(condition, message)


def _number(value):
    _require(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value),
             "native attempt counter is absent or noncanonical")
    return int(value)


def _control_epoch(value):
    # Native controller CAS increments store this field as a JSON integer.
    return value if type(value) is int and value > 0 else _number(value)


def _substitute(value, variables):
    if isinstance(value, str):
        return re.sub(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}",
                      lambda match: variables.get(match[1], match[0]), value)
    if isinstance(value, list):
        return [_substitute(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, variables) for key, item in value.items()}
    return value


def attempt_metadata(seed, control, number, prefix):
    """Later roots come from the frozen authored step, not its stripped first seed."""
    metadata = copy.deepcopy(seed)
    old_prefix = control["seed_ref"]
    for key in ("gc.step_ref", "gc.scope_ref", "gc.control_for"):
        value = metadata.get(key)
        if isinstance(value, str) and (value == old_prefix or value.startswith(old_prefix + ".")):
            metadata[key] = prefix + value[len(old_prefix):]
    root = seed["gc.step_ref"] == old_prefix
    kind = control["kind"]
    if root:
        metadata = copy.deepcopy(control["source_spec"].get("metadata") or {})
        metadata["gc.step_id"] = control["step_id"]
        metadata["gc.step_ref"] = prefix
        metadata["gc.kind"] = "scope" if control["scoped"] else "task"
        metadata["gc.control_for"] = metadata["gc.logical_bead_id"] = control["control_id"]
        if control["scoped"]:
            metadata.update({"gc.scope_role": "body", "gc.scope_name": control["step_id"],
                             "gc.ralph_step_id": control["step_id"]})
        if kind == "retry":
            metadata["gc.retry_attempt"] = str(number)
            iteration = control["iteration"]
            metadata["gc.attempt"] = iteration or str(number)
            if iteration:
                metadata["gc.iteration"] = iteration
            else:
                metadata.pop("gc.iteration", None)
        else:
            metadata["gc.attempt"] = metadata["gc.iteration"] = str(number)
            metadata.pop("gc.retry_attempt", None)
    elif seed.get("gc.kind") == "scope-check":
        metadata["gc.attempt"] = str(number)
    else:
        metadata["gc.kind"] = metadata.get("gc.kind") or "task"
        metadata["gc.attempt"] = metadata["gc.iteration"] = str(number)
    return metadata


def attempt_recipe(control, number, prefix):
    """Reconstruct native attempt metadata and blocks, including minted scope checks."""
    templates, seed_ref = control["templates"], control["seed_ref"]
    def rename(ref):
        template = templates.get(ref)
        if template and template["metadata"].get("gc.kind") == "scope-check":
            subject = template["metadata"].get("gc.control_for", "")
            if subject == seed_ref or subject.startswith(seed_ref + "."):
                return ref if number == 1 else prefix + subject[len(seed_ref):] + "-scope-check"
        return prefix + ref[len(seed_ref):] if ref == seed_ref or ref.startswith(
            (seed_ref + ".", seed_ref + "-")) else ref
    recipe = {rename(ref): dict(metadata=(copy.deepcopy(template["metadata"]) if number == 1 else
                attempt_metadata(template["metadata"], control, number, prefix)),
                blocks=[rename(ref) for ref in template["blocks"]],
                dependencies=template["dependencies"])
              for ref, template in templates.items()}
    if number == 1:
        return recipe
    # buildAttemptRecipe has no external root blocks. Its scoped root waits on
    # raw children; a child scope-check closes that root, so rewriting that edge
    # would create the cycle deliberately excluded by RewriteRecipeDepsToControls.
    children = control["source_spec"].get("children") or []
    recipe[prefix]["blocks"] = [prefix + "." + child["id"] for child in children]
    authored_refs = {prefix, *recipe[prefix]["blocks"]}
    for ref, entry in list(recipe.items()):
        # These compiler-minted controls are re-minted by the native attempt
        # builder, even when the first compiled iteration already had them.
        subject = entry["metadata"].get("gc.control_for")
        if (ref not in authored_refs and entry["metadata"].get("gc.kind") == "scope-check"
                and subject in recipe and ref == subject + "-scope-check"):
            del recipe[ref]
    for child in children:
        ref = prefix + "." + child["id"]
        _require(ref in recipe, "native attempt child lacks its exact compiled seed")
        if not any(child.get(key) for key in ("retry", "ralph", "drain")):
            metadata = copy.deepcopy(child.get("metadata") or {})
            metadata.update({"gc.attempt": str(number), "gc.step_ref": ref, "gc.step_id": child["id"],
                "gc.scope_ref": prefix, "gc.ralph_step_id": control["step_id"], "gc.scope_role": "member",
                "gc.on_fail": "abort_scope"})
            iteration = str(number) if control["kind"] == "ralph" else control["iteration"]
            if iteration:
                metadata["gc.iteration"] = iteration
            else:
                metadata.pop("gc.iteration", None)
            metadata["gc.kind"] = metadata.get("gc.kind") or "task"
            recipe[ref]["metadata"] = metadata
        recipe[ref]["blocks"] = [prefix + "." + need for need in child.get("needs", [])]
    replacements = {}
    for ref, entry in list(recipe.items()):
        metadata = entry["metadata"]
        if (not metadata.get("gc.scope_ref") or metadata.get("gc.scope_role") == "teardown"
                or metadata.get("gc.kind") in ("scope", "scope-check", "workflow-finalize", "fanout", "check", "drain", "spec")):
            continue
        check_ref = ref + "-scope-check"
        if check_ref in recipe:
            continue
        check = {"gc.kind": "scope-check", "gc.scope_role": "control",
                 "gc.scope_ref": metadata["gc.scope_ref"], "gc.control_for": ref,
                 "gc.step_ref": check_ref}
        check.update({key: metadata[key] for key in
                      ("gc.step_id", "gc.ralph_step_id", "gc.attempt", "gc.on_fail") if metadata.get(key)})
        recipe[check_ref] = dict(metadata=check, blocks=[ref])
        replacements[ref] = check_ref
    for ref, entry in recipe.items():
        _require(all(need in recipe for need in entry["blocks"]), "native attempt block leaves its source recipe")
        if ref in replacements.values():
            continue
        entry["blocks"] = [replacements.get(need, need) if not (
            entry["metadata"].get("gc.kind") == "scope" and entry["metadata"].get("gc.scope_role") == "body"
            and recipe[need]["metadata"].get("gc.scope_ref") == ref) else need
            for need in entry["blocks"]]
    # Native topology groups the local recipe's physical edges by semantic ID;
    # only the attempt root inherits its logical control's external topology.
    topology = {}
    for ref, entry in recipe.items():
        step_id = entry["metadata"]["gc.step_id"]
        topology.setdefault(step_id, set()).update(recipe[need]["metadata"]["gc.step_id"]
            for need in entry["blocks"] if recipe[need]["metadata"]["gc.step_id"] != step_id)
    for entry in recipe.values():
        entry["dependencies"] = sorted(topology[entry["metadata"]["gc.step_id"]])
    recipe[prefix]["dependencies"] = control["dependencies"]
    return recipe


def physical_attempt_edges(control):
    """Expected native blocks by physical ID, retaining all prior attempt roots."""
    physical = {ref: bead_id for attempt in control["attempts"] for ref, bead_id in attempt["refs"].items()}
    physical.update(control["external_refs"])
    edges = {control["control_id"]: sorted(set(
        [physical[ref] for ref in control["control_blocks"]] + [item["root_id"] for item in control["attempts"]]))}
    for attempt in control["attempts"]:
        prefix = next(ref for ref, bead_id in attempt["refs"].items() if bead_id == attempt["root_id"])
        recipe = attempt_recipe(control, attempt["number"], prefix)
        for ref, entry in recipe.items():
            _require(all(need in physical for need in entry["blocks"]), "native attempt block has no exact physical source")
            edges[attempt["refs"][ref]] = sorted(physical[need] for need in entry["blocks"])
    return edges


def decode_lineage(writer_map):
    raw = writer_map.lineage_bytes
    if raw is None:
        return []
    _require(isinstance(raw, bytes), "native attempt lineage requires canonical bytes")
    data = parse_record(raw.decode())
    _require(set(data) == {"version", "controls"} and type(data["version"]) is int
             and data["version"] == 1 and isinstance(data["controls"], list) and data["controls"]
             and canonical_bytes(data) == raw, "native attempt lineage is malformed")
    return data["controls"]


def discover_attempts(compiled, dependencies, rows, expansion_id, raw_formula, variables, show_spec, snapshot):
    """Read the frozen native spec once; never infer a writer from a ref suffix."""
    from workspace_store import _dependencies, _root
    descriptors, expected, owners = [], {}, {}
    def original(row):
        return (row["metadata"].get("gc.attach_root_id") or _root(row)) == expansion_id
    raw_steps = {step["id"]: step for step in raw_formula["steps"]
                 if isinstance(step, dict) and isinstance(step.get("id"), str)}
    _require(len(raw_steps) == len(raw_formula["steps"]) and set(raw_steps) == {step["id"] for step in compiled.values()},
             "native raw formula steps are malformed or ambiguous")
    refs_by_id = {entry["id"]: ref for ref, entry in compiled.items()}
    blocks = {ref: [] for ref in compiled}
    for edge in raw_formula.get("deps", []):
        if edge.get("type") == "blocks":
            _require(edge.get("step_id") in refs_by_id and edge.get("depends_on_id") in refs_by_id,
                     "native attempt block has no exact compiled source")
            blocks[refs_by_id[edge["step_id"]]].append(refs_by_id[edge["depends_on_id"]])
    for control_ref, step in compiled.items():
        meta = step["metadata"]
        kind = meta.get("gc.kind")
        if kind not in ("retry", "ralph"):
            continue
        matches = [row for row in rows.values() if original(row) and row["metadata"].get("gc.step_ref") == control_ref]
        _require(len(matches) <= 1, "native control occurrence is ambiguous")
        if not matches:
            continue
        control_row = matches[0]
        control_id = control_row["id"]
        attached = [row for row in rows.values() if row["metadata"].get("gc.control_for") == control_id
                    and row["metadata"].get("gc.logical_bead_id") == control_id]
        if not attached:
            continue
        semantic = meta.get("gc.step_id", step["id"])
        seeds = [entry for entry in compiled.values()
                 if entry["metadata"].get("gc.control_for") in (semantic, control_ref)
                 and entry["metadata"].get("gc.kind") not in ("retry", "ralph", "scope-check")
                 and entry["metadata"].get("gc.attempt") == "1"]
        _require(len(seeds) == 1, "native control lacks one exact compiled first attempt")
        seed = seeds[0]["metadata"]
        seed_ref = seed["gc.step_ref"]
        seed_refs = {ref for ref in compiled if ref == seed_ref or ref.startswith(seed_ref + ".")}
        templates = {ref: dict(metadata=copy.deepcopy(entry["metadata"]),
                               dependencies=sorted(dependencies[entry["metadata"]["gc.step_id"]]), blocks=blocks[ref])
                     for ref, entry in compiled.items()
                     if ref in seed_refs or ref == seed_ref + "-scope-check" or (
                         entry["metadata"].get("gc.kind") == "scope-check"
                         and entry["metadata"].get("gc.control_for") in seed_refs)}
        specs = [entry for entry in compiled.values()
                 if entry["metadata"].get("gc.kind") == "spec"
                 and entry["metadata"].get("gc.spec_for_ref") == control_ref]
        if not specs:
            specs = [entry for entry in compiled.values() if entry["metadata"].get("gc.kind") == "spec"
                     and entry["metadata"].get("gc.spec_for") == semantic]
        _require(len(specs) == 1, "native control lacks its exact frozen source specification")
        spec_step = specs[0]
        spec_ref = spec_step["metadata"].get("gc.step_ref", spec_step["id"])
        spec_rows = [row for row in rows.values() if original(row) and row["metadata"].get("gc.step_ref") == spec_ref]
        _require(len(spec_rows) == 1, "native frozen specification occurrence is ambiguous or absent")
        spec_row = spec_rows[0]
        source = _substitute(parse_record(raw_steps[spec_step["id"]]["description"]), variables)
        detail = show_spec(spec_row["id"])
        _require(detail.get("id") == spec_row["id"] and detail.get("revision") == spec_row["revision"]
                 and detail.get("status") == spec_row["status"] and isinstance(detail.get("description"), str)
                 and isinstance(detail.get("updated_at"), str)
                 and canonical_bytes(parse_record(detail["description"])) == canonical_bytes(source),
                 "native frozen specification differs from its exact compiled source or revision")
        _require(canonical_bytes(snapshot([spec_row["id"]])[spec_row["id"]]) == canonical_bytes(spec_row),
                 "native frozen specification changed during readback")
        _require(show_spec(spec_row["id"]) == detail, "native frozen specification text changed during readback")
        descriptor = dict(control_id=control_id, control_ref=control_ref, kind=kind,
            step_id=semantic, seed_ref=seed_ref, scoped=bool(source.get("children")),
            iteration=control_row["metadata"].get("gc.iteration", ""),
            spec_id=spec_row["id"], spec_ref=spec_ref, spec_revision=spec_row["revision"], source_spec=source,
            spec_for_ref=spec_step["metadata"].get("gc.spec_for_ref"),
            control_metadata={key: meta.get(key) for key in (*FACTS, *POLICY)},
            source_description=detail["description"],
            description_sha256=hashlib.sha256(detail["description"].encode()).hexdigest(),
            dependencies=_dependencies(control_row["metadata"]), control_blocks=blocks[control_ref],
            templates=templates, external_refs={}, attempts=[])
        roots = {1: [row for row in rows.values() if original(row) and row["metadata"].get("gc.step_ref") == seed_ref]}
        for row in attached:
            counter = _number(row["metadata"].get("gc.retry_attempt") if kind == "retry"
                              else row["metadata"].get("gc.attempt"))
            _require(counter >= 2, "attached native attempt has an invalid first-attempt counter")
            roots.setdefault(counter, []).append(row)
        latest = max(roots)
        _require(set(roots) == set(range(1, latest + 1)) and all(len(value) == 1 for value in roots.values()),
                 "native attempt history is missing or ambiguous")
        for number, values in sorted(roots.items()):
            root = values[0]
            prefix = seed_ref if number == 1 else control_ref + (".iteration." if kind == "ralph" else ".attempt.") + str(number)
            occurrence = dict(number=number, root_id=root["id"], refs={})
            for actual_ref, entry in attempt_recipe(descriptor, number, prefix).items():
                candidates = [row for row in rows.values() if row["metadata"].get("gc.step_ref") == actual_ref
                              and (original(row) if number == 1 else
                                   row["id"] == root["id"] or row["metadata"].get("gc.attach_root_id") == root["id"])]
                _require(len(candidates) == 1, "native attempt body is missing or ambiguous")
                bead_id = candidates[0]["id"]
                _require(bead_id not in owners, "native attempt belongs to multiple controls")
                owners[bead_id] = (control_id, number)
                occurrence["refs"][actual_ref] = bead_id
                if number > 1:
                    expected[actual_ref] = entry
            descriptor["attempts"].append(occurrence)
        family_refs = {ref for attempt in descriptor["attempts"] for ref in attempt["refs"]}
        external = set(descriptor["control_blocks"]) | {ref for template in templates.values() for ref in template["blocks"]}
        for ref in external - family_refs:
            candidates = [row for row in rows.values() if original(row) and row["metadata"].get("gc.step_ref") == ref]
            _require(ref in compiled and len(candidates) == 1, "native attempt prerequisite is absent or ambiguous")
            descriptor["external_refs"][ref] = candidates[0]["id"]
        descriptors.append(descriptor)
    return expected, descriptors, owners


def validate_attempts(writer_map, rows, claimed_step_id):
    from workspace_store import _dependencies, _root
    controls = decode_lineage(writer_map)
    owners, expected, guards = {}, {}, []
    for descriptor in controls:
        _require(isinstance(descriptor, dict) and all(isinstance(descriptor.get(key), str) and descriptor[key]
                 for key in ("control_id", "control_ref", "step_id", "seed_ref", "spec_id", "spec_ref", "spec_for_ref"))
                 and descriptor.get("kind") in ("ralph", "retry") and type(descriptor.get("scoped")) is bool
                 and isinstance(descriptor.get("spec_revision"), str)
                 and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", descriptor["spec_revision"])
                 and -(2**63) <= int(descriptor["spec_revision"]) < 2**63
                 and isinstance(descriptor.get("iteration"), str) and isinstance(descriptor.get("source_spec"), dict)
                 and isinstance(descriptor.get("control_metadata"), dict)
                 and set(descriptor["control_metadata"]) == set((*FACTS, *POLICY))
                 and isinstance(descriptor.get("source_description"), str)
                 and hashlib.sha256(descriptor["source_description"].encode()).hexdigest() == descriptor.get("description_sha256")
                 and canonical_bytes(parse_record(descriptor["source_description"])) == canonical_bytes(descriptor["source_spec"])
                 and descriptor["control_id"] in rows and descriptor["spec_id"] in rows,
                 "native attempt source descriptor is malformed")
        control, spec = rows[descriptor["control_id"]], rows[descriptor["spec_id"]]
        _require(spec["revision"] == writer_map._spec_revisions.get(descriptor["spec_id"], descriptor["spec_revision"]),
                 "native frozen specification revision changed after discovery")
        metadata = control["metadata"]
        expansion_id = writer_map.declaration["expansion_root_id"]
        physical_root = _root(rows[expansion_id]) or expansion_id
        _require(all(_root(row) == physical_root
                     and row["metadata"].get("gc.root_store_ref") == writer_map.declaration["store_ref"]
                     and (row["metadata"].get("gc.attach_root_id") or physical_root) == expansion_id
                     for row in (control, spec)), "native control or specification belongs to a foreign expansion")
        _require(metadata.get("gc.kind") == descriptor["kind"]
                 and metadata.get("gc.step_id") == descriptor["step_id"]
                 and metadata.get("gc.step_ref") == descriptor["control_ref"]
                 and spec["metadata"].get("gc.kind") == "spec"
                 and spec["metadata"].get("gc.step_ref") == descriptor["spec_ref"]
                 and spec["metadata"].get("gc.spec_for") == descriptor["step_id"]
                 and spec["metadata"].get("gc.spec_for_ref") == descriptor["spec_for_ref"],
                 "native attempt control or frozen source identity changed")
        _require(all(metadata.get(key) == value for key, value in descriptor["control_metadata"].items()),
                 "native source control policy changed")
        source = descriptor["source_spec"]
        mode = source.get("ralph") if descriptor["kind"] == "ralph" else source.get("retry")
        _require(isinstance(mode, dict) and type(mode.get("max_attempts")) is int
                 and mode["max_attempts"] == _number(metadata.get("gc.max_attempts"))
                 and source.get("id") == descriptor["step_id"], "native source control policy changed")
        attempts = descriptor["attempts"]
        templates = descriptor.get("templates")
        _require(isinstance(templates, dict) and descriptor["seed_ref"] in templates
                 and all(isinstance(ref, str) and isinstance(template, dict)
                     and isinstance(template.get("metadata"), dict) and template["metadata"].get("gc.step_ref") == ref
                     and isinstance(template.get("dependencies"), list)
                     and all(isinstance(dep, str) for dep in template["dependencies"])
                     and template["dependencies"] == sorted(set(template["dependencies"]))
                     and isinstance(template.get("blocks"), list)
                     and all(isinstance(ref, str) for ref in template["blocks"])
                     and len(set(template["blocks"])) == len(template["blocks"])
                     for ref, template in templates.items()), "native compiled attempt seeds are malformed")
        _require(descriptor.get("dependencies") == _dependencies(metadata)
                 and isinstance(descriptor.get("control_blocks"), list)
                 and all(isinstance(ref, str) for ref in descriptor["control_blocks"])
                 and len(set(descriptor["control_blocks"])) == len(descriptor["control_blocks"])
                 and isinstance(descriptor.get("external_refs"), dict), "native attempt block declaration is malformed")
        for ref, bead_id in descriptor["external_refs"].items():
            _require(isinstance(ref, str) and isinstance(bead_id, str) and bead_id in rows
                     and rows[bead_id]["metadata"].get("gc.step_ref") == ref
                     and _root(rows[bead_id]) == physical_root
                     and rows[bead_id]["metadata"].get("gc.root_store_ref") == metadata.get("gc.root_store_ref")
                     and (rows[bead_id]["metadata"].get("gc.attach_root_id") or physical_root) == expansion_id,
                     "native attempt prerequisite belongs to a foreign source occurrence")
        _require(isinstance(attempts, list) and all(isinstance(item, dict) and set(item) == {"number", "root_id", "refs"}
                     and type(item["number"]) is int and isinstance(item["root_id"], str)
                     and item["root_id"] in rows and isinstance(item["refs"], dict) for item in attempts)
                 and [item["number"] for item in attempts] == list(range(1, len(attempts)+1))
                 and 2 <= len(attempts) <= mode["max_attempts"]
                 and _control_epoch(metadata.get("gc.control_epoch")) in (len(attempts)-1, len(attempts)),
                 "native control counter, epoch or maximum differs from its attempt history")
        for attempt in attempts:
            number = attempt["number"]
            root = rows[attempt["root_id"]]
            prefix = descriptor["seed_ref"] if number == 1 else descriptor["control_ref"] + (
                ".iteration." if descriptor["kind"] == "ralph" else ".attempt.") + str(number)
            _require(root["metadata"].get("gc.step_ref") == prefix, "native attempt root reference changed")
            recipe = attempt_recipe(descriptor, number, prefix)
            _require(set(attempt["refs"]) == set(recipe)
                     and attempt["refs"].get(prefix) == root["id"],
                     "native attempt body differs from its exact compiled seeds")
            if number > 1:
                _require(root["metadata"].get("gc.idempotency_key") == descriptor["control_id"] + ":attempt:" + str(number)
                         and root["metadata"].get("gc.logical_bead_id") == descriptor["control_id"],
                         "native attempt attachment idempotency identity changed")
            for ref, bead_id in attempt["refs"].items():
                _require(bead_id in rows and bead_id not in owners and _root(rows[bead_id]) == _root(control)
                         and rows[bead_id]["metadata"].get("gc.root_store_ref") == metadata.get("gc.root_store_ref"),
                         "native attempt belongs to a foreign or ambiguous root/store")
                wanted = recipe[ref]["metadata"]
                observed = rows[bead_id]["metadata"]
                _require(all(observed.get(key) == wanted.get(key) for key in FACTS),
                         "native attempt designation differs from its frozen source")
                deps = recipe[ref]["dependencies"]
                _require(_dependencies(observed) == sorted(deps), "native attempt dependency lineage changed")
                attach = observed.get("gc.attach_root_id")
                _require(not attach or attach in (writer_map.declaration["expansion_root_id"], root["id"]),
                         "native attempt belongs to a sibling attachment")
                if number > 1 and bead_id != root["id"]:
                    _require(attach == root["id"], "native attempt child lost its exact attachment root")
                if number < len(attempts):
                    _require(rows[bead_id]["status"] == "closed", "older native attempt is still live")
                owners[bead_id] = (descriptor["control_id"], number)
                expected[ref] = dict(metadata=wanted, dependencies=deps)
        physical_edges = physical_attempt_edges(descriptor)
        revisions = descriptor.get("physical_revisions")
        _require(isinstance(revisions, dict) and set(revisions) == set(physical_edges),
                 "native attempt physical dependency observations are incomplete")
        for bead_id, revision in revisions.items():
            _require(isinstance(revision, str) and re.fullmatch(r"-?(?:0|[1-9][0-9]*)", revision)
                     and -(2**63) <= int(revision) < 2**63
                     and rows[bead_id]["revision"] == writer_map._attempt_revisions.get(bead_id, revision),
                     "native attempt physical dependency revision changed after discovery")
        if claimed_step_id in owners and owners[claimed_step_id][0] == descriptor["control_id"]:
            _require(owners[claimed_step_id][1] == len(attempts) and rows[claimed_step_id]["status"] == "in_progress",
                     "claimed writer is not the current live native attempt")
            guards.extend((descriptor["spec_id"], *physical_edges))
    return owners, expected, guards
