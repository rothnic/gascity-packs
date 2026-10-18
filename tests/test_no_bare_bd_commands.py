from __future__ import annotations

import ast
from pathlib import Path
import re
import shlex
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

BD_SUBCOMMANDS = (
    "admin",
    "ado",
    "assign",
    "audit",
    "backup",
    "batch",
    "blocked",
    "bootstrap",
    "branch",
    "children",
    "close",
    "comment",
    "comments",
    "compact",
    "completion",
    "config",
    "context",
    "cook",
    "count",
    "create",
    "create-form",
    "defer",
    "delete",
    "dep",
    "diff",
    "doctor",
    "dolt",
    "duplicate",
    "duplicates",
    "edit",
    "epic",
    "export",
    "federation",
    "find-duplicates",
    "flatten",
    "forget",
    "formula",
    "gate",
    "gc",
    "github",
    "gitlab",
    "graph",
    "heartbeat",
    "help",
    "history",
    "hooks",
    "human",
    "import",
    "info",
    "init",
    "init-safety",
    "jira",
    "kv",
    "label",
    "linear",
    "link",
    "list",
    "lint",
    "mail",
    "memories",
    "merge-slot",
    "meta",
    "metrics",
    "migrate",
    "migrate-personal",
    "mol",
    "note",
    "notion",
    "onboard",
    "orphans",
    "ping",
    "preflight",
    "prime",
    "priority",
    "promote",
    "prune",
    "purge",
    "q",
    "query",
    "quickstart",
    "ready",
    "recall",
    "reclaim",
    "recompute-blocked",
    "remember",
    "rename-prefix",
    "rename",
    "reopen",
    "repo",
    "restore",
    "rules",
    "search",
    "set-state",
    "setup",
    "show",
    "ship",
    "sql",
    "stale",
    "state",
    "status",
    "statuses",
    "supersede",
    "swarm",
    "sync",
    "tag",
    "todo",
    "type",
    "types",
    "unclaim",
    "undefer",
    "update",
    "upgrade",
    "vc",
    "version",
    "where",
    "worktree",
)
BD_SUBCOMMAND_PATTERN = "|".join(re.escape(command) for command in BD_SUBCOMMANDS)
BARE_BD_COMMAND = re.compile(rf"\bbd[ \t]+(?:{BD_SUBCOMMAND_PATTERN})\b")
BARE_BD_LEADING_FLAG = re.compile(r"\bbd[ \t]+-{1,2}[A-Za-z]")
BARE_BD_DYNAMIC_COMMAND = re.compile(r'''\bbd[ \t]+(?:["']?\$\{?[A-Za-z_]|\$\()''')
MULTILINE_BARE_BD_COMMAND = re.compile(
    rf"\bbd[ \t]*\r?\n[ \t]*(?:{BD_SUBCOMMAND_PATTERN})\b"
)
BARE_BD_GO_EXEC = re.compile(
    r'(?:exec\.Command(?:Context)?|dispatchExecCommand)\(\s*["\']bd["\']'
)
BARE_BD_PATH_CHECK = re.compile(r"\bcommand[ \t]+-v[ \t]+bd\b")
BARE_BD_SERIALIZED_ARGV = re.compile(
    rf'''(?:\[|\{{|=|:)\s*["']bd["']\s*,\s*["'](?:{BD_SUBCOMMAND_PATTERN})["']'''
)
GC_BD_ARGV_TAIL_MARKER = "gc-bd-argv-tail"
GC_BD_ARGV_TAIL_FIXTURE = Path("tests/test_gascity_pack_inference_gate.py")
GC_BD_ARGV_TAIL_LINES = {
    '*"bd show fi-root --json"*) # gc-bd-argv-tail: fake gc receives the wrapper\'s argv tail',
    '*"bd list --json --limit 1000"*) # gc-bd-argv-tail: fake gc receives the wrapper\'s argv tail',
    'assert "bd show fi-root --json" in args_path.read_text(encoding="utf-8")  # gc-bd-argv-tail',
}

