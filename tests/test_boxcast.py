"""Tests for BoxCast channel-broadcast matching (app/platforms/boxcast.py).

Real shapes confirmed live 2026-08-29 via direct `curl` against three
independent real government BoxCast tenants (Wilmington OH, St. Louis
County MO, City of Hondo TX) -- see boxcast.py's own module docstring.
Wilmington's real data is used throughout: channel `x1jps4n28nlgtaozsv5y`,
broadcast `afjvqrnty4auvtywkunc` ("Wilmington City Council Regular
Meeting 8/6/2026", `starts_at` "2026-08-06T23:00:00Z",
`time_zone_offset` -240 -- i.e. 7pm Eastern on 2026-08-06, confirmed via
a real `/view` fetch returning a working signed HLS playlist).
"""

import json

from app.platforms import boxcast

from aiohttp_mock import FakeResponse, mock_session

CHANNEL_ID = "x1jps4n28nlgtaozsv5y"
SEARCH_URL = f"https://rest.boxcast.com/channels/{CHANNEL_ID}/broadcasts/_search?l=50"

# Real (trimmed) shape from a live `_search` response.
WILMINGTON_BROADCAST = {
    "id": "afjvqrnty4auvtywkunc",
    "name": "Wilmington City Council Regular Meeting 8/6/2026",
    "starts_at": "2026-08-06T23:00:00Z",
    "stops_at": "2026-08-07T00:25:00Z",
    "timeframe": "past",
    "time_zone_offset": -240,
    "recording_duration_seconds": 5043.23,
}
FUTURE_BROADCAST = {
    "id": "zzzfuture000000000000",
    "name": "Wilmington City Council Regular Meeting 12/1/2026",
    "starts_at": "2026-12-01T21:30:00Z",
    "stops_at": "2026-12-01T23:30:00Z",
    "timeframe": "future",
    "time_zone_offset": -240,
    "recording_duration_seconds": 0,
}
REAL_PLAYLIST_URL = (
    "https://play.boxcast.com/p/skd3evxqqhli7timl3qw/r/157.601s/5200.83s/"
    "v/all.m3u8?Expires=1788149760&Signature=abc&Key-Pair-Id=xyz"
)
VIEW_URL = f"https://rest.boxcast.com/broadcasts/{WILMINGTON_BROADCAST['id']}/view"


def _search_response(broadcasts):
    return FakeResponse(status=200, text=json.dumps({"results": broadcasts}))


async def test_find_channel_match_matches_by_local_calendar_date():
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST, FUTURE_BROADCAST]),
        VIEW_URL: FakeResponse(
            status=200,
            text=json.dumps({"status": "recorded", "playlist": REAL_PLAYLIST_URL}),
        ),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )

    assert match is not None
    assert match.broadcast_id == "afjvqrnty4auvtywkunc"
    assert match.video_url == REAL_PLAYLIST_URL


async def test_find_channel_match_uses_local_time_zone_not_bare_utc_date():
    # Real case this guards against: starts_at is already 11pm UTC on the
    # 6th (7pm Eastern) -- a bare UTC-date comparison against "2026-08-06"
    # would still happen to work here, but this pins the local-shift math
    # directly rather than relying on the search test above alone (see
    # _broadcast_local_date's own comment on why a later-starting meeting
    # would actually roll over).
    assert boxcast._broadcast_local_date(WILMINGTON_BROADCAST) == "2026-08-06"


async def test_find_channel_match_ignores_future_broadcasts():
    routes = {SEARCH_URL: _search_response([FUTURE_BROADCAST])}
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-12-01"
        )
    assert match is None


async def test_find_channel_match_disambiguates_same_day_meetings_by_title():
    budget = {
        **WILMINGTON_BROADCAST,
        "id": "budgetmeetingid00000000",
        "name": "Wilmington Budget Committee Meeting",
    }
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST, budget]),
        VIEW_URL: FakeResponse(
            status=200,
            text=json.dumps({"status": "recorded", "playlist": REAL_PLAYLIST_URL}),
        ),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is not None
    assert match.broadcast_id == "afjvqrnty4auvtywkunc"


async def test_find_channel_match_declines_an_unresolvable_same_day_tie():
    other = {
        **WILMINGTON_BROADCAST,
        "id": "othermeetingid000000000",
        "name": "Wilmington Regular Meeting",
    }
    routes = {SEARCH_URL: _search_response([WILMINGTON_BROADCAST, other])}
    with mock_session(routes):
        # "Special Session" shares no meaningful token with either real
        # broadcast name -- both score 0, a genuine tie, so this must
        # decline rather than guess.
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Special Session", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_declines_when_recording_not_yet_available():
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST]),
        VIEW_URL: FakeResponse(status=200, text=json.dumps({"status": "processing"})),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_returns_none_on_search_failure():
    routes = {SEARCH_URL: FakeResponse(status=500)}
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_returns_none_without_meeting_date():
    match = await boxcast.find_channel_match(CHANNEL_ID, "Some Meeting", None)
    assert match is None


# ---------------------------------------------------------------------------
# WO-227 (2026-09-11): BoxcastAssetFinder, the standalone AssetFinder.
#
# Real data from all FOUR confirmed tenants, fetched live 2026-09-11 (in
# addition to the three above, already used by find_channel_match's own
# tests): Atlantic City NJ (the new real tenant this WO was built for --
# channel `lqsszohc5p0q4yemoddl`, account `uihhbexsazftbrytfhlb`, real
# captions), St. Louis County - Clayton MO (channel `wdeojvfau9uqc9qt6k8z`,
# account `xfukwjyyursckbjslcb5`, ALSO real captions -- a real St. Louis
# Call Newspapers article, found independently, confirms St. Louis County
# pays a yearly fee for live closed-captioning), Hondo TX (channel
# `ffa3guzpvskttftiveop`, account `n8fsyrc76zlufwj5dt8e`, no captions --
# its real account name is the genuinely messy `"City of Hondo - ,"`,
# missing its state, kept as-is rather than guessed/cleaned up). Signature/
# Policy/Key-Pair-Id query values below are shortened placeholders, same
# convention `REAL_PLAYLIST_URL` above already uses -- the real signed
# values are meaningless outside their own expiry window anyway.
# ---------------------------------------------------------------------------

AC_CHANNEL_ID = "lqsszohc5p0q4yemoddl"
AC_ACCOUNT_ID = "uihhbexsazftbrytfhlb"
AC_BROADCAST_ID = "wuv2iiwzlyzhny1zietp"
AC_BROADCAST_SLUG = "city-council-meeting-081926-kdhkjrwnostnrznx7yxy"

