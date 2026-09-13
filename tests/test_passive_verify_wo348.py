"""Tests for WO-348's "look one hop deeper" fix
(`app/platforms/passive_verify.py`).

WO-347's 60-government hand audit found the passive pipeline's two
negative verdicts ("nothing walkable" and "candidate-not-confirmed")
wrong most of the time -- 30 of 40 checked -- because the pipeline
stopped one hop short of a real, live meetings/agendas page. WO-348
measured where, live, on those 30 rows
(`research/wo348_hop_measurements.csv`, rtr-business): of 24 rows with a
real page to measure from, ~20 were reachable by exactly ONE direct link
from the page the pipeline had already stopped at, with anchor text
built from a small, real vocabulary ("Agendas/Minutes", "Meeting
Minutes", "Meeting Agendas", "Zoning Minutes", "Calendar", "Document
Center", ...). Every synthetic HTML fixture below reuses that REAL,
measured anchor-text/href vocabulary and real government names/states
from WO-347's audit rows -- not invented shapes -- per this repo's own
"synthetic tests reuse a confirmed real shape" convention (CLAUDE.md).

Also covers the audio-only-file fix WO-347 filed (a CivicClerk
`video_url` that is really an `.mp3`, confirmed live on Olmos Park city,
TX), the new CivicWeb/Diligent third domain shape
(`*.diligent.community`, confirmed live on Eatwp township, PA), and a
THIRD real CivicClerk tenant domain shape found while proving this fix
on WO-347's 60-row audit sample -- a bare `<tenant>.civicclerk.com` with
no `.portal.`/`.api.` infix, confirmed live on Upper Providence
Township, PA (301s to the `.portal.` host, but the walker is handed the
pre-redirect URL).
"""

from app.platforms.passive_verify import (
    _CIVICCLERK_TENANT_RE,
    _civicweb_walker,
    _confirm_not_audio_only,
    _extract_hop_candidates,
    _has_agenda_minutes_content,
    _is_catchall,
    _name_state_matches,
    _score_hop_link,
    verify_hub,
)

from aiohttp_mock import FakeResponse, mock_session


# --- hop-weight scoring (unit, no network) -----------------------------


def test_score_hop_link_real_measured_anchor_text_scores_positive():
    # Real anchor text WO-348 measured live leading to a real meetings
    # page (Woodruff UT, Berrien Springs MI, Lawrence Township NJ,
    # Fernie BC): all should score above zero.
    for text in (
        "Meetings",
        "Agendas/Minutes",
        "Zoning Minutes",
        "Meeting Minutes",
        "Document Center",
        "Calendar",
    ):
        assert _score_hop_link(text, "/some/path") > 0, text


def test_score_hop_link_generic_nav_text_scores_zero():
    for text in ("About", "Home", "Contact Us", "Staff Directory"):
        assert _score_hop_link(text, "/whatever") == 0, text


def test_score_hop_link_french_table_scores_positive():
    # Not measured from WO-347's audit sample (no French-language tenant
    # was in the 30 wrong rows) -- a deliberate generalization to
    # Francophone Canadian municipalities, per WO-348's brief. Flagged
    # here and in the methods writeup as unconfirmed-by-audit.
    for text in ("Ordre du jour", "Procès-verbaux", "Séances du conseil"):
        assert _score_hop_link(text, "/fr/reunions") > 0, text


def test_extract_hop_candidates_excludes_youtube_and_payment_portal():
    html = (
        "<html><body>"
        '<a href="https://www.youtube.com/c/CityChannel">Meeting Minutes on YouTube</a>'
        '<a href="https://xpress-pay.com/pay?ref=meeting-fees">Pay Meeting Fees</a>'
        '<a href="/agendas-minutes/">Agendas/Minutes</a>'
        "</body></html>"
    )
    candidates = _extract_hop_candidates(html, "https://example.gov/")
    urls = [c[1] for c in candidates]
    assert "https://example.gov/agendas-minutes/" in urls
    assert not any("youtube.com" in u for u in urls)
    assert not any("xpress-pay.com" in u for u in urls)