# `gc lint`'s own diagnostic text, pinned so gastown cannot drift. These are
# not instructions to run anything; they are the linter's output quoted back at
# it, and the guard that reads them compares byte for byte, so they cannot be
# reworded to say `gc bd`.
#
# Two conditions, and the second is a grammar rather than a line list: the line
# must be exactly a `bd-unknown-flag` diagnostic, in that one file. A list was
# the first shape here and it does not survive the waiver growing -- the same
# twenty-four lines then have to be maintained in two files, and the copy that
# drifts fails as a bare-bd violation rather than as a stale waiver, which
# points at the wrong problem. Nothing that matches this grammar is a command
# anyone could run.
#
# The line number is optional because the waiver stopped carrying one: it is
# keyed on path and message so that moving a diagnostic within a file is not a
# CI failure. Both forms stay matchable, since gc lint's raw output still
# carries the number and gets pasted here before it is trimmed.
GC_LINT_DIAGNOSTIC_FILE = Path("tests/gastown_lint_upstream_defects.txt")
GC_LINT_DIAGNOSTIC = re.compile(
    r'[\w./-]+:(?:\d+:)? bd-unknown-flag: bd [a-z][a-z ]* uses unrecognized flag "[-\w]+"'
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return [REPO_ROOT / path for path in result.stdout.decode().split("\0") if path]


def scoped_gc_command(scope: ast.AST, name: str) -> bool:
    writes = [node for node in ast.walk(scope) if isinstance(node, ast.Name)
              and node.id == name and isinstance(node.ctx, ast.Store)]
    parents = {child: node for node in ast.walk(scope) for child in ast.iter_child_nodes(node)}
    initializers = [parents[node] for node in writes if isinstance(parents[node], ast.Assign)]
    if len(initializers) != 1:
        return False
    value = initializers[0].value
    if not isinstance(value, ast.List) or len(value.elts) != 3:
        return False
    executable, flag, _ = value.elts
    if not (isinstance(executable, ast.Name) and executable.id == "gc"
            or isinstance(executable, ast.Attribute) and executable.attr == "gc"):
        return False
    if not isinstance(flag, ast.Constant) or flag.value != "--city":
        return False
    for node in writes:
        parent = parents[node]
        if parent is not initializers[0] and not (
            isinstance(parent, ast.AugAssign) and isinstance(parent.op, ast.Add)
        ):
            return False
    # An indexed write, deletion or mutator could remove the routing prefix.
    return not any(
        isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
        and node.value.id == name and isinstance(node.ctx, (ast.Store, ast.Del))
        or isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == name
        for node in ast.walk(scope)
    )


def native_json_routes_gc() -> bool:
    path = REPO_ROOT / "gascity/assets/scripts/workspace_run.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "native_json")
    executions = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute) and node.func.attr == "run"
                  and isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess"]
    return scoped_gc_command(function, "command") and bool(executions) and all(
        node.args and isinstance(node.args[0], ast.BinOp) and isinstance(node.args[0].op, ast.Add)
        and isinstance(node.args[0].left, ast.Name) and node.args[0].left.id == "command"
        and isinstance(node.args[0].right, ast.Name) and node.args[0].right.id == "args"
        for node in executions
    )


