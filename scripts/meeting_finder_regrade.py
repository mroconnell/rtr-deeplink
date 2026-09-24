#!/usr/bin/env python3
"""WO-1041: re-label existing Meeting Finder verdict files under the new
"meeting evidence" rule (`app.utils.video_hand_check.assess_meeting_
evidence()`), WITHOUT re-running Meeting Finder.

Why a separate script rather than just re-running `scripts/
meeting_finder.py`: the overnight/overnight2 runs already spent the real
network budget (thousands of governments, `~/Documents/rtr-deeplink`'s own
per-host politeness limits) -- re-running the whole walk just to apply a
smarter accept/reject rule on top of data already fetched would throw that
work away for nothing. Everything this script needs to re-grade a row is
either already in the verdict JSONL (`platform`, `result_url`,
`duration_seconds`, `note`, `identity_verdict`) or cheap to fetch fresh
(a Vimeo oEmbed title, a Google Drive file's own page title) -- both far
lighter than a real resolve.

What changes, per `app.utils.video_hand_check.assess_meeting_evidence()`
(see that module's own WO-1041 section for the full rule and the real
spot-check evidence it's built from):

  - A `direct_file`/`vimeo` find, or any find `resolve.py`'s `pick.py` note
    says was "picked by: undated, lister order", is DEMOTED from a clean
    find (`outcome=None`) to a low-confidence one (`video-low-confidence`,
    reason "no meeting evidence") when nothing in its title/filename/oEmbed
    title/Drive title/linking-page URL names a meeting or carries a date.
    Every other find (a per-meeting listing, a dedicated meeting platform)
    is untouched -- it already carries its own evidence.
  - A find whose automatic identity check `disagrees` (a different real
    government's own meeting) is relabeled `needs-hand-check` -- not a
    clean find either, but a different kind of miss than "no evidence of a
    meeting at all". `identity_points_to` is kept in the output row.

Usage:
    .venv/bin/python scripts/meeting_finder_regrade.py \\
        --run overnight=<path>/overnight --run overnight2=<path>/overnight2 \\
        --out <path>/regraded.csv \\
        --handcheck-dir <path>/followup

`--handcheck-dir`, when given, must hold `hc*.json` (case order, each row
carries `run`/`domain`) and matching `hc*_result.csv` (same row order, a
human verdict per row -- see `followup/HANDCHECK_BRIEF.md`) and produces
the agreement table between the human hand-check and this script's
regrade, printed at the end alongside the per-stratum summary.

Polite and YouTube-free: `scripts/youtube_fetch_guard.install()` is
installed before any network call, one request at a time with a fixed
delay between them, and every oEmbed/Drive title is cached in-process (and,
across runs of this script, in `--cache-file`) so re-running it never
re-fetches the same id twice.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402

from app.utils.video_hand_check import assess_meeting_evidence  # noqa: E402

# --- Platforms/picks that need real meeting evidence (see resolve.py's
# `_EVIDENCE_REQUIRED_PLATFORMS`/`_needs_meeting_evidence()` -- this script
# applies the SAME rule to already-written verdict rows). --------------
_EVIDENCE_REQUIRED_PLATFORMS = frozenset({"direct_file", "vimeo"})
_UNDATED_LISTER_ORDER_MARK = "picked by: undated, lister order"

_VIMEO_ID_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")
_OEMBED_ENDPOINT = "https://vimeo.com/api/oembed.json?url="
_DRIVE_TITLE_RE = re.compile(r"<title[^>]*>([^<]*)</title>", re.IGNORECASE)

# Same one-request-at-a-time politeness every hand-read script in this
# repo uses for a public, unauthenticated metadata endpoint.
_REQUEST_DELAY_SECONDS = 1.0
_FETCH_TIMEOUT_SECONDS = 8


@dataclass
class RegradeOutcome:
    new_outcome: Optional[str]
    reason: str
    evidence_source: str = ""


def _needs_evidence(platform: Optional[str], note: str) -> bool:
    return (platform or "").lower() in _EVIDENCE_REQUIRED_PLATFORMS or (
        _UNDATED_LISTER_ORDER_MARK in (note or "")
    )


def _is_google_drive_url(url: Optional[str]) -> bool:
    return "drive.google.com" in (url or "")


def _is_youtube_url(url: Optional[str]) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return "youtube.com" in host or host == "youtu.be" or host.endswith(".youtu.be")


class TitleFetcher:
    """Vimeo oEmbed / Google Drive title lookups, cached in-process and
    persisted to `cache_path` (a flat `{url: title_or_null}` JSON file) so
    a later run of this script never re-fetches the same id. One request
    at a time, `_REQUEST_DELAY_SECONDS` apart, same host or not -- this
    script only ever touches two hosts (`vimeo.com`, `drive.google.com`),
    so a single global pace is simplest and still polite."""

    def __init__(self, cache_path: Optional[Path] = None):
        self.cache_path = cache_path
        self.cache: Dict[str, Optional[str]] = {}
        if cache_path and cache_path.exists():
            try:
                self.cache = json.loads(cache_path.read_text())
            except (ValueError, OSError):
                self.cache = {}
        self._session = None
        self.fetch_count = 0

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True))

    async def _get_text(self, url: str) -> Optional[str]:
        import aiohttp

        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=_FETCH_TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(timeout=timeout)
        if _is_youtube_url(url):
            raise AssertionError(f"refusing YouTube fetch: {url}")
        try:
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
            async with self._session.get(url) as resp:
                self.fetch_count += 1
                if resp.status != 200:
                    return None
                return await resp.text(errors="ignore")
        except Exception:  # noqa: BLE001 -- a failed lookup is "no title"
            return None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    async def vimeo_title(self, video_url: str) -> Optional[str]:
        if video_url in self.cache:
            return self.cache[video_url]
        oembed_url = _OEMBED_ENDPOINT + quote(video_url, safe="")
        body = await self._get_text(oembed_url)
        title = None
        if body:
            try:
                title = (json.loads(body).get("title") or None) or None
            except ValueError:
                title = None
        self.cache[video_url] = title
        return title

    async def drive_title(self, drive_url: str) -> Optional[str]:
        if drive_url in self.cache:
            return self.cache[drive_url]
        body = await self._get_text(drive_url)
        title = None
        if body:
            match = _DRIVE_TITLE_RE.search(body)
            if match:
                title = match.group(1).rsplit(" - Google Drive", 1)[0].strip() or None
        self.cache[drive_url] = title
        return title


async def regrade_row(row: Dict[str, Any], fetcher: TitleFetcher) -> RegradeOutcome:
    outcome = row.get("outcome") or None
    if outcome is not None:
        # Not a clean find under the OLD rule either (a genuine miss,
        # or already demoted to video-low-confidence for some other
        # reason, e.g. "too short") -- nothing for the evidence check to
        # do; identity is still worth checking (see below).
        pass

    identity_verdict = row.get("identity_verdict") or ""
    if outcome is None and identity_verdict == "disagrees":
        points_to = row.get("identity_points_to") or "an unnamed different government"
        return RegradeOutcome(
            new_outcome="needs-hand-check",
            reason=f"identity disagrees: resolver points to {points_to}",
        )

    if outcome is not None:
        return RegradeOutcome(
            new_outcome=outcome, reason="unchanged (not a clean find)"
        )

    platform = (row.get("platform") or "").lower()
    note = row.get("note") or ""
    if not _needs_evidence(platform, note):
        return RegradeOutcome(
            new_outcome=None, reason="unchanged (evidence not required)"
        )

    result_url = row.get("result_url") or ""
    duration = row.get("duration_seconds")
    texts: List[str] = [result_url]
    evidence_source = "filename/url only"

    if platform == "vimeo":
        vid_match = _VIMEO_ID_RE.search(result_url)
        if vid_match and not _is_youtube_url(result_url):
            title = await fetcher.vimeo_title(result_url)
            if title:
                texts.append(title)
                evidence_source = "vimeo oEmbed title"
    if _is_google_drive_url(result_url):
        title = await fetcher.drive_title(result_url)
        if title:
            texts.append(title)
            evidence_source = "google drive title"

    evidence = assess_meeting_evidence(
        *texts, duration_seconds=duration, is_direct_file=(platform == "direct_file")
    )
    if evidence.has_evidence:
        return RegradeOutcome(
            new_outcome=None,
            reason=f"meeting evidence found ({evidence.reason})",
            evidence_source=evidence_source,
        )
    reason = evidence.non_meeting_sign or "nothing found"
    return RegradeOutcome(
        new_outcome="video-low-confidence",
        reason=f"no meeting evidence ({reason})",
        evidence_source=evidence_source,
    )


# --- Loading run directories ------------------------------------------


def load_strata(run_dir: Path) -> Dict[str, Tuple[str, Optional[int]]]:
    """`{url: (stratum, pool_size)}` from `<run_dir>/strata.csv`, or `{}`
    when the run has no strata file."""
    path = run_dir / "strata.csv"
    if not path.exists():
        return {}
    out: Dict[str, Tuple[str, Optional[int]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pool_size = row.get("pool_size") or None
            out[row["url"]] = (
                row.get("stratum") or "",
                int(pool_size) if pool_size else None,
            )
    return out


def load_verdicts(run_dir: Path) -> List[Dict[str, Any]]:
    path = run_dir / "verdicts.csv.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"no verdicts.csv.jsonl under {run_dir}")
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --- Hand-check agreement ------------------------------------------------


def load_handcheck_truth(handcheck_dir: Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    """`{(run, domain): {verdict, other_gov, video_title, evidence}}` from
    every `hc<N>.json` (row order: `run`/`domain`) matched positionally
    against its own `hc<N>_result.csv` (same order -- see
    `followup/HANDCHECK_BRIEF.md`'s output format)."""
    truth: Dict[Tuple[str, str], Dict[str, str]] = {}
    case_files = sorted(handcheck_dir.glob("hc*.json"))
    for case_file in case_files:
        n = case_file.stem[2:]  # "hc1" -> "1"
        result_file = handcheck_dir / f"hc{n}_result.csv"
        if not result_file.exists():
            continue
        cases = json.loads(case_file.read_text())
        with result_file.open(newline="", encoding="utf-8") as f:
            results = list(csv.DictReader(f))
        for case, result in zip(cases, results):
            if case.get("domain") != result.get("domain"):
                continue  # positional mismatch -- skip rather than misjoin
            key = (case["run"], case["domain"])
            truth[key] = result
    return truth


def _truth_is_found(verdict: str) -> Optional[bool]:
    if verdict == "approve":
        return True
    if verdict in ("other-gov", "not-a-meeting"):
        return False
    return None  # "cant-tell" -- excluded from strict agreement scoring


# --- Reporting -------------------------------------------------------


def print_stratum_summary(regraded: List[Dict[str, Any]], strata_by_run) -> None:
    print("\n## Summary by stratum (old vs. new find count, projected nationwide)\n")
    header = (
        f"{'run':<11} {'stratum':<24} {'sample':>7} {'old found':>10} "
        f"{'new found':>10} {'pool size':>10} {'old proj.':>10} {'new proj.':>10}"
    )
    print(header)
    print("-" * len(header))
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(
        lambda: {"sample": 0, "old_found": 0, "new_found": 0, "pool_size": None}
    )
    for row in regraded:
        key = (row["run"], row["stratum"])
        g = grouped[key]
        g["sample"] += 1
        if row["old_outcome_effective"] is None:
            g["old_found"] += 1
        if row["new_outcome"] is None:
            g["new_found"] += 1
        if row["pool_size"] is not None:
            g["pool_size"] = row["pool_size"]

    total_old = total_new = 0
    for (run, stratum), g in sorted(grouped.items()):
        pool_size = g["pool_size"]
        sample = g["sample"]
        old_proj = new_proj = None
        if pool_size and sample:
            old_proj = round(g["old_found"] / sample * pool_size)
            new_proj = round(g["new_found"] / sample * pool_size)
        total_old += g["old_found"]
        total_new += g["new_found"]
        print(
            f"{run:<11} {stratum:<24} {sample:>7} {g['old_found']:>10} "
            f"{g['new_found']:>10} {pool_size or '':>10} "
            f"{old_proj if old_proj is not None else '':>10} "
            f"{new_proj if new_proj is not None else '':>10}"
        )
    print("-" * len(header))
    print(
        f"Raw sample totals: {total_old} found under the old rule, "
        f"{total_new} found under the new WO-1041 rule "
        f"({total_old - total_new} demoted, out of {len(regraded)} rows checked)."
    )


def print_agreement_table(
    regraded: List[Dict[str, Any]], truth: Dict[Tuple[str, str], Dict[str, str]]
) -> None:
    if not truth:
        return
    print("\n## Agreement with the 95 hand-check verdicts\n")
    matched = []
    for row in regraded:
        key = (row["run"], row["input_url"])
        if key in truth:
            matched.append((row, truth[key]))

    print(
        f"Matched {len(matched)} of {len(truth)} hand-checked rows to a verdict row.\n"
    )

    # Confusion table: human verdict vs. this script's regrade (found /
    # not found), old rule alongside new rule.
    header = (
        f"{'human verdict':<16} {'count':>6} {'old: found':>11} "
        f"{'new: found':>11} {'old agrees':>11} {'new agrees':>11}"
    )
    print(header)
    print("-" * len(header))
    by_verdict: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "count": 0,
            "old_found": 0,
            "new_found": 0,
            "old_agree": 0,
            "new_agree": 0,
        }
    )
    for row, truth_row in matched:
        verdict = truth_row.get("verdict", "")
        truth_found = _truth_is_found(verdict)
        b = by_verdict[verdict]
        b["count"] += 1
        old_found = row["old_outcome_effective"] is None
        new_found = row["new_outcome"] is None
        if old_found:
            b["old_found"] += 1
        if new_found:
            b["new_found"] += 1
        if truth_found is not None:
            if old_found == truth_found:
                b["old_agree"] += 1
            if new_found == truth_found:
                b["new_agree"] += 1
    total_scoreable = 0
    total_old_agree = 0
    total_new_agree = 0
    for verdict, b in sorted(by_verdict.items()):
        print(
            f"{verdict:<16} {b['count']:>6} {b['old_found']:>11} {b['new_found']:>11} "
            f"{b['old_agree']:>11} {b['new_agree']:>11}"
        )
        if verdict != "cant-tell":
            total_scoreable += b["count"]
            total_old_agree += b["old_agree"]
            total_new_agree += b["new_agree"]
    print("-" * len(header))
    if total_scoreable:
        old_pct = round(100 * total_old_agree / total_scoreable)
        new_pct = round(100 * total_new_agree / total_scoreable)
        print(
            f"Agreement (excluding 'cant-tell'): old rule {total_old_agree}/"
            f"{total_scoreable} ({old_pct}%), new rule {total_new_agree}/"
            f"{total_scoreable} ({new_pct}%)."
        )


