"""Adapter health canary (WO-13, AUDIT_EXECUTION_BRIEF.md) -- re-resolves
one real, known-good meeting URL per supported platform and reports which
ones broke.

Complements WO-7's Sentry integration rather than duplicating it: Sentry
catches raised exceptions, but the failure mode this repo hits most often
in practice is quieter than that -- a government site changes its page/API
structure and a working adapter starts returning empty or wrong content
while still returning HTTP 200, no exception anywhere for Sentry to see.
This script calls each platform's real `AssetFinder.resolve()` directly
(the same code `/api/resolve` uses), not the deployed HTTP service, so a
run doesn't depend on the app being deployed and doesn't write canary
noise into production's cache/stats/Archive.

Usage (from the repo root, with the venv active):
    python scripts/adapter_canary.py

Exits 1 if any platform's canary URL fails to resolve or comes back with
no real content; 0 if every platform is healthy. Meant to run on a
schedule (.github/workflows/adapter-canary.yml), which turns a non-zero
exit into a failed run and reuses WO-7's `if: failure()` notification
step.

CANARY_URLS below holds one real URL per platform by default -- "keep it
cheap: one URL per platform, not a full crawl" per WO-13's own acceptance
criteria still applies -- but a platform can carry more than one when a
single URL genuinely can't exercise every path worth monitoring (e.g.
"legistar" carries a second, Phoenix URL specifically for WO-30's
city-YouTube-channel fallback, which the ordinary Charlotte URL never
touches). Each URL is the actual real, live meeting URL that platform's
test fixtures were built and verified against (see tests/test_<platform>.py)
-- not a guess. A URL going stale (the source city removing an old
meeting) is a real, expected failure mode distinct from an adapter bug; if
a canary run starts failing, check the URL still resolves in a browser
before assuming the adapter regressed.

Every registered platform must appear in either CANARY_URLS or
CANARY_EXCLUSIONS -- `tests/test_adapter_canary.py` enforces that in CI,
so a newly-added adapter can't silently ship unmonitored.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import CalendarPageError, detect_platform, get_finder  # noqa: E402
from app.platforms.models import ResolvedMeeting  # noqa: E402

# See this file's module docstring for how these were chosen: each is the
# real URL that platform's own test fixtures were built and verified
# against (tests/test_<platform>.py), picked for the richest confirmed
# positive signal when a test file had more than one real candidate (e.g.
# Granicus/Hyland/CivicClerk/Cablecast/Legistar each had a weaker "first"
# example -- blank transcript, no video, or a pick-list page -- and a
# stronger fully-populated one; the stronger one is used here so a real
# regression is more likely to actually change the outcome).
#
# **Every key here must be exactly the platform's registered
# `AssetFinder.platform_name`** (the key `register_all_finders()` puts in
# base.py's registry), not a prettier label -- three of them are less
# obvious than they look ("aurora_tv", "seattle_channel", and "unknown"
# for the generic fallback). `tests/test_adapter_canary.py`'s coverage
# test asserts exactly that, and also asserts that every registered
# platform appears either here or in CANARY_EXCLUSIONS below -- so a new
# adapter that forgets its canary entry fails CI at PR time instead of
# silently going unmonitored (which is what happened to destinyhosted,
# suiteone, and open_media, all added blind between 2026-08-19 and
# 2026-08-21 and only caught by that test being written).
CANARY_URLS: dict[str, list[str]] = {
    "aurora_tv": [
        "https://www.auroratv.org/video/regular-meeting-aurora-city-council-june-22-2026"
    ],
    "ca_legislature": ["https://www.senate.ca.gov/media/senate-floor-session-20260806"],
    "cablecast": ["http://charlotte.cablecast.tv/internetchannel/show/2451?site=1"],
    "castus": [
        "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME"
    ],
    "champds": ["https://play.champds.com/atlantaga/event/1227"],
    # Chicago's 2026-07-15 City Council meeting -- live-verified 2026-08-21
    # (WO-29). Watch for two distinct failure shapes here: the ELMS API
    # itself changing, or Vimeo's public oEmbed endpoint starting to
    # refuse this app's server IP (the metadata half comes from there, see
    # vimeo.py). A resolve with a real video_url but no title/date points
    # at the second.
    "chicago_elms": [
        "https://chicityclerkelms.chicago.gov/Meeting/"
        "?meetingId=DF5C52EA-0D6B-F111-A823-001DD8019941"
    ],
    "civicclerk": ["https://emporiaks.portal.civicclerk.com/event/585/media"],
    # Durham, NC -- confirmed live 2026-08-30, replacing the earlier
    # ca-westlakevillage.civicplus.com sample after it went DNS-dead (see
    # civicplus.py's own docstring and tests/fixtures/civicplus/README.md).
    # This is a category listing page, not a single-meeting URL -- CivicPlus
    # has no single-meeting URL shape at all (every real one observed is a
    # listing) -- so this always raises CalendarPageError, which
    # _attempt_platform() already treats as a correct, expected outcome as
    # long as real per-meeting candidates come back (31 rows, 22 with a
    # real video link, confirmed at canary-build time).
    "civicplus": ["https://nc-durham.civicplus.com/AgendaCenter/City-Council-4"],
    "civicweb": [
        "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal&Id=2108"
    ],
    "clerkbase": [
        "https://clerkshq.com/YellowSprings-OH?docId=feb07_22ag&"
        "path=ArchAgenda_VilCouncil%2C2022_COUNCIL_AGENDAS%2Cfeb07_22ag%2C"
    ],
    # The Woodlands Township, TX -- the exact real URL
    # tests/test_destinyhosted.py's fixture shape was taken from, and the
    # one real confirmed case of this CMS's onclick-Swagit delegation
    # actually producing a video (most destinyhosted tenants are
    # agenda-only). A successful resolve here reports platform "swagit",
    # since the delegation's own identity survives on purpose.
    "destinyhosted": [
        "https://public.destinyhosted.com/agenda_publish.cfm"
        "?id=96635&mt=ALL&get_month=8&get_year=2026&dsp=ag&seq=4147"
    ],
    "escribe": [
        "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?"
        "Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74&Agenda=Agenda&lang=English"
    ],
    "granicus": ["https://simivalley.granicus.com/player/clip/2840"],
    "hyland": [
        "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3"
    ],
    "iqm2": ["https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=17601"],
    # Charlotte, NC -- the ordinary Legistar->Granicus delegation, plus (as
    # of 2026-08-29) a real Phoenix URL that exercises WO-30's
    # city-YouTube-channel fallback (app/platforms/youtube_channel.py)
    # specifically -- the same URL tests/test_legistar.py's `_PHOENIX_URL`
    # is built against. That path used to be genuinely unmonitored here: it
    # introduces no new registered platform_name (still resolves as
    # "legistar" -> "youtube", like the Charlotte URL), so the coverage
    # test was satisfied without ever exercising it. This second URL costs
    # more per run than a single-page resolve -- it drives the real,
    # heavier yt-dlp channel-listing path (~400 entries, ~6s per tab, per
    # youtube_channel.py's own docstring), untested from Render's egress --
    # that's the point (catching this path breaking), but it's worth
    # knowing before treating a Phoenix-only failure as equally cheap to
    # retry as everything else here.
    "legistar": [
        "https://charlottenc.legistar.com/MeetingDetail.aspx?ID=1365278"
        "&GUID=E6E474AC-A2A9-4CE4-BCF0-5B118522E3BE&Options=info|",
        "https://phoenix.legistar.com/MeetingDetail.aspx?ID=1425831",
    ],
    "lims": ["https://lims.minneapolismn.gov/MarkedAgenda/CI/6133"],
    # Eugene, OR -- the richest of tests/test_openmedia.py's three real
    # tenants (Goodyear AZ and Cortez CO are the other two, both also
    # live-verified 2026-08-21 if this one ever goes stale). open.media
    # embeds YouTube, so a failure here can also mean yt-dlp needs an
    # update rather than an open.media change -- check that first.
    "open_media": [
        "https://eugene.open.media/sessions/344982/"
        "city-council-work-session-july-15-2026"
    ],
    "primegov": ["https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482"],
    # Town of Fairfax, CA -- the tenant this adapter was built and tested
    # against (see proudcity.py's own module docstring, BACKLOG_DONE.md's
    # 2026-08-26 entry). Real video, real jurisdiction, real agenda PDF.
    "proudcity": [
        "https://townoffairfaxca.gov/meetings/town-council-meeting-august-5-2026/"
    ],
    "seattle_channel": ["https://www.seattlechannel.org/videos?videoid=x184865"],
    "slc": ["https://www.slc.gov/council/march-3-2026-meeting-recap/"],
    # Holladay, UT -- the strongest of tests/test_suiteone.py's six
    # confirmed-live tenants: real populated WebVTT captions *and* a real
    # agenda PDF on the same event.
    "suiteone": ["https://holladayut.suiteonemedia.com/event/?id=2652"],
    # Tampa, FL City Council -- a real 8/20/2026 evening meeting,
    # confirmed live 2026-08-30 (WO-73): real paired video plus 713 real
    # timestamped closed-captioning segments. See tampa.py's own module
    # docstring.
    "tampa": ["https://apps.tampagov.net/cttv_cc_webapp/Agenda.aspx?pkey=2698"],
    "telvue": [
        "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1040134"
    ],
    "townhallstreams": [
        "https://townhallstreams.com/stream.php?location_id=94&id=75799"
    ],
    # "unknown" is generic_fallback.py's registered platform_name -- the
    # exact string detect_platform() returns for an unmatched host, not a
    # placeholder. Kept under that key so the coverage test can compare
    # registry keys directly.
    "unknown": ["https://www.crrma.org/information/meetings/board/2025-11-12"],
    "viebit": [
        "https://councilnyc.viebit.com/vod/?s=true&v=NYCC-250-8-1_260722-110636.mp4"
    ],
    # Salisbury, NC's real 7/21/2026 City Council meeting -- the one city
    # in the WO-29 investigation confirmed (via a real browser) to have
    # populated English captions inside the Vimeo player. This adapter is
    # video-only by design (see vimeo.py), so `has_real_content()` here is
    # satisfied by video + metadata, not segments.
    "vimeo": ["https://vimeo.com/1212025580"],
    "youtube": ["https://www.youtube.com/watch?v=uNDJRR3ywVo"],
}

# Registered platforms that deliberately have no canary URL, each with the
# real reason why. Per this repo's "never claim it works without a real
# confirmed example" convention, don't guess at a URL for either of these
# -- a canary entry that was never verified live is worse than no entry,
# since it produces a daily false alarm.
#
# Keep this in sync with CANARY_URLS: tests/test_adapter_canary.py asserts
# every registered platform appears in exactly one of the two, so removing
# a platform from here without adding a URL (or vice versa) fails CI.
CANARY_EXCLUSIONS: dict[str, str] = {
    "swagit": (
        "No real Swagit meeting URL appears anywhere in this repo's text "
        "(tests/test_swagit.py's own header says so explicitly -- 'no real "
        "Swagit meeting has ever been observed with a caption file at "
        "all'), only a described-but-not-recorded Dublin, CA example. "
        "Partially covered indirectly: the destinyhosted canary URL "
        "delegates into the real Swagit adapter, so a total Swagit "
        "parsing break would surface there -- but as a destinyhosted "
        "failure, not a swagit one."
    ),
    "civiclive": (
        "No live CivicLive page has yet been found to produce "
        "has_real_content()-shaped output -- see civiclive.py's own module "
        "docstring for the full investigation. The one confirmed real "
        "off-domain delegation (Auburn, WA's 'Agendas & Minutes' page "
        "302-redirecting to auburnwa.portal.civicclerk.com) lands on "
        "CivicClerk's bare portal HOME, not a specific meeting -- no "
        "video_url/segments/agenda_link of its own, so it would false-alarm "
        "here daily despite the adapter behaving correctly. No live tenant "
        "has been found with a server-rendered, per-meeting embedded video "
        "either (the real agenda/calendar tables are client-rendered and "
        "invisible to a plain fetch on every tenant checked so far -- "
        "Auburn, Escalon). Revisit if a real per-meeting-video CivicLive "
        "sample ever turns up."
    ),
}


def has_real_content(result: ResolvedMeeting) -> bool:
    """Same "meaningful content" definition as app/main.py's
    /api/health/resolve-check (WO-7) -- kept in sync deliberately, since
    both exist to answer the same underlying question: did this resolve
    produce something real, not just a 200 with nothing in it?"""
    return bool(
        result.segments or result.agenda_items or result.video_url or result.agenda_link
    )


# A canary run makes one request each to 29 live third-party sites it
# does not control (28 platforms, one -- "legistar" -- carrying 2 URLs),
# so a transient failure somewhere in that set is
# expected rather than exceptional -- and reporting the first one as a
# real failure emails an alert that costs a full triage investigation.
# That is not hypothetical: the 2026-08-22 `destinyhosted` failure was
# investigated as a possible adapter regression and refuted only by the
# next two runs coming back green.
#
# One retry, not a loop: the point is to absorb a blip, not to keep
# hammering a site that is genuinely down, and one extra request to one
# site stays well inside this repo's politeness posture.
_RETRY_DELAY_SECONDS = 5.0


async def _attempt_platform(name: str, url: str) -> dict:
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
        result = await finder.resolve(url)
    except CalendarPageError as e:
        # A listing/calendar page (e.g. CivicPlus's AgendaCenter, which
        # has no single-meeting URL shape at all -- every real URL is a
        # category page) is a correct, expected outcome for some canary
        # URLs, not a failure. What actually matters is whether real
        # per-meeting rows were still found -- a real regression would
        # show up as this list going empty, not as the error itself.
        if e.candidates:
            return {"platform": name, "url": url, "ok": True, "reason": None}
        return {
            "platform": name,
            "url": url,
            "ok": False,
            "reason": "calendar page returned zero candidates",
        }
    except Exception as e:
        return {
            "platform": name,
            "url": url,
            "ok": False,
            "reason": f"{type(e).__name__}: {e}"[:300],
        }

    if not has_real_content(result):
        return {
            "platform": name,
            "url": url,
            "ok": False,
            "reason": "resolve returned no real content",
        }
    return {"platform": name, "url": url, "ok": True, "reason": None}


async def check_platform(name: str, url: str) -> dict:
    """One platform's canary result, retried once before reporting failure.

    Retries every failure shape, not just raised exceptions: the observed
    real-world flake reported "resolve returned no real content", which is
    the non-exception path.

    A platform that failed once and then passed still says so in its
    result (`recovered_after_retry`), so a site that is *becoming* flaky
    stays distinguishable from one that is simply stable -- silence should
    never be the only signal, the same reason the daily reports in this
    repo send even when nothing happened.
    """
    result = await _attempt_platform(name, url)
    if result["ok"]:
        return result

    await asyncio.sleep(_RETRY_DELAY_SECONDS)
    retried = await _attempt_platform(name, url)
    # The second attempt's reason is the one worth reporting -- it
    # describes a failure that actually persisted.
    retried["first_attempt_reason"] = result["reason"]
    retried["recovered_after_retry"] = retried["ok"]
    return retried


async def run_canary(urls: dict[str, list[str]]) -> list[dict]:
    # One request per distinct real-world site, not the same site hit
    # repeatedly -- concurrent is fine, no politeness concern like a
    # single-site crawl would have.
    #
    # A platform with only one URL keeps its report label exactly as
    # before ("legistar", not "legistar[0]") -- every existing single-URL
    # platform's report output stays byte-identical. A platform with more
    # than one gets an index suffix per URL so each result stays
    # independently attributable.
    tasks = []
    for name, url_list in urls.items():
        if len(url_list) == 1:
            tasks.append(check_platform(name, url_list[0]))
        else:
            tasks.extend(
                check_platform(f"{name}[{i}]", url) for i, url in enumerate(url_list)
            )
    return await asyncio.gather(*tasks)


def format_report(results: list[dict]) -> str:
    failed = [r for r in results if not r["ok"]]
    lines = [
        f"Adapter health canary: {len(results) - len(failed)}/{len(results)} platforms OK"
    ]
    for r in failed:
        lines.append(f"  FAIL {r['platform']}: {r['reason']} ({r['url']})")
    for r in results:
        if r.get("recovered_after_retry"):
            lines.append(
                f"  FLAKY {r['platform']}: first attempt failed "
                f"({r['first_attempt_reason']}), retry passed ({r['url']})"
            )
    return "\n".join(lines)


async def main() -> int:
    if not CANARY_URLS:
        print("CANARY_URLS is empty -- nothing to check.")
        return 0

    register_all_finders()
    results = await run_canary(CANARY_URLS)
    print(format_report(results))
    return 1 if any(not r["ok"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