# The real (trimmed) `GET /channels/{id}/broadcasts?...&s=-starts_at`
# response for Atlantic City, newest first -- confirms this WO's own
# hand-check reasoning: the real City Council meeting sits behind three
# real non-meeting broadcasts in "newest past" order.
AC_CHANNEL_BROADCASTS = [
    {
        "id": "zx3kxrersqkl3mauxefj",
        "name": "Great Day Cafe Grand Opening 09/09/26",
        "starts_at": "2026-09-09T15:05:00Z",
        "stops_at": "2026-09-09T15:36:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "great-day-cafe-grand-opening-090926-qlaexwjxy6cgvbrfqokw",
    },
    {
        "id": "jgd724osemy5esg1lzsh",
        "name": "CITISTAT",
        "starts_at": "2026-09-02T21:00:00Z",
        "stops_at": "2026-09-02T21:21:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "citistat-smjo0e3651g4tf7c7x2h",
    },
    {
        "id": AC_BROADCAST_ID,
        "name": "City Council Meeting 08/19/26",
        "starts_at": "2026-08-19T20:30:00Z",
        "stops_at": "2026-08-19T22:17:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": AC_BROADCAST_SLUG,
    },
    {
        "id": "nilgyynrh9scfvj1o1e5",
        "name": "Mayor's Press Conference K. Hovnanian Groundbreaking 08/12/26",
        "starts_at": "2026-08-12T15:00:00Z",
        "stops_at": "2026-08-12T15:47:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "mayors-press-conference-k-hovnanian-groundbreaking-081226-x",
    },
    {
        "id": "f9e1perfzdztnnzn9sce",
        "name": "CITISTAT Meeting 08/05/26",
        "starts_at": "2026-08-05T21:00:00Z",
        "stops_at": "2026-08-05T21:30:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "citistat-meeting-080526-vsonkzv5hfip3i4ncn3t",
    },
    {
        "id": "pc8cxrqivjig8ajomji0",
        "name": "Coursey Building Dedication Ceremony 08/05/26",
        "starts_at": "2026-08-05T15:00:00Z",
        "stops_at": "2026-08-05T16:09:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "coursey-building-dedication-ceremony-080526-x",
    },
    {
        "id": "wrc2beig4efbiughmjac",
        "name": "City Council Meeting 07/22/26",
        "starts_at": "2026-07-22T20:30:00Z",
        "stops_at": "2026-07-22T22:54:00Z",
        "timeframe": "past",
        "account_id": AC_ACCOUNT_ID,
        "channel_id": "city-council-meeting-072226-cxjtwtq1nked4x9enztd",
    },
]

# The real, FULL `GET /broadcasts/{id}` object for the 08/19 meeting --
# unlike the channel-listing items above, this carries `time_zone_offset`
# (confirmed live: the listing endpoint omits it on every item, WO-227's
# own real bug -- see resolve()'s own comment on why the picked broadcast
# is always re-fetched this way before its date is computed).
AC_BROADCAST_FULL = {
    "id": AC_BROADCAST_ID,
    "name": "City Council Meeting 08/19/26",
    "starts_at": "2026-08-19T20:30:00Z",
    "stops_at": "2026-08-19T22:17:00Z",
    "timeframe": "past",
    "time_zone_offset": -240,
    "account_id": AC_ACCOUNT_ID,
    "channel_id": AC_BROADCAST_SLUG,
}

AC_VIEW = {
    "status": "recorded",
    "playlist": "https://play.boxcast.com/p/ynypgubnhhubirooivog/v/all.m3u8"
    "?Expires=1789257600&Signature=sig123&Key-Pair-Id=xyz",
}

AC_ACCOUNT = {
    "id": AC_ACCOUNT_ID,
    "name": "City of Atlantic City, NJ",
    "channel_id": AC_CHANNEL_ID,
}

# Real master HLS playlist (trimmed to one variant), confirmed live to
# carry a genuine `#EXT-X-MEDIA:TYPE=SUBTITLES` English track -- the
# discovery this WO's own caption support is built from.
AC_MASTER_URL = AC_VIEW["playlist"]
AC_SUBTITLE_URL = (
    "https://play.boxcast.com/p/ynypgubnhhubirooivog/v/English.m3u8"
    "?Expires=1789257600&Signature=sig456&Key-Pair-Id=xyz"
)
AC_MASTER_M3U8 = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",NAME="English",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="en",URI="{AC_SUBTITLE_URL}"
#EXT-X-STREAM-INF:BANDWIDTH=996483,AVERAGE-BANDWIDTH=839754,CODECS="avc1.42001e,mp4a.40.2",RESOLUTION=426x240,SUBTITLES="sub1",FRAME-RATE=30.000
https://play.boxcast.com/p/ynypgubnhhubirooivog/v/240p.m3u8?Expires=1789257600&Signature=sig789&Key-Pair-Id=xyz
"""

# Three REAL, consecutive ~12-second WebVTT caption segments (indices
# 250-252 of the real 533-segment track), fetched live 2026-09-11 from
# the real 08/19/26 Atlantic City City Council meeting -- a real
# councilmember's real remarks about the Public Works department, ~50
# minutes into the meeting. Confirms the real, positive finding WO-227's
# brief didn't expect: BoxCast captions exist and are server-fetchable on
# some tenants. Each segment's own cue timestamps are ALREADY absolute
# (broadcast-relative) -- see boxcast.py's own module docstring for the
# live verification (20 segments sampled across the full recording) that
# ruled out needing any `start_mpegts`-based offset.
AC_CAPTION_SEG_1_URL = (
    "https://captions.boxcast.com/recordings/ynypgubnhhubirooivog/webvtt"
    "?Policy=p1&Signature=s1&Key-Pair-Id=xyz&lang=en"
    "&start_mpegts=318535344&stop_mpegts=319615254"
)
AC_CAPTION_SEG_2_URL = (
    "https://captions.boxcast.com/recordings/ynypgubnhhubirooivog/webvtt"
    "?Policy=p2&Signature=s2&Key-Pair-Id=xyz&lang=en"
    "&start_mpegts=319615335&stop_mpegts=320695245"
)
AC_CAPTION_SEG_3_URL = (
    "https://captions.boxcast.com/recordings/ynypgubnhhubirooivog/webvtt"
    "?Policy=p3&Signature=s3&Key-Pair-Id=xyz&lang=en"
    "&start_mpegts=320695335&stop_mpegts=321775245"
)
AC_SUBTITLE_MEDIA_M3U8 = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-TARGETDURATION:12
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:11.999,
{AC_CAPTION_SEG_1_URL}
#EXTINF:12.000,
{AC_CAPTION_SEG_2_URL}
#EXTINF:12.000,
{AC_CAPTION_SEG_3_URL}
"""
AC_CAPTION_SEG_1_TEXT = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:49439686,LOCAL:00:00:00.000

284
00:49:47.427 --> 00:49:50.787
we're well informed and I'd like to take time I've always given

285
00:49:51.027 --> 00:49:54.467
the police and fire. Their due respect because they do

286
00:49:54.547 --> 00:49:56.627
a tremendous job. But I really want to point out

287
00:49:58.307 --> 00:50:01.267
to director Lewis in public works. Her team
"""
AC_CAPTION_SEG_2_TEXT = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:49439686,LOCAL:00:00:00.000

288
00:50:02.227 --> 00:50:05.507
is tremendous we have a great in-house staff the public will not

289
00:50:05.747 --> 00:50:07.987
see the back here because that's where we hold out.

290
00:50:09.587 --> 00:50:12.947
Personal business but when I came here 16 years ago it was

291
00:50:13.027 --> 00:50:13.187
a mess.
"""
AC_CAPTION_SEG_3_TEXT = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:49439686,LOCAL:00:00:00.000