# --- Main ------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="a run name and its directory (containing verdicts.csv.jsonl "
        "and strata.csv), e.g. --run overnight=<path>/overnight. Repeatable.",
    )
    parser.add_argument("--out", required=True, type=Path, help="output CSV path")
    parser.add_argument(
        "--handcheck-dir",
        type=Path,
        default=None,
        help="directory with hc*.json/hc*_result.csv for the agreement table",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        default=None,
        help="JSON file to cache Vimeo/Drive title lookups across runs",
    )
    args = parser.parse_args()

    install_youtube_guard()

    runs: List[Tuple[str, Path]] = []
    for spec in args.run:
        name, _, path = spec.partition("=")
        if not path:
            parser.error(f"--run must be NAME=PATH, got {spec!r}")
        runs.append((name, Path(path)))

    fetcher = TitleFetcher(args.cache_file)
    regraded: List[Dict[str, Any]] = []

    try:
        for run_name, run_dir in runs:
            strata = load_strata(run_dir)
            verdicts = load_verdicts(run_dir)
            print(
                f"Regrading {len(verdicts)} rows from {run_name} ({run_dir})...",
                file=sys.stderr,
            )
            for i, row in enumerate(verdicts):
                stratum, pool_size = strata.get(row["input_url"], ("", None))
                result = await regrade_row(row, fetcher)
                regraded.append(
                    {
                        "run": run_name,
                        "input_url": row["input_url"],
                        "identity_expected_gov_id": row.get("identity_expected_gov_id"),
                        "stratum": stratum,
                        "pool_size": pool_size,
                        "platform": row.get("platform"),
                        "result_url": row.get("result_url"),
                        "duration_seconds": row.get("duration_seconds"),
                        "identity_verdict": row.get("identity_verdict"),
                        "identity_points_to": row.get("identity_points_to"),
                        "old_outcome_effective": row.get("outcome") or None,
                        "new_outcome": result.new_outcome,
                        "regrade_reason": result.reason,
                        "evidence_source": result.evidence_source,
                        "note": row.get("note"),
                    }
                )
                if (i + 1) % 200 == 0:
                    print(f"  ...{i + 1}/{len(verdicts)}", file=sys.stderr)
                    fetcher.save()
    finally:
        fetcher.save()
        await fetcher.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run",
        "input_url",
        "identity_expected_gov_id",
        "stratum",
        "pool_size",
        "platform",
        "result_url",
        "duration_seconds",
        "identity_verdict",
        "identity_points_to",
        "old_outcome_effective",
        "new_outcome",
        "regrade_reason",
        "evidence_source",
        "note",
    ]
    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in regraded:
            writer.writerow(row)
    print(f"\nWrote {len(regraded)} regraded rows to {args.out}")
    print(f"Title lookups made: {fetcher.fetch_count}")

    print_stratum_summary(regraded, None)

    if args.handcheck_dir:
        truth = load_handcheck_truth(args.handcheck_dir)
        print_agreement_table(regraded, truth)


if __name__ == "__main__":
    asyncio.run(main())
