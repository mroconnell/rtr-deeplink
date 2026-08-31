from app.platforms.castus import CastusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Castus (cloud.castus.tv) -- WO-19, 2026-08-21. Real fixtures below are
# from a live Billings, MT City Council Work Session recording
# (comm7tv/video/6a83b3f9d94c83000226f83d) -- see castus.py's own module
# docstring for the full investigation. video_info.json is a trimmed
# real `/upload/info` response (real fields the adapter reads kept
# as-is; the response's own `views`/`comments`/`likes`/`watchBuys`/etc.
# arrays dropped entirely -- those carry real site visitors' IP
# addresses/user agents, which the adapter never reads and shouldn't be
# committed to a fixture regardless). captions.vtt is trimmed to its
# first 30 real cues (same "trimmed real VTT fixture" convention
# test_telvue.py/test_escribe.py already use for a long real transcript).
# destinyhosted_billings_agenda.html is the real, full, public
# destinyhosted.com agenda page one of the real agenda items links to --
# kept in full (16KB, no PII -- it's a public government agenda page).

PAGE_URL = (
    "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME"
)
VIDEO_INFO_URL = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/info"
CAPTIONS_URL = (
    "https://dlttx48mxf9m3.cloudfront.net/captions/6a83b3f9d94c83000226f83d.vtt"
)
HLS_URL = (
    "https://dlttx48mxf9m3.cloudfront.net/outputs/"
    "6a83b3f9d94c83000226f83d/Default/HLS/out.m3u8"
)
DESTINYHOSTED_URL = "https://public.destinyhosted.com/24568/agenda/agenda.cfm?seq=2036"


async def test_resolve_real_billings_city_council_work_session():
    video_info = load_fixture("castus", "video_info.json")
    captions = load_fixture("castus", "captions.vtt")
    destinyhosted_html = load_fixture("castus", "destinyhosted_billings_agenda.html")

    routes = {
        CAPTIONS_URL: FakeResponse(status=200, text=captions, url=CAPTIONS_URL),
        DESTINYHOSTED_URL: FakeResponse(
            status=200, text=destinyhosted_html, url=DESTINYHOSTED_URL
        ),
    }
    post_routes = {
        VIDEO_INFO_URL: FakeResponse(status=200, text=video_info, url=VIDEO_INFO_URL),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await CastusAssetFinder().resolve(PAGE_URL)

    assert result.platform == "castus"
    assert result.external_id == "castus:comm7tv:6a83b3f9d94c83000226f83d"
    # metadata.filename's own "{title} - {Month DD, YYYY}" shape -- NOT
    # the file's `date`/`original_date` fields, which are upload
    # timestamps two days after the real meeting date (see module
    # docstring).
    assert result.title == "Billings City Council Work Session"
    assert result.date == "2026-08-17"
    # extract_jurisdiction_chain() finds "City of Billings" from the real
    # destinyhosted page text; its own ZIP (a PO Box, not a Census-covered
    # ZCTA) can't fill in the state, so the known-tenant map for
    # destinyhosted id 24568 supplies the final "Billings, MT" (see
    # castus.py's _jurisdiction_from_destinyhosted()).
    assert result.jurisdiction == "Billings, MT"
    assert result.video_url == HLS_URL
    assert result.video_format == "m3u8"
    assert result.video_warnings == []

    assert len(result.segments) == 30
    assert result.transcript_language == "en"
    # parse_vtt()'s existing generic _TAG_RE strips the AWS-Transcribe
    # voice/confidence tags with no Castus-specific handling needed.
    assert "<v." not in result.segments[0].text
    assert "<c." not in result.segments[0].text
    assert "17th" in result.segments[0].text

    assert len(result.agenda_items) == 7
    assert result.agenda_items[0].start == 16
    assert (
        result.agenda_items[0].text == "PROCLAMATION: Billings Navy Week - August 17-23"
    )
    assert result.agenda_items[-1].text == "ADJOURN:"


async def test_resolve_no_video_found_for_unknown_id():
    post_routes = {
        VIDEO_INFO_URL: FakeResponse(
            status=200,
            text='{"response": {"success": false, "payload": {}}}',
            url=VIDEO_INFO_URL,
        ),
    }

    with mock_session({}, post_routes=post_routes):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/comm7tv/video/doesnotexist?page=HOME"
        )

    assert result.platform == "castus"
    assert result.video_warnings == ["No video found for this Castus meeting."]


async def test_resolve_rejects_url_with_no_tenant_or_video_id():
    result = await CastusAssetFinder().resolve("https://cloud.castus.tv/vod/")

    assert result.platform == "castus"
    assert result.video_warnings == [
        "Could not find a tenant/video id in this Castus URL."
    ]


async def test_jurisdiction_from_tenant_slug_fallback_is_none_for_real_tenant():
    """Exercises the tenant-slug fallback path directly (no destinyhosted
    hyperlink at all in the agenda) using this adapter's own real
    Billings, MT tenant slug, "comm7tv" -- confirmed it does NOT parse as
    a place name (unlike a hypothetical "cityofsomewhereca"), so the
    fallback should return None rather than a wrong guess.
    """
    assert CastusAssetFinder._jurisdiction_from_tenant_slug("comm7tv") is None


async def test_jurisdiction_from_tenant_slug_known_tenant_westford():
    # A real second Castus customer confirmed 2026-08-30, "westfordcat"
    # (Westford, MA) -- see castus.py's own comment on
    # _KNOWN_TENANT_SLUG_JURISDICTIONS for the full investigation
    # (confirmed via a live VIDEO_INFO_URL call, real content "Select
    # Board Meeting - 8/25/2026"). This is the real customer that proved
    # the generic fallback needed a curated entry: "cat" isn't a stripped
    # branding suffix, and "Westford" is a genuine 6-state collision
    # (MA/NY/VT/WI/MN/ND) the generic lookup correctly declines on its
    # own, confirmed below.
    assert (
        CastusAssetFinder._jurisdiction_from_tenant_slug("westfordcat")
        == "Westford, MA"
    )


async def test_jurisdiction_from_tenant_slug_declines_ambiguous_westford_without_curation():
    # Confirms the generic fallback's own reasoning for why "westfordcat"
    # needed a curated entry above: even with the "cat" suffix stripped,
    # bare "Westford" is a real 6-state collision the generic
    # Census-backed lookup correctly declines rather than guessing.
    assert CastusAssetFinder._jurisdiction_from_tenant_slug("westford") is None
