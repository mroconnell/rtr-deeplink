"""WO-1027: `app/platforms/meeting_finder/identify.py` -- Identify says
which platform a page is on, and which account.

Every test passes `fetcher=None` when it also passes `page=` (an
already-fetched `FetchResult`) -- `identify()` never touches `fetcher`
once a `page` is supplied (see that function's own docstring), and for
the "no fetch needed" cases (a URL `detect_platform()`/`host_recognition`
already resolves) it never reaches the fetch step at all. This keeps
every test here fully offline and deterministic -- no real network call,
no monkeypatched `Fetcher`.

Two kinds of coverage, per CLAUDE.md's own rule about synthetic tests:

- `tests/fixtures/civiclive/escalon_city_council_agendas.html` (already in
  the repo, real, captured live for `civiclive.py`) and
  `tests/fixtures/civiclive/piedmont_ca_gov_footer_excerpt.html` (new,
  this WO -- a real, verbatim excerpt fetched live 2026-09-23 from
  https://piedmont.ca.gov/, see that fixture's own header comment) cover
  the CivicLive-on-a-first-party-domain footer heuristic against REAL
  captured pages, not invented markup.
- The ranking/branch tests below (own-site meeting page, direct media,
  other-video-host, YouTube meeting-list-vs-lead, account-not-found, the
  Granicus GovAccess footer) are synthetic HTML built to exercise ONE
  logic branch each, per CLAUDE.md's synthetic-test rule -- each uses a
  URL SHAPE already confirmed real elsewhere in this repo (a real
  `.mp4`/vimeo id, the real `/internetchannel/show/{id}` Cablecast shape
  already documented in `app/platforms/base.py`, the real Granicus
  GovAccess footer credit measured live on Lake Helen, FL) rather than a
  fabricated shape, and is commented as synthetic where it matters.
- The redirect-then-host-match test (San Rafael -> Laserfiche Cloud) uses
  the REAL confirmed redirect target from rtr-upcoming's 2026-09-23
  finding (cited in docs/MEETING_FINDER.md and this WO's brief) --
  constructed directly as a `FetchResult` rather than a live fetch, since
  only the HOST match matters for that branch, not page content.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.identify import identify
from app.platforms.meeting_finder.models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
)
from tests.conftest import load_fixture


@pytest.fixture(autouse=True, scope="module")
def _register_finders():
    """`_supported_flag()` (identify.py) reads `base._REGISTRY` -- this
    package's tests don't get that populated for free (unlike
    `resolve.py`'s tests, which mock `resolve_via_platform` directly and
    never touch the registry). Idempotent and process-global, same as
    every real caller (the CLI calls this once at startup)."""
    from app.platforms import register_all_finders

    register_all_finders()


def _page(
    html: str | None,
    *,
    final_url: str,
    status: int | None = 200,
    outcome: str | None = None,
    links_only: bool = False,
) -> FetchResult:
    return FetchResult(
        requested_url=final_url,
        final_url=final_url,
        status=status,
        html=html,
        access_mode="plain",
        outcome=outcome,
        challenge=False,
        wayback_timestamp=None,
        links_only=links_only,
        elapsed_ms=1,
    )


# --- Rule 1: URL first, no fetch --------------------------------------


async def test_url_only_match_needs_no_fetch():
    result = await identify("https://adamscounty.primegov.com", fetcher=None, page=None)
    assert result.platform == "primegov"
    assert result.supported is True
    assert result.account_url == "https://adamscounty.primegov.com/"
    assert result.outcome is None
    assert result.page is None  # never fetched


async def test_path_only_match_needs_no_fetch():
    # CivicPlus AgendaCenter is one of base.py's own netloc-independent
    # path branches (host_recognition.platform_for_path() picks it up via
    # a neutral placeholder host) -- a real, common self-hosted shape.
    result = await identify(
        "https://www.exampletown-nc.gov/AgendaCenter", fetcher=None, page=None
    )
    assert result.platform == "civicplus"
    assert result.supported is True


# --- Rule 2: check hosts on the FINAL url after redirects ---------------


async def test_redirect_to_unsupported_platform_host():
    # Real finding (rtr-upcoming, 2026-09-23):
    # publicrecords.cityofsanrafael.org redirects straight to a Laserfiche
    # Cloud repository -- host_recognition.UNSUPPORTED_PLATFORMS already
    # knows portal.laserfiche.com has no adapter.
    page = _page(
        "<html></html>",
        final_url="https://portal.laserfiche.com/Portal/Welcome.aspx?repo=r-40198117",
    )
    result = await identify(
        "https://publicrecords.cityofsanrafael.org", fetcher=None, page=page
    )
    assert result.final_url != result.input_url
    assert result.platform == "laserfiche_cloud"
    assert result.supported is False
    assert result.outcome == OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER


# --- Rule 4: raw HTML incl. iframe/embed/script, real CivicLive fixtures -


async def test_civiclive_recognized_on_hosted_civiclive_host_via_url_alone():
    # tests/fixtures/civiclive/escalon_city_council_agendas.html's own
    # real URL is already on *.hosted.civiclive.com -- detect_platform()
    # recognizes that host directly, no page scan/footer heuristic needed.
    result = await identify(
        "https://escalon.hosted.civiclive.com/city_hall/agendas___minutes",
        fetcher=None,
        page=None,
    )
    assert result.platform == "civiclive"
    assert result.supported is True


async def test_civiclive_first_party_domain_needs_footer_heuristic():
    # Piedmont, CA is a real CivicLive tenant on its OWN domain
    # (piedmont.ca.gov) -- detect_platform()/host_recognition can't
    # recognize that host at all, so this must come from the page's own
    # footer credit (see identify.py's `_CIVICLIVE_FOOTER_RE`).
    html = load_fixture("civiclive/piedmont_ca_gov_footer_excerpt.html")
    page = _page(html, final_url="https://piedmont.ca.gov/")
    result = await identify("https://piedmont.ca.gov/", fetcher=None, page=page)
    assert result.platform == "civiclive"
    assert result.supported is True
    # No distinct {tenant}.hosted.civiclive.com reference on this real
    # excerpt -- the government's own domain IS the account, same as a
    # CivicPlus/DestinyHosted wrapper site.
    assert result.account_url == "https://piedmont.ca.gov/"
    assert any(s.kind == "civiclive_footer" for s in result.signals)


async def test_escribe_iframe_delegation():
    # Real, confirmed live 2026-09-23: cityofvacaville.gov's own "Agendas
    # and Minutes" page is a full-viewport <iframe> around eScribe, with
    # no visible text of its own -- exactly the "page you were given is
    # often a frame around a different product" case
    # UPCOMING_AGENDAS_FIELD_GUIDE.md documents. The surrounding page is
    # synthetic (a minimal wrapper); the iframe tag and its `src` are the
    # real, verbatim values found live.
    html = (
        "<html><body>"
        '<iframe style="width:100%; height:100vh; border:none;" '
        'src="https://pub-vacaville.escribemeetings.com"></iframe>'
        "</body></html>"
    )
    page = _page(
        html, final_url="https://www.cityofvacaville.gov/government/agendas-and-minutes"
    )
    result = await identify(
        "https://www.cityofvacaville.gov/government/agendas-and-minutes",
        fetcher=None,
        page=page,
    )
    assert result.platform == "escribe"
    assert result.supported is True
    assert result.account_url == "https://pub-vacaville.escribemeetings.com"
    assert any(s.kind == "vendor_link" for s in result.signals)


async def test_page_param_is_reused_not_refetched():
    # A Fetcher that would raise if ever called -- proves `page` reuse
    # really skips the fetch, per this WO's brief.
    class _ExplodingFetcher:
        async def fetch(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("identify() should not have called fetch()")

    html = (
        "<html><body>"
        '<iframe src="https://pub-vacaville.escribemeetings.com"></iframe>'
        "</body></html>"
    )
    page = _page(html, final_url="https://www.cityofvacaville.gov/agendas")
    result = await identify(
        "https://www.cityofvacaville.gov/agendas",
        fetcher=_ExplodingFetcher(),
        page=page,
    )
    assert result.platform == "escribe"


# --- Ranking: vendor link beats direct media beats own-site meeting page -


async def test_ranked_signals_vendor_link_wins_over_direct_media():
    # A real Granicus ViewPublisher link (rank 1) alongside a bare .mp4
    # direct-file link (rank 2) on the same synthetic page -- vendor link
    # must win.
    html = (
        "<html><body>"
        '<a href="https://sandiego.granicus.com/ViewPublisher.php?view_id=3">Watch</a>'
        '<a href="https://example.gov/videos/2026-09-08-council.mp4">Download</a>'
        "</body></html>"
    )
    page = _page(html, final_url="https://example.gov/meetings")
    result = await identify("https://example.gov/meetings", fetcher=None, page=page)
    assert result.platform == "granicus"
    kinds = {s.kind: s.rank for s in result.signals}
    assert kinds["vendor_link"] < kinds["direct_media"]


async def test_direct_media_signal_when_no_vendor_link():
    html = '<html><body><a href="https://example.gov/videos/2026-09-08.mp4">Video</a></body></html>'
    page = _page(html, final_url="https://example.gov/meetings")
    result = await identify("https://example.gov/meetings", fetcher=None, page=page)
    assert result.platform == "direct_file"


async def test_own_site_meeting_page_signal_when_nothing_else_found():
    # docs/MEETING_FINDER.md's own Scan example shape:
    # "/meetings/2026-09-08-council". Not a recognized platform on its
    # own -- just evidence Scan (wave 2) has somewhere concrete to look.
    html = (
        '<html><body><a href="/meetings/2026-09-08-council">Council meeting</a>'
        "</body></html>"
    )
    page = _page(html, final_url="https://example.gov/calendar")
    result = await identify("https://example.gov/calendar", fetcher=None, page=page)
    assert result.platform is None
    assert any(s.kind == "own_site_meeting_page" for s in result.signals)


async def test_other_video_host_ranked_below_vendor_link():
    # Salisbury, NC's real Vimeo id (CLAUDE.md's own Vimeo sample) --
    # confirmed real, but the surrounding page here is synthetic.
    html = '<html><body><a href="https://vimeo.com/1212025580">Watch</a></body></html>'
    page = _page(html, final_url="https://example.gov/meetings")
    result = await identify("https://example.gov/meetings", fetcher=None, page=page)
    assert result.platform == "vimeo"
    assert result.supported is True
    assert any(s.kind == "other_video_host" for s in result.signals)


# --- YouTube: meeting list (rank 5) vs a bare lead (never the answer) ---


async def test_multiple_youtube_videos_become_a_meeting_list_signal_not_the_answer():
    html = (
        "<html><body>"
        '<a href="https://www.youtube.com/watch?v=aaaaaaaaaaa">Sep 8</a>'
        '<a href="https://www.youtube.com/watch?v=bbbbbbbbbbb">Sep 22</a>'
        "</body></html>"
    )
    page = _page(html, final_url="https://example.gov/videos")
    result = await identify("https://example.gov/videos", fetcher=None, page=page)
    # Never handed back as the platform/account, per this module's own
    # docstring -- only recorded as a signal and as leads.
    assert result.platform is None
    assert result.account_url is None
    assert any(s.kind == "youtube_meeting_list" for s in result.signals)
    assert len(result.youtube_leads) == 2


async def test_single_youtube_link_is_a_lead_only():
    html = '<html><body><a href="https://www.youtube.com/channel/UCabc">YouTube</a></body></html>'
    page = _page(html, final_url="https://example.gov/")
    result = await identify("https://example.gov/", fetcher=None, page=page)
    assert result.platform is None
    assert result.youtube_leads == ["https://www.youtube.com/channel/UCabc"]
    assert not any(s.kind == "youtube_meeting_list" for s in result.signals)


# --- Platform known, account unknown: account-not-found + guess queue ---


async def test_web_host_hint_with_no_account_goes_to_guess_queue():
    # Real Granicus "GovAccess" CMS footer credit, confirmed live
    # 2026-09-23 on Lake Helen, FL (a real *.granicusgovaccess.net CNAME
    # target per rtr-business research/wo282_recon.jsonl) -- verbatim
    # text, synthetic surrounding page.
    html = (
        "<html><body>"
        '<p class="footer_copyright">Created By '
        '<a href="//www.granicus.com/">Granicus</a> - Connecting People '
        "and Government</p>"
        '<a href="https://www.youtube.com/channel/UCabc">YouTube</a>'
        "</body></html>"
    )
    page = _page(html, final_url="https://www.lakehelen.org/")
    result = await identify("https://www.lakehelen.org/", fetcher=None, page=page)
    assert result.web_host_hint == "granicus"
    assert result.platform == "granicus"
    assert result.account_url is None
    assert result.outcome == OUTCOME_ACCOUNT_NOT_FOUND
    assert result.guess_queue_row == {
        "vendor": "granicus",
        "evidence": (
            "web-host hint (granicus), but no granicus tenant link or "
            "account was found on https://www.lakehelen.org/"
        ),
    }


async def test_platform_hint_with_no_account_goes_to_guess_queue():
    html = "<html><body><p>Nothing recognizable here.</p></body></html>"
    page = _page(html, final_url="https://example.gov/")
    result = await identify(
        "https://example.gov/", fetcher=None, page=page, platform_hint="civicweb"
    )
    assert result.platform == "civicweb"
    assert result.supported is True
    assert result.account_url is None
    assert result.outcome == OUTCOME_ACCOUNT_NOT_FOUND
    assert result.guess_queue_row["vendor"] == "civicweb"


async def test_url_match_beats_a_conflicting_platform_hint():
    # A real URL/host match always wins over a caller's own belief.
    result = await identify(
        "https://adamscounty.primegov.com",
        fetcher=None,
        page=None,
        platform_hint="granicus",
    )
    assert result.platform == "primegov"


# --- No html at all: propagate the fetch's own outcome -------------------


async def test_no_html_propagates_fetch_outcome():
    page = _page(None, final_url="https://example.gov/", outcome="dns-unresolvable")
    result = await identify("https://example.gov/", fetcher=None, page=page)
    assert result.platform is None
    assert result.outcome == "dns-unresolvable"
    assert result.page is page
