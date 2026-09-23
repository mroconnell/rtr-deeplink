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


# --- Listing walk (2026-09-23) -------------------------------------------
# Real fixtures from the same-day investigation in castus.py's module
# docstring ("Listing walk"): playlist_lincoln_town_meeting.json is the
# first 3 of 49 real videos from `GET .../playlist/lincoln/Town%20Meeting`;
# home_recent_blackstone.json is the first 6 of ~30 real videos from
# Blackstone's `home/recent`; tenant_config_blackstone.json is Blackstone's
# real tenant config (playlistOrder trimmed to 5 entries); the two
# video_info_*.json files are trimmed real `/upload/info` responses for
# the videos each walk picks. Every item is trimmed to the fields the
# adapter reads (no views/comments/likes arrays), same convention as
# video_info.json above.

PLAYLIST_API_URL = (
    "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/playlist/lincoln/"
    "Town%20Meeting"
)
BLACKSTONE_CONFIG_URL = (
    "https://837sc3bew0.execute-api.us-west-2.amazonaws.com/blackstone"
)
BLACKSTONE_RECENT_URL = (
    "https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/"
    "662ab8f7462d1041bed8203e/home/recent"
)


async def test_resolve_playlist_url_walks_to_newest_video():
    # The real Lincoln, MA playlist URL found by hand on 2026-09-23. The
    # walk must land on 69cbe826f23ec40002de421d -- the exact video a
    # human had already found on that same page and confirmed through
    # the one-video path.
    routes = {
        PLAYLIST_API_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "playlist_lincoln_town_meeting.json"),
            url=PLAYLIST_API_URL,
        ),
    }
    post_routes = {
        VIDEO_INFO_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "video_info_lincoln_annual_town_meeting.json"),
            url=VIDEO_INFO_URL,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/lincoln/playlist/Town%20Meeting?page=PLAYLIST"
        )

    assert result.external_id == "castus:lincoln:69cbe826f23ec40002de421d"
    # The picked video's own canonical URL, not the playlist URL (see the
    # module docstring's "After picking" note).
    assert (
        result.source_url
        == "https://cloud.castus.tv/vod/lincoln/video/69cbe826f23ec40002de421d?page=HOME"
    )
    # Real title as Castus stores it -- two spaces before the date; the
    # filename carries no "- Month DD, YYYY" tail, so no date is parsed.
    assert result.title == "Annual Town Meeting  03.28.26"
    assert result.date is None
    assert result.video_url == (
        "https://dlttx48mxf9m3.cloudfront.net/outputs/"
        "69cbe826f23ec40002de421d/Default/HLS/out.m3u8"
    )
    assert result.video_warnings == []
    assert result.jurisdiction == "Lincoln, MA"
    # captioned is False on this real video: no VTT fetch is attempted.
    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]


async def test_resolve_hash_router_playlist_url_is_accepted():
    # What a browser's address bar shows after the redirect shell runs
    # (`/vod/#/{tenant}/...`) -- same walk, same result.
    routes = {
        PLAYLIST_API_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "playlist_lincoln_town_meeting.json"),
            url=PLAYLIST_API_URL,
        ),
    }
    post_routes = {
        VIDEO_INFO_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "video_info_lincoln_annual_town_meeting.json"),
            url=VIDEO_INFO_URL,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/#/lincoln/playlist/Town%20Meeting?page=PLAYLIST"
        )

    assert result.external_id == "castus:lincoln:69cbe826f23ec40002de421d"


async def test_resolve_unknown_playlist_reports_plainly():
    # Confirmed live: an unknown playlist name returns HTTP 500 with a
    # plain-text body, not a JSON envelope.
    bad_url = (
        "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/playlist/lincoln/"
        "No%20Such%20Playlist"
    )
    routes = {
        bad_url: FakeResponse(
            status=500,
            text="Error getting playlist: Playlist No Such Playlist does not exist for lincoln",
            url=bad_url,
        ),
    }

    with mock_session(routes, post_routes={}):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/lincoln/playlist/No%20Such%20Playlist?page=PLAYLIST"
        )

    assert result.external_id is None
    assert result.video_warnings == [
        'Could not find a playlist named "No Such Playlist" on this Castus channel.'
    ]


