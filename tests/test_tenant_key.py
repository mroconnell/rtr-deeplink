"""Tests for app/platforms/tenant_key.py, and a check that keeps it
consistent with tenant_overrides.csv's pins.

Every URL below is real: taken from an existing test or fixture, a
`tenant_overrides.csv` row's own match/evidence, or checked live on
2026-09-25 (noted where so). None is invented.
"""

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional, Tuple

import pytest

from app.platforms import tenant_key as tk
from app.platforms.tenant_key import tenant_key, tenant_name
from app.utils.gov_registry.registry import MULTI_GOV_HOSTS

OVERRIDES = (
    Path(__file__).parent.parent
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "tenant_overrides.csv"
)

# ---------------------------------------------------------------------------
# 1. Real URL -> expected key, per shared platform.

SHARED_CASES = [
    # ChampDS -- tests/test_champds.py (Atlanta 1227, El Paso caption path),
    # WO-1045's live API/stream URLs for Cobb County GA.
    ("https://play.champds.com/atlantaga/event/1227", "atlantaga"),
    (
        "https://play.champds.com/DOWNLOAD-MEDIA/atlantaga/eventmainmedia/1227",
        "atlantaga",
    ),
    (
        "https://play.champds.com/CAPTION/elpasococo/2026-09/"
        "e6ceecf86eb48b6c349cb46adb72b3fd73862d46.vtt",
        "elpasococo",
    ),
    ("https://playapi.champds.com/cobbcoga/event/155", "cobbcoga"),
    (
        "https://securestream10.champds.com/VOD/event/CobbCoGA/155/"
        "1788977097000/1o3BB_6OF2yCFDiWWL9CXA/master.m3u8",
        "cobbcoga",
    ),
    ("https://play.champds.com/_COMMON/js/cds.event.js", None),
    # Invintus -- tests/test_invintus*.py and the Oregon/Wisconsin pins.
    (
        "https://player.invintus.com/?clientID=4879615486&eventID=2026091002",
        "4879615486",
    ),
    (
        "https://player.invintus.com/?clientID=2789595964&eventID=2026051017",
        "2789595964",
    ),
    ("https://player.invintus.com/", None),
    # Cablecast stations shared by `site=` -- cablecast.py's own comments
    # (Town Square's Mendota Heights embed; CCX Media's Brooklyn Park show)
    # and tests/test_cablecast.py. A show URL with no `site=` is FINDING-23's
    # shape: it cannot be placed, so None, never the whole host.
    (
        "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5964&site=8",
        "site=8",
    ),
    (
        "https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/35842?site=8",
        "site=8",
    ),
    (
        "https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/36986?site=16",
        "site=16",
    ),
    ("https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/36986", None),
    # Castus -- tests/test_castus.py, both the path and the hash-route shape.
    (
        "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME",
        "comm7tv",
    ),
    ("https://cloud.castus.tv/vod/blackstone/?page=PLAYLIST", "blackstone"),
    (
        "https://cloud.castus.tv/vod/#/lincoln/playlist/Town%20Meeting?page=PLAYLIST",
        "lincoln",
    ),
    ("https://cloud.castus.tv/vod/", None),
    # TelVue -- tests/test_telvue.py, a pin's evidence URL, and a live
    # stream URL; the org token keeps its case.
    (
        "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1040134",
        "w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP",
    ),
    (
        "https://videoplayer.telvue.com/player/GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/playlists/4806",
        "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru",
    ),
    (
        "https://videoplayer.telvue.com/player/KPxII4Dm-djtTqV7JZXpXeOM2kiyqvRV/stream/983"
        "?fullscreen=true&showtabssearch=true&autostart=true",
        "KPxII4Dm-djtTqV7JZXpXeOM2kiyqvRV",
    ),
    ("https://videoplayer.telvue.com/", None),
    # Sliq Harmony -- a Maine Legislature line in the tier-3 queue.
    (
        "https://sg001-harmony.sliq.net/00281/Harmony/en/PowerBrowser/"
        "PowerBrowserV3/20260909/-1/28462",
        "00281",
    ),
    # BoardDocs -- tests/test_boarddocs.py.
    ("https://go.boarddocs.com/az/ccschools/Board.nsf/Public", "az/ccschools"),
    (
        "https://go.boarddocs.com/fla/talgov/Board.nsf/BD-GETMeetingsListForSEO",
        "fla/talgov",
    ),
    ("https://go.boarddocs.com/", None),
    # ClerkBase -- tests/test_clerkbase.py; lowercased, as the pins are.
    ("https://clerkshq.com/YellowSprings-OH?docId=feb07_22ag", "yellowsprings-oh"),
    (
        "https://clerkshq.com/Content/YellowSprings-OH/council/2022/feb07_22ag.htm",
        "yellowsprings-oh",
    ),
    ("https://clerkshq.com/help?ajax=1", None),
    # BoxCast -- tests/test_boxcast.py. A /view/ link can be a channel or a
    # one-broadcast id; only BoxCast's API can tell, so None.
    ("https://boxcast.tv/channel/x1jps4n28nlgtaozsv5y", "x1jps4n28nlgtaozsv5y"),
    (
        "https://boxcast.tv/view/pascagoula-city-council-81826-z0nwcd5m4geotcf6h3ti",
        None,
    ),
    # Town Hall Streams -- tests/test_townhallstreams.py; `town.php?id=94`
    # checked live 2026-09-25: its page links `location_id=94` 426 times
    # (Lisbon, ME).
    ("https://townhallstreams.com/stream.php?location_id=94&id=75799", "94"),
    ("https://townhallstreams.com/stream.php?full=1&location_id=169", "169"),
    ("https://townhallstreams.com/town.php?id=94", "94"),
    # DestinyHosted -- tests/test_base.py and test_destinyhosted*.py; both
    # shapes checked live 2026-09-25 (24263 is the City of Chandler, AZ).
    ("https://public.destinyhosted.com/24568/agenda/agenda.cfm?seq=2036", "24568"),
    ("https://public.destinyhosted.com/24263/agenda/", "24263"),
    ("https://public.destinyhosted.com/agenda_publish.cfm?id=24263", "24263"),
    ("https://public.destinyhosted.com/agenda_publish.cfm", None),
    # SpectrumStream -- tests/test_spectrumstream.py.
    ("https://spectrumstream.com/streaming/gusd/2024_10_08.cfm", "gusd"),
    # Shared, but one listing: the whole host is the tenant.
    ("https://amsva.wistia.com/medias/i2vooa0pno", ""),
    ("https://lmctvny.new.swagit.com/videos/399987", ""),
    ("https://reflect-lmcc.cablecast.tv/CablecastPublicSite/show/57519?site=1", ""),
    (
        "https://reflect-townofmerrimack.cablecast.tv/internetchannel/show/8909?site=5",
        "",
    ),
]

