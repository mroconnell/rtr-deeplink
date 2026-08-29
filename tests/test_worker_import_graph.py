"""BACKLOG.md's "CI guard for the worker's real import graph" -- see
scripts/check_worker_import_graph.py's own module docstring for the full
reasoning and the 2026-08-24 markupsafe outage this is defense-in-depth
for. Running this as a pytest test (not just a standalone script) means a
future regression fails the existing `pytest` CI gate rather than only
surfacing at worker startup, which is the whole point of building it.
"""

import ast
from pathlib import Path

from scripts.check_worker_import_graph import (
    ENTRY_POINT,
    WORKER_REQUIREMENTS,
    _collect_called_names,
    find_missing_worker_dependencies,
)


def test_worker_requirements_covers_the_real_import_graph():
    missing = find_missing_worker_dependencies()
    assert not missing, (
        "worker/requirements.txt is missing packages the worker's real "
        f"import graph needs: {missing}. If this is a genuinely new "
        "dependency, add it to worker/requirements.in and re-run "
        "pip-compile; if it's meant to be optional, guard the import with "
        "try/except ImportError the way headless_browser.py's playwright "
        "import already is."
    )


def test_a_genuinely_undeclared_module_scope_import_is_detected():
    # Regression test for the checker itself, not the worker: proves this
    # would have caught the real 2026-08-24 incident's exact shape
    # (archive/utils/date_status.py importing markupsafe at module scope
    # before that fix -- see BACKLOG_DONE.md) rather than just happening
    # to pass today because nothing is currently broken.
    from scripts import check_worker_import_graph as m

    fake_path = ENTRY_POINT.parent.parent / "archive" / "utils" / "date_status.py"
    tree = ast.parse(
        "import some_totally_undeclared_fake_package_xyz\n", filename=str(fake_path)
    )
    required = {}
    m._extract_required_imports(
        tree.body,
        path=fake_path,
        called_names=set(),
        required=required,
        guarded=False,
        type_checking=False,
        owner_func=None,
        owner_class=None,
    )
    assert "some_totally_undeclared_fake_package_xyz" in required


def test_try_except_import_error_guarded_imports_are_not_required():
    # headless_browser.py's own playwright import -- deliberately absent
    # from worker/requirements.txt (see that file's own comment). Proves
    # the guard-detection logic itself, independent of whatever the real
    # file currently contains.
    from scripts import check_worker_import_graph as m

    src = (
        "try:\n"
        "    import some_optional_package_abc\n"
        "except ImportError:\n"
        "    some_optional_package_abc = None\n"
    )
    tree = ast.parse(src, filename="fake.py")
    required = {}
    m._extract_required_imports(
        tree.body,
        path=Path("fake.py"),
        called_names=set(),
        required=required,
        guarded=False,
        type_checking=False,
        owner_func=None,
        owner_class=None,
    )
    assert "some_optional_package_abc" not in required


def test_dead_init_is_not_required_but_a_called_class_init_is():
    # The exact discrimination this script exists to make: a class's
    # __init__ only counts as reachable if the class is ever instantiated
    # somewhere in the graph. GeminiTranscriptionEngine's own
    # `from google import genai` is the real live example (confirmed dead
    # -- build_default_engine() always returns FasterWhisperEngine(),
    # never Gemini, see BACKLOG_DONE.md's "Gemini 3.5 Transcribe"
    # decision), reproduced synthetically here so this test doesn't
    # silently stop meaning anything if that file changes shape later.
    from scripts import check_worker_import_graph as m

    src = (
        "class NeverInstantiated:\n"
        "    def __init__(self):\n"
        "        import dead_dependency\n"
        "\n"
        "class ActuallyUsed:\n"
        "    def __init__(self):\n"
        "        import live_dependency\n"
        "\n"
        "ActuallyUsed()\n"
    )
    tree = ast.parse(src, filename="fake.py")
    called_names = _collect_called_names(tree)
    required = {}
    m._extract_required_imports(
        tree.body,
        path=ENTRY_POINT,  # any real repo-relative path; content is synthetic
        called_names=called_names,
        required=required,
        guarded=False,
        type_checking=False,
        owner_func=None,
        owner_class=None,
    )
    assert "dead_dependency" not in required
    assert "live_dependency" in required


def test_collect_called_names_ignores_attribute_calls():
    # Real bug caught while building this script: collecting `obj.attr(...)`
    # calls by bare attribute name put dunder names like `__init__` into
    # the called-names set the moment *any* class anywhere calls
    # `super().__init__(...)` -- which every class here does -- which
    # silently made every class's own __init__ read as "reachable"
    # regardless of whether the class itself was ever instantiated.
    tree = ast.parse(
        "class Foo:\n    def __init__(self):\n        super().__init__()\n"
    )
    called = _collect_called_names(tree)
    assert "__init__" not in called


def test_worker_requirements_file_exists():
    # Sanity check the constants themselves resolve correctly in this
    # checkout, so a future path rename fails loudly here instead of the
    # main test silently checking nothing (an empty graph would also
    # report "no missing dependencies").
    assert ENTRY_POINT.is_file()
    assert WORKER_REQUIREMENTS.is_file()