def test_extract_hop_candidates_skips_same_page_anchor():
    html = '<html><body><a href="#content">Skip to content</a></body></html>'
    assert _extract_hop_candidates(html, "https://example.gov/") == []


def test_extract_hop_candidates_sorts_highest_score_first():
    html = (
        "<html><body>"
        '<a href="/government/">Government</a>'
        '<a href="/agendas-minutes/">Agendas/Minutes</a>'
        "</body></html>"
    )
    candidates = _extract_hop_candidates(html, "https://example.gov/")
    assert candidates[0][1] == "https://example.gov/agendas-minutes/"


# --- catch-all guard (unit) ---------------------------------------------


def test_is_catchall_true_when_body_matches_signature():
    import hashlib

    body = "<html>parked domain</html>"
    sig = (len(body), hashlib.sha256(body.encode()).hexdigest())
    assert _is_catchall(body, sig) is True


def test_is_catchall_false_for_real_different_content():
    import hashlib

    parked = "<html>parked domain</html>"
    sig = (len(parked), hashlib.sha256(parked.encode()).hexdigest())
    real_page = "<html><body>" + "<p>City Council Agenda</p>" * 50 + "</body></html>"
    assert _is_catchall(real_page, sig) is False


def test_is_catchall_false_when_no_signature():
    assert _is_catchall("<html>anything</html>", None) is False


# --- agenda/minutes content check (WO-348's own proof-run finding) ------


def test_has_agenda_minutes_content_true_for_literal_agenda_word():
    html = "<html><body>City Council Agenda and Minutes archive</body></html>"
    assert _has_agenda_minutes_content(html) is True


def test_has_agenda_minutes_content_true_for_meeting_in_title_when_js_rendered():
    # Real, confirmed shape (Woodruff UT, Doylestown PA): the real agenda
    # content is loaded by a JS meeting-notice widget, so "agenda"/
    # "minutes" never appear in the plain-fetched HTML -- but the page's
    # own <title> says so.
    html = (
        "<html><head><title>Meetings &#8211; Woodruff Town</title></head>"
        "<body><h1>Meetings</h1>"
        '<script src="https://www.utah.gov/pmn/meetingsJS.html?entityIds=310"></script>'
        "</body></html>"
    )
    assert _has_agenda_minutes_content(html) is True


def test_has_agenda_minutes_content_false_for_sitewide_nav_boilerplate_only():
    # Real, confirmed false positive this WO's own proof run caught live:
    # Argyle WI's sitewide nav mentions "meeting" via a "Village Board
    # Meeting" boilerplate link present on EVERY page, but the page's own
    # title/h1 (Community Building Room Rental Request) has nothing to
    # do with a meeting -- must not be credited.
    html = (
        "<html><head><title>Community Building Room Rental Request | "
        "Village of Argyle</title></head><body>"
        '<nav><a href="/board">Village Board Meeting</a></nav>'
        "<h1>Community Building Room Rental Request</h1>"
        "</body></html>"
    )
    assert _has_agenda_minutes_content(html) is False


# --- name+state evidence check (unit) -----------------------------------


def test_name_state_matches_requires_both_when_state_given():
    html = "<html><body>Town of Woodruff, Utah meeting agendas</body></html>"
    assert _name_state_matches(html, "Woodruff", "Utah") is True
    assert _name_state_matches(html, "Woodruff", "Wyoming") is False
    assert _name_state_matches(html, "Ephrata", "Utah") is False


def test_name_state_matches_true_when_no_name_given():
    assert _name_state_matches("<html>anything</html>", None, None) is True


def test_name_state_matches_accepts_abbreviation_when_full_name_missing():
    # Real, confirmed live: Fernie BC's real agenda archive page says
    # "Fernie" but never spells out "British Columbia" -- only "BC".
    html = "<html><body>Fernie Document Center -- BC public records</body></html>"
    assert _name_state_matches(html, "Fernie", "British Columbia") is True


