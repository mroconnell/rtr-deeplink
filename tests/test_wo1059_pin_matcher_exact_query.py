"""WO-1059: a `key=value` pin in tenant_overrides.csv matches an exact
query parameter (or page hint), never any text that contains it.

Before this, `resolver._match_override()` tested every pin with
`needle in haystack`, so Town Square's `site=8` (Mendota Heights) also
fired on `?site=80` -- confirmed 2026-09-25 at 630a774:
`resolve_government(None, tenant_host="reflect-tst-mn.cablecast.tv",
path="/show/1?site=80")` returned us:place:2741696, tier pinned.

Every pin tested here is a real row from the committed CSV, loaded
through `registry.tenant_overrides()`. The URLs are built from each
pin's host plus a real path shape for that platform, named per shape
below. The "one extra digit" and "name that ends the same way" URLs are
synthetic by construction: they are what the old matcher got wrong, and
no real page with them has been seen (see the PR's page counts).
"""

from typing import List, Tuple

import pytest

from app.utils.gov_registry import registry, resolver
from app.utils.gov_registry.resolver import _key_value_pin_pairs, resolve_government

# Pins whose key is a real URL query parameter on that platform, and the
# real path each one's URL is built on.
URL_PARAM_PATHS = {
    # tests/test_townhallstreams.py: stream.php?location_id=94&id=75799
    "townhallstreams.com": "/stream.php?id=75799",
    # tests/test_base.py: agenda_publish.cfm?id=56691&get_month=7
    "public.destinyhosted.com": "/agenda_publish.cfm?get_month=7",
    # cablecast.py's own comment: watch-vod-embed?showId=5964&site=8
    "reflect-tst-mn.cablecast.tv": "/watch-vod-embed?showId=5964",
    # tests/test_invintus.py: /?clientID=...&eventID=...
    "player.invintus.com": "/",
    # Archive page 9904's own source URL: MeetingInformation.aspx?Id=3639
    # (WO-1061's per-meeting pins on this multi-government portal).
    "princeedwardcounty.civicweb.net": "/Portal/MeetingInformation.aspx",
}


def _key_value_rows() -> List[Tuple[str, object, list]]:
    out = []
    for host, rows in registry.tenant_overrides().items():
        for row in rows:
            if row.match is None:
                continue
            pairs = _key_value_pin_pairs(row.match.lower())
            if pairs is not None:
                out.append((host, row, pairs))
    return out


KV_ROWS = _key_value_rows()
URL_ROWS = [(h, r, p) for h, r, p in KV_ROWS if h in URL_PARAM_PATHS]
HINT_ROWS = [(h, r, p) for h, r, p in KV_ROWS if h not in URL_PARAM_PATHS]


def _url_path(host: str, pairs, *, alter=None) -> str:
    base = URL_PARAM_PATHS[host]
    params = "&".join(f"{k}={alter(v) if alter else v}" for k, v in pairs)
    return base + ("&" if "?" in base else "?") + params


def _fires(host: str, row, path: str, hints=None) -> bool:
    return row in resolver._match_override(host, path, hints)


def test_the_counts_the_brief_names():
    # Guards the loops below against silently checking nothing.
    by_key = {}
    for _h, _r, pairs in KV_ROWS:
        by_key[pairs[0][0]] = by_key.get(pairs[0][0], 0) + 1
    assert by_key["location_id"] == 34
    assert by_key["id"] == 18  # 16 DestinyHosted + 2 Prince Edward (WO-1061)
    assert by_key["site"] == 3
    assert by_key["clientid"] == 3
    assert by_key["external_id"] == 10
    assert by_key["channel"] > 1000


@pytest.mark.parametrize("host,row,pairs", URL_ROWS, ids=lambda x: str(x)[:40])
def test_url_param_pin_fires_on_its_own_exact_value(host, row, pairs):
    assert _fires(host, row, _url_path(host, pairs))


@pytest.mark.parametrize("host,row,pairs", URL_ROWS, ids=lambda x: str(x)[:40])
def test_url_param_pin_does_not_fire_on_one_extra_digit(host, row, pairs):
    assert not _fires(host, row, _url_path(host, pairs, alter=lambda v: v + "0"))


@pytest.mark.parametrize("host,row,pairs", URL_ROWS, ids=lambda x: str(x)[:40])
def test_url_param_pin_does_not_fire_on_a_name_that_ends_the_same(host, row, pairs):
    renamed = [(f"clip_{k}", v) for k, v in pairs]
    assert not _fires(host, row, _url_path(host, renamed))


@pytest.mark.parametrize("host,row,pairs", HINT_ROWS, ids=lambda x: str(x)[:40])
def test_hint_pin_fires_on_its_own_hint_and_not_a_longer_one(host, row, pairs):
    # `channel=`/`external_id=` pins match a page hint (the adapter's
    # `video_channel`/`external_id`, `resolver.page_hints_for()`), not the
    # URL. Path shape: a plain `/` -- the hint is what is being tested.
    (key, value) = pairs[0]
    assert _fires(host, row, "/", {key: value})
    assert not _fires(host, row, "/", {key: value + "0"})


@pytest.mark.parametrize(
    "site,expected",
    [
        ("6", "us:place:2731076"),  # Inver Grove Heights, MN
        ("8", "us:place:2741696"),  # Mendota Heights, MN
        ("15", "us:place:2769700"),  # West St. Paul, MN
    ],
)
def test_town_square_site_pins_resolve_to_their_own_town(site, expected):
    match = resolve_government(
        None, tenant_host="reflect-tst-mn.cablecast.tv", path=f"/show/1?site={site}"
    )
    assert match.gov_id == expected
    assert match.tier == resolver.TIER_PINNED


@pytest.mark.parametrize("site", ["60", "80", "150"])
def test_town_square_longer_site_numbers_get_no_pinned_government(site):
    match = resolve_government(
        None, tenant_host="reflect-tst-mn.cablecast.tv", path=f"/show/1?site={site}"
    )
    assert match.tier != resolver.TIER_PINNED


def test_destinyhosted_id_pin_ignores_clip_id():
    # "id=24263" is a substring of "clip_id=24263"; only a real `id=` fires.
    # 24263 is the City of Chandler, AZ (checked live 2026-09-25, WO-1056).
    hit = resolve_government(
        None,
        tenant_host="public.destinyhosted.com",
        path="/agenda_publish.cfm?id=24263",
    )
    miss = resolve_government(
        None, tenant_host="public.destinyhosted.com", path="/x.cfm?clip_id=24263"
    )
    assert hit.gov_id == "us:place:0412000"
    assert miss.tier != resolver.TIER_PINNED


def test_path_shaped_pins_still_match_as_text():
    # `vod/weston/video/...?page=HOME` has a "/" before its "=", so it stays
    # a text match (a real Castus pin row).
    assert (
        _key_value_pin_pairs("vod/weston/video/6a9884618f04390002ee839d?page=home")
        is None
    )
    assert _key_value_pin_pairs("/az/ccschools/") is None
    assert _key_value_pin_pairs("5lzqonrdmyk") is None
    assert _key_value_pin_pairs("site=8") == [("site", "8")]