OUT_OF_SCOPE_CASES = [
    "https://vimeo.com/1212025580",  # tests/test_vimeo.py
    "https://www.youtube.com/watch?v=5LZqoNDRMYk",  # CLAUDE.md's Philadelphia sample
    "https://youtu.be/baOM15QBojM",  # tier-3 queue line (Miami Township OH)
    # drive.google.com's one real pin.
    "https://drive.google.com/file/d/1h7Pfp4UKVEGE5UV36IQQLr0oqjzrlmOa/view?usp=sharing",
    "https://www.utah.gov/pmn/sitemap/notice/1100143.html",  # tests/test_utah_pmn.py
]


@pytest.mark.parametrize("url,expected", SHARED_CASES)
def test_shared_platform_keys(url, expected):
    assert tenant_key(url) == expected


@pytest.mark.parametrize("url", OUT_OF_SCOPE_CASES)
def test_out_of_scope_hosts_have_no_tenant(url):
    assert tenant_key(url) is None
    assert tenant_name(url) is None


def test_tenant_name_is_host_or_host_hash_key():
    assert tenant_name("https://play.champds.com/atlantaga/event/1227") == (
        "play.champds.com#atlantaga"
    )
    assert tenant_name("https://playapi.champds.com/cobbcoga/event/155") == (
        "play.champds.com#cobbcoga"
    )
    assert tenant_name(
        "https://reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=5964&site=8"
    ) == ("reflect-tst-mn.cablecast.tv#site=8")
    assert tenant_name(
        "https://detroit-vod.cablecast.tv/internetchannel/show/15323"
    ) == ("detroit-vod.cablecast.tv")
    assert (
        tenant_name("https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/36986")
        is None
    )


