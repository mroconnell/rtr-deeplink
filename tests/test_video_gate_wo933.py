"""WO-933: the ONE shared "is this really a meeting video?" gate
(`app/utils/video_hand_check.py`) and its callers.

Where each expectation comes from (CLAUDE.md's "real examples first"):

- REAL, taken from a file already in this repo: the three homepages with a
  looping hero video (McLeansboro IL, Atlantic City NJ, Union Grove WI), the
  Lavon TX homepage, the real Cablecast/Swagit meeting titles in
  `tests/fixtures/`, and the real meeting-player pages used as the negative
  control for the hero-video rule.
- REAL, quoted from `BACKLOG.md` / `BACKLOG_DONE.md` hand-reads: the video
  titles and addresses named in the entries this WO closes (Hometown IL's
  "Weekly Chat, Explosion in E-Learning!", Forest Park GA's "TEST 3", the
  muscache address, the six channel-listing titles, Bowling Green KY's
  "Video Ad: ..." and so on).
- REAL, re-checked live on 2026-09-21 with one oEmbed request each: the three
  Vimeo titles used below. `vimeo.com/745833271` is "Why McLeansboro.mp4"
  (the McLeansboro homepage's "View Our Video" link), `vimeo.com/461557381`
  is "TML_Muni Awards_2020_Finalmp4" by the Texas Municipal League (the
  Lavon homepage's "Watch the Video" link: someone else's award video), and
  `vimeo.com/1199438213` is still "video1516165031" (Oak Bluffs, MA).
- SYNTHETIC, and marked so where they appear: a hand-built homepage or a
  fake adapter used only to exercise one gate branch that the real data
  above already confirms (a title that names a council meeting passing, a
  promo title rejecting, the ranking-fix note).
"""

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.platforms import base as base_mod
from app.platforms.base import AssetFinder, find_platform_link
from app.platforms.models import ResolvedMeeting
from app.platforms.passive_verify import verify_hub
from app.utils import video_hand_check as vhc
from app.utils.video_hand_check import (
    CANNOT_TELL,
    PASS,
    REJECT,
    assess_video_candidate,
    decorative_url_reason,
    is_placeholder_title,
    not_a_real_video_link_reason,
    page_evidence,
    prescreen_homepage_link,
    same_organization_flag,
    structural_reject,
)

from aiohttp_mock import FakeResponse, mock_session

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
HUB_FIXTURES = FIXTURES / "wo228_hub_ranking"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# --- One definition -----------------------------------------------------------


def test_the_lists_and_the_risky_platform_set_are_defined_once():
    """Before WO-933 six ingest scripts each defined
    `HIGH_RISK_TITLE_PLATFORMS = {"youtube", "vimeo"}` and five kept their own
    substring copy of the allow/block lists. Nothing but the shared module may
    assign these names again."""
    shared = REPO / "app" / "utils" / "video_hand_check.py"
    pattern = re.compile(
        r"^(HIGH_RISK_TITLE_PLATFORMS|MEETING_ALLOWLIST|PROMO_BLOCKLIST)\s*=", re.M
    )
    offenders = []
    for root in ("app", "scripts", "archive", "worker"):
        for path in (REPO / root).rglob("*.py"):
            if path == shared:
                continue
            if pattern.search(_read(path)):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_the_risky_platform_set_is_the_one_wo145_needed():
    assert vhc.HIGH_RISK_TITLE_PLATFORMS == {"youtube", "vimeo", "cablecast", "swagit"}


def test_scripts_that_re_export_the_names_share_the_same_objects():
    import scripts.hub_sweep_wo126 as hub_sweep
    import scripts.nationwide_1911_ingest as n1911
    import scripts.nationwide_2404_ingest as n2404
    import scripts.nationwide_395_ingest as n395
    import scripts.nationwide_431_ingest as n431
    import scripts.wo130_county_ingest as wo130
    import scripts.wo134_confirmed_hits_ingest as wo134

    for module in (n1911, n2404, n395, n431, wo130, wo134, hub_sweep):
        assert module.HIGH_RISK_TITLE_PLATFORMS is vhc.HIGH_RISK_TITLE_PLATFORMS
    for module in (n1911, n2404, n395, n431, wo130, wo134):
        assert module.MEETING_ALLOWLIST is vhc.MEETING_ALLOWLIST
        assert module.PROMO_BLOCKLIST is vhc.PROMO_BLOCKLIST
        # The same word-boundary rule everywhere: five of these six used to
        # be a plain substring test that let "Boardroom" through.
        assert (
            module._looks_like_real_meeting(
                "Larry J. Dix Boardroom", require_allowlist=True
            )
            is False
        )


# --- The title rule, on real titles ------------------------------------------


@pytest.mark.parametrize(
    "title, platform",
    [
        # Real Cablecast fixtures (tests/fixtures/cablecast/*.json, *.html).
        ("City Council Regular meeting - 8/24/2026 6:30:00 PM", "cablecast"),
        ("Beer Board Meeting - April 6, 2026", "cablecast"),
        ("Council Meeting - June 22, 2026", "cablecast"),
        ("City Council Meeting 2026-09-08", "cablecast"),
        ("Detroit City Council Formal Session 07-28-2026", "cablecast"),
        # Real Swagit titles (fixtures and BACKLOG.md).
        ("Jun 02, 2025 Planning Commission - Middleburg, VA", "swagit"),
        ("Jan 13, 2026 City Council - Dublin, CA", "swagit"),
        # Real: the WO-149 pilot's "BOCC" abbreviation.
        ("BOCC Livestream - December 1, 2025", "youtube"),
    ],
)
def test_real_meeting_titles_pass_on_the_risky_platforms(title, platform):
    verdict = assess_video_candidate(title=title, platform=platform)
    assert verdict.verdict == PASS, verdict


