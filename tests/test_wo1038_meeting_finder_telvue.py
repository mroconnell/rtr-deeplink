"""WO-1038: TelVue in Meeting Finder ("...found 9 of 57 [TelVue
governments] across three runs"). Fixes covered here:

1. `telvue.account_url_for()` -- TelVue's real "account" is per-org-TOKEN
   (`/player/{token}/`), not per-host (every customer shares the same
   `videoplayer.telvue.com` host) -- generic `identify()` reduction would
   otherwise collapse every TelVue link down to the same useless bare
   host.
2. `passive_verify._telvue_walker()` -- lists a TelVue tenant's own
   `/home`/`/videos` page. Real bug found live against Exeter, NH's own
   page (2026-09-23): each card renders TWO anchors to the same href (one
   title-less, wrapping just the thumbnail), which silently dropped every
   real meeting's title if the title-less anchor happened to come first.
   Also sorts meeting-shaped titles (GOVERNING_BODY_KEYWORDS) ahead of a
   channel's other programming, since a TelVue lineup mixes both and
   `max_tries` wouldn't reach a real meeting behind enough of it.
3. `scan._is_specific_telvue_media_url()` / `_SCAN_MEDIA_PLATFORMS` --
   a TelVue/Cablecast `<iframe>` embed is now a real Scan media
   candidate, but only for a URL that names one specific video, not a
   TelVue listing page.

Fixture: `tests/fixtures/wo1038/telvue_home_exeter.html` -- synthetic
(see its own header comment), shape and titles copied from a real fetch
of Exeter, NH's TelVue `/home` page."""

from pathlib import Path

from app.platforms import passive_verify
from app.platforms import telvue
from app.platforms.meeting_finder.scan import (
    _is_specific_telvue_media_url,
    _anchor_media_candidates,
    find_meeting_page_links,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "wo1038" / "telvue_home_exeter.html"
).read_text()

ORG_TOKEN = "LyAOBTaTsnn_CnwjwcB5-VoxQtyoKR1P"
HOME_URL = f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/home"


def test_account_url_for_preserves_the_org_token():
    # A specific media/playlist/category page collapses to the token's
    # own canonical /home listing entry point...
    assert (
        telvue.account_url_for(
            f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/media/1042135"
        )
        == HOME_URL
    )
    assert (
        telvue.account_url_for(
            f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/playlists/4806/media/958491"
        )
        == HOME_URL
    )
    # ...a /stream/{n} live-stream link does too (Ryan's brief: "go to the
    # same token's /home or /videos to list VOD")...
    assert (
        telvue.account_url_for(
            f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/playlists/4983/stream/472"
        )
        == HOME_URL
    )
    # ...but a /home or /videos URL is already the account -- unchanged.
    assert telvue.account_url_for(HOME_URL) == HOME_URL
    videos_url = f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/videos"
    assert telvue.account_url_for(videos_url) == videos_url
    # No org token at all -- nothing to recover.
    assert telvue.account_url_for("https://videoplayer.telvue.com/") is None


def test_telvue_walker_survives_the_two_anchor_per_card_shape(monkeypatch):
    async def fake_fetch(url):
        assert url == HOME_URL
        return FIXTURE, url, None

    monkeypatch.setattr(passive_verify, "_fetch", fake_fetch)

    import asyncio

    rows = asyncio.run(passive_verify._telvue_walker(HOME_URL))

    urls = [r["url"] for r in rows]
    assert len(urls) == len(set(urls)) == 3  # no duplicate from the 2nd anchor

    titles_by_id = {r["url"].rsplit("/", 1)[-1]: r["title"] for r in rows}
    assert titles_by_id["1042135"] == "Select Board - 08/24/26"
    assert titles_by_id["1042940"] == "Planning Board - 09/10/26"
    assert "Biweekly Report" in titles_by_id["1042973"]

    # Meeting-shaped titles (a real governing body name) sort ahead of the
    # channel's other programming, so a small `max_tries` still reaches a
    # real meeting.
    assert rows[0]["title"] in {
        "Select Board - 08/24/26",
        "Planning Board - 09/10/26",
    }
    assert rows[1]["title"] in {
        "Select Board - 08/24/26",
        "Planning Board - 09/10/26",
    }
    assert "Biweekly Report" in rows[2]["title"]


def test_telvue_walker_scopes_to_its_own_org_token(monkeypatch):
    other_token_html = FIXTURE.replace(ORG_TOKEN, "someOtherSchoolDistrictToken")

    async def fake_fetch(url):
        return other_token_html, url, None

    monkeypatch.setattr(passive_verify, "_fetch", fake_fetch)

    import asyncio

    rows = asyncio.run(passive_verify._telvue_walker(HOME_URL))
    # `HOME_URL` still names the ORIGINAL org token, so a page that (for
    # whatever reason) came back carrying only a DIFFERENT token's links
    # yields nothing -- Medina, OH's real "schools + city" mixed-token
    # page is the real case this guards against.
    assert rows == []


def test_specific_telvue_media_url_excludes_listing_shapes():
    assert _is_specific_telvue_media_url(
        f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/media/1042135"
    )
    assert _is_specific_telvue_media_url(
        f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/playlists/4806/media/958491"
    )
    assert not _is_specific_telvue_media_url(HOME_URL)
    assert not _is_specific_telvue_media_url(
        f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/videos"
    )
    assert not _is_specific_telvue_media_url(
        f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/stream/472"
    )


def test_scan_treats_a_specific_telvue_iframe_as_a_media_candidate():
    media_url = f"https://videoplayer.telvue.com/player/{ORG_TOKEN}/media/1042135"
    html = f'<iframe src="{media_url}"></iframe>'
    candidates = _anchor_media_candidates(
        html, "https://auburnhills.org/meetings", lister="scan"
    )
    assert len(candidates) == 1
    assert candidates[0].platform == "telvue"
    assert candidates[0].url == media_url


def test_scan_does_not_treat_a_telvue_listing_iframe_as_a_media_candidate():
    html = f'<iframe src="{HOME_URL}"></iframe>'
    candidates = _anchor_media_candidates(
        html, "https://auburnhills.org/meetings", lister="scan"
    )
    assert candidates == []


def test_scan_still_offers_a_telvue_home_link_as_a_page_to_visit():
    # Unchanged from before this WO: a plain <a href> to a TelVue /home
    # page is still a "page" Scan hands back to be visited via Identify ->
    # List (that's how Irondequoit NY's real listing page gets reached).
    html = f'<a href="{HOME_URL}">Watch Meetings</a>'
    links = find_meeting_page_links(html, "https://irondequoit.gov/meetings")
    assert any(url == HOME_URL for url, _date, _title in links)