292
00:50:15.587 --> 00:50:18.227
Public Works. Do Crystal

293
00:50:19.107 --> 00:50:22.467
director is tremendous back then. It is beautiful

294
00:50:23.667 --> 00:50:23.987
we haven't had

295
00:50:25.507 --> 00:50:28.947
a conference room like that to sit down and do. The people's
"""

# Wilmington OH's own real broadcast/account (no subtitle track -- video
# only, confirmed live) -- used for the direct-`/view` link test and as
# the video-only contrast case against Atlantic City's real captions.
WILM_CHANNEL_ID = "x1jps4n28nlgtaozsv5y"
WILM_ACCOUNT_ID = "gutfku8y1lmddbijjyam"
WILM_BROADCAST_ID = "p4zgybgffhenii05u50b"
WILM_BROADCAST_SLUG = "wilmington-city-council-meeting-932026-kfqggledgvyp3dpduiwt"
WILM_BROADCAST_FULL = {
    "id": WILM_BROADCAST_ID,
    "name": "Wilmington City Council Meeting 9/3/2026",
    "starts_at": "2026-09-03T23:00:00Z",
    "stops_at": "2026-09-04T01:55:00Z",
    "timeframe": "past",
    "time_zone_offset": -240,
    "account_id": WILM_ACCOUNT_ID,
    "channel_id": WILM_BROADCAST_SLUG,
}
WILM_VIEW = {
    "status": "recorded",
    "playlist": "https://play.boxcast.com/p/wazg6xb9fdmdgl2jxssu/v/all.m3u8"
    "?Expires=1789257600&Signature=sigw&Key-Pair-Id=xyz",
}
WILM_ACCOUNT = {
    "id": WILM_ACCOUNT_ID,
    "name": "City of Wilmington, OH",
    "channel_id": WILM_CHANNEL_ID,
}
# Real master playlist -- confirmed live to carry NO subtitle track at
# all (unlike Atlantic City's above).
WILM_MASTER_M3U8 = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=973331,AVERAGE-BANDWIDTH=942403,CODECS="avc1.42001e,mp4a.40.2",RESOLUTION=432x240,FRAME-RATE=30.000
https://play.boxcast.com/p/wazg6xb9fdmdgl2jxssu/v/240p.m3u8?Expires=1789257600&Signature=sigw2&Key-Pair-Id=xyz
"""

# Hondo TX's real channel scan -- one real broadcast, a real, genuinely
# messy account name (missing its state) kept as-is.
HONDO_CHANNEL_ID = "ffa3guzpvskttftiveop"
HONDO_ACCOUNT_ID = "n8fsyrc76zlufwj5dt8e"
HONDO_BROADCAST_ID = "b63gkdi4yagapbvtoopb"
HONDO_BROADCAST_SLUG = "regular-city-council-meeting---82426-c79nxf7c0jusetnphnzb"
HONDO_CHANNEL_BROADCASTS = [
    {
        "id": HONDO_BROADCAST_ID,
        "name": "Regular City Council Meeting - 8/24/26",
        "starts_at": "2026-08-24T22:50:00Z",
        "stops_at": "2026-08-25T00:00:00Z",
        "timeframe": "past",
        "account_id": HONDO_ACCOUNT_ID,
        "channel_id": HONDO_BROADCAST_SLUG,
    }
]
HONDO_BROADCAST_FULL = {
    **HONDO_CHANNEL_BROADCASTS[0],
    "time_zone_offset": -300,
}
HONDO_VIEW = {
    "status": "recorded",
    "playlist": "https://play.boxcast.com/p/du7riye7ju0zn1ja7reo/v/all.m3u8"
    "?Expires=1789329408&Signature=sigh&Key-Pair-Id=xyz",
}
HONDO_ACCOUNT = {
    "id": HONDO_ACCOUNT_ID,
    "name": "City of Hondo - ,",
    "channel_id": HONDO_CHANNEL_ID,
}
HONDO_MASTER_M3U8 = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=900000,AVERAGE-BANDWIDTH=800000,CODECS="avc1.42001e,mp4a.40.2",RESOLUTION=426x240,FRAME-RATE=30.000
https://play.boxcast.com/p/du7riye7ju0zn1ja7reo/v/240p.m3u8?Expires=1789329408&Signature=sigh2&Key-Pair-Id=xyz
"""

# St. Louis County - Clayton MO's real channel scan -- a real "Committee
# of the Whole" meeting, picked over other real recent broadcasts by the
# "meeting" keyword (see test_looks_like_meeting_matches_real_atlantic_
# city_titles above). This tenant's own real master playlist ALSO carries
# a genuine subtitle track (`requestsCaptioning: true` in its real
# account `content_settings`, confirmed live) -- not re-exercised here
# since the caption-assembly mechanism itself is already covered end to
# end by the Atlantic City test above; this test's own master playlist is
# mocked WITHOUT one, so it only covers the id-resolution/pick/
# jurisdiction path for this fourth real tenant.
STLOUIS_CHANNEL_ID = "wdeojvfau9uqc9qt6k8z"
STLOUIS_ACCOUNT_ID = "xfukwjyyursckbjslcb5"
STLOUIS_BROADCAST_ID = "aclk3otduravjul1dod8"
STLOUIS_BROADCAST_SLUG = "9926---cow-meeting-vkimkyl9g3mfwrqkvcgn"
STLOUIS_CHANNEL_BROADCASTS = [
    {
        "id": STLOUIS_BROADCAST_ID,
        "name": "9.9.26 - COW Meeting",
        "starts_at": "2026-09-09T20:26:00Z",
        "stops_at": "2026-09-09T21:44:00Z",
        "timeframe": "past",
        "account_id": STLOUIS_ACCOUNT_ID,
        "channel_id": STLOUIS_BROADCAST_SLUG,
    },
]
STLOUIS_BROADCAST_FULL = {
    **STLOUIS_CHANNEL_BROADCASTS[0],
    "time_zone_offset": -300,
}
STLOUIS_VIEW = {
    "status": "recorded",
    "playlist": "https://play.boxcast.com/p/mxb0mk0bbirqlgplg3df/v/all.m3u8"
    "?Expires=1789329408&Signature=sigs&Key-Pair-Id=xyz",
}
STLOUIS_ACCOUNT = {
    "id": STLOUIS_ACCOUNT_ID,
    "name": "St. Louis County - Clayton, MO",
    "channel_id": STLOUIS_CHANNEL_ID,
}
STLOUIS_MASTER_M3U8 = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-STREAM-INF:BANDWIDTH=900000,AVERAGE-BANDWIDTH=800000,CODECS="avc1.42001e,mp4a.40.2",RESOLUTION=426x240,FRAME-RATE=30.000
https://play.boxcast.com/p/mxb0mk0bbirqlgplg3df/v/240p.m3u8?Expires=1789329408&Signature=sigs2&Key-Pair-Id=xyz
"""


