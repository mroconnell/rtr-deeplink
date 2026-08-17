"""Backtest the generic fallback adapter against the real coverage-gap corpus.

Runs `GenericFallbackAssetFinder().resolve()` live against every real
coverage-gap URL logged in BACKLOG.md (plus two production fallback
failures found via a 2026-08-14 classification of all archived pages'
source URLs), and prints a per-URL scorecard: which of
title/date/jurisdiction/video/captions/agenda came back matching the
expectation recorded for that page. Built as Phase 0 of the 2026-08-14
generic-fallback rebuild -- run it BEFORE each phase lands to record a
baseline, and after, to prove the scorecard only ever improves.

This is a dev-time diagnostic, not a test suite or a migration tool: it
fetches real live pages (strictly sequentially, politeness delay between
each -- these are small-government servers), never pushes anything to the
Archive, and its expectations describe what the *rebuilt* adapter should
achieve, so a baseline run is EXPECTED to show failures -- that's the
point. Fixture-backed regression tests for the same shapes live in
tests/test_generic_fallback.py; sample HTML captured from these same URLs
lives in tests/fixtures/generic_fallback/.

Usage (from the repo root, with the venv active):
    python scripts/backtest_fallback.py                  # non-headless corpus
    python scripts/backtest_fallback.py --url-contains saccounty
    python scripts/backtest_fallback.py --include-headless
    python scripts/backtest_fallback.py --json

Exits nonzero if any non-headless row FAILs, so it can gate a release.
Rows marked requires_headless are skipped by default (they cannot work
without the env-gated headless escalation, Phase 5) and never affect the
exit code even with --include-headless.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Each row: what the REBUILT fallback should achieve on this real page.
# `video`: expected ResolvedMeeting.video_format ("m3u8"/"mp4"/"youtube"),
# "video_link" for the pointer-only outcome, or None for genuinely nothing.
# String expectations are substring matches. `backlog_ref` names the
# BACKLOG.md entry each row came from.
CORPUS = [
    {
        "name": "sacramento",
        "url": "https://agendanet.saccounty.gov/BoardofSupervisors/Meetings/ViewMeeting?id=10231&doctype=1",
        "requires_headless": False,
        "expect": {
            "video": "m3u8",
            "video_url_contains": "playlist.m3u8?instance=1&token=",
            "agenda_link": True,
            "title_contains": "Board Of Supervisors",
            "date": "2026-08-11",
        },
        "backlog_ref": "Sacramento County OnBase-family entry",
    },
    {
        "name": "maricopa",
        "url": "https://mccobagenda.databankcloud.com/AgendaOnline/Meetings/ViewMeeting?id=4694&doctype=3",
        "requires_headless": False,
        "expect": {
            "video": "m3u8",
            "video_url_contains": "playlist.m3u8?instance=1&token=",
        },
        "backlog_ref": "Hyland 221/OnBase entry (Maricopa update)",
    },
    {
        "name": "tarrant",
        "url": "https://agendamgmtprod.tarrantcountytx.gov/Meetings/GetHTMLAgenda?meetingId=&dataSource=&id=21849bbe-d099-4637-1560-08ddc611a5e2",
        "requires_headless": False,
        "expect": {
            # "Commissioners Court" is satisfied on BOTH real paths: when
            # yt-dlp succeeds (residential networks) the real YouTube title
            # is exactly "Commissioners Court" and correctly wins; when
            # yt-dlp is blocked (Render) the page's own h1 assembly gives
            # "Tarrant County Commissioners Court".
            "video": "youtube",
            "video_url_contains": "Awrb74sMXyM",
            "title_contains": "Commissioners Court",
            "date": "2025-08-19",
        },
        "backlog_ref": "Tarrant County Agenda Management System entry",
    },
    {
        "name": "seattle",
        "url": "https://www.seattlechannel.org/videos?videoid=x189286",
        "requires_headless": False,
        "expect": {
            "video": "mp4",
            "video_url_contains": "video.seattle.gov/media/council/council_081126",
            "captions": True,
            "date": "2026-08-11",
        },
        "backlog_ref": "Seattle Channel entry (/videos?videoid= shape)",
    },
    {
        "name": "sebastopol",
        "url": "https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/",
        "requires_headless": False,
        "expect": {
            "video": "video_link",
            "video_link_contains": "vimeo.com/1152708575",
            "title_contains": "City Council Meeting",
            "jurisdiction_contains": "Sebastopol",
            "agenda_link": True,
        },
        "backlog_ref": "generic_fallback Sebastopol entry + Vimeo entry",
    },
    {
        "name": "ocfl",
        "url": "https://netapps.ocfl.net/Mod/meetings/1/2069",
        "requires_headless": False,
        "expect": {
            "video": "mp4",
            "video_url_contains": "otv.ocfl.net",
            "captions": True,
        },
        "backlog_ref": "found 2026-08-14 via archived-URL classification (empty archived page)",
    },
    {
        "name": "wayne_county",
        "url": "https://www.waynecountymi.gov/Government/Elected-Officials/Commission/Committees/Full-Commission-Meetings/2026/Wayne-County-Commission-January-8-2026",
        "requires_headless": True,
        "expect": {
            # "Commission" is satisfied on both real paths: yt-dlp success
            # gives the real YouTube title ("Commission Meeting | Full
            # Commission - Jan 8, 2026"), the blocked path gives og:title
            # ("Wayne County Commission - January 8, 2026").
            "video": "youtube",
            "video_url_contains": "RFwXrAzkXR8",
            "agenda_link": True,
            "title_contains": "Commission",
        },
        "backlog_ref": "Wayne County MI Akamai-block entry",
    },
    {
        "name": "pbc",
        "url": "https://discover.pbc.gov/countycommissioners/Pages/bcc-meeting-videos.aspx?videoid=bcc%2F2026%2F20260707-bcc-board-mtg-AM",
        "requires_headless": True,
        # JS-rendered SharePoint -- unknown what a headless render exposes;
        # loose expectations on purpose, this row documents the limit.
        "expect": {"video": None},
        "backlog_ref": "found 2026-08-14 via archived-URL classification (empty archived page)",
    },
    {
        "name": "tucson_hyland",
        "url": "https://tucsonaz.hylandcloud.com/221agendaonline/Meetings/ViewMeeting?doctype=2&id=1956",
        "requires_headless": True,
        # Confirmed fully client-rendered with nothing static; the honest
        # outcome without headless is an empty best-effort result.
        "expect": {"video": None},
        "backlog_ref": "Hyland 221 Agenda Online entry (Tucson)",
    },
]


def score(entry, resolved) -> list:
    """Returns [(field, PASS|PARTIAL|FAIL, detail), ...] for one resolve."""
    exp = entry["expect"]
    rows = []

    expected_video = exp.get("video")
    if expected_video == "video_link":
        link = getattr(resolved, "video_link", None)
        want = exp.get("video_link_contains", "")
        if link and want in link:
            rows.append(("video", "PASS", f"pointer {link}"))
        else:
            rows.append(
                (
                    "video",
                    "FAIL",
                    f"expected pointer containing {want!r}, got video_link={link!r} video_url={resolved.video_url!r}",
                )
            )
    elif expected_video is None:
        if resolved.video_url is None:
            rows.append(("video", "PASS", "honestly empty, as expected"))
        else:
            rows.append(
                (
                    "video",
                    "PARTIAL",
                    f"unexpectedly found {resolved.video_format}: {resolved.video_url[:80]} (better than expected -- tighten this row)",
                )
            )
    else:
        want_url = exp.get("video_url_contains", "")
        if (
            resolved.video_format == expected_video
            and resolved.video_url
            and want_url in resolved.video_url
        ):
            rows.append(("video", "PASS", resolved.video_url[:90]))
        else:
            rows.append(
                (
                    "video",
                    "FAIL",
                    f"expected {expected_video} containing {want_url!r}, got format={resolved.video_format!r} url={str(resolved.video_url)[:90]!r}",
                )
            )

    if exp.get("captions"):
        rows.append(
            (
                "captions",
                "PASS" if resolved.segments else "FAIL",
                f"{len(resolved.segments)} segments",
            )
        )
    if exp.get("agenda_link"):
        rows.append(
            (
                "agenda",
                "PASS" if resolved.agenda_link else "FAIL",
                str(resolved.agenda_link)[:90],
            )
        )
    if exp.get("title_contains"):
        ok = resolved.title and exp["title_contains"].lower() in resolved.title.lower()
        rows.append(("title", "PASS" if ok else "FAIL", repr(resolved.title)))
    if exp.get("date"):
        rows.append(
            (
                "date",
                "PASS" if resolved.date == exp["date"] else "FAIL",
                repr(resolved.date),
            )
        )
    if exp.get("jurisdiction_contains"):
        ok = (
            resolved.jurisdiction
            and exp["jurisdiction_contains"].lower() in resolved.jurisdiction.lower()
        )
        rows.append(
            ("jurisdiction", "PASS" if ok else "PARTIAL", repr(resolved.jurisdiction))
        )
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url-contains",
        type=str,
        default=None,
        help="Only run corpus rows whose URL contains this substring",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0, help="Seconds between rows (default 2.0)"
    )
    parser.add_argument(
        "--include-headless",
        action="store_true",
        help="Also run rows that need the headless escalation",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of text",
    )
    args = parser.parse_args()

    # Deferred import, same reasoning as scripts/backfill_archived_pages.py:
    # load_dotenv() in __main__ must run before app modules read env vars.
    from app.platforms.generic_fallback import GenericFallbackAssetFinder

    rows = CORPUS
    if args.url_contains:
        rows = [r for r in rows if args.url_contains in r["url"]]
    if not args.include_headless:
        rows = [r for r in rows if not r["requires_headless"]]

    if not rows:
        print("No matching corpus rows.")
        return

    report = []
    any_fail = False
    for i, entry in enumerate(rows, 1):
        if i > 1:
            await asyncio.sleep(args.delay)
        try:
            resolved = await GenericFallbackAssetFinder().resolve(entry["url"])
            results = score(entry, resolved)
        except Exception as e:  # a crash is itself a scorecard result
            results = [("resolve", "FAIL", f"{type(e).__name__}: {e}")]
        headless_note = " [requires_headless]" if entry["requires_headless"] else ""
        if not args.json:
            print(
                f"[{i}/{len(rows)}] {entry['name']}{headless_note}  ({entry['backlog_ref']})"
            )
            for field, verdict, detail in results:
                print(f"    {verdict:8s} {field:12s} {detail}")
            print()
        report.append(
            {
                "name": entry["name"],
                "url": entry["url"],
                "requires_headless": entry["requires_headless"],
                "results": [
                    {"field": f, "verdict": v, "detail": d} for f, v, d in results
                ],
            }
        )
        if not entry["requires_headless"] and any(v == "FAIL" for _, v, _ in results):
            any_fail = True

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        n_pass = sum(1 for r in report for x in r["results"] if x["verdict"] == "PASS")
        n_fail = sum(1 for r in report for x in r["results"] if x["verdict"] == "FAIL")
        n_part = sum(
            1 for r in report for x in r["results"] if x["verdict"] == "PARTIAL"
        )
        print(
            f"Scorecard: {n_pass} PASS, {n_part} PARTIAL, {n_fail} FAIL across {len(report)} page(s)."
        )

    if any_fail:
        sys.exit(1)


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