@pytest.mark.parametrize(
    "title, platform",
    [
        # Real: Hometown, IL's Cablecast tenant (WO-145 pilot, 2026-09-10).
        ("Weekly Chat, Explosion in E-Learning!", "cablecast"),
        ("Case Study: HCAM", "cablecast"),
        # Real Cablecast fixtures: a show, not a meeting.
        ("Maple Grove Report 3/4/2025", "cablecast"),
        # Real: WO-355's hand-read of homepage Vimeo hits.
        ("City of Garfield 2024", "vimeo"),
        ("Video Ad: Bowling Green - A Great Place to Live and Work", "vimeo"),
        ("VisionGuntersville-2026", "vimeo"),
        ("Regional Promotional Video", "vimeo"),
        # Real oEmbed titles, re-checked live 2026-09-21.
        ("Why McLeansboro.mp4", "vimeo"),
        ("TML_Muni Awards_2020_Finalmp4", "vimeo"),
        # Real: the three channel-listing titles the current word-boundary
        # rule rejects and the five substring copies used to pass.
        ("Commissioners Tour Picatinny Arsenal's Revolutionary Roots", "youtube"),
        ("Larry J. Dix Boardroom", "youtube"),
        (
            "Senate Bill 152: Foreign Funding Restrictions of Ballot Measures "
            "for Entities Other Than Committees",
            "youtube",
        ),
    ],
)
def test_real_non_meeting_titles_are_not_passed_on_the_risky_platforms(title, platform):
    verdict = assess_video_candidate(title=title, platform=platform)
    assert verdict.verdict in (CANNOT_TELL, REJECT), verdict
    assert not verdict.passed


def test_no_title_word_is_cannot_tell_not_reject():
    # "Budget Workshop" is a real kind of meeting the allowlist has no word
    # for; the gate must not call it "not a meeting", only "cannot tell".
    # (Synthetic title; the shape is the false-negative risk BACKLOG.md's
    # "Standing decisions" and the WO-279 entry both name.)
    verdict = assess_video_candidate(title="Budget Workshop", platform="swagit")
    assert verdict.verdict == CANNOT_TELL
    assert verdict.reason == "no_meeting_word_in_title"


# The four channel-listing titles that STILL pass. BACKLOG.md's "A bare
# YouTube channel-listing scan measurably ingests non-meeting videos" entry
# names them; WO-933 does not close that gap (the fix is an open design
# question, see BACKLOG_DONE.md). They are pinned here as strict xfails so
# that whoever settles the design has to remove the marker on purpose.
@pytest.mark.xfail(
    strict=True,
    reason="open gap: a real allowlist word sits in a title no meeting would have",
)
@pytest.mark.parametrize(
    "title",
    [
        "HAIRitage 2026 CROWN Act Workshop: Advice from Our Commissioner Board",
        "Council Participation Instructions",
        "What Does a County Commissioner or Council Member Do?",
        "Pennsylvania Fish and Boat Commission Water Conservation Officer "
        "training: Boating Scenarios",
    ],
)
def test_open_gap_channel_listing_titles_with_an_allowlist_word_still_pass(title):
    assert not assess_video_candidate(title=title, platform="youtube").passed


# --- The three shapes WO-279 said the filter misses ---------------------------


@pytest.mark.parametrize(
    "title",
    [
        "MV Council 6.21.2021",  # Mayfield Village OH
        "BZA Special Meeting",  # Mayfield Village OH
        "Common Council: Meeting of September 8, 2026",  # Madison WI
    ],
)
def test_wo279_abbreviation_and_colon_shapes_already_pass(title):
    """BACKLOG.md's "`classify_video_hand_check()`'s title-keyword pre-filter"
    entry said these three real titles are missed. Re-derived 2026-09-21: they
    all pass the current word-boundary rule."""
    assert assess_video_candidate(title=title, platform="youtube").passed


def test_wo279_french_title_is_still_a_miss_with_only_one_real_example():
    # The fourth shape (Val-d'Or QC, one real example) is still a miss. The
    # entry's own constraint is "confirm a second real example first", so the
    # allowlist is NOT widened here.
    verdict = assess_video_candidate(
        title="569e séance ordinaire du 1 juin 2026", platform="youtube"
    )
    assert verdict.verdict == CANNOT_TELL


# --- Test uploads, placeholder titles ----------------------------------------


def test_a_test_upload_title_is_rejected_on_any_platform():
    # Real: Forest Park city, GA's CivicClerk event "TEST 3" (WO-348 hand-read).
    verdict = assess_video_candidate(
        title="TEST 3", platform="civicclerk", structured=True
    )
    assert verdict.verdict == REJECT and verdict.reason == "test_title"
    assert assess_video_candidate(
        title="test", platform="civicclerk", structured=True
    ).rejected
    # Only "test" plus an optional number is a test upload. A title that merely
    # starts with the word (a fixture in test_wo222_gov_id_ingest_payload.py is
    # "Test City Council Meeting") or starts with "Test..." is not.
    for title in (
        "Test City Council Meeting",
        "Testimony on the Budget - Council Meeting",
    ):
        assert assess_video_candidate(
            title=title, platform="civicclerk", structured=True
        ).passed


