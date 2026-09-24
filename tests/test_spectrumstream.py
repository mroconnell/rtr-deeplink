from app.platforms.spectrumstream import (
    SpectrumStreamAssetFinder,
    is_spectrumstream_non_gov_tenant,
    parse_spectrumstream_tenant,
)
from app.platforms.passive_verify import _spectrumstream_walker

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Every fixture below was fetched live 2026-09-24 (WO-1047) against real,
# current tenants -- confirmed against 5 real tenants (alhambra, arcadia,
# south_pasadena, gusd, bgpaa), all sharing one legacy ColdFusion template
# (see spectrumstream.py's own module docstring).

ALHAMBRA_URL = "https://spectrumstream.com/streaming/alhambra/meeting_2026_08_24.cfm"
ALHAMBRA_CAPTIONS_URL = (
    "https://www.spectrumstream.com/streaming/alhambra/meeting_captions/"
    "alhambra_2026_08_24.vtt"
)
GUSD_URL = "https://spectrumstream.com/streaming/gusd/2024_10_08.cfm"
SOUTH_PASADENA_URL = (
    "https://spectrumstream.com/streaming/south_pasadena/2026_01_14.cfm"
)
BGPAA_URL = "https://spectrumstream.com/streaming/bgpaa/2026_09_21.cfm"


async def test_resolve_real_alhambra_meeting_with_captions():
    # Real Alhambra, CA City Council meeting (2026-08-24) -- a real,
    # unauthenticated S3 MP4, real seek()-linked agenda items (a special
    # 5pm session and a regular 6pm session concatenated into one
    # recording, confirmed live), and a real, populated English caption
    # track.
    html = load_fixture("spectrumstream", "alhambra_meeting.html")
    captions = load_fixture("spectrumstream", "alhambra_captions.vtt")

    routes = {
        ALHAMBRA_URL: FakeResponse(status=200, text=html, url=ALHAMBRA_URL),
        ALHAMBRA_CAPTIONS_URL: FakeResponse(
            status=200, text=captions, url=ALHAMBRA_CAPTIONS_URL
        ),
    }

    with mock_session(routes):
        result = await SpectrumStreamAssetFinder().resolve(ALHAMBRA_URL)

    assert result.platform == "spectrumstream"
    assert result.title == "Alhambra City Council"
    assert result.date == "2026-08-24"
    assert result.jurisdiction == "Alhambra, CA"
    assert result.video_url == (
        "https://spectrum_streaming.s3.amazonaws.com/alhambra/alhambra_2026_08_24.mp4"
    )
    assert result.video_format == "mp4"
    assert result.transcript_language == "en"
    assert len(result.segments) > 500
    assert result.transcript_warnings == []
    assert result.video_warnings == []
    assert len(result.agenda_items) > 5
    assert result.agenda_items[0].start == 132


async def test_resolve_real_gusd_meeting_empty_captions_file():
    # Real Glendale USD Board of Education meeting (2024-10-08) -- a real,
    # confirmed "no captions yet" shape: the `tracks` array is present in
    # the jwplayer config, but its `file` is an empty string, not a real
    # .vtt URL. Also confirms the nested-body-name title/date extraction
    # ("Glendale Unified School District - Board of Education Meeting").
    html = load_fixture("spectrumstream", "gusd_meeting.html")

    routes = {GUSD_URL: FakeResponse(status=200, text=html, url=GUSD_URL)}

    with mock_session(routes):
        result = await SpectrumStreamAssetFinder().resolve(GUSD_URL)

    assert (
        result.title == "Glendale Unified School District - Board of Education Meeting"
    )
    assert result.date == "2024-10-08"
    assert result.jurisdiction == "Glendale Unified School District, CA"
    assert result.video_url == (
        "https://spectrum_streaming.s3.amazonaws.com/gusd/gusd_2024_10_08.mp4"
    )
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    assert len(result.agenda_items) > 0


async def test_resolve_real_south_pasadena_meeting_no_tracks_key_at_all():
    # Real South Pasadena, CA City Council meeting (2026-01-14) -- a
    # second real "no captions" shape: the jwplayer config carries no
    # `tracks` key at all (not even an empty one).
    html = load_fixture("spectrumstream", "south_pasadena_meeting.html")

    routes = {
        SOUTH_PASADENA_URL: FakeResponse(status=200, text=html, url=SOUTH_PASADENA_URL),
    }

    with mock_session(routes):
        result = await SpectrumStreamAssetFinder().resolve(SOUTH_PASADENA_URL)

    assert result.title == "City of South Pasadena - City Council"
    assert result.date == "2026-01-14"
    assert result.jurisdiction == "South Pasadena, CA"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_real_bgpaa_meeting_joint_powers_authority():
    # Burbank-Glendale-Pasadena Airport Authority -- a real joint powers
    # authority tenant, not a single city, confirming the curated
    # jurisdiction map handles a non-"City, ST"-shaped entry correctly.
    html = load_fixture("spectrumstream", "bgpaa_meeting.html")

    routes = {BGPAA_URL: FakeResponse(status=200, text=html, url=BGPAA_URL)}

    with mock_session(routes):
        result = await SpectrumStreamAssetFinder().resolve(BGPAA_URL)

    assert result.title == "Burbank-Glendale-Pasadena Airport Authority"
    assert result.date == "2026-09-21"
    assert result.jurisdiction == "Burbank-Glendale-Pasadena Airport Authority, CA"
    assert result.video_url == (
        "https://spectrum_streaming.s3.amazonaws.com/bgpaa/2026_09_21.mp4"
    )