# ---------------------------------------------------------------------------
# 2. Every single-website platform returns "". One real URL per platform
# `detect_platform()` names, taken from the named test file.

SINGLE_WEBSITE_CASES = [
    (
        "aurora_tv",
        "https://www.auroratv.org/sites/default/files/video-captions-70037.vtt",
        "test_aurora.py",
    ),
    (
        "az_legislature",
        "https://www.azleg.gov/videoplayer/?eventID=2025011041",
        "test_az_legislature.py",
    ),
    (
        "ca_legislature",
        "https://vod.senate.ca.gov/captions.scc",
        "test_ca_legislature.py",
    ),
    (
        "cablecast",
        "https://detroit-vod.cablecast.tv/internetchannel/show/15323",
        "test_cablecast.py",
    ),
    (
        "chicago_elms",
        "https://api.chicityclerkelms.chicago.gov/meeting-agenda/",
        "test_chicago_elms.py",
    ),
    (
        "civicclerk",
        "https://clovisca.portal.civicclerk.com/event/20/media",
        "test_base.py",
    ),
    (
        "civiclive",
        "https://escalon.hosted.civiclive.com/government/agenda_packets/",
        "test_civiclive.py",
    ),
    (
        "civicmedia",
        "https://www.cityofhobart.org/CivicMedia.aspx?VID=Board-of-Works-09022026-327",
        "test_civicmedia.py",
    ),
    ("civicplus", "https://ks-desoto.civicplus.com/AgendaCenter", "test_civicplus.py"),
    (
        "civicweb",
        "https://achdidaho.civicweb.net/api/geteventwithindexpoints/702",
        "test_civicweb.py",
    ),
    (
        "escribe",
        "https://richmond.escribemeetings.com/Meeting.aspx?Id=1",
        "test_escribe.py",
    ),
    (
        "granicus",
        "https://hacsc.granicus.com/player/clip/promo-jx-split",
        "test_ingest_promotion.py",
    ),
    (
        "hyland",
        "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3",
        "test_hyland.py",
    ),
    (
        "iqm2",
        "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=18002",
        "test_iqm2.py",
    ),
    (
        "legistar",
        "https://mesa.legistar.com/MeetingDetail.aspx?ID=1428059",
        "test_legistar.py",
    ),
    ("lims", "https://lims.minneapolismn.gov/MarkedAgenda/BHZ/6105", "test_lims.py"),
    (
        "municode_meetings",
        "https://fairoaksranch-tx.municodemeetings.com/",
        "test_wo1029_meeting_finder_scan.py",
    ),
    (
        "open_media",
        "https://littleton.ompnetwork.org/sessions/346131/",
        "test_openmedia.py",
    ),
    (
        "primegov",
        "https://slc.primegov.com/Portal/Meeting?meetingTemplateId=3948",
        "test_primegov.py",
    ),
    (
        "proudcity",
        "https://wilmingtonohio.gov/meetings/city-council-meeting-april-16-2026",
        "test_transcribe_backlog_locally.py",
    ),
    (
        "seattle_channel",
        "https://www.seattlechannel.org/videos?videoid=x189286",
        "test_generic_fallback.py",
    ),
    ("slc", "https://www.slc.gov/council/march-3-2026-meeting-recap/", "test_base.py"),
    (
        "suiteone",
        "https://stmarysga.suiteonemedia.com/event/?id=1000",
        "test_suiteone.py",
    ),
    (
        "swagit",
        "https://wisecountytx.new.swagit.com/videos/1001",
        "test_wo1028_meeting_finder_listing.py",
    ),
    ("tampa", "https://apps.tampagov.net/cttv_cc_webapp", "test_tampa.py"),
    ("tvw", "https://tvw.org/video/senate-housing-2026091165/", "test_tvw.py"),
    (
        "twelvemilesout",
        "https://escondido.12milesout.com/api/meetings/list/1/12",
        "test_twelvemilesout.py",
    ),
    ("viebit", "https://someothertown.viebit.com/watch?hash=abc", "test_viebit.py"),
    ("wistia", "https://amsva.wistia.com/channel/kcpy3xurof", "test_wistia.py"),
]