@pytest.mark.parametrize(
    "title", ["video1516165031", "IMG_2041", "1516165031", " video1516165031 "]
)
def test_placeholder_titles_are_recognised(title):
    assert is_placeholder_title(title)


@pytest.mark.parametrize(
    "title", ["Council Meeting", "Video Ad: Bowling Green", "", None, "video"]
)
def test_ordinary_titles_are_not_placeholders(title):
    assert not is_placeholder_title(title)


def test_a_placeholder_title_is_cannot_tell_never_a_reject():
    # Real: Oak Bluffs, MA's Vimeo video (page 10200), title re-checked live.
    verdict = assess_video_candidate(title="video1516165031", platform="vimeo")
    assert verdict.verdict == CANNOT_TELL
    assert verdict.reason == "placeholder_title"


# --- Wrong body, promo -------------------------------------------------------


def test_wrong_body_and_ceremony_titles_are_rejected_even_from_a_listing():
    # The WO-191 phrase list is one of the gate's checks (BACKLOG_DONE.md
    # WO-258: Springfield MA's School Committee on the city's tenant).
    verdict = assess_video_candidate(
        title="School Committee Regular Meeting", platform="civicclerk", structured=True
    )
    assert verdict.verdict == REJECT and verdict.reason == "hand_check_kind_a"
    verdict = assess_video_candidate(
        title="Ribbon Cutting - New Fire Station", platform="youtube"
    )
    assert verdict.verdict == REJECT


def test_promo_blocklist_wins_over_an_allowlist_word():
    # Real (WO-187): Capitol Heights, MD.
    verdict = assess_video_candidate(
        title="Council Member Victor James Sr interview for N'style back to "
        "school block party",
        platform="youtube",
    )
    assert verdict.verdict == REJECT and verdict.reason == "promo_title"


# --- Decorative and not-a-video addresses ------------------------------------


def test_the_muscache_widget_animation_is_rejected_by_host():
    # Real (WO-284): matched as a video on Ferdinand town, IN and Council
    # Grove city, KS.
    url = (
        "https://a0.muscache.com/videos/search-bar-icons/hevc/house-twirl-selected.mov"
    )
    assert decorative_url_reason(url) == "decorative_asset_host:muscache.com"
    # By HOST, not by path: a different file on the same host is refused too.
    assert decorative_url_reason("https://a0.muscache.com/pictures/x/other.mp4")
    verdict = assess_video_candidate(video_url=url, platform="direct_file")
    assert verdict.verdict == REJECT


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://vimeo.com/12345?background=1", True),
        ("https://vimeo.com/12345?loop=1&muted=1", True),
        ("https://vimeo.com/12345?loop=1", True),  # WO-909
        ("https://vimeo.com/12345?muted=1", False),
        ("https://vimeo.com/12345", False),
        ("https://vimeo.com/12345?xloop=1", False),
    ],
)
def test_vimeo_hero_embed_query_shape(url, expected):
    assert (decorative_url_reason(url) is not None) is expected


def test_decorative_filename_tokens_only_apply_when_asked():
    url = "https://cdn.example.gov/videos/Banniere-accueil.mp4"  # WO-909 tokens
    assert decorative_url_reason(url) is None
    assert decorative_url_reason(url, check_filename=True)
    assert (
        decorative_url_reason(
            "https://cdn.example.gov/videos/council-2026-09-01.mp4", check_filename=True
        )
        is None
    )


@pytest.mark.parametrize(
    "url, reason",
    [
        # Real shapes from WO-908/909/912/913's hand-reads.
        ("https://www.youtube.com/", "bare_youtube_host"),
        ("https://www.youtube.com", "bare_youtube_host"),
        (
            "https://www.youtube.com/results?search_query=city+council",
            "youtube_search_page",
        ),
        ("https://www.youtube.com/shorts/abcdefghijk", "youtube_short"),
        ("https://www.youtube.com/embed/", "youtube_embed_without_id"),
        ("https://www.youtube.com/watch", "youtube_watch_without_id"),
        ("https://accounts.google.com/ServiceLogin?continue=x", "google_sign_in_page"),
    ],
)
def test_links_that_are_not_a_video_or_a_channel(url, reason):
    assert not_a_real_video_link_reason(url) == reason
    assert structural_reject(url).verdict == REJECT


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@cityofexample",  # a channel is a valid lead
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
        "https://www.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk",
        "https://www.youtube.com/embed/abcdefghijk",
        "https://vimeo.com/745833271",
    ],
)
def test_real_video_and_channel_links_are_not_refused(url):
    assert not_a_real_video_link_reason(url) is None
    assert structural_reject(url) is None


# --- The page around a link (real fixtures) ----------------------------------

_HERO_HOMEPAGES = [
    # (fixture, page url, the hero video's address as it appears on the page)
    (
        "mcleansboro_vimeo_home.html",
        "https://mcleansboro.us/",
        "https://mcleansboro.us/app/themes/bd-basetheme-2023/video/mcl-header-bkg.m4v",
    ),
    (
        "atlantic_city_nj_home.html",
        "https://www.acnj.gov/",
        "https://www.acnj.gov/_Content/video/ac-black-cultural-heritage-tour-thumbnail.mp4",
    ),
    (
        "union_grove_civicweb_home.html",
        "https://www.uniongrovewi.gov/",
        "https://www.uniongrovewi.gov/media/mmicli3d/aerial.mp4",
    ),
]


