"""WO-1050 (2026-09-24): eScribe tenant pins that named the wrong
government.

A bulk sweep (`wildcard_http_sweep_2`) pinned bare eScribe hosts by
matching the slug's letters against the national tables, so
`norfolkcounty` became Norfolk County, MA and `salinecounty` became Saline
County, MO. Every tenant below was re-checked live from its own public
meeting pages on 2026-09-24 (see BACKLOG_DONE.md's WO-1050 entry for the
quoted evidence). These tests pin the corrected answers, and use the name
string the eScribe adapter really extracts for each tenant today.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government


@pytest.mark.parametrize(
    "raw_name, tenant_host, gov_id",
    [
        # Real extracted names (no state) that used to leave pages with
        # no government at all.
        ("Saline County", "pub-salinecounty.escribemeetings.com", "us:county:20169"),
        ("Norfolk County", "pub-norfolkcounty.escribemeetings.com", "ca:csd:3528052"),
        # "Langley" alone also matches Langley, WA; the tenant is the City
        # of Langley, BC (not the separate Township of Langley).
        ("Langley", "pub-langleycity.escribemeetings.com", "ca:csd:5915002"),
        ("Langley, WA", "pub-langleycity.escribemeetings.com", "ca:csd:5915002"),
        # Bare staff-login hosts, corrected to match their public twin.
        ("", "norfolkcounty.escribemeetings.com", "ca:csd:3528052"),
        ("", "salinecounty.escribemeetings.com", "us:county:20169"),
        ("", "oxfordcounty.escribemeetings.com", "ca:cd:3532"),
        ("", "halifax.escribemeetings.com", "ca:csd:1209034"),
        ("", "hainescity.escribemeetings.com", "us:place:1228400"),
        ("", "langleycity.escribemeetings.com", "ca:csd:5915002"),
        ("", "shelburne.escribemeetings.com", "ca:csd:3522021"),
        ("", "strathcona.escribemeetings.com", "ca:csd:4811052"),
        ("", "wellington.escribemeetings.com", "ca:cd:3523"),
    ],
)
def test_escribe_tenant_resolves_to_its_real_government(raw_name, tenant_host, gov_id):
    assert (
        resolve_government(raw_name or None, tenant_host=tenant_host).gov_id == gov_id
    )
