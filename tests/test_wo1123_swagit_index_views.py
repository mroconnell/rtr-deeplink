"""WO-1123: Swagit views that are only an index get filed, owner-proven.

Why (2026-09-26): rtr-discovery's first owner sweep (WO-1087) found 337
view pages with no meetings of their own. 108 of them are an index: they
link category pages (`/views/{n}/{slug}`) that hold the meetings (San
Benito TX's view 322 -> `commission-meetings`). A follow-up sweep read
each index's categories on the owner's own address and proved the owner
from two video pages (one, when the view holds a single meeting). This
files the 85 proven views whose owner is an rtr-discovery Swagit site.
Evidence: rtr-business `research/swagit_owner_sweep_2026-09-26/
index_view_sweep/results.jsonl`.
"""

from __future__ import annotations

import pytest

from app.platforms.swagit import known_views, known_views_for


@pytest.mark.parametrize(
    "host, view",
    [
        ("sanbenitotx.new.swagit.com", "322"),
        ("dart.new.swagit.com", "561"),
        ("cypressca.new.swagit.com", "630"),
        ("hgac.new.swagit.com", "634"),
        ("yellowknifent.new.swagit.com", "254"),
        ("tetoncountywy.new.swagit.com", "223"),
        ("tetoncountywy.new.swagit.com", "453"),
    ],
)
def test_an_index_view_is_filed_under_its_owner(host, view):
    assert view in known_views_for(host)


def test_a_known_owner_keeps_its_first_view_first():
    # Irving TX already had a view from WO-1087; the index view is added
    # after it, so `known_view_for()` still returns the older one.
    views = known_views_for("irvingtx.new.swagit.com")
    assert views[-1] == "697"
    assert len(views) >= 2


@pytest.mark.parametrize("view", ["117", "527", "556"])
def test_an_unproven_index_view_is_not_filed(view):
    # 117 (lead: Austin) and 527 (lead: Plano): one of the two video pages
    # was unreadable. 556 is tagged "buenaparkca-not a customer".
    owners = [host for host, views in known_views().items() if view in views]
    assert owners == []