@pytest.mark.parametrize("fixture, page_url, video_url", _HERO_HOMEPAGES)
def test_real_homepage_hero_videos_are_recognised_by_their_markup(
    fixture, page_url, video_url
):
    """Three real homepages, three looping `<video ... autoplay muted loop>`
    with no controls. None of these three has a decorative-looking filename
    ("aerial", "...tour-thumbnail", "mcl-header-bkg"), which is exactly why the
    address checks alone let them through (WO-904's own test file says so for
    McLeansboro)."""
    html = _read(HUB_FIXTURES / fixture)
    assert decorative_url_reason(video_url, check_filename=True) is None
    evidence = page_evidence(html, video_url, page_url)
    assert evidence.found is True
    assert evidence.hero_reason == "looping_video_without_controls"
    verdict = prescreen_homepage_link(html, page_url, video_url)
    assert verdict is not None and verdict.verdict == REJECT
    assert assess_video_candidate(
        video_url=video_url, platform="direct_file", evidence=evidence
    ).rejected


# Real meeting-player pages already in the repo: the negative control. None of
# their `<video>` tags loops, so the hero rule never fires on a real meeting.
_REAL_PLAYER_PAGES = [
    "cablecast/dyersville_embed_vod_3660.html",
    "civicmedia/tikilive_embed_160547.html",
    "granicus/alexandria_clip6490.html",
    "granicus/hercules_clip1306.html",
    "granicus/simivalley_clip2840.html",
    "iqm2/knoxvillecitytn_1691_split.html",
    "iqm2/monroecountyfl_1180_split.html",
    "platform_fingerprints/swagit_middleburg_va_videos.html",
    "vimeo/player_salisbury_1212025580.html",
    "viebit/nycc_vod_page.html",
]


@pytest.mark.parametrize("relative", _REAL_PLAYER_PAGES)
def test_the_hero_rule_never_fires_on_a_real_meeting_player_page(relative):
    html = _read(FIXTURES / relative)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["video", "source"]):
        src = tag.get("src")
        if not src or src.startswith("data:"):
            continue
        assert page_evidence(html, src, "https://example.test/").hero_reason is None
    # The pages differ in how they name their player; the point is that no
    # `<video>` on any of them is a looping banner.
    assert not [v for v in soup.find_all("video") if v.has_attr("loop")]


def test_find_platform_link_skips_a_hero_video_and_keeps_looking_mcleansboro():
    """Real McLeansboro IL homepage. Without `accept`, the first vendor-shaped
    link is the hero `.m4v` (WO-904's test pins that). With the gate's
    prescreen as `accept`, both hero sources (`.m4v`, `.webm`) are refused and
    the scan reaches the page's real Vimeo link."""
    html = _read(HUB_FIXTURES / "mcleansboro_vimeo_home.html")
    page_url = "https://mcleansboro.us/"
    without = find_platform_link(html, page_url)
    assert without is not None and without[1] == "direct_file"
    refused = []

    def accept(url, platform):
        verdict = prescreen_homepage_link(html, page_url, url)
        if verdict is not None:
            refused.append((url, verdict.reason))
        return verdict is None

    with_gate = find_platform_link(html, page_url, accept=accept)
    assert with_gate == ("https://vimeo.com/745833271", "vimeo")
    assert [u.rsplit(".", 1)[-1] for u, _ in refused] == ["m4v", "webm"]


def test_find_platform_link_default_is_unchanged_when_accept_is_omitted():
    html = _read(HUB_FIXTURES / "zoar_youtube_home.html")
    a = find_platform_link(html, "https://historiczoarvillage.com/")
    b = find_platform_link(
        html, "https://historiczoarvillage.com/", accept=lambda u, p: True
    )
    assert a == b


def test_lavon_homepage_vimeo_link_has_no_meeting_context():
    """Real Lavon TX homepage: "Watch the Video" under "2020 Excellence Award
    for Public Safety". The video is the Texas Municipal League's "TML_Muni
    Awards_2020_Finalmp4" (oEmbed re-checked live 2026-09-21): someone else's
    award video, not a Lavon meeting."""
    html = _read(HUB_FIXTURES / "lavon_vimeo_home.html")
    evidence = page_evidence(
        html, "https://vimeo.com/461557381", "https://lavontx.gov/"
    )
    assert evidence.found is True
    assert evidence.hero_reason is None
    assert evidence.has_meeting_context is False
    verdict = assess_video_candidate(
        title="TML_Muni Awards_2020_Finalmp4",
        platform="vimeo",
        evidence=evidence,
        gov_name="Lavon city",
        page_url="https://lavontx.gov/",
    )
    assert verdict.verdict == CANNOT_TELL


def test_a_meeting_phrase_next_to_the_link_is_evidence():
    # SYNTHETIC page: the phrase list is the WO-355/364 hand-read reference
    # regex; this only exercises the "context passes" branch.
    html = (
        "<html><body><div class='card'><h3>Watch the June 9 City Council "
        "Meeting</h3><a href='https://vimeo.com/999000111'>Video</a></div>"
        "</body></html>"
    )
    evidence = page_evidence(
        html, "https://vimeo.com/999000111", "https://example.gov/"
    )
    assert evidence.has_meeting_context is True
    verdict = assess_video_candidate(title=None, platform="vimeo", evidence=evidence)
    assert verdict.verdict == PASS and verdict.reason == "page_context_names_meeting"


