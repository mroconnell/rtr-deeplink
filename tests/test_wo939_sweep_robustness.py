"""WO-939 (2026-09-21): the remaining sweep-robustness fixes that don't
already have their own dedicated test file --
- wo149_county_ladder_sweep.py's find_hop_links() import (was its own
  separate, unranked copy; WO-228's scored ranking never reached it).
- wo191_access_ladder_sweep.py's init_headless_budget() (was two manual
  steps a reusing WO had to remember; forgetting the second silently
  inherited a stale cumulative count -- the real WO-218 incident).
- wo282_recon.py's/wo282_targeted.py's polite_request()/polite_fetch()/
  cdx_get()/wayback_id_read() (moved verbatim from the now-retired
  wo273_recon.py/wo273_targeted.py, WO-1019 2026-09-23) wrap their
  requests.request()/requests.get() calls in run_with_deadline(), the
  shared fix for the real WO-322 slow-trickling-response hang.

(scripts/sweep_deadline.py and scripts/challenge_markers.py have their own
test files; app/platforms/base.py's youtube_resolve_guard()/
resolve_via_platform(allow_youtube=...) are covered in tests/test_base.py.)
"""

import json
import sys
from pathlib import Path


def _import_script(name: str):
    sys.path.insert(0, "scripts")
    try:
        return __import__(name)
    finally:
        if sys.path and sys.path[0] == "scripts":
            sys.path.pop(0)


def test_wo149_find_hop_links_is_wo147s_scored_version_not_its_own_copy():
    # wo149 imports via `from scripts.wo147_access_ladder_sweep import
    # find_hop_links` (package-qualified) -- import it the same way here,
    # not the bare `_import_script()` helper, which would load wo147
    # under a SECOND module-cache key (`wo147_access_ladder_sweep`
    # instead of `scripts.wo147_access_ladder_sweep`) and produce a
    # different-but-equal function object, making an `is` check
    # meaningless. See test_challenge_markers.py's own note on the same
    # dual-import-path Python behavior.
    from scripts.wo147_access_ladder_sweep import find_hop_links as w147_find_hop_links

    w149 = _import_script("wo149_county_ladder_sweep")

    # Same function object -- confirms wo149 no longer defines its own
    # separate find_hop_links() (the old, unranked, first-match version
    # WO-228's scoring fix never reached), and picks up any future fix to
    # wo147's version automatically.
    assert w149.find_hop_links is w147_find_hop_links
    assert w149.find_hop_links.__module__ == "scripts.wo147_access_ladder_sweep"


def test_wo149_find_hop_links_real_call_shape_still_works():
    # wo149's own hop loop calls find_hop_links(html, final_url)
    # positionally, two args -- confirm that still works against wo147's
    # newer (legacy=False, gov_id="" keyword-only) signature.
    w149 = _import_script("wo149_county_ladder_sweep")
    html = (
        "<html><body>"
        '<a href="https://example.gov/agenda">Agenda</a>'
        '<a href="https://example.gov/about">About</a>'
        "</body></html>"
    )
    links = w149.find_hop_links(html, "https://example.gov/")
    assert any("agenda" in link for link in links)


def test_init_headless_budget_re_derives_from_the_new_file_not_the_old_one(
    tmp_path,
):
    # Real, confirmed incident (WO-218, 2026-09-11) this pins: overriding
    # HEADLESS_BUDGET_JSON alone left _headless_used holding whatever
    # wo191's OWN file had at import time (579 in the real incident,
    # already over any per-WO cap) -- silently disabling the headless
    # rung for the whole run with no error.
    w191 = _import_script("wo191_access_ladder_sweep")

    stale_file = tmp_path / "stale_budget.json"
    stale_file.write_text(json.dumps({"used": 579}))
    w191.HEADLESS_BUDGET_JSON = stale_file
    w191._headless_used = w191._load_headless_used()
    assert w191._headless_used == 579  # sanity: simulating the old state

    fresh_file = tmp_path / "fresh_budget.json"
    w191.init_headless_budget(fresh_file, 150)

    assert w191.HEADLESS_BUDGET_JSON == fresh_file
    assert w191.HEADLESS_BUDGET_TOTAL == 150
    assert w191._headless_used == 0  # re-derived from the NEW, empty file


def test_init_headless_budget_reads_a_real_existing_count_from_the_new_file(
    tmp_path,
):
    w191 = _import_script("wo191_access_ladder_sweep")

    existing_file = tmp_path / "existing_budget.json"
    existing_file.write_text(json.dumps({"used": 42}))

    w191.init_headless_budget(existing_file, 600)

    assert w191._headless_used == 42


def test_wo218_ladder_sweep_uses_init_headless_budget_not_the_old_two_step_dance():
    # Confirms the real, already-shipped reuser (wo218_ladder_sweep.py)
    # was updated to the new single-call helper, not left on the old
    # error-prone pattern the helper exists to replace.
    source = Path("scripts/wo218_ladder_sweep.py").read_text()
    assert "wo191.init_headless_budget(" in source
    assert "wo191._headless_used = wo191._load_headless_used()" not in source


def test_wo282_recon_polite_request_and_cdx_calls_use_run_with_deadline():
    # wo282_recon.py imports run_with_deadline bare (`from sweep_deadline
    # import ...`, not `scripts.sweep_deadline` -- see its own WO-939
    # comment, carried over verbatim from the retired wo273_recon.py), so
    # it's re-imported the same way here rather than via tests.sweep_
    # deadline's own `scripts.sweep_deadline` path -- same dual-import-path
    # note as test_challenge_markers.py.
    w282 = _import_script("wo282_recon")
    bare_deadline_module = _import_script("sweep_deadline")
    source = Path("scripts/wo282_recon.py").read_text()

    assert w282.run_with_deadline is bare_deadline_module.run_with_deadline
    # All three real hang sites identified while re-deriving this entry
    # (polite_request()'s live robots.txt/sitemap fetch, cdx_get()'s and
    # wayback_id_read()'s archive calls) now route through it.
    assert source.count("run_with_deadline(") >= 3


def test_wo282_targeted_polite_fetch_uses_run_with_deadline():
    # wo282_targeted.py is the "phase 3" sibling of wo282_recon.py, with
    # its own separate polite_fetch() (moved verbatim from the retired
    # wo273_targeted.py, WO-1019) carrying the identical WO-322 gap
    # (confirmed live: wo337_targeted.py's own capped_polite_fetch() was
    # already built as a workaround in ITS OWN copy specifically because
    # this shared module still needed the real fix -- see that file's own
    # comment). Fixed here at the shared-module level instead.
    w282t = _import_script("wo282_targeted")
    bare_deadline_module = _import_script("sweep_deadline")
    assert w282t.run_with_deadline is bare_deadline_module.run_with_deadline
    assert "run_with_deadline" in Path("scripts/wo282_targeted.py").read_text()
