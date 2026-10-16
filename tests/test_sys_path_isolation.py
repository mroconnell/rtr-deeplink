"""Backlog triage 2026-10-16: an imported sweep script that puts
`~/Documents/rtr-discovery` on sys.path must not keep it there for the rest
of the run. conftest.py drops such entries after collection and after each
test; this checks the helper it uses."""

import sys
from pathlib import Path

from conftest import drop_foreign_sys_path_entries

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_an_outside_entry_is_dropped_and_a_repo_entry_is_kept():
    outside = str(Path.home() / "Documents" / "rtr-discovery")
    inside = str(_REPO_ROOT / "scripts")
    had_inside = inside in sys.path
    sys.path.insert(0, outside)
    sys.path.insert(0, inside)
    try:
        removed = drop_foreign_sys_path_entries()
        assert outside in removed
        assert outside not in sys.path
        assert inside in sys.path
    finally:
        if not had_inside:
            while inside in sys.path:
                sys.path.remove(inside)
        while outside in sys.path:
            sys.path.remove(outside)