def native_json_names(tree: ast.AST) -> set[str]:
    entry = ast.parse((REPO_ROOT / "gascity/assets/scripts/workspace_entry.py").read_text(encoding="utf-8"))
    reexported = any(isinstance(node, ast.ImportFrom) and node.module == "workspace_run"
                     and any(alias.name == "native_json" and alias.asname is None for alias in node.names)
                     for node in entry.body) and not any(
        isinstance(node, ast.Name) and node.id == "native_json" and isinstance(node.ctx, ast.Store)
        or isinstance(node, ast.FunctionDef) and node.name == "native_json" for node in ast.walk(entry))
    names = {alias.asname or alias.name for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module == "workspace_run"
                                                    or node.module == "workspace_entry" and reexported)
            for alias in node.names if alias.name == "native_json"}
    return names - {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                    and isinstance(node.ctx, ast.Store)} - {
                        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def python_argv_context(path: Path, text: str) -> tuple[list[str], list[tuple[int, int]]]:
    if path.suffix != ".py":
        return [], []
    tree = ast.parse(text, filename=str(path))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    forwarders = native_json_names(tree)
    # The injected reader is checked at every shipped allocation call site.
    if path == REPO_ROOT / "gascity/assets/scripts/workspace_allocation.py":
        callers = [ast.parse(source.read_text(encoding="utf-8"))
                   for source in (REPO_ROOT / "gascity/assets/scripts").glob("*.py")]
        calls = [(source, node) for source in callers for node in ast.walk(source)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == "allocate_roles"]
        if calls and all(any(keyword.arg == "native_read" and isinstance(keyword.value, ast.Name)
                            and keyword.value.id in native_json_names(source)
                            for keyword in call.keywords) for source, call in calls):
            forwarders.add("native_read")
    module_forwarders = set()
    # importlib fixtures load this same reviewed helper, rather than an arbitrary object.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute) \
                and node.value.func.attr == "spec_from_file_location" and node.value.args \
                and isinstance(node.value.args[0], ast.Constant) and node.value.args[0].value == "workspace_run" \
                and len(node.value.args) == 2 and isinstance(node.value.args[1], ast.BinOp) \
                and isinstance(node.value.args[1].right, ast.Constant) \
                and node.value.args[1].right.value == "workspace_run.py":
            spec = node.targets[0].id
            module_forwarders.update(candidate.targets[0].id for candidate in ast.walk(tree)
                if isinstance(candidate, ast.Assign) and len(candidate.targets) == 1
                and isinstance(candidate.targets[0], ast.Name) and isinstance(candidate.value, ast.Call)
                and isinstance(candidate.value.func, ast.Attribute) and candidate.value.func.attr == "module_from_spec"
                and candidate.value.args and isinstance(candidate.value.args[0], ast.Name)
                and candidate.value.args[0].id == spec)
    module_forwarders = {name for name in module_forwarders
                         if sum(isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store)
                                for node in ast.walk(tree)) == 1}
    helper_proven = native_json_routes_gc()

    def routed_call(node: ast.AST, tail: ast.AST) -> bool:
        return helper_proven and isinstance(node, ast.Call) and len(node.args) >= 3 and node.args[2] is tail and (
            isinstance(node.func, ast.Name) and node.func.id in forwarders
            or isinstance(node.func, ast.Attribute) and node.func.attr == "native_json"
            and isinstance(node.func.value, ast.Name) and node.func.value.id in module_forwarders
        )

    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    violations, data_spans = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
            continue
        first = node.elts[0]
        if not isinstance(first, ast.Constant) or first.value != "bd":
            continue
        parent = parents[node]
        scope = parent
        while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = parents[scope]
        data = isinstance(parent, ast.Compare) or routed_call(parent, node) or (
            isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute)
            and parent.func.attr in {"assertEqual", "assertNotEqual", "assertIn", "assertNotIn"}
            and isinstance(parent.func.value, ast.Name) and parent.func.value.id == "self"
        )
        if isinstance(parent, ast.AugAssign) and isinstance(parent.target, ast.Name):
            data = scoped_gc_command(scope, parent.target.id)
        if isinstance(parent, ast.Assign) and len(parent.targets) == 1 and isinstance(parent.targets[0], ast.Name):
            name = parent.targets[0].id
            reads = [item for item in ast.walk(scope) if isinstance(item, ast.Name)
                     and item.id == name and isinstance(item.ctx, ast.Load)]
            data = bool(reads) and all(routed_call(parents[item], item) for item in reads)
        if data:
            data_spans.append((offsets[node.lineno - 1] + node.col_offset,
                               offsets[node.end_lineno - 1] + node.end_col_offset))
        else:
            violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: argv starts with bd")
    # Fake gc scripts compare their received tail; parse them instead of waiving a file.
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and BARE_BD_SERIALIZED_ARGV.search(node.value):
            try:
                nested, spans = python_argv_context(path, node.value)
            except SyntaxError:
                continue
            if not nested and all(any(start <= match.start() < end for start, end in spans)
                                  for match in BARE_BD_SERIALIZED_ARGV.finditer(node.value)):
                data_spans.append((offsets[node.lineno - 1] + node.col_offset,
                                   offsets[node.end_lineno - 1] + node.end_col_offset))
    return violations, data_spans