@pytest.mark.parametrize("platform,url,source", SINGLE_WEBSITE_CASES)
def test_single_website_platforms_are_the_whole_host(platform, url, source):
    assert tenant_key(url) == ""


def test_single_website_samples_really_are_those_platforms():
    from app.platforms.base import detect_platform

    for platform, url, source in SINGLE_WEBSITE_CASES:
        assert detect_platform(url) == platform, (url, source)


# ---------------------------------------------------------------------------
# 3. Every MULTI_GOV_HOSTS entry is classified exactly once.


def _classification(host: str) -> str:
    kinds = []
    if host in tk.OUT_OF_SCOPE_HOSTS:
        kinds.append("out_of_scope")
    if host in tk.SHARED_SINGLE_LISTING_HOSTS:
        kinds.append("one_listing")
    if tk.is_keyed_shared_host(host):
        kinds.append("keyed")
    assert len(kinds) == 1, (host, kinds)
    return kinds[0]


@pytest.mark.parametrize("host", sorted(MULTI_GOV_HOSTS))
def test_every_multi_gov_host_is_classified(host):
    _classification(host)


# ---------------------------------------------------------------------------
# 4. Pins agree with the keys.
#
# Some pins name their tenant in a way the match text alone cannot show.
# These maps say which tenant each belongs to, from real checks:

# TelVue playlist and media ids -> their station's org token. Checked live
# 2026-09-25: each id is listed on (or answers 200 under) this token's
# /player/{token}/home, and answers 403 under another token.
TELVUE_ID_TOKEN = {
    "playlists/4806": "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru",  # C-NET
    "playlists/4815": "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru",  # C-NET
    **{
        f"playlists/{n}": "w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP"  # RVTV
        for n in (5222, 5224, 5226, 5229, 5237, 5242)
    },
    **{
        f"playlists/{n}": "Hejq7tDUseFZXc46e8pIxdl8NpmSEupd"  # CMNtv
        for n in (4479, 4480, 4483, 4536, 4537, 4538, 8590)
    },
    **{
        f"playlists/{n}": "lfzlfeW2jHTLCtEU2AKNyEA0B8A5stMI"  # Schopeg
        for n in (11253, 11276, 11277, 11278, 11279, 11280, 11281, 11295)
    },
    "media/1040134": "w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP",  # the pin's own evidence URL
    "/media/951693": "CXN6V2zmqTebSQfLjvlDzEql3BwiQh_l",  # Derry NH
}

# BoxCast /view/ and bare broadcast pins -> the account's channel id, via
# BoxCast's own API (checked 2026-09-25: /channels/{x}/broadcasts ->
# account_id -> /accounts/{id}.channel_id).
BOXCAST_BROADCAST_CHANNEL = {
    "view-embed/dcj8qnxnnonndniok58o": "dcj8qnxnnonndniok58o",  # Habersham County
    "view/farmersville-community-development-corporation-fcdc-4b-meeting-ewh3fjbymcc64jcz0sja": "pjlmoamwdrud0o6wncn9",
    "view/pascagoula-city-council-81826-z0nwcd5m4geotcf6h3ti": "xjmrwvcskgh36gcbtsxl",  # WGUD
    "city-council-work-session-nt9q4bsnt9xuckwizr0a": "heb1rus0rmpm1yorwlud",  # Scandia MN
}