def test_name_state_matches_accepts_full_name_when_abbreviation_missing():
    # Real, confirmed live: Ephrata township PA's real homepage says
    # "Ephrata" and spells out "Pennsylvania" but never "PA".
    html = "<html><body>Ephrata Township, Pennsylvania -- agendas</body></html>"
    assert _name_state_matches(html, "Ephrata", "PA") is True


def test_name_state_matches_abbreviation_is_a_whole_word_not_a_substring():
    # A 2-letter code must not match inside an unrelated word.
    html = "<html><body>Ephrata Township -- capital projects update</body></html>"
    assert _name_state_matches(html, "Ephrata", "PA") is False


# --- audio-only guard (WO-347 finding) -----------------------------------


async def test_confirm_not_audio_only_true_for_non_audio_extension():
    # No network call at all -- the extension alone rules it out.
    assert await _confirm_not_audio_only("https://example.gov/video.mp4") is True


async def test_confirm_not_audio_only_false_for_real_mp3_content_type():
    # Real, confirmed shape: Olmos Park city, TX's CivicClerk listing
    # walker returned a `video_url` ending in `.mp3` whose own
    # Content-Type is `audio/mp3` (a real 58 MB file) -- WO-347.
    url = "https://olmospark.civicclerk.com/files/meeting123.mp3"
    with mock_session(
        {},
        head_routes={
            url: FakeResponse(status=200, headers={"Content-Type": "audio/mp3"})
        },
    ):
        assert await _confirm_not_audio_only(url) is False


async def test_confirm_not_audio_only_true_for_real_video_content_type():
    url = "https://example.gov/files/meeting123.mp3"
    with mock_session(
        {},
        head_routes={
            url: FakeResponse(status=200, headers={"Content-Type": "video/mp4"})
        },
    ):
        assert await _confirm_not_audio_only(url) is True


async def test_confirm_not_audio_only_treats_failed_head_as_audio():
    # HEAD fails (unmocked route -> mock raises, `_confirm_not_audio_only`
    # catches it) -- the extension alone is strong evidence, so the safer
    # wrong answer (treat as audio, don't wrongly queue it) wins.
    url = "https://example.gov/files/meeting123.mp3"
    with mock_session({}, head_routes={}):
        assert await _confirm_not_audio_only(url) is False


# --- end-to-end: verify_hub() looks one hop deeper ------------------------


async def test_verify_hub_finds_real_page_one_hop_deeper_from_homepage():
    # Modeled on Woodruff UT / Central Valley UT (WO-347's real, wrong
    # "nothing walkable" rows): no known vendor platform link anywhere,
    # no guessable first-party path matches, but the homepage has a real
    # "Meetings" nav link the guessable-path list never tried.
    home_html = (
        "<html><body>"
        '<a href="/about">About</a>'
        '<a href="/meetings/">Meetings</a>'
        "</body></html>"
    )
    real_page_html = (
        "<html><body><h1>Town of Woodruff, Utah</h1>"
        + "<p>Meeting Agenda and Minutes archive</p>" * 60
        + "</body></html>"
    )
    routes = {
        "https://woodruff.example.gov": FakeResponse(status=200, text=home_html),
        "https://woodruff.example.gov/agendacenter": FakeResponse(status=404),
        "https://woodruff.example.gov/AgendaCenter": FakeResponse(status=404),
        "https://woodruff.example.gov/agendas-minutes": FakeResponse(status=404),
        "https://woodruff.example.gov/agendas_minutes": FakeResponse(status=404),
        "https://woodruff.example.gov/Agendas-and-Minutes": FakeResponse(status=404),
        "https://woodruff.example.gov/government/agendas-minutes": FakeResponse(
            status=404
        ),
        "https://woodruff.example.gov/meetings/": FakeResponse(
            status=200, text=real_page_html
        ),
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://woodruff.example.gov", name="Woodruff", state="Utah"
        )

    assert result.meeting_found is True
    assert result.video_found is False
    assert result.tier == 4
    assert result.verdict == "hop_deeper_found"
    assert result.meeting_url == "https://woodruff.example.gov/meetings/"