def gc_routes_bd(line: str, bd_start: int) -> bool:
    prefix = line[:bd_start]
    gc_tokens = list(re.finditer(r'(?<![A-Za-z0-9_=/.-])(?:gc\b|"\$GC_BIN")', prefix))
    if not gc_tokens:
        return False
    command_prefix = prefix[gc_tokens[-1].end() :]
    quote, escaped = None, False
    for character in command_prefix:
        if escaped:
            escaped = False
        elif character == "\\" and quote != "'":
            escaped = True
        elif quote:
            if character == quote:
                quote = None
        elif character in "\"'":
            quote = character
        elif character in ";&|\n\r":
            return False
    try:
        tokens = shlex.split(command_prefix)
    except ValueError:
        return False

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--city", "--rig"}:
            if index + 1 >= len(tokens):
                return False
            index += 2
            continue
        if token.startswith("--city=") or token.startswith("--rig="):
            if token.endswith("="):
                return False
            index += 1
            continue
        return False
    return True


def intentional_gc_bd_argv_tail(relative: Path, line: str) -> bool:
    return (
        relative == GC_BD_ARGV_TAIL_FIXTURE
        and GC_BD_ARGV_TAIL_MARKER in line
        and line.strip() in GC_BD_ARGV_TAIL_LINES
    )


def intentional_gc_lint_verbatim(relative: Path, line: str) -> bool:
    return relative == GC_LINT_DIAGNOSTIC_FILE and bool(
        GC_LINT_DIAGNOSTIC.fullmatch(line.strip())
    )


def bare_bd_violations(path: Path, text: str) -> list[str]:
    violations = []
    python_violations, python_data = python_argv_context(path, text)
    relative = path.relative_to(REPO_ROOT)
    for line_number, line in enumerate(text.splitlines(), start=1):
        for pattern in (BARE_BD_COMMAND, BARE_BD_LEADING_FLAG, BARE_BD_DYNAMIC_COMMAND):
            for match in pattern.finditer(line):
                if gc_routes_bd(line, match.start()):
                    continue
                if intentional_gc_bd_argv_tail(relative, line):
                    continue
                if intentional_gc_lint_verbatim(relative, line):
                    continue
                violations.append(f"{relative}:{line_number}: {line.strip()}")
        if BARE_BD_GO_EXEC.search(line):
            violations.append(f"{relative}:{line_number}: direct bd argv")
        if BARE_BD_PATH_CHECK.search(line):
            violations.append(f"{relative}:{line_number}: checks bd instead of gc")
        if "BD_BIN" in line:
            violations.append(f"{relative}:{line_number}: BD_BIN bypasses gc bd routing")
    for match in MULTILINE_BARE_BD_COMMAND.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        first_line = text[line_start : text.find("\n", match.start())]
        if gc_routes_bd(first_line, match.start() - line_start):
            continue
        line_number = text.count("\n", 0, match.start()) + 1
        violations.append(f"{relative}:{line_number}: bd command is split across lines")
    for match in BARE_BD_SERIALIZED_ARGV.finditer(text):
        if any(start <= match.start() < end for start, end in python_data):
            continue
        line_number = text.count("\n", 0, match.start()) + 1
        violations.append(f"{relative}:{line_number}: serialized argv starts with bd")
    violations.extend(python_violations)
    return list(dict.fromkeys(violations))


def test_shipped_pack_assets_route_beads_commands_through_gc() -> None:
    violations = []
    for path in tracked_files():
        if path.resolve() == THIS_FILE:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        violations.extend(bare_bd_violations(path, text))

    assert not violations, "bare bd commands bypass store-aware routing:\n" + "\n".join(violations)