def test_a_site_wide_nav_does_not_count_as_context_for_every_link():
    # SYNTHETIC: a hero video inside a big wrapper that also holds the nav.
    nav = "".join(f"<a href='/p{i}'>Agendas and minutes {i}</a>" for i in range(40))
    html = (
        f"<html><body><div id='wrap'>{nav}"
        "<div><a href='https://vimeo.com/999000222'>Our Story</a></div>"
        "</div></body></html>"
    )
    evidence = page_evidence(
        html, "https://vimeo.com/999000222", "https://example.gov/"
    )
    assert evidence.found is True
    assert evidence.has_meeting_context is False


# --- Same organization -------------------------------------------------------


def test_a_page_on_the_governments_own_site_is_not_flagged():
    # Real page host: the Zoar OH homepage fixture is `historiczoarvillage.com`.
    assert (
        same_organization_flag("https://historiczoarvillage.com/", "Zoar village")
        is None
    )
    # The recorded website counts even when the name is not in the address.
    assert (
        same_organization_flag(
            "https://www.cityhall.example.org/news",
            "Bloomfield city",
            gov_domain="cityhall.example.org",
        )
        is None
    )


def test_a_page_on_another_organizations_site_is_flagged_for_a_human_look_not_rejected():
    # SYNTHETIC page; the organization is real: BACKLOG.md's WO-908 entry says
    # 11 of 35 YouTube hits were Iowa's DNR, a tourism board, a court system...
    flag = same_organization_flag("https://www.iowadnr.gov/parks", "Bloomfield city")
    assert flag is not None
    assert flag.verdict == CANNOT_TELL  # never REJECT: shared channels exist
    assert flag.reason == "other_organization_site"


def test_a_title_that_passes_is_downgraded_when_the_page_is_someone_elses():
    verdict = assess_video_candidate(
        title="City Council Regular Meeting",
        platform="vimeo",
        gov_name="Bloomfield city",
        page_url="https://www.iowadnr.gov/parks",
    )
    assert verdict.verdict == CANNOT_TELL
    assert verdict.reason == "other_organization_site"


def test_no_name_or_no_page_means_nothing_to_compare():
    assert same_organization_flag(None, "Bloomfield city") is None
    assert same_organization_flag("https://www.iowadnr.gov/", None) is None


# --- The gate never defaults to accept ---------------------------------------


def test_an_unknown_platform_with_no_evidence_is_cannot_tell():
    assert assess_video_candidate(title=None, platform=None).verdict == CANNOT_TELL
    assert (
        assess_video_candidate(title="Anything at all", platform="unknown").verdict
        == CANNOT_TELL
    )


def test_a_dedicated_meeting_platform_or_a_listing_is_explicit_evidence():
    v1 = assess_video_candidate(title=None, platform="granicus")
    assert v1.verdict == PASS and v1.reason == "dedicated_meeting_platform"
    v2 = assess_video_candidate(title=None, platform="vimeo", structured=True)
    assert v2.verdict == PASS and v2.reason == "structured_listing"


def test_require_evidence_overrides_the_platform_default():
    assert assess_video_candidate(
        title="Regular Session", platform="civicplus", require_evidence=True
    ).passed
    assert (
        assess_video_candidate(
            title="Budget", platform="civicplus", require_evidence=True
        ).verdict
        == CANNOT_TELL
    )


def test_skip_note_keeps_the_phrase_the_reject_reason_maps_key_on():
    note = assess_video_candidate(
        title="Tabor City Promo", platform="vimeo"
    ).skip_note()
    assert note.startswith("title looks like a non-meeting video")
    assert "gate rejected" in note
    cannot = assess_video_candidate(title="Budget", platform="vimeo").skip_note()
    assert cannot.startswith("title looks like a non-meeting video")
    assert "gate could not tell" in cannot


# --- verify_hub: the bare-homepage path --------------------------------------


class _FakeVideoFinder(AssetFinder):
    """Stands in for one registered adapter and returns a scripted result."""

    def __init__(self, platform_name: str, result: ResolvedMeeting):
        self.platform_name = platform_name
        self._result = result
        self.calls = []

    async def resolve(self, url: str) -> ResolvedMeeting:
        self.calls.append(url)
        return self._result


@pytest.fixture
def fake_registry(monkeypatch):
    """Registers fake finders for the duration of one test only, then puts the
    real registry back (monkeypatch.setitem restores it)."""

    def _register(finder):
        monkeypatch.setitem(base_mod._REGISTRY, finder.platform_name, finder)
        return finder

    return _register


def _vimeo_result(title):
    return ResolvedMeeting(
        platform="vimeo",
        source_url="https://vimeo.com/x",
        video_url="https://player.vimeo.com/video/1",
        title=title,
    )