# Known, reported to Ryan, not changed here (pin rows are out of scope).
# A NEW entry in either set fails the tests below.
#
# Mad River Valley TV's three playlists: its org token is in no fixture,
# pin, research file or its own website (mrvtv.com embeds TelVue's other
# product, connect.telvue.com), so which tenant they sit in is unknown.
KNOWN_UNMAPPED_PINS = {
    ("videoplayer.telvue.com", "playlists/4259"),
    ("videoplayer.telvue.com", "playlists/4260"),
    ("videoplayer.telvue.com", "playlists/4261"),
}
# One TelVue org token pinned whole to two governments: Yarmouth, MA
# (us:cousub:2500182525, archive_study) and us:cousub:2300587845 (wo309b,
# evidence says Yarmouth, ME; that id is not in the registry).
KNOWN_CONFLICTING_KEYS = {
    ("videoplayer.telvue.com", "GdKmpgaiQkyNQGt9mPxbWef1BmyvHIOm"),
}

_TELVUE_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32}$")
_CASTUS_HINT_RE = re.compile(r"^castus:([^:]+):")
_BOXCAST_HINT_RE = re.compile(r"^channel=boxcast:(.+)$")
# A query-only pin needs a real page path to be read as a URL.
_QUERY_PIN_PATH = {
    "public.destinyhosted.com": "agenda_publish.cfm",
    "townhallstreams.com": "stream.php",
}
_KEY_PREFIXES = ("player/", "vod/", "channel/", "clientid=", "location_id=", "id=")


def _pin_tenant(host: str, match: str) -> Tuple[Optional[str], bool]:
    """(tenant key, is_the_key_itself) for one pin, or (None, False) when
    the pin cannot be placed in exactly one tenant."""
    if host in tk.SHARED_SINGLE_LISTING_HOSTS:
        return "", False  # a per-meeting pin inside the one listing
    key: Optional[str] = None
    if host == "videoplayer.telvue.com" and _TELVUE_BARE_TOKEN_RE.match(match):
        key = match
    elif match in TELVUE_ID_TOKEN and host == "videoplayer.telvue.com":
        return TELVUE_ID_TOKEN[match], False
    elif host == "boxcast.tv" and match.split("?")[0] in BOXCAST_BROADCAST_CHANNEL:
        return BOXCAST_BROADCAST_CHANNEL[match.split("?")[0]], False
    elif _CASTUS_HINT_RE.match(match) and host == "cloud.castus.tv":
        return _CASTUS_HINT_RE.match(match).group(1).lower(), False
    elif _BOXCAST_HINT_RE.match(match) and host == "boxcast.tv":
        key = _BOXCAST_HINT_RE.match(match).group(1).lower()
    else:
        if re.match(r"^[A-Za-z_]+=", match):
            url = f"https://{host}/{_QUERY_PIN_PATH.get(host, '')}?{match}"
        else:
            url = f"https://{host}/{match.lstrip('/')}"
        key = tenant_key(url)
    if not key:
        return None, False
    norm = match.strip("/").lower()
    for prefix in ("channel=boxcast:",) + _KEY_PREFIXES:
        if norm.startswith(prefix) and norm[len(prefix) :] == key.lower():
            return key, True
    return key, norm == key.lower()


