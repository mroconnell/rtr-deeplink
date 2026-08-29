"""Static checker for BACKLOG.md's "CI guard for the worker's real import
graph" entry -- defense-in-depth on top of the 2026-08-24 markupsafe
outage fix (see BACKLOG_DONE.md), not a replacement for it. That outage's
actual mechanism (archive/utils/date_status.py importing markupsafe at
module scope, made a hard worker dependency via archive/db/crud.py) is
closed; this exists so a *different* future import added anywhere in the
worker's reachable graph fails here instead of only at worker startup.

Graph reachability (which files to even look at) follows every local
app./archive./worker. import found *anywhere* in a file, not just at
module top level -- because app/platforms/__init__.py's
register_all_finders() imports every platform adapter from inside its own
function body on purpose (see that function's docstring), and worker/
main.py's run_forever() calls it unconditionally on every real run.
Restricting graph traversal to module-level imports alone would never
reach a single adapter file.

Within a visited file, a *nested* (non-module-level) import is only
counted as something the worker really needs if the function/class it
lives in is itself demonstrably reachable:

- A module-top-level import always counts (unless guarded, see below).
- An import inside a plain function counts if that function's name
  appears anywhere in the whole graph as a direct call (`name(...)`) --
  e.g. worker/main.py's own `_init_sentry()`, called unconditionally
  right after its own definition, whose nested `import sentry_sdk` would
  otherwise be invisible to a module-level-only check.
- An import inside a class's `__init__` counts if that class name
  appears anywhere as a direct call (i.e. the class is ever instantiated)
  -- e.g. FasterWhisperEngine() (real, called from build_default_engine()).
- Anything else is treated as optional. This is deliberately how
  GeminiTranscriptionEngine's own `from google import genai` (inside its
  `__init__`) is excluded: build_default_engine() always returns
  FasterWhisperEngine(), never Gemini (confirmed dead from the cloud
  worker's perspective -- see BACKLOG_DONE.md's "Gemini 3.5 Transcribe"
  decision), so `GeminiTranscriptionEngine(...)` never appears as a call
  anywhere in the reachable graph. This is a shallow, name-based
  approximation, not real call-graph/type analysis -- it would be fooled
  by a method invoked only through an attribute call on an object whose
  type it can't resolve, but no such pattern exists anywhere in this
  codebase today (verified by hand against every nested import this
  script's own graph walk turns up; extend this docstring's reasoning if
  that ever changes).

A module-level import guarded by `try: ... except (ImportError,
ModuleNotFoundError, Exception):` (headless_browser.py's own playwright
import -- deliberately absent from worker/requirements.txt, see that
file's own comment) or sitting inside `if TYPE_CHECKING:` (never executes
at runtime at all) is always excluded, regardless of nesting.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ROOTS = ("app", "archive", "worker")
ENTRY_POINT = REPO_ROOT / "worker" / "main.py"
WORKER_REQUIREMENTS = REPO_ROOT / "worker" / "requirements.txt"

# Import name -> real pip package name, for the cases where they genuinely
# differ (not just case/hyphen/underscore -- _normalize() already handles
# those). Extend this if a future import needs it; the checker's own
# failure message says which name wasn't found.
_IMPORT_TO_PIP_NAME = {
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "yaml": "PyYAML",
    "PIL": "Pillow",
    "jwt": "PyJWT",
    "dateutil": "python-dateutil",
}

_GUARD_EXCEPTION_NAMES = {"ImportError", "ModuleNotFoundError", "Exception"}


def _normalize(name: str) -> str:
    return name.lower().replace("-", "").replace("_", "")


def _top_level_name(dotted: str) -> str:
    return dotted.split(".")[0]


def _find_local_module_file(dotted: str) -> Optional[Path]:
    if not dotted or _top_level_name(dotted) not in LOCAL_ROOTS:
        return None
    base = REPO_ROOT.joinpath(*dotted.split("."))
    as_module = base.with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = base / "__init__.py"
    if as_package.is_file():
        return as_package
    return None


def _dotted_name_for_file(path: Path) -> str:
    rel_parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if rel_parts[-1] == "__init__":
        rel_parts = rel_parts[:-1]
    return ".".join(rel_parts)


def _package_dotted_for_file(path: Path) -> str:
    """The dotted package a relative import inside `path` resolves against."""
    dotted = _dotted_name_for_file(path)
    if path.name == "__init__.py":
        return dotted
    parts = dotted.split(".")
    return ".".join(parts[:-1])


def _resolve_relative_base(
    path: Path, level: int, module: Optional[str]
) -> Optional[str]:
    pkg_dotted = _package_dotted_for_file(path)
    pkg_parts = pkg_dotted.split(".") if pkg_dotted else []
    drop = level - 1
    if drop > len(pkg_parts):
        return None
    base_parts = pkg_parts[: len(pkg_parts) - drop] if drop else pkg_parts
    if module:
        return ".".join([*base_parts, *module.split(".")]) if base_parts else module
    return ".".join(base_parts) if base_parts else None


def _local_import_targets(path: Path, node: ast.AST) -> List[str]:
    """Every dotted local-module name a single Import/ImportFrom node
    might resolve to, for BFS edge-following -- used regardless of where
    in the file the node lives (see module docstring)."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    assert isinstance(node, ast.ImportFrom)
    if node.level == 0:
        base_dotted = node.module
    else:
        base_dotted = _resolve_relative_base(path, node.level, node.module)
    if not base_dotted or _top_level_name(base_dotted) not in LOCAL_ROOTS:
        return []
    # A `from pkg import name` may import a submodule (`name` is a file)
    # or a re-exported attribute (`name` lives in pkg/__init__.py) --
    # return both candidates rather than guess which.
    return [f"{base_dotted}.{a.name}" for a in node.names] + [base_dotted]


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _handler_is_import_guard(handler: ast.excepthandler) -> bool:
    if handler.type is None:  # bare except
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        isinstance(n, ast.Name) and n.id in _GUARD_EXCEPTION_NAMES for n in names
    )