async def test_verify_hub_records_a_real_homepage_vimeo_video_as_cannot_tell_mcleansboro(
    fake_registry,
):
    """Real McLeansboro IL homepage, real oEmbed title ("Why McLeansboro.mp4",
    live 2026-09-21). Before WO-933 the hero `.m4v` was the "video found" and
    the verdict was tier 3. Now the hero sources are refused, the scan reaches
    the Vimeo link, and the title names no meeting: video recorded, meeting NOT
    credited, and the refusals are listed."""
    html = _read(HUB_FIXTURES / "mcleansboro_vimeo_home.html")
    fake = fake_registry(
        _FakeVideoFinder("vimeo", _vimeo_result("Why McLeansboro.mp4"))
    )
    routes = {
        "https://mcleansboro.us/": FakeResponse(
            status=200, text=html, url="https://mcleansboro.us/"
        )
    }
    with mock_session(routes):
        result = await verify_hub("https://mcleansboro.us/", name="McLeansboro city")

    assert fake.calls == ["https://vimeo.com/745833271"]
    assert result.verdict == "resolved_unverified_video"
    assert result.video_gate == CANNOT_TELL
    assert result.video_gate_reason == "no_meeting_word_in_title"
    assert result.video_found is True
    assert result.meeting_found is False
    assert result.tier is None  # no caller can credit this as tier 1/3
    assert result.video_title == "Why McLeansboro.mp4"
    assert [r["url"].rsplit(".", 1)[-1] for r in result.rejected_video_links[:2]] == [
        "m4v",
        "webm",
    ]
    assert "cannot tell" in result.evidence


async def test_verify_hub_records_the_lavon_award_video_as_cannot_tell(fake_registry):
    """Real Lavon TX homepage; the video is the Texas Municipal League's award
    film (oEmbed re-checked live 2026-09-21)."""
    html = _read(HUB_FIXTURES / "lavon_vimeo_home.html")
    fake_registry(
        _FakeVideoFinder("vimeo", _vimeo_result("TML_Muni Awards_2020_Finalmp4"))
    )
    routes = {
        "https://lavontx.gov/": FakeResponse(
            status=200, text=html, url="https://lavontx.gov/"
        )
    }
    with mock_session(routes):
        result = await verify_hub("https://lavontx.gov/", name="Lavon city")
    assert result.verdict == "resolved_unverified_video"
    assert result.tier is None


async def test_verify_hub_credits_a_homepage_video_whose_title_names_a_meeting(
    fake_registry,
):
    # SYNTHETIC homepage and title: exercises the PASS branch. The title rule
    # is the real one (see the parametrized real-title tests above).
    hub = "https://example.gov/"
    html = "<html><body><a href='https://vimeo.com/555000111'>Watch</a></body></html>"
    fake_registry(
        _FakeVideoFinder(
            "vimeo", _vimeo_result("City Council Regular Meeting - September 9, 2026")
        )
    )
    with mock_session({hub: FakeResponse(status=200, text=html, url=hub)}):
        result = await verify_hub(hub, name="Example city")
    assert result.verdict == "resolved"
    assert result.video_gate == PASS
    assert result.video_gate_reason == "title_names_governing_body"
    assert result.tier == 3


async def test_verify_hub_rejects_a_homepage_promo_video(fake_registry):
    # Real title: "Tabor City Promo" (WO-355 hand-read, Tabor City NC). SYNTHETIC
    # page around it.
    hub = "https://example.gov/"
    html = "<html><body><a href='https://vimeo.com/555000222'>Watch</a></body></html>"
    fake_registry(_FakeVideoFinder("vimeo", _vimeo_result("Tabor City Promo")))
    with mock_session({hub: FakeResponse(status=200, text=html, url=hub)}):
        result = await verify_hub(hub, name="Tabor City town")
    assert result.verdict == "video_rejected"
    assert result.video_gate == REJECT
    assert result.video_found is False
    assert result.meeting_found is False
    assert result.tier is None
    assert result.rejected_video_links[-1]["reason"] == "promo_title"


async def test_verify_hub_leaves_a_hub_that_is_itself_a_known_platform_alone(
    fake_registry,
):
    # The gate is for what a bare homepage scan finds. A hub the earlier phase
    # already confirmed as a platform page is not re-judged by title.
    hub = "https://vimeo.com/555000333"
    fake_registry(_FakeVideoFinder("vimeo", _vimeo_result("video1516165031")))
    result = await verify_hub(hub)
    assert result.verdict == "resolved"
    assert result.video_gate == ""
    assert result.tier == 3


async def test_verify_hub_rejects_a_decorative_only_homepage_and_says_so(fake_registry):
    # Real address shape (WO-355/WO-909): a Vimeo hero embed. SYNTHETIC page.
    hub = "https://example.gov/"
    html = (
        "<html><body><iframe src='https://player.vimeo.com/video/555000444"
        "?background=1&autoplay=1'></iframe></body></html>"
    )
    with mock_session({hub: FakeResponse(status=200, text=html, url=hub)}):
        result = await verify_hub(hub, name="Example city")
    assert result.video_found is False
    assert result.verdict == "no_platform_detected"
    assert (
        result.rejected_video_links[0]["reason"] == "hero_embed_parameter:background=1"
    )
    assert "refused 1 homepage video" in result.evidence


# --- The shared `accept` filter leaves a listing walk's rows alone ------------