async def test_verify_hub_home_page_body_itself_has_real_content():
    # Modeled on Ephrata township PA (WO-347's real wrong row): the real
    # agenda content sits directly ON the homepage, not a subpath --
    # `_probe_first_party_agenda_pages()`'s stage 0 should catch it
    # without needing any deeper hop.
    home_html = (
        "<html><body><h1>Ephrata Township, Pennsylvania</h1>"
        + "<p>Board of Supervisors Meeting Agenda, dated Sep 2026</p>" * 40
        + '<a href="/about">About</a>'
        + "</body></html>"
    )
    routes = {
        "https://ephrata.example.gov": FakeResponse(status=200, text=home_html),
    }
    with mock_session(routes):
        result = await verify_hub(
            "https://ephrata.example.gov", name="Ephrata", state="Pennsylvania"
        )

    assert result.meeting_found is True
    assert result.verdict == "first_party_agenda_page"


async def test_verify_hub_deeper_hop_rejects_name_state_mismatch():
    # A deeper candidate exists and scores well, but its content belongs
    # to a DIFFERENT real government -- the name+state check must reject
    # it rather than crediting a wrong page.
    home_html = '<html><body><a href="/meetings/">Meetings</a></body></html>'
    wrong_page_html = (
        "<html><body><h1>City of Springfield, Illinois</h1>"
        + "<p>Council Meeting Agenda</p>" * 60
        + "</body></html>"
    )
    routes = {
        "https://example.gov": FakeResponse(status=200, text=home_html),
        "https://example.gov/agendacenter": FakeResponse(status=404),
        "https://example.gov/AgendaCenter": FakeResponse(status=404),
        "https://example.gov/agendas-minutes": FakeResponse(status=404),
        "https://example.gov/agendas_minutes": FakeResponse(status=404),
        "https://example.gov/Agendas-and-Minutes": FakeResponse(status=404),
        "https://example.gov/government/agendas-minutes": FakeResponse(status=404),
        "https://example.gov/meetings/": FakeResponse(status=200, text=wrong_page_html),
    }
    with mock_session(routes):
        result = await verify_hub("https://example.gov", name="Woodruff", state="Utah")

    assert result.verdict == "no_platform_detected"
    assert result.meeting_found is False


async def test_verify_hub_no_false_positive_when_nothing_hop_worthy():
    # WO-333 regression shape: a homepage with no vendor link and no
    # hop-worthy anchors at all must stay a confident "no meeting" --
    # not a hallucinated hop.
    home_html = (
        "<html><body>"
        '<a href="/about">About</a>'
        '<a href="/contact">Contact</a>'
        '<a href="https://facebook.com/examplegov">Facebook</a>'
        "</body></html>"
    )
    routes = {
        "https://example.gov": FakeResponse(status=200, text=home_html),
        "https://example.gov/agendacenter": FakeResponse(status=404),
        "https://example.gov/AgendaCenter": FakeResponse(status=404),
        "https://example.gov/agendas-minutes": FakeResponse(status=404),
        "https://example.gov/agendas_minutes": FakeResponse(status=404),
        "https://example.gov/Agendas-and-Minutes": FakeResponse(status=404),
        "https://example.gov/government/agendas-minutes": FakeResponse(status=404),
    }
    with mock_session(routes):
        result = await verify_hub("https://example.gov")

    assert result.verdict == "no_platform_detected"
    assert result.meeting_found is False


async def test_verify_hub_deeper_hop_rejects_payment_portal_even_with_meeting_text():
    # A real government site's most prominent "meeting"-worded link is a
    # third-party bill-pay portal -- must never be followed.
    home_html = (
        "<html><body>"
        '<a href="https://xpress-pay.com/pay?bill=meeting-room-fee">'
        "Pay Your Meeting Room Rental Fee</a>"
        "</body></html>"
    )
    routes = {
        "https://example.gov": FakeResponse(status=200, text=home_html),
        "https://example.gov/agendacenter": FakeResponse(status=404),
        "https://example.gov/AgendaCenter": FakeResponse(status=404),
        "https://example.gov/agendas-minutes": FakeResponse(status=404),
        "https://example.gov/agendas_minutes": FakeResponse(status=404),
        "https://example.gov/Agendas-and-Minutes": FakeResponse(status=404),
        "https://example.gov/government/agendas-minutes": FakeResponse(status=404),
    }
    with mock_session(routes):
        result = await verify_hub("https://example.gov")

    assert result.verdict == "no_platform_detected"


