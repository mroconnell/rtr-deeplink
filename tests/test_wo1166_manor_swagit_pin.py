"""WO-1166: Manor, TX posts meeting video on Swagit, not its CivicPlus site.

Checked live 2026-09-29 (evidence in the row of `tenant_overrides.csv`).
"""

from app.utils.gov_registry.resolver import resolve_government


def test_manor_swagit_resolves_to_manor():
    got = resolve_government(None, tenant_host="manortx.new.swagit.com", path="/")
    assert got.gov_id == "us:place:4846440"