async def test_a_listing_row_with_a_decorative_address_is_not_credited(fake_registry):
    # SYNTHETIC listing: a per-meeting listing vouches for its rows' titles, but
    # not for an address that is the muscache animation file (real, WO-284).
    from app.platforms.base import CalendarPageError

    hub = "https://example.test/hub"

    class _Listing(AssetFinder):
        platform_name = "fake_listing"

        async def resolve(self, url):
            if url == hub:
                raise CalendarPageError(
                    "listing",
                    candidates=[
                        {
                            "title": "A",
                            "date": "2026-09-01",
                            "url": "https://example.test/a",
                        },
                        {
                            "title": "TEST 3",
                            "date": "2026-08-01",
                            "url": "https://example.test/b",
                        },
                        {
                            "title": "C",
                            "date": "2026-07-01",
                            "url": "https://example.test/c",
                        },
                    ],
                )
            video = {
                "https://example.test/a": "https://a0.muscache.com/videos/x/y.mov",
                "https://example.test/b": "https://cdn.example.test/b.mp4",
                "https://example.test/c": "https://cdn.example.test/c.mp4",
            }[url]
            return ResolvedMeeting(
                platform="fake_listing", source_url=url, video_url=video, title="t"
            )

    fake_registry(_Listing())
    bland = "<html><body><a href='/about'>About</a></body></html>"
    with mock_session({hub: FakeResponse(status=200, text=bland, url=hub)}):
        result = await verify_hub(hub, platform_hint="fake_listing", name=None)
    # Row A is refused (decorative host), row B is refused (a "TEST 3" event,
    # real title from Forest Park GA), row C is the first credited video.
    assert result.meeting_url == "https://example.test/c"
    assert [r["reason"] for r in result.rejected_video_links] == [
        "decorative_asset_host:muscache.com",
        "test_title",
    ]


# --- generic_fallback: the user-facing resolver ------------------------------


@pytest.mark.parametrize(
    "fixture, page_url",
    [
        ("atlantic_city_nj_home.html", "https://www.acnj.gov/"),
        ("union_grove_civicweb_home.html", "https://www.uniongrovewi.gov/"),
    ],
)
def test_generic_fallback_no_longer_offers_a_real_hero_video_as_the_video(
    fixture, page_url
):
    """Real Atlantic City NJ and Union Grove WI homepages. The shared media
    scan still FINDS the looping hero mp4 (that is unchanged); the fallback's
    own scan now drops it, so it is not offered as "the video"."""
    from app.platforms.generic_fallback import scan_page_for_video_evidence
    from app.platforms.media_scan import scan_media_urls

    html = _read(HUB_FIXTURES / fixture)
    assert scan_media_urls(html, page_url)  # the hero file is on the page
    video_url, _fmt, video_link, _recognized = scan_page_for_video_evidence(
        html, page_url
    )
    assert video_url is None


def test_generic_fallback_falls_through_to_the_pointer_for_mcleansboro():
    from app.platforms.generic_fallback import scan_page_for_video_evidence

    html = _read(HUB_FIXTURES / "mcleansboro_vimeo_home.html")
    video_url, _fmt, video_link, recognized = scan_page_for_video_evidence(
        html, "https://mcleansboro.us/"
    )
    assert video_url is None
    assert video_link == "https://vimeo.com/745833271" and recognized is True


async def test_generic_fallback_delegates_to_the_real_link_not_the_hero_file(
    fake_registry,
):
    """Real McLeansboro homepage. `find_platform_link()`'s first hit used to be
    the hero `.m4v`; delegation now goes to the Vimeo link instead."""
    from app.platforms.generic_fallback import GenericFallbackAssetFinder

    fake = fake_registry(
        _FakeVideoFinder("vimeo", _vimeo_result("Why McLeansboro.mp4"))
    )
    html = _read(HUB_FIXTURES / "mcleansboro_vimeo_home.html")
    resolved = await GenericFallbackAssetFinder()._resolve_from_html(
        "https://mcleansboro.us/", html
    )
    assert fake.calls == ["https://vimeo.com/745833271"]
    assert resolved.video_url == "https://player.vimeo.com/video/1"
    assert resolved.best_effort is True


def test_generic_fallback_keeps_a_plain_player_video_and_drops_the_muscache_file():
    from app.platforms.generic_fallback import _drop_decorative_media

    kept = _drop_decorative_media(
        "<html></html>",
        "https://example.gov/meeting",
        [
            "https://a0.muscache.com/videos/search-bar-icons/hevc/house-twirl-selected.mov",
            "https://cdn.example.gov/council-2026-09-01.mp4",
        ],
    )
    assert kept == ["https://cdn.example.gov/council-2026-09-01.mp4"]


def test_wo264_find_video_candidates_skips_the_muscache_file():
    """Real WO-284 shape: an Airbnb embed's animation file matched the
    extension regex as a "video" on two real governments."""
    import scripts.wo264_overnight_sweep as wo264

    html = (
        "<html><body>"
        '<video><source src="https://a0.muscache.com/videos/search-bar-icons/'
        'hevc/house-twirl-selected.mov"></video>'
        '<a href="https://vimeo.com/745833271">Video</a>'
        "</body></html>"
    )
    assert wo264.find_video_candidates(html, "https://example.gov/") == [
        "https://vimeo.com/745833271"
    ]


# --- The ladder notes a hit found on somebody else's site ----------------------


def test_the_ladder_notes_a_hit_from_another_organizations_page_but_keeps_it():
    """`run_access_ladder()` (scripts/wo147_access_ladder_sweep.py) adds a note,
    it never drops the hit: real shared channels have no name overlap. The page
    here is SYNTHETIC; the shape (a link picked up on a state agency's page) is
    the one BACKLOG.md's WO-908 entry counted 11 of 35 YouTube hits for."""
    from scripts.wo147_access_ladder_sweep import LadderResult, _flag_other_organization

    result = LadderResult(
        "plain",
        "plain",
        "https://www.bloomfieldia.example/",
        "<html></html>",
        "https://www.iowadnr.gov/parks",
        "none",
        "",
        "youtube",
        "https://www.youtube.com/@iowadnr",
    )
    flagged = _flag_other_organization(
        result, "Bloomfield city", "bloomfieldia.example"
    )
    assert flagged.platform == "youtube"
    assert flagged.hit_url == "https://www.youtube.com/@iowadnr"
    assert "cannot tell whose link this is" in flagged.note