def _channel_broadcasts_url(channel_id):
    return (
        f"https://rest.boxcast.com/channels/{channel_id}/broadcasts?l=50&s=-starts_at"
    )


def _broadcast_url(broadcast_id):
    return f"https://rest.boxcast.com/broadcasts/{broadcast_id}"


def _view_url(broadcast_id):
    return f"https://rest.boxcast.com/broadcasts/{broadcast_id}/view"


def _account_url(account_id):
    return f"https://rest.boxcast.com/accounts/{account_id}"


def _json_response(payload):
    return FakeResponse(status=200, text=json.dumps(payload))


def test_parse_boxcast_id_recognizes_all_three_real_url_shapes():
    assert (
        boxcast.parse_boxcast_id("https://boxcast.tv/view/some-slug-abc123")
        == "some-slug-abc123"
    )
    assert (
        boxcast.parse_boxcast_id(
            "https://boxcast.tv/view-embed/lqsszohc5p0q4yemoddl?showTitle=1"
        )
        == "lqsszohc5p0q4yemoddl"
    )
    assert (
        boxcast.parse_boxcast_id("https://boxcast.tv/channel/x1jps4n28nlgtaozsv5y")
        == "x1jps4n28nlgtaozsv5y"
    )


def test_parse_boxcast_id_rejects_a_non_boxcast_or_unrecognized_url():
    assert boxcast.parse_boxcast_id("https://example.com/view/abc") is None
    assert boxcast.parse_boxcast_id("https://boxcast.tv/") is None
    assert boxcast.parse_boxcast_id("https://boxcast.tv/pricing") is None


def test_looks_like_meeting_matches_real_atlantic_city_titles():
    # The exact real mix that made a bare "pick the newest past
    # broadcast" rule wrong -- see boxcast.py's own module docstring.
    assert boxcast._looks_like_meeting("City Council Meeting 08/19/26") is True
    assert boxcast._looks_like_meeting("CITISTAT Meeting 08/05/26") is True
    assert boxcast._looks_like_meeting("Regular City Council Meeting - 8/24/26") is True
    assert (
        boxcast._looks_like_meeting(
            "Wilmington City Council - Public Workshop 12/17/2026"
        )
        is True
    )
    assert boxcast._looks_like_meeting("9.9.26 - COW Meeting") is True
    # Real non-meetings this gate must reject.
    assert boxcast._looks_like_meeting("Great Day Cafe Grand Opening 09/09/26") is False
    assert boxcast._looks_like_meeting("CITISTAT") is False
    assert (
        boxcast._looks_like_meeting(
            "Mayor's Press Conference K. Hovnanian Groundbreaking 08/12/26"
        )
        is False
    )
    assert (
        boxcast._looks_like_meeting("Coursey Building Dedication Ceremony 08/05/26")
        is False
    )
    assert boxcast._looks_like_meeting(None) is False


async def test_resolve_channel_link_picks_newest_meeting_like_broadcast_and_gets_real_captions():
    routes = {
        _channel_broadcasts_url(AC_CHANNEL_ID): _json_response(AC_CHANNEL_BROADCASTS),
        _broadcast_url(AC_BROADCAST_ID): _json_response(AC_BROADCAST_FULL),
        _view_url(AC_BROADCAST_ID): _json_response(AC_VIEW),
        _account_url(AC_ACCOUNT_ID): _json_response(AC_ACCOUNT),
        AC_MASTER_URL: FakeResponse(status=200, text=AC_MASTER_M3U8),
        AC_SUBTITLE_URL: FakeResponse(status=200, text=AC_SUBTITLE_MEDIA_M3U8),
        AC_CAPTION_SEG_1_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_1_TEXT),
        AC_CAPTION_SEG_2_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_2_TEXT),
        AC_CAPTION_SEG_3_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_3_TEXT),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(
            f"https://boxcast.tv/view-embed/{AC_CHANNEL_ID}?showTitle=1"
        )

    # Skipped the newer Great Day Cafe / CITISTAT (bare) broadcasts,
    # picked the real City Council meeting -- and rewrote source_url to
    # this specific broadcast's own stable per-broadcast URL, not the
    # channel URL that was pasted in.
    assert result.title == "City Council Meeting 08/19/26"
    assert result.source_url == f"https://boxcast.tv/view/{AC_BROADCAST_SLUG}"
    assert result.date == "2026-08-19"
    assert result.jurisdiction == "City of Atlantic City, NJ"
    # WO-245: external_id is now the per-broadcast id (globally unique,
    # never a shared government channel -- see
    # test_resolve_two_broadcasts_from_the_same_channel_get_different_external_ids
    # below for why), and the stable government channel rides in
    # video_channel as a tenant_overrides.csv `channel=` pin hint instead.
    assert result.external_id == f"boxcast:{AC_BROADCAST_ID}"
    assert result.video_channel == f"boxcast:{AC_CHANNEL_ID}"
    assert result.platform == "boxcast"
    assert result.video_url == AC_VIEW["playlist"]
    assert result.video_format == "m3u8"

    # Real captions, assembled from the three real segments in playlist
    # order with NO offset applied (see boxcast.py's own module
    # docstring on why an offset would have been wrong here).
    assert len(result.segments) == 12
    assert (
        result.segments[0].text
        == "we're well informed and I'd like to take time I've always given"
    )
    assert result.segments[0].start == 2987.427
    assert result.segments[-1].text.startswith("a conference room")
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []


