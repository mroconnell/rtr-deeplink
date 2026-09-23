"""Regression test: process_government_v2() must read the keys that
wo273_recon.fetch_wayback_domain_index() actually returns.

WO-366 (2026-09-14) renamed that function's `narrow_urls` output to
`top_urls`, but every per-WO recon clone kept copying
`wayback_index["narrow_urls"]` into its record. That raised a KeyError on
every government whenever the CDX health check passed; cmd_sweep() catches
it and writes an `access_mode: "error"` stub instead of a real record. A
real production run on 2026-09-22 hit it 49 times (see rtr-business
research/dns_ctlog_sweep_2026-09-17/production_run_2026-09-22/
wayback_recheck.py's docstring).

The earlier tests never caught it because nothing ran process_government_v2
with cdx_healthy=True. This one does, for every clone. It stubs every
network call EXCEPT fetch_wayback_domain_index itself -- that runs for
real against a stubbed `cdx_get`, so a future key rename on either side
fails here. The CDX rows are hand-built (synthetic) but use the real CDX
JSON shape (header row, then [original, timestamp]) that function parses.
"""

import importlib
import json
import types

import pytest

RECON_MODULES = [
    "wo282_recon",
    "wo283_recon",
    "wo320_recon",
    "wo321_recon",
    "wo322_recon",
    "wo323_recon",
    "wo324_recon",
    "wo325_recon",
    "wo331_recon",
    "wo337_recon",
    "wo338_recon",
]

CDX_ROWS = [
    ["original", "timestamp"],
    ["https://example.gov/agendas-minutes", "20260101000000"],
    ["https://example.gov/parks", "20260101000000"],
]


def _homepage_stub(domain):
    return {
        "fetched": True,
        "access_mode": "direct",
        "status": 200,
        "final_url": f"https://{domain}/",
        "homepage_gz_path": "",
        "link_count": 0,
        "links": [],
        "human_gate": False,
        "error": "",
    }


@pytest.mark.parametrize("module_name", RECON_MODULES)
def test_process_government_v2_records_wayback_top_urls(monkeypatch, module_name):
    mod = importlib.import_module(f"scripts.{module_name}")
    # WO-1019 folded wo273_recon's helpers into wo282_recon itself, so
    # wo282_recon has no `w273` alias; the clones still reach the helpers
    # through one. Patch whichever module actually holds them.
    w273 = getattr(mod, "w273", mod)

    monkeypatch.setattr(mod, "maybe_refresh_cdx_health", lambda: True)
    monkeypatch.setattr(mod, "dns_has_any_answer", lambda _info: True)
    monkeypatch.setattr(mod, "fetch_homepage", _homepage_stub)
    monkeypatch.setattr(mod, "fetch_live_robots_v2", lambda _d: {})
    monkeypatch.setattr(
        mod,
        "fetch_live_sitemap_v2",
        lambda _d, _r: {"found": False, "url_count": 0, "urls": [], "error": ""},
    )
    monkeypatch.setattr(w273, "dns_lookup", lambda _d: {})
    monkeypatch.setattr(w273, "fetch_archived_sitemap_and_robots", lambda _d: {})
    monkeypatch.setattr(w273, "probe_common_crawl", lambda: "")
    monkeypatch.setattr(
        w273,
        "cdx_get",
        lambda _url: types.SimpleNamespace(text=json.dumps(CDX_ROWS)),
    )

    record = mod.process_government_v2({"domain": "example.gov"})

    assert record["cdx_healthy_at_time"] is True
    wayback = record["wayback_index"]
    assert wayback["reachable"] is True
    assert wayback["broad_row_count"] == 2
    assert "narrow_urls" not in wayback
    assert "https://example.gov/agendas-minutes" in wayback["top_urls"]