def _collect_called_names(tree: ast.Module) -> Set[str]:
    """Every plain `name(...)` call target anywhere in the module -- both
    a direct function call and a class instantiation are the same AST
    shape (`Call(func=Name(...))`), which is what lets one check cover
    both `_init_sentry()` and `FasterWhisperEngine()`.

    Deliberately NOT `obj.name(...)` (`ast.Attribute` calls): `attr` alone
    is just the method name with no receiver type, so collecting those
    would put dunder names like `__init__` into this set the moment
    *any* class anywhere calls `super().__init__(...)` -- which every
    class here does -- silently making the `__init__`-reachability check
    below true for every class regardless of whether it's ever
    instantiated. Confirmed live while building this script: without
    this restriction, GeminiTranscriptionEngine's own `__init__` read as
    "reachable" purely because some unrelated class's `__init__` was
    called via `super()` elsewhere in the graph."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def _record_if_third_party(top: str, path: Path, required: Dict[str, Set[str]]) -> None:
    if top in LOCAL_ROOTS or top in sys.stdlib_module_names:
        return
    required.setdefault(top, set()).add(str(path.relative_to(REPO_ROOT)))


def _extract_required_imports(
    stmts: List[ast.stmt],
    *,
    path: Path,
    called_names: Set[str],
    required: Dict[str, Set[str]],
    guarded: bool,
    type_checking: bool,
    owner_func: Optional[str],
    owner_class: Optional[str],
) -> None:
    reachable = (
        owner_func is None
        or owner_func in called_names
        or (owner_func == "__init__" and owner_class in called_names)
    )
    for stmt in stmts:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            if guarded or type_checking or not reachable:
                continue
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    _record_if_third_party(_top_level_name(alias.name), path, required)
            elif stmt.level == 0 and stmt.module:
                _record_if_third_party(_top_level_name(stmt.module), path, required)
            # A module-top-level relative import (level > 0) is always
            # local in this repo -- nothing third-party to record.
        elif isinstance(stmt, ast.Try):
            try_guarded = guarded or any(
                _handler_is_import_guard(h) for h in stmt.handlers
            )
            _extract_required_imports(
                stmt.body,
                path=path,
                called_names=called_names,
                required=required,
                guarded=try_guarded,
                type_checking=type_checking,
                owner_func=owner_func,
                owner_class=owner_class,
            )
            for handler in stmt.handlers:
                _extract_required_imports(
                    handler.body,
                    path=path,
                    called_names=called_names,
                    required=required,
                    guarded=guarded,
                    type_checking=type_checking,
                    owner_func=owner_func,
                    owner_class=owner_class,
                )
            for extra in (stmt.orelse, stmt.finalbody):
                _extract_required_imports(
                    extra,
                    path=path,
                    called_names=called_names,
                    required=required,
                    guarded=guarded,
                    type_checking=type_checking,
                    owner_func=owner_func,
                    owner_class=owner_class,
                )
        elif isinstance(stmt, ast.If):
            this_type_checking = type_checking or _is_type_checking_test(stmt.test)
            _extract_required_imports(
                stmt.body,
                path=path,
                called_names=called_names,
                required=required,
                guarded=guarded,
                type_checking=this_type_checking,
                owner_func=owner_func,
                owner_class=owner_class,
            )
            _extract_required_imports(
                stmt.orelse,
                path=path,
                called_names=called_names,
                required=required,
                guarded=guarded,
                type_checking=type_checking,
                owner_func=owner_func,
                owner_class=owner_class,
            )
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _extract_required_imports(
                stmt.body,
                path=path,
                called_names=called_names,
                required=required,
                guarded=guarded,
                type_checking=type_checking,
                owner_func=stmt.name,
                owner_class=owner_class if owner_func is None else None,
            )
        elif isinstance(stmt, ast.ClassDef):
            _extract_required_imports(
                stmt.body,
                path=path,
                called_names=called_names,
                required=required,
                guarded=guarded,
                type_checking=type_checking,
                owner_func=owner_func,
                owner_class=stmt.name,
            )
        else:
            # Generic statement (For/While/With/...) -- recurse into any
            # nested statement-list fields so an import inside one is
            # still found at the same reachability level.
            for field_name in ("body", "orelse", "finalbody"):
                field = getattr(stmt, field_name, None)
                if isinstance(field, list):
                    _extract_required_imports(
                        field,
                        path=path,
                        called_names=called_names,
                        required=required,
                        guarded=guarded,
                        type_checking=type_checking,
                        owner_func=owner_func,
                        owner_class=owner_class,
                    )


def build_worker_import_graph() -> Dict[str, Set[str]]:
    """Returns {top-level import name: {repo-relative file paths that
    reachably import it}} for every file reachable from worker/main.py."""
    visited: Set[Path] = set()
    queue = [ENTRY_POINT]
    trees: Dict[Path, ast.Module] = {}

    while queue:
        path = queue.pop()
        if path in visited or not path.is_file():
            continue
        visited.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[path] = tree

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for dotted in _local_import_targets(path, node):
                    local_file = _find_local_module_file(dotted)
                    if local_file and local_file not in visited:
                        queue.append(local_file)

    called_names: Set[str] = set()
    for tree in trees.values():
        called_names |= _collect_called_names(tree)

    required: Dict[str, Set[str]] = {}
    for path, tree in trees.items():
        _extract_required_imports(
            tree.body,
            path=path,
            called_names=called_names,
            required=required,
            guarded=False,
            type_checking=False,
            owner_func=None,
            owner_class=None,
        )

    return required


def _declared_worker_packages() -> Set[str]:
    names: Set[str] = set()
    for raw_line in WORKER_REQUIREMENTS.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[=\[<>; ]", line)[0]
        if name:
            names.add(_normalize(name))
    return names


def find_missing_worker_dependencies() -> Dict[str, Set[str]]:
    """{import name: {files}} for every third-party import the worker's
    real reachable graph needs but worker/requirements.txt doesn't
    declare. Empty when everything is covered."""
    required = build_worker_import_graph()
    declared = _declared_worker_packages()
    missing = {}
    for top, files in required.items():
        pip_name = _IMPORT_TO_PIP_NAME.get(top, top)
        if _normalize(pip_name) not in declared:
            missing[top] = files
    return missing


if __name__ == "__main__":
    missing_deps = find_missing_worker_dependencies()
    if not missing_deps:
        print(
            "worker's reachable import graph is fully covered by "
            "worker/requirements.txt"
        )
        sys.exit(0)
    print(
        "Packages imported by the worker's reachable graph but missing "
        "from worker/requirements.txt:"
    )
    for name, files in sorted(missing_deps.items()):
        print(f"  {name} (used by: {', '.join(sorted(files))})")
    sys.exit(1)