async def test_resolve_two_broadcasts_from_the_same_channel_get_different_external_ids():
    # WO-245's own real incident, reproduced: Atlantic City's real
    # "City Council Meeting 08/19/26" (AC_BROADCAST_ID) and its real
    # "CITISTAT" broadcast (both confirmed live, same account
    # AC_ACCOUNT_ID, same government channel AC_CHANNEL_ID) used to get
    # the SAME `external_id` (`boxcast:{AC_CHANNEL_ID}`) -- so ingesting
    # the second one silently overwrote the first one's Archive page
    # (`archive/db/crud.py`'s `_find_existing_page()` matches by
    # `(platform, external_id)` before `source_url_normalized`). Each
    # broadcast must get its OWN `external_id` while still sharing the
    # same `video_channel` pin hint.
    citistat_broadcast_id = "jgd724osemy5esg1lzsh"
    citistat_slug = "citistat-smjo0e3651g4tf7c7x2h"
    citistat_broadcast_full = {
        "id": citistat_broadcast_id,
        "name": "CITISTAT",
        "starts_at": "2026-09-02T21:00:00Z",
        "stops_at": "2026-09-02T21:21:00Z",
        "timeframe": "past",
        "time_zone_offset": -240,
        "account_id": AC_ACCOUNT_ID,
        "channel_id": citistat_slug,
    }
    citistat_view = {
        "status": "recorded",
        "playlist": "https://play.boxcast.com/p/citistat/v/all.m3u8"
        "?Expires=1789257600&Signature=sigc&Key-Pair-Id=xyz",
    }
    routes_ac = {
        _channel_broadcasts_url(AC_CHANNEL_ID): _json_response(AC_CHANNEL_BROADCASTS),
        _broadcast_url(AC_BROADCAST_ID): _json_response(AC_BROADCAST_FULL),
        _view_url(AC_BROADCAST_ID): _json_response(AC_VIEW),
        _account_url(AC_ACCOUNT_ID): _json_response(AC_ACCOUNT),
        AC_MASTER_URL: FakeResponse(status=200, text=AC_MASTER_M3U8),
        AC_SUBTITLE_URL: FakeResponse(status=200, text=AC_SUBTITLE_MEDIA_M3U8),
        AC_CAPTION_SEG_1_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_1_TEXT),
        AC_CAPTION_SEG_2_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_2_TEXT),
        AC_CAPTION_SEG_3_URL: FakeResponse(status=200, text=AC_CAPTION_SEG_3_TEXT),
    }
    with mock_session(routes_ac):
        finder = boxcast.BoxcastAssetFinder()
        council_result = await finder.resolve(
            f"https://boxcast.tv/view-embed/{AC_CHANNEL_ID}?showTitle=1"
        )

    routes_citistat = {
        _channel_broadcasts_url(citistat_slug): _json_response(
            [citistat_broadcast_full]
        ),
        _broadcast_url(citistat_broadcast_id): _json_response(citistat_broadcast_full),
        _view_url(citistat_broadcast_id): _json_response(citistat_view),
        _account_url(AC_ACCOUNT_ID): _json_response(AC_ACCOUNT),
    }
    with mock_session(routes_citistat):
        finder = boxcast.BoxcastAssetFinder()
        citistat_result = await finder.resolve(
            f"https://boxcast.tv/view/{citistat_slug}"
        )

    assert council_result.external_id == f"boxcast:{AC_BROADCAST_ID}"
    assert citistat_result.external_id == f"boxcast:{citistat_broadcast_id}"
    assert council_result.external_id != citistat_result.external_id
    # Both still carry the SAME government channel as their pin hint --
    # the part that's supposed to collide, unlike external_id.
    assert council_result.video_channel == f"boxcast:{AC_CHANNEL_ID}"
    assert citistat_result.video_channel == f"boxcast:{AC_CHANNEL_ID}"


async def test_resolve_direct_view_link_to_a_broadcast_with_no_captions_is_video_only():
    routes = {
        # A `/view`|`/view-embed` slug is a real one-broadcast pseudo-
        # channel (module docstring) -- `_channel_broadcasts_url()` is
        # the FIRST call `_resolve_id()` makes for any id.
        _channel_broadcasts_url(WILM_BROADCAST_SLUG): _json_response(
            [WILM_BROADCAST_FULL]
        ),
        _view_url(WILM_BROADCAST_ID): _json_response(WILM_VIEW),
        _account_url(WILM_ACCOUNT_ID): _json_response(WILM_ACCOUNT),
        WILM_VIEW["playlist"]: FakeResponse(status=200, text=WILM_MASTER_M3U8),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/view/{WILM_BROADCAST_SLUG}")

    assert result.title == "Wilmington City Council Meeting 9/3/2026"
    assert result.date == "2026-09-03"
    assert result.jurisdiction == "City of Wilmington, OH"
    assert result.external_id == f"boxcast:{WILM_BROADCAST_ID}"
    assert result.video_channel == f"boxcast:{WILM_CHANNEL_ID}"
    assert result.video_url == WILM_VIEW["playlist"]
    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]
    # A direct single-broadcast link keeps its own URL as source_url --
    # it's already the broadcast's own stable channel_id slug.
    assert result.source_url == f"https://boxcast.tv/view/{WILM_BROADCAST_SLUG}"