def test_the_ladder_adds_no_note_for_a_hit_on_the_governments_own_site():
    from scripts.wo147_access_ladder_sweep import LadderResult, _flag_other_organization

    # Real Zoar OH homepage fixture host (historiczoarvillage.com).
    result = LadderResult(
        "plain",
        "plain",
        "https://historiczoarvillage.com/",
        "<html></html>",
        "https://historiczoarvillage.com/",
        "none",
        "",
        "youtube",
        "https://www.youtube.com/@zoarvillage",
    )
    assert (
        _flag_other_organization(result, "Zoar village", "historiczoarvillage.com").note
        == ""
    )
    # A ladder result with no hit is never touched.
    empty = LadderResult(
        "dead", "dead", "https://x.example/", None, "", "none", "dns-fail"
    )
    assert (
        _flag_other_organization(empty, "Zoar village", "x.example").note == "dns-fail"
    )


def test_dummerston_videobg_is_a_decorative_filename():
    # Real: Dummerston town, VT's homepage video `img/videobg.mp4` (WO-348).
    assert (
        decorative_url_reason(
            "https://example.gov/img/videobg.mp4", check_filename=True
        )
        == "decorative_filename:videobg"
    )


# --- A bare homepage link to a video file (`direct_file`) ---------------------


@pytest.mark.parametrize(
    "link_text",
    [
        # Real link texts from WO-338's hand-read (Geistown, a dredge
        # documentary, two community clips, a bare download link). The page
        # and file address around each are SYNTHETIC; the texts are the real
        # ones BACKLOG.md's "A bare homepage link to a video file" entry names.
        "HELLO GEISTOWN",
        "Planting Activities",
        "Forest Overview",
        "Download the video",
    ],
)
def test_a_bare_homepage_video_file_with_no_meeting_text_is_cannot_tell(link_text):
    url = "https://example.gov/files/clip.m4v"
    html = f"<html><body><p><a href='{url}'>{link_text}</a></p></body></html>"
    evidence = page_evidence(html, url, "https://example.gov/")
    assert evidence.found is True and evidence.has_meeting_context is False
    verdict = assess_video_candidate(
        title=None, video_url=url, platform="direct_file", evidence=evidence
    )
    assert verdict.verdict == CANNOT_TELL
    assert verdict.reason == "no_title"


def test_a_bare_homepage_video_file_with_a_meeting_link_text_passes():
    # SYNTHETIC page: the branch the WO-355/364 hand-read reference regex
    # covers ("Watch the ... Council Meeting" next to the file link).
    url = "https://example.gov/files/2026-09-08.mp4"
    html = (
        f"<html><body><p><a href='{url}'>Watch the September 8 City Council "
        "Meeting</a></p></body></html>"
    )
    verdict = assess_video_candidate(
        title=None,
        video_url=url,
        platform="direct_file",
        evidence=page_evidence(html, url, "https://example.gov/"),
    )
    assert verdict.verdict == PASS
    assert verdict.reason == "page_context_names_meeting"


# --- The ranking fix does not prefer a video the gate cannot verify -------------


async def test_ranking_fix_does_not_prefer_an_unverified_extra_video(fake_registry):
    """SYNTHETIC hub, built like `test_passive_verify.py`'s ranking-fix test: a
    CivicPlus AgendaCenter page with real (title+date) rows and no video, which
    also links a Vimeo video elsewhere on the page. Before WO-933 that Vimeo
    video replaced the aggregator's honest "meeting found, no video" result.
    The title is the real oEmbed title of McLeansboro's homepage video (live
    2026-09-21), which names no meeting, so the aggregator's own result stays
    and the extra link is only noted."""
    from app.platforms.civicplus import CivicPlusAssetFinder

    fake_registry(CivicPlusAssetFinder())
    fake_registry(_FakeVideoFinder("vimeo", _vimeo_result("Why McLeansboro.mp4")))
    hub_url = "https://example.civicplus.com/291/Boards-Committees"
    agenda_row = (
        '<tr class="catAgendaRow">'
        "<td><h3><strong>{date}</strong></h3><p><a>Meeting {date}</a></p></td>"
        '<td class="media"></td>'
        "</tr>"
    )
    hub_html = (
        "<html><body><table>"
        + "".join(
            agenda_row.format(date=d)
            for d in ("Sep 05, 2026", "Sep 04, 2026", "Sep 03, 2026")
        )
        + '</table><a href="https://vimeo.com/555000999">Our Story</a>'
        "</body></html>"
    )
    routes = {hub_url: FakeResponse(status=200, text=hub_html, url=hub_url)}
    with mock_session(routes):
        result = await verify_hub(hub_url, platform_hint="civicplus", name="Example")

    assert result.ranking_fix_applied is False
    assert result.platform == "civicplus"
    assert result.meeting_found is True  # the aggregator's own honest answer
    assert result.video_found is False
    assert "was not credited" in result.evidence
    assert result.rejected_video_links[-1] == {
        "url": "https://vimeo.com/555000999",
        "platform": "vimeo",
        "reason": "no_meeting_word_in_title",
    }
