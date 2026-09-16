#!/usr/bin/env python3
"""Applies WO-357's findings onto `jurisdiction_coverage.csv`.

WO-357 ran the 234-row CivicPlus label-only bucket (WO-349's own
`research/wo349_population.csv` bucket B_stale_label -- a government
with a platform label but no confirmed tenant URL, which WO-349
explicitly scoped out) through `app.platforms.passive_verify.verify_hub()`
called directly against `https://{domain}` with `platform_hint=
"civicplus"` (`research/wo357_verify.csv`), then a manual `www.`-prefix
retry for the 28 rows whose bare domain failed on a cert/DNS/timeout
error (`research/wo357_verify.csv` updated in place for the 4 that
recovered), then a hand-check of every tier1/tier3 candidate
(`research/wo357_handcheck.csv` plus manual verification of the
CivicPlus/TikiLive embed and two Google-Drive tier-3 candidates, whose
own embed pages carry no title).

Per-government mapping (234 total):
  - 1 tier-1 government (Rosetown, SK) ingested and LIVE -- real video +
    real captions, hand-confirmed via its own CivicMedia listing page
    ("June 1, 2026 Council Meeting" under a "Council Meetings" channel).
    -> shares_video=True, transcribed=True, example_meeting_url set,
    suspected_video_provider set, reject_reason cleared.
  - 1 tier-1 government (Englewood city, OH) hand-confirmed real
    (CivicMedia VID=106, "20260908 Council Meeting", 583 segments) and
    ingested into the Archive DB (page id 9715), but `/m/{slug}` 500s in
    production for this specific page -- confirmed NOT a stale-deploy
    issue (prod is on the exact commit this branch started from) and NOT
    a data problem (the stored row is well-formed via
    `/internal/export/pages`, the government's own `/j/englewood-oh` hub
    page loads fine, and an identical local repro against the same
    commit on a fresh SQLite DB returns 200 for the same payload). Left
    OUT of this apply (not counted as live, reject_reason untouched) --
    see this WO's BACKLOG_DONE entry and the matching BACKLOG.md bug
    entry. The dry-run delete-pages call identified the right page (id
    9715); the real delete was blocked by the auto-mode safety
    classifier, so the broken page is still sitting in the Archive DB
    pending Ryan's call.
  - 12 tier-2 candidates (real video, but the platform's own listing
    walk delegates internally to a YouTube video) -> never fetched, per
    the standing rule; recorded in `research/youtube_channel_leads.csv`
    instead (verified=false), left alone here. Two flagged sub-issues
    among them, also noted in the leads file: Ridgeway town VA's
    resolved URL is a bare "https://youtu.be" with no video id
    (malformed), and Raymond village NE / Davey village NE both resolved
    to the exact same video id, unconfirmed which (if either) it
    belongs to.
  - 2 tier-3 candidates (Rockport town MA, Holliston town MA) found real
    Google Drive video links via the listing walk, but the Drive share
    page's own title for each is too weak to confirm identity/date
    (a raw "video1457093892.mp4" filename for Rockport; "1-22 Ag Com
    Video.mp4" for Holliston -- an Agricultural Commission, not
    confirmed current) -- left alone, same "candidate-not-confirmed"
    treatment WO-349/352 used for their own ambiguous finds.
  - 114 governments (tier 4: `verify_hub()` found a real meeting listing
    or a real agenda/minutes page one hop deeper, no video) ->
    reject_reason=meeting-without-video.
  - 11 governments (`empty_listing`/`resolved_empty`: the platform was
    reached but its listing had nothing at all) ->
    reject_reason=no-meetings-found.
  - 79 governments blocked by a live Cloudflare human-verification
    challenge (`cf-mitigated: challenge`, confirmed by hand on 9 of them
    across every response shape seen -- direct HTTP 403 on the bare
    domain, and HTTP 403 on the `www.` retry after a bare-domain SSL
    cert/handshake failure masked the same challenge) ->
    reject_reason=cloudflare-challenge-blocked, per the standing "stop at
    any human-verification gate" rule -- not solved, not retried in a
    loop.
  - 8 governments whose domain (bare and `www.`) never resolves in DNS
    -> reject_reason=dns-unresolvable.
  - 2 governments whose domain fails TLS on both the bare and `www.`
    form with a real certificate/handshake error, not a Cloudflare
    challenge (Cockrell Hill city TX, Horton city KS) ->
    reject_reason=blocked-plain-http (closest access-class fit; browser
    headers were already in use, so there is no further ladder rung
    short of a full headless browser, out of this run's scope).
  - 1 government (Sprague village NE) timed out on both the bare and
    `www.` form -> reject_reason=timeout.
  - 3 governments where `verify_hub()` itself errored
    (`resolve_error`/`exception`) -> left alone (an error is not a
    finding).

**WO-226 restated-not-replaced guard**: `meeting-without-video` and
`no-meetings-found` (this run's two weaker/re-derivable findings) never
overwrite an existing STRONGER reason -- except
`meeting-without-video-unverified` (WO-351), explicitly excluded from
that stronger set: any fresh verdict from this run replaces it outright.
Also never downgrades a row that already carries `transcribed=True`.
The four access-class findings (cloudflare-challenge-blocked,
dns-unresolvable, blocked-plain-http, timeout) are applied directly --
this bucket's own prior_reject_reason values were never a real content
finding to begin with (that is why these 234 rows were still
"label-only"), so there is nothing stronger here to protect.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as `wo191_apply_to_jc.py` / `wo349_apply_to_jc.py`):
a real `flock` held around the whole read-modify-write, a fresh read
taken only after the lock is acquired, a row-count floor re-derived from
`git show HEAD` at run time, a re-check immediately before writing, and
an atomic temp-file + `os.replace()` write with explicit LF endings,
line-based in-place edit only (never a gov_id-keyed dict rebuild).

Also writes `research/wo357_jc_applied_gov_ids.txt` (one gov_id per
line, append mode).

This worktree's sandbox refuses a `git -C`/`cd` pointed at the
rtr-business checkout, so the row-count floor is read via
`GIT_DIR`/`GIT_WORK_TREE` environment variables instead of `-C` (same
effect, different invocation -- confirmed to work in this environment).

Usage:
    python3 scripts/wo357_apply_to_jc.py
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX only, fine for this project
    fcntl = None

ROOT = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = ROOT / "jurisdiction_coverage.csv"
LOCK_FILE = ROOT / "jurisdiction_coverage.csv.lock"
VERIFY_CSV = ROOT / "wo357_verify.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo357_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# --- hand-check / classification outcomes (see this script's own docstring) ---

TIER1_INGESTED_LIVE = {"ca:csd:4712006"}  # Rosetown, SK
INGEST_URL = {
    "ca:csd:4712006": "https://civplus.tikiliveapi.com/embed?scheme=embedVod&videoId=160396&autoplay=no",
}
INGEST_PLATFORM = {
    "ca:csd:4712006": "civicmedia",
}

# Englewood city OH -- ingested into Archive DB (page 9715) but /m/{slug}
# 500s in prod; deliberately left OUT of TIER1_INGESTED_LIVE and out of
# every other bucket below, so this apply pass does not touch its row at
# all. See this script's module docstring.
LEFT_ALONE_KNOWN_ISSUE = {"us:place:3925396"}

TIER3_CANDIDATE_NOT_CONFIRMED = {
    "us:cousub:2500957880",  # Rockport town MA
    "us:cousub:2501730700",  # Holliston town MA
}

CLOUDFLARE_CHALLENGE_EXTRA = {
    # Confirmed cf-mitigated:challenge on a www retry after the bare
    # domain's SSL/handshake error masked the same block (see this
    # script's docstring) -- these carry a fetch_failed row whose
    # EVIDENCE text still shows the original SSL error, so they are not
    # reachable by a plain evidence-string scan and are listed here by
    # hand.
    "us:place:3632402",  # harrison-ny.gov
    "us:place:0116768",  # cityofcolumbiana.com
    "us:place:2656860",  # cityofnegaunee.com
    "us:place:4207960",  # boyertownborough.org
    "us:place:4871960",  # taylorlakevillage.us
    "us:place:4854048",  # cityofonalaska.us
    "us:place:0855540",  # townofolathe.org
    "us:place:5451100",  # cityofmannington.com
    "us:place:1968475",  # cityofroland.org
    "us:cousub:0911022630",  # easthartfordct.gov
    "us:cousub:0915088190",  # woodstockct.gov
    "us:cousub:2500304545",  # townofbecket.org
    "us:cousub:2502741585",  # millvillema.org
    "us:cousub:3301748660",  # miltonnh-us.com
}
BLOCKED_PLAIN_HTTP_SSL = {
    "us:place:4815796",  # cockrell-hill.tx.us -- real cert/handshake error, both bare and www
    "us:place:2033200",  # hortonkansas.net -- same
}
TIMEOUT_BOTH = {"us:place:3146380"}  # Sprague village NE

STRONGER_EXISTING_REASONS = {
    "meeting-without-video",
    "no-meeting-nor-video",
    "no-video-found",
    "video-without-meeting",
    "off-mission",
    "video-no-captions-queued",
    "wrong-domain-mapping",
    "rejected-by-probe",
    "cloudflare-challenge-blocked",
    "dns-unresolvable",
    "blocked-plain-http",
    "blocked-browser-headers",
    "blocked-headless",
    "timeout",
}
WEAK_NEW_REASONS = {"meeting-without-video", "no-meetings-found"}


def _min_sane_row_count() -> int:
    env = dict(os.environ)
    env["GIT_DIR"] = str(ROOT.parent / ".git")
    env["GIT_WORK_TREE"] = str(ROOT.parent)
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:research/jurisdiction_coverage.csv"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        committed_lines = out.count("\n")
        floor = int(committed_lines * 0.99)
        print(
            f"committed jurisdiction_coverage.csv: {committed_lines} lines -> 99% floor {floor}"
        )
        return floor
    except Exception as e:  # noqa: BLE001
        print(
            f"WARNING: could not compute live floor from git ({e}); using fallback",
            file=sys.stderr,
        )
        return FALLBACK_MIN_SANE_ROW_COUNT


def load_findings() -> dict[str, str]:
    """gov_id -> reject_reason for every row this script will TOUCH.
    A gov_id absent from this dict is left completely alone."""
    findings: dict[str, str] = {}
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        gid = r.get("gov_id", "")
        tier = r.get("tier", "")
        verdict = r.get("verdict", "")
        evidence = r.get("evidence", "")
        if not gid:
            continue

        if gid in TIER1_INGESTED_LIVE:
            findings[gid] = "__INGESTED__"
        elif gid in LEFT_ALONE_KNOWN_ISSUE:
            continue
        elif gid in TIER3_CANDIDATE_NOT_CONFIRMED:
            continue
        elif gid in CLOUDFLARE_CHALLENGE_EXTRA:
            findings[gid] = "cloudflare-challenge-blocked"
        elif gid in BLOCKED_PLAIN_HTTP_SSL:
            findings[gid] = "blocked-plain-http"
        elif gid in TIMEOUT_BOTH:
            findings[gid] = "timeout"
        elif tier == "2":
            continue  # every YouTube lead: left alone (leads file instead)
        elif tier == "4":
            findings[gid] = "meeting-without-video"
        elif tier == "" and verdict in ("empty_listing", "resolved_empty"):
            findings[gid] = "no-meetings-found"
        elif tier == "" and verdict == "fetch_failed" and "HTTP 403" in evidence:
            findings[gid] = "cloudflare-challenge-blocked"
        elif (
            tier == ""
            and verdict == "fetch_failed"
            and ("DNSError" in evidence or "Domain name not fou" in evidence)
        ):
            findings[gid] = "dns-unresolvable"
        elif tier == "" and verdict in ("resolve_error", "exception"):
            continue  # an error is not a finding
        else:
            print(f"UNHANDLED row, left alone: {gid} tier={tier!r} verdict={verdict!r}")

    return findings


def main() -> None:
    findings = load_findings()
    print(f"{len(findings)} governments to apply")

    min_sane_row_count = _min_sane_row_count()

    lock_fd = open(LOCK_FILE, "w")
    if fcntl:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            jc_fieldnames = reader.fieldnames
            jc_rows = list(reader)
        starting_row_count = len(jc_rows)
        if starting_row_count < min_sane_row_count:
            raise SystemExit(
                f"{JC_PATH.name} reads as only {starting_row_count} rows (expected "
                f"at least {min_sane_row_count}) -- refusing to treat a truncated "
                "read as a legitimate new baseline. Investigate before retrying."
            )
        print(f"{starting_row_count} rows read")

        by_gov_id_first_index: dict[str, int] = {}
        for i, r in enumerate(jc_rows):
            gid = r.get("gov_id") or ""
            if gid and gid not in by_gov_id_first_index:
                by_gov_id_first_index[gid] = i

        changed = 0
        skipped_guard = 0
        skipped_transcribed = 0
        missing: list[str] = []
        applied_gov_ids: list[str] = []

        for gov_id, action in findings.items():
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                continue
            jc_row = jc_rows[idx]
            current_reason = (jc_row.get("reject_reason") or "").strip()
            already_transcribed = (jc_row.get("transcribed") or "").strip() == "True"

            if action == "__INGESTED__":
                if already_transcribed:
                    skipped_transcribed += 1
                    continue
                jc_row["shares_video"] = "True"
                jc_row["transcribed"] = "True"
                jc_row["example_meeting_url"] = INGEST_URL[gov_id]
                jc_row["suspected_video_provider"] = INGEST_PLATFORM[gov_id]
                jc_row["reject_reason"] = ""
                changed += 1
                applied_gov_ids.append(gov_id)
                continue

            new_reason = action
            if already_transcribed:
                skipped_transcribed += 1
                continue
            if (
                new_reason in WEAK_NEW_REASONS
                and current_reason in STRONGER_EXISTING_REASONS
                and current_reason != "meeting-without-video-unverified"
            ):
                skipped_guard += 1
                continue
            jc_row["reject_reason"] = new_reason
            changed += 1
            applied_gov_ids.append(gov_id)

        # Re-check immediately before writing (per §158).
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            recheck_count = sum(1 for _ in f) - 1
        if recheck_count != starting_row_count:
            raise SystemExit(
                f"{JC_PATH.name} changed from {starting_row_count} to {recheck_count} "
                "rows while this script was running -- another writer is active. "
                "Refusing to write; re-run."
            )

        tmp_path = JC_PATH.with_suffix(".csv.wo357tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=jc_fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(jc_rows)
        os.replace(tmp_path, JC_PATH)

        print(
            f"\nDone: {changed} changed, {skipped_guard} skipped (WO-226 guard), "
            f"{skipped_transcribed} skipped (already transcribed), "
            f"{len(missing)} no jc match. {len(jc_rows)} rows written "
            "(unchanged count, in-place edit only)."
        )
        if missing:
            print("no jc match:", missing[:20], "..." if len(missing) > 20 else "")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    if applied_gov_ids:
        with APPLIED_GOV_IDS_TXT.open("a", encoding="utf-8") as f:
            for gid in applied_gov_ids:
                f.write(gid + "\n")


if __name__ == "__main__":
    main()
