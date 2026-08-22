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

CANARY_URLS below is deliberately one real URL per platform, not a list --
"keep it cheap: one URL per platform, not a full crawl" per WO-13's own
acceptance criteria. Each URL is the actual real, live meeting URL that
platform's test fixtures were built and verified against (see
tests/test_<platform>.py) -- not a guess. A URL going stale (the source
city removing an old meeting) is a real, expected failure mode distinct
from an adapter bug; if a canary run starts failing, check the URL still
resolves in a browser before assuming the adapter regressed.

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
CANARY_URLS: dict[str, str] = {
    "aurora_tv": "https://www.auroratv.org/video/regular-meeting-aurora-city-council-june-22-2026",
    "ca_legislature": "https://www.senate.ca.gov/media/senate-floor-session-20260806",
    "cablecast": "http://charlotte.cablecast.tv/internetchannel/show/2451?site=1",
    "castus": "https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d?page=HOME",
    "champds": "https://play.champds.com/atlantaga/event/1227",
    "civicclerk": "https://emporiaks.portal.civicclerk.com/event/585/media",
    "civicweb": "https://dallascounty.civicweb.net/Portal/MeetingInformation.aspx?Org=Cal&Id=2108",
    "clerkbase": (
        "https://clerkshq.com/YellowSprings-OH?docId=feb07_22ag&"
        "path=ArchAgenda_VilCouncil%2C2022_COUNCIL_AGENDAS%2Cfeb07_22ag%2C"
    ),
    # The Woodlands Township, TX -- the exact real URL
    # tests/test_destinyhosted.py's fixture shape was taken from, and the
    # one real confirmed case of this CMS's onclick-Swagit delegation
    # actually producing a video (most destinyhosted tenants are
    # agenda-only). A successful resolve here reports platform "swagit",
    # since the delegation's own identity survives on purpose.
    "destinyhosted": (
        "https://public.destinyhosted.com/agenda_publish.cfm"
        "?id=96635&mt=ALL&get_month=8&get_year=2026&dsp=ag&seq=4147"
    ),
    "escribe": (
        "https://pub-bakersfield.escribemeetings.com/Meeting.aspx?"
        "Id=981f78d7-8211-4b4b-b066-5f93b4fd5e74&Agenda=Agenda&lang=English"
    ),
    "granicus": "https://simivalley.granicus.com/player/clip/2840",
    "hyland": "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3",
    "iqm2": "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=17601",
    # Charlotte, NC -- the ordinary Legistar->Granicus delegation. Note
    # this does NOT exercise WO-30's city-YouTube-channel fallback
    # (app/platforms/youtube_channel.py), which only runs on the four
    # registered instances and only when a page has no video link at all.
    # That path introduced no new registered platform_name (it resolves as
    # "legistar" -> "youtube" like every other delegation), so the
    # coverage test below is satisfied without a new key -- but it is
    # genuinely unmonitored here. See BACKLOG.md's WO-30 residual-gaps
    # entry: the real fix is letting this dict hold more than one URL per
    # platform, a per-tenant gap that applies to every multi-tenant
    # adapter in it, not a second legistar-shaped key.
    "legistar": (
        "https://charlottenc.legistar.com/MeetingDetail.aspx?ID=1365278"
        "&GUID=E6E474AC-A2A9-4CE4-BCF0-5B118522E3BE&Options=info|"
    ),
    "lims": "https://lims.minneapolismn.gov/MarkedAgenda/CI/6133",
    # Eugene, OR -- the richest of tests/test_openmedia.py's three real
    # tenants (Goodyear AZ and Cortez CO are the other two, both also
    # live-verified 2026-08-21 if this one ever goes stale). open.media
    # embeds YouTube, so a failure here can also mean yt-dlp needs an
    # update rather than an open.media change -- check that first.
    "open_media": (
        "https://eugene.open.media/sessions/344982/"
        "city-council-work-session-july-15-2026"
    ),
    "primegov": "https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482",
    "seattle_channel": "https://www.seattlechannel.org/videos?videoid=x184865",
    "slc": "https://www.slc.gov/council/march-3-2026-meeting-recap/",
    # Holladay, UT -- the strongest of tests/test_suiteone.py's six
    # confirmed-live tenants: real populated WebVTT captions *and* a real
    # agenda PDF on the same event.
    "suiteone": "https://holladayut.suiteonemedia.com/event/?id=2652",
    "telvue": "https://videoplayer.telvue.com/player/w9sPsSE7vna3XTN_39bs1rEXjVWF0kfP/media/1040134",
    "townhallstreams": "https://townhallstreams.com/stream.php?location_id=94&id=75799",
    # "unknown" is generic_fallback.py's registered platform_name -- the
    # exact string detect_platform() returns for an unmatched host, not a
    # placeholder. Kept under that key so the coverage test can compare
    # registry keys directly.
    "unknown": "https://www.crrma.org/information/meetings/board/2025-11-12",
    "viebit": "https://councilnyc.viebit.com/vod/?s=true&v=NYCC-250-8-1_260722-110636.mp4",
    "youtube": "https://www.youtube.com/watch?v=uNDJRR3ywVo",
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
    "civicplus": (
        "The one real site this adapter was ever confirmed against "
        "(ca-westlakevillage.civicplus.com) already had a documented "
        "fixture note (tests/fixtures/civicplus/README.md) saying it "
        "stopped resolving as of 2026-08-07 -- re-confirmed live "
        "2026-08-16 building this canary (DNS failure, not an adapter "
        "bug). BACKLOG.md's Platform coverage section has a real untested "
        "replacement candidate (Maricopa County, AZ's CivicPlus "
        "AgendaCenter) -- add civicplus back to CANARY_URLS once that (or "
        "another) real site is actually verified against the live adapter."
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


async def check_platform(name: str, url: str) -> dict:
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


async def run_canary(urls: dict[str, str]) -> list[dict]:
    # One request per distinct real-world site, not the same site hit
    # repeatedly -- concurrent is fine, no politeness concern like a
    # single-site crawl would have.
    return await asyncio.gather(
        *(check_platform(name, url) for name, url in urls.items())
    )


def format_report(results: list[dict]) -> str:
    failed = [r for r in results if not r["ok"]]
    lines = [
        f"Adapter health canary: {len(results) - len(failed)}/{len(results)} platforms OK"
    ]
    for r in failed:
        lines.append(f"  FAIL {r['platform']}: {r['reason']} ({r['url']})")
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