async def test_resolve_hub_url_walks_recent_behind_strict_title_gate():
    # The real Blackstone, MA hub URL found by hand on 2026-09-23. Its
    # real `recent` feed, newest first: "Parks and Recreation 09-21-26",
    # "Zoning Board 09-16-26", "Board of Selectmen 09-15-26", "Library
    # Trustees 09-14-26", "Parks and Recreation 09-14-26", "9:11 Memorial
    # 2026". The strict gate (a governing-body word required) rejects the
    # memorial as intended -- and, a known false negative recorded in the
    # module docstring, also "Parks and Recreation" (no such word), so
    # the walk lands on the Zoning Board meeting five days older.
    routes = {
        BLACKSTONE_CONFIG_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "tenant_config_blackstone.json"),
            url=BLACKSTONE_CONFIG_URL,
        ),
        BLACKSTONE_RECENT_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "home_recent_blackstone.json"),
            url=BLACKSTONE_RECENT_URL,
        ),
    }
    post_routes = {
        VIDEO_INFO_URL: FakeResponse(
            status=200,
            text=load_fixture("castus", "video_info_blackstone_zoning_board.json"),
            url=VIDEO_INFO_URL,
        ),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/blackstone/?page=PLAYLIST"
        )

    assert result.external_id == "castus:blackstone:6aab2089c74c3300024832f0"
    assert (
        result.source_url
        == "https://cloud.castus.tv/vod/blackstone/video/6aab2089c74c3300024832f0?page=HOME"
    )
    assert result.title == "Zoning Board 09-16-26.mp4"
    assert result.video_format == "m3u8"
    assert result.video_warnings == []
    # No agenda hyperlinks on this real video, so the slug path answers --
    # via the curated entry, because the generic lookup says "VA" (see
    # castus.py's _KNOWN_TENANT_SLUG_JURISDICTIONS note).
    assert result.jurisdiction == "Blackstone, MA"


async def test_jurisdiction_from_tenant_slug_real_2026_09_23_tenants():
    # The generic path's real wrong answer that forced the curated entry.
    assert (
        CastusAssetFinder._jurisdiction_from_tenant_slug("blackstone")
        == "Blackstone, MA"
    )
    assert CastusAssetFinder._jurisdiction_from_tenant_slug("lincoln") == "Lincoln, MA"
    assert CastusAssetFinder._jurisdiction_from_tenant_slug("durham") == "Durham, NH"
    # Uncurated on purpose: the generic Census-backed path's first real
    # positive (nationally unique name, confirmed by the tenant's own
    # playlist title).
    assert (
        CastusAssetFinder._jurisdiction_from_tenant_slug("tyngsborough")
        == "Tyngsborough, MA"
    )


async def test_resolve_hub_url_unknown_tenant_reports_plainly():
    # Confirmed live: an unknown tenant slug returns HTTP 404 with a
    # plain-text body ("No configuration found for the company name ...").
    bad_url = "https://837sc3bew0.execute-api.us-west-2.amazonaws.com/no-such-tenant"
    routes = {
        bad_url: FakeResponse(
            status=404,
            text="No configuration found for the company name no-such-tenant",
            url=bad_url,
        ),
    }

    with mock_session(routes, post_routes={}):
        result = await CastusAssetFinder().resolve(
            "https://cloud.castus.tv/vod/no-such-tenant/?page=HOME"
        )

    assert result.external_id is None
    assert result.video_warnings == [
        "Could not find this Castus channel's configuration."
    ]


async def test_resolve_self_hosted_vod_widget_is_named_not_guessed():
    # Millbury, MA's real URL -- a self-hosted "Castus VOD Widget", a
    # different product with host-local APIs and UUID video ids (module
    # docstring). No request is made; the warning names the product.
    result = await CastusAssetFinder().resolve(
        "https://millbury-public-access.vod.castus.tv/vod/?video=56af3108-2000-4c8b-bbe6-e0bfef952292"
    )

    assert result.external_id is None
    assert result.video_warnings == [
        "This is a self-hosted Castus VOD Widget site (a different product "
        "from cloud.castus.tv) -- not supported yet."
    ]


def test_pick_newest_orders_by_upload_date_then_playlist_position():
    # Real ordering quirk from Lincoln's playlist: the tenant's curated
    # `sort` order is NOT upload order (sort 2 was uploaded after sort 1),
    # so upload date decides, and `sort` only breaks exact ties.
    import json

    videos = json.loads(load_fixture("castus", "playlist_lincoln_town_meeting.json"))[
        "response"
    ]["payload"]
    assert [v["sort"] for v in videos] == [0, 1, 2]
    assert videos[2]["date"] > videos[1]["date"]

    picked = CastusAssetFinder._pick_newest(videos, require_allowlist=False)
    assert picked["_id"] == "69cbe826f23ec40002de421d"

    # Drop the real newest: the remaining two are "State of the Town"
    # sessions; the later upload (sort 2) wins over the earlier (sort 1).
    picked = CastusAssetFinder._pick_newest(videos[1:], require_allowlist=False)
    assert picked["_id"] == "6924d8df10217800025a73e0"

    # A future premiere and an untranscoded upload are both skipped.
    tied = [dict(videos[0]), dict(videos[0])]
    tied[0]["_id"], tied[0]["premiereDate"] = "future", "2999-01-01T00:00:00.000Z"
    tied[1]["_id"], tied[1]["transcoded"] = "unfinished", False
    assert CastusAssetFinder._pick_newest(tied, require_allowlist=False) is None


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