def _pins_in_scope():
    with open(OVERRIDES, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        host = r["tenant_host"].strip().lower()
        if host in tk.OUT_OF_SCOPE_HOSTS or host == "www.utah.gov":
            continue
        if host in MULTI_GOV_HOSTS or tk.is_keyed_shared_host(host):
            yield host, r["match"].strip(), r["gov_id"].strip()


def test_there_are_pins_to_check():
    # Guards the loop below against silently checking nothing.
    assert sum(1 for _ in _pins_in_scope()) > 200


def test_every_shared_host_pin_sits_in_exactly_one_tenant():
    unmapped = []
    for host, match, _gov in _pins_in_scope():
        key, _ = _pin_tenant(host, match)
        if key is None and (host, match) not in KNOWN_UNMAPPED_PINS:
            unmapped.append((host, match))
    assert unmapped == []


def test_known_unmapped_pins_still_exist():
    # When a listed pin is fixed or removed, drop it from the list too.
    present = {(h, m) for h, m, _ in _pins_in_scope()}
    assert KNOWN_UNMAPPED_PINS <= present


def test_no_two_pins_name_one_tenant_with_different_governments():
    by_key = defaultdict(set)
    for host, match, gov in _pins_in_scope():
        key, is_key = _pin_tenant(host, match)
        if key and is_key:
            by_key[(host, key)].add(gov)
    conflicts = {k for k, govs in by_key.items() if len(govs) > 1}
    assert conflicts == KNOWN_CONFLICTING_KEYS


# ---------------------------------------------------------------------------
# 5. The two other places that read a tenant agree with this module.


def test_telvue_org_token_is_the_tenant_key():
    from app.platforms.telvue import _org_token_from_url, account_url_for

    for url, expected in SHARED_CASES:
        if "videoplayer.telvue.com" in url:
            assert _org_token_from_url(url) == tenant_key(url) or expected is None
            if expected:
                assert account_url_for(url).startswith(
                    f"https://videoplayer.telvue.com/player/{expected}/"
                )


def test_meeting_finder_keeps_the_tenant_on_a_shared_host():
    from app.platforms.meeting_finder.identify import _account_url_for_platform

    url = "https://play.champds.com/atlantaga/event/1227"
    assert _account_url_for_platform("champds", url) == url
    # A single website still collapses to its root, as before.
    assert (
        _account_url_for_platform(
            "legistar", "https://mesa.legistar.com/MeetingDetail.aspx?ID=1428059"
        )
        == "https://mesa.legistar.com/"
    )


# ---------------------------------------------------------------------------
# 6. Two real pin bugs this test surfaced (WO-1056). Both are recorded as
# strict expected failures: fixing either one makes its test pass, which
# then fails as "XPASS" until the marker is removed. See BACKLOG.md.


@pytest.mark.xfail(
    strict=True,
    reason=(
        "WO-1056: pins are tried alphabetically, not most-specific first, so "
        "CMNtv's whole-station pin (player/Hejq7..., Berkley's school "
        "district) beats its per-city playlist pins (playlists/4479, Auburn "
        "Hills). See BACKLOG.md."
    ),
)
def test_a_playlist_pin_beats_its_stations_whole_token_pin():
    from app.utils.gov_registry.resolver import resolve_government

    match = resolve_government(
        None,
        tenant_host="videoplayer.telvue.com",
        path="/player/Hejq7tDUseFZXc46e8pIxdl8NpmSEupd/playlists/4479",
    )
    assert match.gov_id == "us:place:2604105"  # Auburn Hills, MI


@pytest.mark.xfail(
    strict=True,
    reason=(
        "WO-1056: DestinyHosted pins are written `id=N`, which only matches "
        "the agenda_publish.cfm?id= shape; a meeting page "
        "(/{id}/agenda/agenda.cfm?seq=...) carries the same id in its path "
        "and resolves to unknown. See BACKLOG.md."
    ),
)
def test_a_destinyhosted_meeting_page_gets_its_pinned_government():
    from app.utils.gov_registry.resolver import resolve_government

    # 24263 is the City of Chandler, AZ in both shapes (checked live
    # 2026-09-25); its pin is `id=24263 -> us:place:0412000`.
    match = resolve_government(
        None,
        tenant_host="public.destinyhosted.com",
        path="/24263/agenda/agenda.cfm?seq=2036",
    )
    assert match.gov_id == "us:place:0412000"