async def test_resolve_live_cfm_is_a_warning_not_a_meeting():
    # `live.cfm` is a real, confirmed-live option value on every tenant
    # checked (the "Live Broadcast" entry) -- never a recorded meeting.
    url = "https://spectrumstream.com/streaming/alhambra/live.cfm"

    with mock_session({}):
        result = await SpectrumStreamAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == [
        "This is a live-broadcast page, not a recorded meeting."
    ]


def test_parse_spectrumstream_tenant():
    assert (
        parse_spectrumstream_tenant(
            "https://spectrumstream.com/streaming/alhambra/meeting_2026_08_24.cfm"
        )
        == "alhambra"
    )
    assert (
        parse_spectrumstream_tenant("https://www.spectrumstream.com/streaming/gusd/")
        == "gusd"
    )
    # The vendor's own shared static-asset folder -- never a tenant.
    assert (
        parse_spectrumstream_tenant(
            "https://spectrumstream.com/streaming/_jwplayer/jwplayer.js"
        )
        is None
    )
    # Confirmed non-government tenants (WO-1047 discovery notes).
    assert (
        parse_spectrumstream_tenant("https://spectrumstream.com/streaming/gef/x.cfm")
        is None
    )
    assert (
        parse_spectrumstream_tenant(
            "https://spectrumstream.com/streaming/lusd_grad/x.cfm"
        )
        is None
    )
    # An unrelated host is never claimed.
    assert (
        parse_spectrumstream_tenant("https://example.com/streaming/alhambra/") is None
    )


def test_is_spectrumstream_non_gov_tenant():
    assert is_spectrumstream_non_gov_tenant("gef")
    assert is_spectrumstream_non_gov_tenant("lef")
    assert is_spectrumstream_non_gov_tenant("lusd_grad")
    assert is_spectrumstream_non_gov_tenant("some_other_grad")
    assert not is_spectrumstream_non_gov_tenant("alhambra")


async def test_walker_bootstraps_from_broken_root_fragment():
    # Every real tenant's bare root is a truncated fragment carrying only
    # the newest meeting's filename (confirmed live on Alhambra: a bare
    # `<option value="meeting_2026_08_24.cfm">` with no closing tag and
    # no label) -- the walker reads that filename, then fetches THAT
    # meeting's own page for the real, full past-meetings `<select>`.
    root_fragment = load_fixture("spectrumstream", "alhambra_root_fragment.html")
    meeting_html = load_fixture("spectrumstream", "alhambra_meeting.html")
    root_url = "https://spectrumstream.com/streaming/alhambra/"

    routes = {
        root_url: FakeResponse(status=200, text=root_fragment, url=root_url),
        ALHAMBRA_URL: FakeResponse(status=200, text=meeting_html, url=ALHAMBRA_URL),
    }

    with mock_session(routes):
        candidates = await _spectrumstream_walker(root_url)

    assert candidates
    assert candidates[0]["date"] == "2026-09-14"
    assert candidates[1]["url"] == ALHAMBRA_URL
    assert candidates[1]["date"] == "2026-08-24"
    assert not any(c["url"].endswith("live.cfm") for c in candidates)


async def test_walker_falls_back_to_seed_when_root_has_no_select():
    # South Pasadena's own root is a real, live page (a Castr live embed,
    # its past-meetings `<select>` entirely HTML-commented out) -- the
    # walker falls back to a known-real seed meeting page instead.
    root_live_html = load_fixture("spectrumstream", "south_pasadena_root_live.html")
    meeting_html = load_fixture("spectrumstream", "south_pasadena_meeting.html")
    root_url = "https://spectrumstream.com/streaming/south_pasadena/"

    routes = {
        root_url: FakeResponse(status=200, text=root_live_html, url=root_url),
        SOUTH_PASADENA_URL: FakeResponse(
            status=200, text=meeting_html, url=SOUTH_PASADENA_URL
        ),
    }

    with mock_session(routes):
        candidates = await _spectrumstream_walker(root_url)

    assert candidates
    assert candidates[0]["date"] == "2026-09-22"
    assert not any(c["url"].endswith("live.cfm") for c in candidates)


async def test_resolve_listing_root_delegates_to_walker():
    root_fragment = load_fixture("spectrumstream", "gusd_root_fragment.html")
    meeting_html = load_fixture("spectrumstream", "gusd_meeting.html")
    root_url = "https://spectrumstream.com/streaming/gusd/"

    # `resolve()` walks candidates newest-first, and the fixture's own
    # embedded `<select>` lists a newer real meeting (2026-09-08) ahead of
    # the one this fixture's own page IS (2024-10-08) -- reusing the same
    # real fixture content for both stands in for a second real meeting
    # page, since only the delegation (jurisdiction/video extraction)
    # is under test here, not that specific meeting's own content.
    newest_url = "https://spectrumstream.com/streaming/gusd/2026_09_08.cfm"
    routes = {
        root_url: FakeResponse(status=200, text=root_fragment, url=root_url),
        newest_url: FakeResponse(status=200, text=meeting_html, url=newest_url),
        GUSD_URL: FakeResponse(status=200, text=meeting_html, url=GUSD_URL),
    }

    with mock_session(routes):
        result = await SpectrumStreamAssetFinder().resolve(root_url)

    assert result.jurisdiction == "Glendale Unified School District, CA"
    assert result.video_url is not None
    assert result.source_url == newest_url