async def test_resolve_channel_link_for_hondo_picks_its_one_real_meeting_no_captions():
    routes = {
        _channel_broadcasts_url(HONDO_CHANNEL_ID): _json_response(
            HONDO_CHANNEL_BROADCASTS
        ),
        _broadcast_url(HONDO_BROADCAST_ID): _json_response(HONDO_BROADCAST_FULL),
        _view_url(HONDO_BROADCAST_ID): _json_response(HONDO_VIEW),
        _account_url(HONDO_ACCOUNT_ID): _json_response(HONDO_ACCOUNT),
        HONDO_VIEW["playlist"]: FakeResponse(status=200, text=HONDO_MASTER_M3U8),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/channel/{HONDO_CHANNEL_ID}")

    assert result.title == "Regular City Council Meeting - 8/24/26"
    # Real, genuinely messy account name (missing its state) -- kept
    # as-is, never guessed/cleaned up.
    assert result.jurisdiction == "City of Hondo - ,"
    assert result.external_id == f"boxcast:{HONDO_BROADCAST_ID}"
    assert result.video_channel == f"boxcast:{HONDO_CHANNEL_ID}"
    assert result.segments == []


async def test_resolve_channel_link_for_st_louis_county_picks_its_real_cow_meeting():
    routes = {
        _channel_broadcasts_url(STLOUIS_CHANNEL_ID): _json_response(
            STLOUIS_CHANNEL_BROADCASTS
        ),
        _broadcast_url(STLOUIS_BROADCAST_ID): _json_response(STLOUIS_BROADCAST_FULL),
        _view_url(STLOUIS_BROADCAST_ID): _json_response(STLOUIS_VIEW),
        _account_url(STLOUIS_ACCOUNT_ID): _json_response(STLOUIS_ACCOUNT),
        STLOUIS_VIEW["playlist"]: FakeResponse(status=200, text=STLOUIS_MASTER_M3U8),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(
            f"https://boxcast.tv/channel/{STLOUIS_CHANNEL_ID}"
        )

    # "9.9.26 - COW Meeting" (a real Committee of the Whole meeting) is
    # picked because it has "meeting" in its own title, the same gate
    # `test_looks_like_meeting_matches_real_atlantic_city_titles` checks
    # directly.
    assert result.title == "9.9.26 - COW Meeting"
    assert result.date == "2026-09-09"
    assert result.jurisdiction == "St. Louis County - Clayton, MO"
    assert result.external_id == f"boxcast:{STLOUIS_BROADCAST_ID}"
    assert result.video_channel == f"boxcast:{STLOUIS_CHANNEL_ID}"
    assert result.video_url == STLOUIS_VIEW["playlist"]
    assert result.source_url == f"https://boxcast.tv/view/{STLOUIS_BROADCAST_SLUG}"


async def test_resolve_channel_with_no_past_broadcasts_warns_honestly():
    future_only = [
        {
            "id": "zzzfuture",
            "name": "City Council Meeting 12/1/2026",
            "starts_at": "2026-12-01T21:30:00Z",
            "stops_at": "2026-12-01T23:30:00Z",
            "timeframe": "future",
            "account_id": WILM_ACCOUNT_ID,
            "channel_id": "future-slug",
        }
    ]
    routes = {
        _channel_broadcasts_url(WILM_CHANNEL_ID): _json_response(future_only),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/channel/{WILM_CHANNEL_ID}")

    assert result.video_url is None
    assert "no recorded broadcasts yet" in result.video_warnings[0]


async def test_resolve_channel_with_only_non_meeting_broadcasts_is_video_without_meeting():
    # The real Atlantic City mix, minus its two real City Council meetings
    # AND its real "CITISTAT Meeting" (which has "meeting" in its own
    # title, so it correctly passes _looks_like_meeting on its own) --
    # every remaining broadcast is a real ceremony/press conference/bare
    # CITISTAT, none of which should ever be auto-picked.
    non_meetings = [
        b
        for b in AC_CHANNEL_BROADCASTS
        if "City Council" not in b["name"] and "meeting" not in b["name"].lower()
    ]
    routes = {
        _channel_broadcasts_url(AC_CHANNEL_ID): _json_response(non_meetings),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/channel/{AC_CHANNEL_ID}")

    assert result.video_url is None
    assert "none of its recent" in result.video_warnings[0]


async def test_resolve_unknown_id_warns_honestly():
    routes = {
        _channel_broadcasts_url("nosuchid"): FakeResponse(status=404),
        _broadcast_url("nosuchid"): FakeResponse(status=404),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve("https://boxcast.tv/view/nosuchid")

    assert result.video_url is None
    assert "couldn't find this BoxCast" in result.video_warnings[0]


async def test_resolve_a_non_boxcast_url_warns_without_any_network_call():
    finder = boxcast.BoxcastAssetFinder()
    result = await finder.resolve("https://example.com/nope")
    assert result.video_url is None
    assert "couldn't find a BoxCast" in result.video_warnings[0]


def test_boxcast_registered_in_detect_platform_and_the_registry():
    from app.platforms import register_all_finders
    from app.platforms.base import detect_platform, get_finder

    register_all_finders()
    assert (
        detect_platform("https://boxcast.tv/channel/x1jps4n28nlgtaozsv5y") == "boxcast"
    )
    assert (
        detect_platform("https://boxcast.tv/view-embed/lqsszohc5p0q4yemoddl?a=1")
        == "boxcast"
    )
    assert isinstance(get_finder("boxcast"), boxcast.BoxcastAssetFinder)


def test_boxcast_link_is_found_on_a_government_page(tmp_path):
    from app.platforms.base import find_platform_link

    # Atlantic City's real recordings page embeds its channel via a
    # `view-embed` iframe with real query parameters -- confirmed live
    # 2026-09-11 (`www.acnj.gov/pages/meeting-recordings`).
    html = (
        '<html><body><iframe src="https://boxcast.tv/view-embed/'
        f"{AC_CHANNEL_ID}?showTitle=1&amp;showDescription=1&amp;"
        'defaultVideo=next"></iframe></body></html>'
    )
    result = find_platform_link(html, "https://www.acnj.gov/pages/meeting-recordings")
    assert result is not None
    link, platform = result
    assert platform == "boxcast"
    assert f"boxcast.tv/view-embed/{AC_CHANNEL_ID}" in link


# ---------------------------------------------------------------------------
# WO-227b (2026-09-11): a shared regional media operator's BoxCast account,
# NOT the government -- real data from Livermore Falls, ME, found through
# the town's own WordPress site. Its channel (`LF_CHANNEL_ID`) carries only
# Livermore Falls Select Board meetings, confirmed real; its ACCOUNT
# (`irhhkp1kj2wjp6fa03qj`, "Mt. Blue Television - Farmington, ME") is a
# regional community-TV operator whose own umbrella channel (confirmed live,
# not re-exercised here) also carries Farmington's and Jay's own Select
# Board meetings and an RSU 9 school-board meeting -- a real multi-
# government host one layer inside a single BoxCast account. Real captions
# confirmed live (module docstring's new section) -- the first case this
# WO found beyond WO-227's original Atlantic City/St. Louis County pair.
# ---------------------------------------------------------------------------

LF_CHANNEL_ID = "vvohjjgvcdbmeatv03km"
LF_ACCOUNT_ID = "irhhkp1kj2wjp6fa03qj"
LF_BROADCAST_ID = "m6gexeisxxqbmj8e6gis"
# The broadcast's own one-off pseudo-channel -- confirmed DIFFERENT from
# LF_CHANNEL_ID above, which is what makes this a genuine "distinct
# channel" case rather than the Wilmington/Hondo/Bartow shape.
LF_BROADCAST_SLUG = (
    "livermore-falls-select-board-meeting---september-1st-2026-n53uh3iocsj1rbpiogmm"
)

LF_CHANNEL_BROADCASTS = [
    {
        "id": LF_BROADCAST_ID,
        "name": "Livermore Falls Select Board Meeting - September 1st, 2026",
        "starts_at": "2026-09-01T21:58:00Z",
        "stops_at": "2026-09-02T00:10:00Z",
        "timeframe": "past",
        "account_id": LF_ACCOUNT_ID,
        "channel_id": LF_BROADCAST_SLUG,
    },
    {
        "id": "qdzukxlyurm0mzgurstn",
        "name": "Livermore Falls Select Board Meeting - August 18th, 2026",
        "starts_at": "2026-08-18T21:58:00Z",
        "stops_at": "2026-08-18T23:20:00Z",
        "timeframe": "past",
        "account_id": LF_ACCOUNT_ID,
        "channel_id": "livermore-falls-select-board-meeting---august-18th-2026-iiy9drsr9yezrmoq4lfe",
    },
]

LF_BROADCAST_FULL = {
    "id": LF_BROADCAST_ID,
    "name": "Livermore Falls Select Board Meeting - September 1st, 2026",
    "starts_at": "2026-09-01T21:58:00Z",
    "stops_at": "2026-09-02T00:10:00Z",
    "timeframe": "past",
    "time_zone_offset": -240,
    "account_id": LF_ACCOUNT_ID,
    "channel_id": LF_BROADCAST_SLUG,
}

LF_VIEW = {
    "status": "recorded",
    "playlist": "https://play.boxcast.com/p/yrsozutyozbeupbki5xg/v/all.m3u8"
    "?Expires=1789257600&Signature=siglf&Key-Pair-Id=xyz",
}

# The SHARED operator's own account -- its `channel_id`
# (`ckxiq1bpg9hm3tt3zvsb`, confirmed live to be a DIFFERENT real channel
# carrying Farmington/Jay/RSU 9 content, not re-exercised here) must NOT
# end up as this government's video_channel or jurisdiction.
LF_ACCOUNT = {
    "id": LF_ACCOUNT_ID,
    "name": "Mt. Blue Television - Farmington, ME",
    "channel_id": "ckxiq1bpg9hm3tt3zvsb",
}

LF_MASTER_URL = LF_VIEW["playlist"]
LF_SUBTITLE_URL = (
    "https://play.boxcast.com/p/yrsozutyozbeupbki5xg/v/English.m3u8"
    "?Expires=1789257600&Signature=siglfsub&Key-Pair-Id=xyz"
)
LF_MASTER_M3U8 = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",NAME="English",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="en",URI="{LF_SUBTITLE_URL}"
#EXT-X-STREAM-INF:BANDWIDTH=1132473,CODECS="avc1.42001e,mp4a.40.2",RESOLUTION=426x240,SUBTITLES="sub1"
https://play.boxcast.com/p/yrsozutyozbeupbki5xg/v/240p.m3u8?Expires=1789257600&Signature=siglf2&Key-Pair-Id=xyz
"""

LF_CAPTION_SEG_URL = (
    "https://captions.boxcast.com/recordings/yrsozutyozbeupbki5xg/webvtt"
    "?Signature=siglfseg&start_mpegts=4578&stop_mpegts=995568"
)
LF_SUBTITLE_MEDIA_M3U8 = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-PLAYLIST-TYPE:VOD
#EXT-X-TARGETDURATION:11
#EXTINF:11.011,
{LF_CAPTION_SEG_URL}
"""
# Real caption text confirmed live 2026-09-11, sampled from this exact
# segment -- a real remark from a real Livermore Falls Select Board
# meeting, not placeholder text.
LF_CAPTION_SEG_TEXT = """WEBVTT
X-TIMESTAMP-MAP=MPEGTS:4578,LOCAL:00:00:00.000

1
00:00:02.000 --> 00:00:09.240
Ladies and gentlemen, thank you for coming. I am Dr. Bruce Perry. I will be your chair for the

2
00:00:09.240 --> 00:00:09.680
evening.
"""


async def test_resolve_channel_link_for_livermore_falls_uses_distinct_channel_not_shared_account():
    routes = {
        _channel_broadcasts_url(LF_CHANNEL_ID): _json_response(LF_CHANNEL_BROADCASTS),
        _broadcast_url(LF_BROADCAST_ID): _json_response(LF_BROADCAST_FULL),
        _view_url(LF_BROADCAST_ID): _json_response(LF_VIEW),
        _account_url(LF_ACCOUNT_ID): _json_response(LF_ACCOUNT),
        LF_MASTER_URL: FakeResponse(status=200, text=LF_MASTER_M3U8),
        LF_SUBTITLE_URL: FakeResponse(status=200, text=LF_SUBTITLE_MEDIA_M3U8),
        LF_CAPTION_SEG_URL: FakeResponse(status=200, text=LF_CAPTION_SEG_TEXT),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/channel/{LF_CHANNEL_ID}")

    assert result.title == "Livermore Falls Select Board Meeting - September 1st, 2026"
    assert result.date == "2026-09-01"
    # The distinct channel this scan actually reached, NOT the shared
    # operator account's own channel (`ckxiq1bpg9hm3tt3zvsb`) -- this was
    # WO-227b's fix: before it, this value (then still `external_id`)
    # would have been `boxcast:ckxiq1bpg9hm3tt3zvsb`, shared with every
    # other government on the same Mt. Blue Television account. WO-245
    # moved it from `external_id` to `video_channel`; `external_id` is
    # now always the per-broadcast id, never a shared channel.
    assert result.external_id == f"boxcast:{LF_BROADCAST_ID}"
    assert result.video_channel == f"boxcast:{LF_CHANNEL_ID}"
    # The shared operator's own account name ("Mt. Blue Television -
    # Farmington, ME") is never this government's jurisdiction -- left
    # blank rather than guessed.
    assert result.jurisdiction is None
    assert result.video_url == LF_VIEW["playlist"]
    assert result.video_format == "m3u8"
    assert len(result.segments) >= 2
    assert "Ladies and gentlemen" in result.segments[0].text
    assert result.transcript_warnings == []


async def test_resolve_channel_link_reuses_account_jurisdiction_when_it_matches_the_distinct_channel():
    # Contrast case: when the distinct channel IS the account's own
    # channel (Atlantic City's real shape -- see
    # test_resolve_channel_link_picks_newest_meeting_like_broadcast_and_gets_real_captions
    # above), the account name is correctly trusted. This test pins that
    # behavior down explicitly against a second, simpler single-broadcast
    # channel so a future change can't silently blank jurisdiction for
    # the single-tenant case too.
    single_tenant_channel_id = "single-tenant-channel-id"
    broadcast_id = "singlebroadcastid"
    account_id = "singletenantaccount"
    broadcast_full = {
        "id": broadcast_id,
        "name": "Town Council Meeting 09/01/26",
        "starts_at": "2026-09-01T23:00:00Z",
        "stops_at": "2026-09-02T00:00:00Z",
        "timeframe": "past",
        "time_zone_offset": -240,
        "account_id": account_id,
        # Same id as the channel that was scanned -- a real
        # single-broadcast government channel, not a shared operator.
        "channel_id": single_tenant_channel_id,
    }
    account = {
        "id": account_id,
        "name": "Town of Example, ZZ",
        "channel_id": single_tenant_channel_id,
    }
    view = {
        "status": "recorded",
        "playlist": "https://play.boxcast.com/p/example/v/all.m3u8"
        "?Expires=1789257600&Signature=sigex&Key-Pair-Id=xyz",
    }
    master_m3u8 = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=900000,CODECS="avc1.42001e,mp4a.40.2",'
        "RESOLUTION=426x240\n"
        "https://play.boxcast.com/p/example/v/240p.m3u8"
        "?Expires=1789257600&Signature=sigex2&Key-Pair-Id=xyz\n"
    )
    routes = {
        _channel_broadcasts_url(single_tenant_channel_id): _json_response(
            [broadcast_full]
        ),
        _broadcast_url(broadcast_id): _json_response(broadcast_full),
        _view_url(broadcast_id): _json_response(view),
        _account_url(account_id): _json_response(account),
        view["playlist"]: FakeResponse(status=200, text=master_m3u8),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(
            f"https://boxcast.tv/channel/{single_tenant_channel_id}"
        )

    assert result.external_id == f"boxcast:{broadcast_id}"
    assert result.video_channel == f"boxcast:{single_tenant_channel_id}"
    assert result.jurisdiction == "Town of Example, ZZ"


async def test_resolve_bartow_via_per_meeting_pseudo_channel_uses_stable_account_channel():
    # Bartow, FL's own real shape (WO-227b): a FRESH single-broadcast
    # pseudo-channel per meeting (`city-commission-meeting---932026-...`),
    # so a pin on that slug would never match next month's meeting --
    # the account's own stable channel (`pzo8uo3hgxrf0pmwalhj`, confirmed
    # live to list every real Bartow meeting, government-owned, not a
    # shared operator) is the only usable stable id here, exactly the
    # existing Wilmington/Hondo fallback path.
    pseudo_channel = "city-commission-meeting---932026-qv27zpwm1ynvwei361kx"
    broadcast_id = "nwgwwbnhjwp31rgxhwun"
    account_id = "kpcnkyfgetmxappqpclx"
    stable_channel_id = "pzo8uo3hgxrf0pmwalhj"
    broadcast_full = {
        "id": broadcast_id,
        "name": "City Commission Meeting - 9/3/2026",
        "starts_at": "2026-09-03T22:00:00Z",
        "stops_at": "2026-09-03T23:18:00Z",
        "timeframe": "past",
        "time_zone_offset": -240,
        "account_id": account_id,
        # Same id as the pseudo-channel the URL itself named -- nothing
        # distinct to prefer, so the account fallback is correct here.
        "channel_id": pseudo_channel,
    }
    account = {
        "id": account_id,
        "name": "City of Bartow - Bartow, FL",
        "channel_id": stable_channel_id,
    }
    view = {
        "status": "recorded",
        "playlist": "https://play.boxcast.com/p/bartow/v/all.m3u8"
        "?Expires=1789257600&Signature=sigb&Key-Pair-Id=xyz",
    }
    master_m3u8 = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=900000,CODECS="avc1.42001e,mp4a.40.2",'
        "RESOLUTION=426x240\n"
        "https://play.boxcast.com/p/bartow/v/240p.m3u8"
        "?Expires=1789257600&Signature=sigb2&Key-Pair-Id=xyz\n"
    )
    routes = {
        _channel_broadcasts_url(pseudo_channel): _json_response([broadcast_full]),
        _broadcast_url(broadcast_id): _json_response(broadcast_full),
        _view_url(broadcast_id): _json_response(view),
        _account_url(account_id): _json_response(account),
        view["playlist"]: FakeResponse(status=200, text=master_m3u8),
    }
    with mock_session(routes):
        finder = boxcast.BoxcastAssetFinder()
        result = await finder.resolve(f"https://boxcast.tv/view/{pseudo_channel}")

    assert result.external_id == f"boxcast:{broadcast_id}"
    assert result.video_channel == f"boxcast:{stable_channel_id}"
    assert result.jurisdiction == "City of Bartow - Bartow, FL"
    # Stable per-broadcast URL, not the per-meeting pseudo-channel link
    # that was pasted in.
    assert result.source_url == f"https://boxcast.tv/view/{pseudo_channel}"


# --- refresh_playlist_url() (WO-229) -------------------------------------
#
# The signed playlist `resolve()` stores as video_url expires a couple of
# days after ingest (module docstring's "signed and expiring" note, now
# corrected). refresh_playlist_url() is what the Archive calls at page-view
# time instead of trusting that stored URL forever -- see
# archive/utils/video_refresh.py and tests/test_boxcast_video_refresh.py
# for the Archive-side half of this. These tests cover the function
# in isolation, reusing Wilmington's real fixtures above.


async def test_refresh_playlist_url_returns_a_fresh_signed_playlist():
    # source_url is always the per-broadcast pseudo-channel resolve()
    # itself writes (module docstring) -- so the FIRST call _resolve_id()
    # makes is the channel-broadcasts endpoint, exactly like the direct
    # `/view` link test above, not the search/account/caption endpoints
    # (none of which refresh_playlist_url() has any reason to call).
    routes = {
        _channel_broadcasts_url(WILM_BROADCAST_SLUG): _json_response(
            [WILM_BROADCAST_FULL]
        ),
        _view_url(WILM_BROADCAST_ID): _json_response(WILM_VIEW),
    }
    with mock_session(routes):
        fresh = await boxcast.refresh_playlist_url(
            f"https://boxcast.tv/view/{WILM_BROADCAST_SLUG}"
        )
    assert fresh == WILM_VIEW["playlist"]


async def test_refresh_playlist_url_none_for_a_non_boxcast_source_url():
    fresh = await boxcast.refresh_playlist_url("https://example.com/not-boxcast")
    assert fresh is None


async def test_refresh_playlist_url_none_when_the_broadcast_is_unknown():
    routes = {
        _channel_broadcasts_url(WILM_BROADCAST_SLUG): FakeResponse(status=404),
        _broadcast_url(WILM_BROADCAST_SLUG): FakeResponse(status=404),
    }
    with mock_session(routes):
        fresh = await boxcast.refresh_playlist_url(
            f"https://boxcast.tv/view/{WILM_BROADCAST_SLUG}"
        )
    assert fresh is None


async def test_refresh_playlist_url_none_when_the_recording_is_gone():
    # A real, if rare, honest failure: the broadcast still resolves but
    # BoxCast no longer has a recording for it (e.g. the account got
    # deactivated -- BACKLOG_DONE.md's Atlantic Beach case).
    routes = {
        _channel_broadcasts_url(WILM_BROADCAST_SLUG): _json_response(
            [WILM_BROADCAST_FULL]
        ),
        _view_url(WILM_BROADCAST_ID): _json_response({"status": "unavailable"}),
    }
    with mock_session(routes):
        fresh = await boxcast.refresh_playlist_url(
            f"https://boxcast.tv/view/{WILM_BROADCAST_SLUG}"
        )
    assert fresh is None


# --- video_channel reaches the tenant_overrides.csv `channel=` pin (WO-245) -

from app.utils.gov_registry import registry, resolver  # noqa: E402


def test_resolve_real_atlantic_city_broadcast_then_matches_a_channel_pin(monkeypatch):
    """End-to-end: resolve a real Atlantic City fixture through the
    adapter, build the same `page_hints_for()` dict `archive/db/crud.py`
    builds from a stored `MeetingPage`, and confirm a `tenant_overrides.
    csv` row keyed `channel=boxcast:{channel}` (the converted shape this
    WO wrote -- see that file's real Atlantic City row) actually fires
    through the resolver's rung 1b multi-gov-host pin (`boxcast.tv` is a
    real `MULTI_GOV_HOSTS` entry, `registry.py`). This is the real
    consumer of `video_channel` -- `external_id` alone (now per-broadcast)
    could never serve as a stable pin key across two different meetings
    from the same government."""
    row = registry.TenantOverride(
        tenant_host="boxcast.tv",
        match=f"channel=boxcast:{AC_CHANNEL_ID}",
        gov_id="us:place:3402080",  # Atlantic City city, NJ -- real place row
        strength="fallback",
        source="wo245",
        evidence="test",
    )
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {"boxcast.tv": [row]})

    hints = resolver.page_hints_for(
        "boxcast", f"boxcast:{AC_BROADCAST_ID}", channel=f"boxcast:{AC_CHANNEL_ID}"
    )
    assert hints["channel"] == f"boxcast:{AC_CHANNEL_ID}"

    match = resolver.resolve_government(
        None,
        tenant_host="boxcast.tv",
        path=f"/view/{AC_BROADCAST_SLUG}",
        page_hints=hints,
    )
    assert match.gov_id == "us:place:3402080"
    assert match.tier == resolver.TIER_PINNED

    # A different government's broadcast on the same shared host, no
    # matching channel -- the pin must not fire for it.
    other_hints = resolver.page_hints_for(
        "boxcast",
        f"boxcast:{HONDO_BROADCAST_ID}",
        channel=f"boxcast:{HONDO_CHANNEL_ID}",
    )
    other = resolver.resolve_government(
        None, tenant_host="boxcast.tv", path="/view/x", page_hints=other_hints
    )
    assert other.gov_id != "us:place:3402080"