def test_detector_covers_shell_multiline_and_serialized_argv_forms() -> None:
    fixture = REPO_ROOT / "fixture.txt"

    assert bare_bd_violations(fixture, 'command = ["bd", "show"]')
    assert bare_bd_violations(fixture, "value=$(bd\n  list --json)")
    assert bare_bd_violations(fixture, "bd --dir /tmp/rig list --json")
    assert bare_bd_violations(fixture, 'bd "$verb" --json')
    assert bare_bd_violations(fixture, 'command = ["bd",\n "show"]')
    assert bare_bd_violations(fixture, "bd show x  # gc-bd-argv-tail")
    assert bare_bd_violations(fixture, "echo gc; bd show x")
    assert bare_bd_violations(fixture, "GC_BIN=gc bd show x")
    # The gc-lint-diagnostic exemption, proved narrow in both directions: the
    # grammar alone does not exempt a line elsewhere, and the file alone does
    # not exempt a line that is not a diagnostic.
    diagnostic = 'a/b.md:12: bd-unknown-flag: bd create uses unrecognized flag "--rig"'
    lineless = 'a/b.md: bd-unknown-flag: bd create uses unrecognized flag "--rig"'
    waiver = REPO_ROOT / "tests" / "gastown_lint_upstream_defects.txt"
    assert bare_bd_violations(fixture, diagnostic)
    assert bare_bd_violations(fixture, lineless)
    assert bare_bd_violations(waiver, "bd create --labels=x")
    assert not bare_bd_violations(waiver, diagnostic)
    # The form the waiver actually uses now. Without this the exemption could
    # regress to line-numbers-only and every waiver entry would read as a bare
    # bd command, which is a failure about the wrong file.
    assert not bare_bd_violations(waiver, lineless)

    assert not bare_bd_violations(fixture, 'command = ["gc", "bd", "show"]')
    assert not bare_bd_violations(fixture, "gc --city /tmp/city bd list --json")
    assert not bare_bd_violations(fixture, "gc --rig demo bd show demo-1")
    assert not bare_bd_violations(
        fixture, 'row=$("$GC_BIN" --city "$CITY_ROOT" --rig "$RIG_NAME" bd show "$CLAIMED_BEAD_ID" --json)'
    )
    for executable in ('gc', '"$GC_BIN"'):
        assert not bare_bd_violations(
            fixture, f'{executable} --city "/tmp/city;with&literal|punctuation" bd show item'
        )
        for separator in (";", "&&", "||", "|", "&", "\n"):
            assert bare_bd_violations(
                fixture, f'{executable} --city "$CITY_ROOT"{separator} bd show item'
            )
    for text in (
        'row=$("$BD_BIN" --city "$CITY_ROOT" bd show item)',
        'row=$("$OTHER_BIN" --city "$CITY_ROOT" bd show item)',
        '"$GC_BIN"; bd show item',
        '"$GC_BIN" --city bd show item',
        '"$GC_BIN" --unknown value bd show item',
    ):
        assert bare_bd_violations(fixture, text), text


def test_python_detector_distinguishes_routed_tails_from_executable_argv() -> None:
    fixture = REPO_ROOT / "fixture.py"
    for text in (
        'subprocess.run(["bd", "show"])',
        'unknown_reader(gc, city, ["bd", "show"])',
        'native_json(gc, city, ["bd", "show"])',
        'from workspace_run import native_json\nnative_json = subprocess.run\nnative_json(["bd", "show"])',
        'from workspace_run import native_json\nnative_json(["bd", "show"], city, [])',
        'command = ["bd", "show"]\nsubprocess.run(command)',
        'command = [gc, "--city", city]\ncommand = []\ncommand += ["bd", "show"]',
        'command = [gc, "--city", city]\ncommand.clear()\ncommand += ["bd", "show"]',
        'command = [gc, "--city", city]\ncommand[0] = "bd"\ncommand += ["bd", "show"]',
        'script = \'subprocess.run(["bd", "show"])\'',
    ):
        assert bare_bd_violations(fixture, text), text
    for text in (
        'if args[:2] == ["bd", "show"]: pass',
        'self.assertEqual(args[:2], ["bd", "show"])',
        'from workspace_run import native_json\nnative_json(gc, city, ["bd", "show"])',
        'from workspace_run import native_json\nargs = ["bd", "show"]\nnative_json(gc, city, args)',
        'command = [gc, "--city", city]\ncommand += ["--rig", rig]\ncommand += ["bd", "show"]\nsubprocess.run(command)',
        'script = \'if sys.argv[1:] != ["bd", "show"]: sys.exit(2)\'',
    ):
        assert not bare_bd_violations(fixture, text), text


def test_python_tail_exemption_requires_the_actual_gc_helper(monkeypatch) -> None:
    assert native_json_routes_gc()
    monkeypatch.setitem(bare_bd_violations.__globals__, "native_json_routes_gc", lambda: False)
    text = 'from workspace_run import native_json\nnative_json(gc, city, ["bd", "show"])'
    assert bare_bd_violations(REPO_ROOT / "fixture.py", text)