# --- CivicWeb/Diligent: three real domain shapes, WO-348 -----------------


async def test_civicweb_walker_recognizes_diligent_community_domain():
    # Real, live shape confirmed this WO: Eatwp township PA's real
    # "Meeting Portal" homepage link goes to
    # eatwp.diligent.community/Portal/MeetingTypeList.aspx -- a THIRD
    # CivicWeb/Diligent domain shape beyond civicweb.net and
    # community.diligentoneplatform.com.
    listing_html = (
        "<html><body>"
        '<a href="MeetingInformation.aspx?Org=Cal&amp;Id=501">Board of Supervisors</a>'
        '<a href="MeetingInformation.aspx?Org=Cal&amp;Id=498">Planning Commission</a>'
        "</body></html>"
    )
    routes = {
        "https://eatwp.diligent.community/Portal/MeetingTypeList.aspx": FakeResponse(
            status=200, text=listing_html
        ),
    }
    with mock_session(routes):
        candidates = await _civicweb_walker(
            "https://eatwp.diligent.community/Portal/MeetingTypeList.aspx"
        )

    assert candidates
    assert candidates[0]["url"].endswith("Id=501")


async def test_civicweb_walker_falls_back_to_meetingschedule_when_meetingtypelist_empty():
    # Real, live shape confirmed this WO: Ferris TX and Lower Saucon
    # township PA's real listing lives at Portal/MeetingSchedule.aspx --
    # MeetingTypeList.aspx on the same tenant comes back with zero real
    # meeting ids.
    empty_html = "<html><body>No meeting types configured.</body></html>"
    schedule_html = (
        '<html><body><a href="MeetingInformation.aspx?Id=77">Council</a></body></html>'
    )
    routes = {
        "https://ferris-texas.community.diligentoneplatform.com/Portal/MeetingTypeList.aspx": FakeResponse(
            status=200, text=empty_html
        ),
        "https://ferris-texas.community.diligentoneplatform.com/Portal/MeetingSchedule.aspx": FakeResponse(
            status=200, text=schedule_html
        ),
    }
    with mock_session(routes):
        candidates = await _civicweb_walker(
            "https://ferris-texas.community.diligentoneplatform.com/Portal/"
        )

    assert candidates
    assert candidates[0]["url"].endswith("Id=77")


def test_detect_platform_recognizes_diligent_community_host():
    from app.platforms.base import detect_platform

    assert (
        detect_platform("https://eatwp.diligent.community/Portal/MeetingTypeList.aspx")
        == "civicweb"
    )


# --- CivicClerk: a third real tenant domain shape, WO-348 -----------------


def test_civicclerk_tenant_regex_accepts_bare_tenant_domain():
    # Real, live shape confirmed this WO: Upper Providence Township, PA's
    # confirmed hub is upperprovidencetwppa.civicclerk.com -- no
    # `.portal.`/`.api.` infix (it 301s to the `.portal.` host, but the
    # walker is handed the pre-redirect URL).
    match = _CIVICCLERK_TENANT_RE.match("upperprovidencetwppa.civicclerk.com")
    assert match is not None
    assert match.group(1) == "upperprovidencetwppa"


def test_civicclerk_tenant_regex_still_accepts_portal_and_api_shapes():
    assert _CIVICCLERK_TENANT_RE.match("southfultonga.api.civicclerk.com")
    assert _CIVICCLERK_TENANT_RE.match("edinburgtx.portal.civicclerk.com")


def test_civicclerk_tenant_regex_excludes_corporate_www_host():
    # www.civicclerk.com is CivicClerk's own marketing site, never a real
    # tenant (CORPORATE_HOSTS_BY_PLATFORM's own comment).
    assert _CIVICCLERK_TENANT_RE.match("www.civicclerk.com") is None
