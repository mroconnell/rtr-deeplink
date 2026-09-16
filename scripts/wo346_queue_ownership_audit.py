"""WO-346: audits every line of the tier-3 queue and the long-meetings
deferred file for a missing owner, using the SAME pin/registry lookup
`archive/db/crud.py::_resolve_page_government()` (the feed script's and
the worker's own re-resolve at ingest time) actually uses.

Why this is a separate read-only audit script, not a bulk-pin writer:
`BACKLOG.md`'s "Check the full tier-3 queue file for real videos with no
`tenant_overrides.csv` owner recorded" entry (history: WO-345, PR #1134)
says so explicitly -- a missing pin needs a real government match, not a
guess.

What "owner" means here, and why the LINE'S OWN URL is what gets
checked (not a `source_url` override, when one is present as a second
tab-separated field): `app/platforms/youtube.py::resolve_video_id()`
(and the other single-video finders) set `ResolvedMeeting.source_url` to
the URL that was actually resolved, unless a queue line's second field
overrides it purely for display -- the video's OWN host is what
`_resolve_page_government()` parses the tenant host from, because that
override is applied to `result.source_url` (see `scripts/
feed_tier3_auto_transcription.py::_push_if_has_video()`), which then
IS what `_resolve_page_government()` reads. So the identity-bearing host
is always the queued URL's own host; the second field is cosmetic
provenance for display, not identity.

Classification, one line at a time:

  (a) owned by a pin -- the line's host is in `registry.MULTI_GOV_HOSTS`
      (a hosting platform shared by many unrelated governments -- see
      that constant's own docstring) AND a `tenant_overrides.csv` row's
      `match` discriminator (a bare video id, `channel=@handle`, or a
      `key=value` pair) is found in the URL's own path+query --
      `app/utils/gov_registry/resolver.py::_matched_multi_gov_pin()`,
      the exact function rung 1b of `_resolve_government_ladder()`
      calls. This never needs `page_hints` built from a live fetch: a
      per-video/query-keyed pin's needle already has to appear in the
      URL text itself to fire (a `channel=` pin on a bare per-video URL
      with no channel info in the URL literally cannot be confirmed this
      way -- those are left as "no owner" here rather than guessed, and
      called out separately).
  (b) owned by the registry alone -- the line's host is NOT in
      `MULTI_GOV_HOSTS`. Every platform adapter in this repo (Granicus,
      CivicClerk, eScribe, Legistar, Swagit, most Cablecast/TelVue
      subdomains) gives each government its own tenant subdomain, so a
      host that curation has NOT flagged as shared resolves to exactly
      one government by construction once ingested (tenant-host lookup /
      dominant-gov consistency, never a per-video pin) -- the same
      "confirmed, not guessed" discipline that keeps `MULTI_GOV_HOSTS`
      itself a literal, curated set rather than a suffix/wildcard rule
      (see that constant's own comment). This is the registry doing the
      owning, not this script asserting it; a WRONG single-tenant
      assumption would be a `MULTI_GOV_HOSTS` gap, not an ownership gap,
      and is out of this WO's scope (flagged separately if found).
  (c) no owner -- host IS in `MULTI_GOV_HOSTS` and no pin's discriminator
      is found in the URL.

For every (c) line, cross-references committed evidence already on file
(`research/wo*_report.csv` / `wo*_tier3_pending.csv` / `wo*_jc_queued*.
csv` rows whose URL column names this exact line's URL and carries a
gov_id; `jurisdiction_coverage.csv` rows whose `example_meeting_url` or
`alternate_urls` match) and writes a real `tenant_overrides.csv` pin
(per-video, `strength=fallback`, `source=wo346`) ONLY when a row gives an
exact URL match with a real gov_id. Everything else is listed for a hand
read -- this never guesses and never fetches YouTube/Vimeo/etc.

Usage:
    python3 scripts/wo346_queue_ownership_audit.py
"""

from __future__ import annotations

import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import registry  # noqa: E402
from app.utils.gov_registry.resolver import (  # noqa: E402
    _matched_multi_gov_pin,
    _match_override,
    _tenant_host,
)

QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"

RESEARCH_DIR = Path(os.path.expanduser("~/Documents/rtr-business/research"))
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"

OUT_DIR = REPO_ROOT / "scripts"
REPORT_CSV = OUT_DIR / "wo346_ownership_audit.csv"
HAND_READ_CSV = OUT_DIR / "wo346_hand_read.csv"

GOV_ID_COL_RE = re.compile(r"^gov_?id$", re.IGNORECASE)

# Only a column whose value is genuinely the CONFIRMED target URL, never a
# seed/candidate/tried/superseded one -- checked live against wo190_
# report.csv (2026-09-13): `url_used` alone matched 257 queue lines, but
# 104 of those rows had outcome=ingested_tier1_2 and 27 had outcome=
# skipped -- i.e. `url_used` is the SWEEP'S STARTING url, not necessarily
# what the row's gov_id actually owns. `hit_url`/`meeting_url`/`video_url`
# carry the same false-positive risk from `skipped` (119 rows) and
# `rejected_by_probe` (2 rows) -- caught by the OUTCOME filter below, not
# by column choice alone. Excluded on purpose: `url_used`, `url_tried`,
# `url_examined`, `seed_url`, `start_url`, `hop_url(s)`, `answering_url`
# (a probe target, not a confirmed owner), `video_candidate_urls`
# (candidates, not a decision), `replacement_url`/`url_used_stale`
# (superseded), `channel_url`/`channel_lead_url` (a channel is not a
# specific video), `best_url`/`evidence_url`/`platform_evidence_url`
# (too ambiguous across 163 differently-shaped files to trust blindly).
SAFE_URL_COLS = {
    "hit_url",
    "meeting_url",
    "video_url",
    "ingested_url",
    "chosen_video_url",
    "meeting_url_written",
    "media_url",
    "caption_url",
    "final_url",
    "real_hub_url",
    "example_meeting_url",
}

# When a file has one of these columns, a row is trusted ONLY if its value
# says the URL was actually queued/ingested for this gov_id -- never a
# row whose own outcome/status/reject_reason says the candidate was
# skipped, rejected, or merely already covered by something else.
OUTCOME_COLS = ("outcome", "status")
SAFE_OUTCOME_MARKERS = (
    "queued_tier3",
    "duplicate_queued",
    "ingested",
    "confirmed",
    "applied",
    "queued",
)
UNSAFE_OUTCOME_MARKERS = (
    "skip",
    "reject",
    "already_covered",
    "candidate",
    "pending",
    "stale",
    "failed",
    "unresolved",
    "unsupported",
    "off_mission",
    "blocked",
    "cloudflare",
    "dns_unresolvable",
    "timeout",
    "no_video",
    "no_meeting",
    "no_platform",
    "wrong_domain",
    "no_domain",
    "shared_gov_exception",
    "deferred",
)


def parse_queue_line(line: str) -> tuple[str, Optional[str]]:
    url, _, source_url = line.partition("\t")
    return url.strip(), (source_url.strip() or None)


def parse_deferred_line(line: str) -> dict:
    parts = line.rstrip("\n").split("\t")
    parts += [""] * (6 - len(parts))
    return {
        "url": parts[0].strip(),
        "source_url": parts[1].strip(),
        "gov_id": parts[2].strip(),
        "jurisdiction": parts[3].strip(),
        "duration": parts[4].strip(),
        "title": parts[5].strip(),
    }


def host_path_query(url: str) -> tuple[str, str]:
    p = urlparse(url)
    host = _tenant_host(p.netloc)
    path = p.path + (f"?{p.query}" if p.query else "")
    return host, path


def classify_line(url: str) -> dict:
    """Returns a dict describing ownership for one queued URL."""
    host, path = host_path_query(url)
    if not host:
        return {
            "kind": "no-owner",
            "detail": "unparseable host",
            "host": "",
        }
    multi_gov = registry.is_multi_gov_host(host)
    if not multi_gov:
        return {
            "kind": "registry",
            "detail": "not in MULTI_GOV_HOSTS -- single-tenant vendor host",
            "host": host,
        }
    matched = _matched_multi_gov_pin(host, path, {})
    if matched:
        gov, evidence = matched
        # Which row matched, for the pin-kind breakdown -- re-derive strength
        # and match shape from the same lookup rather than a second pass.
        rows = _match_override(host, path, {})
        row = rows[0] if rows else None
        return {
            "kind": "pin",
            "detail": evidence,
            "host": host,
            "gov_id": gov.gov_id,
            "strength": row.strength if row else "",
            "match": row.match if row else "",
            "source": row.source if row else "",
        }
    return {
        "kind": "no-owner",
        "detail": f"{host} is a MULTI_GOV_HOSTS host with no matching pin",
        "host": host,
    }


def _value_is_safe(val: str) -> bool:
    """A single outcome/status/reject_reason value is trusted only when it
    contains a SAFE_OUTCOME_MARKERS term and no UNSAFE_OUTCOME_MARKERS
    term -- allowlist, not denylist, since `jurisdiction_coverage.csv`'s
    `reject_reason` is a closed, enumerated vocabulary (CLAUDE.md's §23
    taxonomy) and an unrecognized value should never be guessed safe.
    Checked live against jurisdiction_coverage.csv (2026-09-13): 54 rows
    with a real gov_id and a real example_meeting_url/alternate_urls carry
    `reject_reason=wrong-domain-mapping` -- the exact Melvern/Osage County
    shape CLAUDE.md's platform-wrapper bullet and WO-345's own apply
    script describe, where the URL genuinely belongs to a DIFFERENT
    government than the row names. An empty value is safe (no verdict
    recorded at all is not evidence of anything wrong)."""
    if not val:
        return True
    if any(m in val for m in UNSAFE_OUTCOME_MARKERS):
        return False
    return any(m in val for m in SAFE_OUTCOME_MARKERS)


def _row_outcome_is_safe(row: dict) -> bool:
    """False when any of this row's outcome/status/reject_reason columns
    holds a value `_value_is_safe()` doesn't trust."""
    for col in OUTCOME_COLS + ("reject_reason",):
        val = (row.get(col) or "").strip().lower().replace("-", "_")
        if not _value_is_safe(val):
            return False
    return True


def load_evidence_index() -> dict[str, tuple[str, str]]:
    """Scans every research/wo*_report.csv / wo*_tier3_pending.csv /
    wo*_jc_queued*.csv for a SAFE_URL_COLS column + a gov_id column,
    building {url: (gov_id, source_file)}. Exact URL string match only --
    no normalization guess. Skips a row whose own outcome/status/
    reject_reason says the candidate was skipped, rejected, or already
    covered elsewhere -- a URL string can survive in one of those columns
    even when the row was a reject (confirmed live: wo190_report.csv had
    2 `rejected_by_probe`/`meeting-without-video` rows whose `hit_url`
    still carried a real-looking URL)."""
    index: dict[str, tuple[str, str]] = {}
    patterns = [
        "wo*_report.csv",
        "wo*_tier3_pending*.csv",
        "wo*_jc_queued*.csv",
    ]
    seen_files = set()
    for pat in patterns:
        for path_str in glob.glob(str(RESEARCH_DIR / pat)):
            seen_files.add(path_str)
    for path_str in sorted(seen_files):
        path = Path(path_str)
        try:
            with open(path, newline="", encoding="utf-8") as f:
                lines = [ln for ln in f if not ln.lstrip().startswith("#")]
                if not lines:
                    continue
                reader = csv.DictReader(lines)
                if not reader.fieldnames:
                    continue
                url_cols = [c for c in reader.fieldnames if c in SAFE_URL_COLS]
                gov_cols = [c for c in reader.fieldnames if GOV_ID_COL_RE.match(c)]
                if not url_cols or not gov_cols:
                    continue
                gov_col = gov_cols[0]
                for row in reader:
                    gov_id = (row.get(gov_col) or "").strip()
                    if not gov_id:
                        continue
                    if not _row_outcome_is_safe(row):
                        continue
                    for uc in url_cols:
                        u = (row.get(uc) or "").strip()
                        if u and u not in index:
                            index[u] = (gov_id, path.name)
        except Exception as e:
            print(f"[WARN] failed to read {path}: {e}", file=sys.stderr)
    return index


def load_jc_index() -> dict[str, tuple[str, str]]:
    """{url: (gov_id, 'jurisdiction_coverage.csv')} from example_meeting_url
    and alternate_urls (pipe- or comma- separated -- checked as literal
    substrings since the exact separator convention varies by row).
    Skips any row whose `reject_reason` isn't trusted by `_value_is_safe()`
    -- see that function's own docstring for the real 54-row
    `wrong-domain-mapping` incident this guards against; those rows have
    a real gov_id AND a real URL, just not for each other."""
    index: dict[str, tuple[str, str]] = {}
    if not JC_CSV.exists():
        return index
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gov_id = (row.get("gov_id") or "").strip()
            if not gov_id:
                continue
            reject_reason = (
                (row.get("reject_reason") or "").strip().lower().replace("-", "_")
            )
            if not _value_is_safe(reject_reason):
                continue
            candidates = []
            emu = (row.get("example_meeting_url") or "").strip()
            if emu:
                candidates.append(emu)
            alt = (row.get("alternate_urls") or "").strip()
            if alt:
                for sep in ("|", ";", ","):
                    if sep in alt:
                        candidates.extend(a.strip() for a in alt.split(sep))
                        break
                else:
                    candidates.append(alt)
            for u in candidates:
                if u and u not in index:
                    index[u] = (gov_id, "jurisdiction_coverage.csv")
    return index


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="Append the evidence-backed pins to tenant_overrides.csv. "
        "Without this flag, the run is report-only (CSVs written, "
        "tenant_overrides.csv untouched) -- default, so a run can always "
        "be reviewed before it changes the tracked pins file.",
    )
    args = parser.parse_args()

    evidence = load_evidence_index()
    jc_evidence = load_jc_index()
    print(
        f"Evidence index: {len(evidence)} URLs from wo*_report/tier3_pending/"
        f"jc_queued files, {len(jc_evidence)} URLs from jurisdiction_coverage.csv"
    )

    rows_out = []
    hand_read = []
    pins_to_write = []

    counts_by_kind = Counter()
    counts_by_kind_platform = defaultdict(Counter)

    def platform_of(host: str) -> str:
        # Coarse platform label from host, for the by-platform table --
        # not app.platforms.detect_platform() (that needs a full URL
        # shape check and network-shaped assumptions this audit doesn't
        # want to depend on); host alone is enough to bucket for reporting.
        h = host.lower()
        if "youtube" in h or h == "youtu.be":
            return "youtube"
        if "vimeo" in h:
            return "vimeo"
        if "civicclerk" in h:
            return "civicclerk"
        if "granicus" in h:
            return "granicus"
        if "escribemeetings" in h:
            return "escribe"
        if "legistar" in h:
            return "legistar"
        if "iqm2" in h:
            return "iqm2"
        if "cablecast" in h:
            return "cablecast"
        if "telvue" in h:
            return "telvue"
        if "swagit" in h:
            return "swagit"
        if "townhallstreams" in h:
            return "townhallstreams"
        if "castus" in h:
            return "castus"
        if "wistia" in h:
            return "wistia"
        if "clerkshq" in h or "clerkbase" in h:
            return "clerkshq"
        return h or "(unparseable)"

    def audit_url(url: str, source_file: str, extra: dict) -> None:
        cls = classify_line(url)
        host = cls.get("host", "")
        plat = platform_of(host)
        counts_by_kind[cls["kind"]] += 1
        counts_by_kind_platform[plat][cls["kind"]] += 1

        out_row = {
            "file": source_file,
            "url": url,
            "host": host,
            "platform": plat,
            "kind": cls["kind"],
            "detail": cls["detail"],
            "gov_id": cls.get("gov_id", ""),
            **extra,
        }
        rows_out.append(out_row)

        if cls["kind"] != "no-owner":
            return

        report_ev = evidence.get(url)
        jc_ev = jc_evidence.get(url)
        if report_ev and jc_ev and report_ev[0] != jc_ev[0]:
            # The two evidence sources disagree on who owns this URL --
            # confirmed live 2026-09-13, 9 real cases (e.g. a wo183_
            # report.csv row says one township for a YouTube video while
            # jurisdiction_coverage.csv's alternate_urls attaches the same
            # URL string to an unrelated state agency). Never silently
            # pick one; hand-read it.
            out_row["evidence_conflict"] = (
                f"report={report_ev[0]} ({report_ev[1]}) vs "
                f"jc={jc_ev[0]} (jurisdiction_coverage.csv)"
            )
            hand_read.append(out_row)
            return
        ev = report_ev or jc_ev
        if not ev:
            hand_read.append(out_row)
            return
        gov_id, ev_source = ev
        gov = registry.government_for_id(gov_id)
        if not gov:
            # A gov_id named in evidence with no governments.csv row is not
            # a usable pin target -- same broken-registry guard resolver.py
            # itself applies. Hand-read it.
            out_row["evidence_gov_id_unresolvable"] = gov_id
            hand_read.append(out_row)
            return
        pins_to_write.append(
            {
                "tenant_host": host,
                "match": _video_or_path_match(url, host),
                "gov_id": gov_id,
                "strength": "fallback",
                "source": "wo346",
                "evidence": f"tier3 queue ownership audit, WO-346 -- matched {url} "
                f"via {ev_source} ({gov.gov_name}, {gov.gov_type})",
            }
        )
        out_row["kind"] = "pin-added"
        out_row["gov_id"] = gov_id
        out_row["detail"] = f"owner found via {ev_source}"

    # --- queue file ---
    if QUEUE_FILE.exists():
        for line in QUEUE_FILE.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            url, source_override = parse_queue_line(line)
            audit_url(
                url,
                "tier3_auto_transcription_queue.txt",
                {"source_url_override": source_override or ""},
            )

    # --- deferred file ---
    if DEFERRED_FILE.exists():
        for line in DEFERRED_FILE.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            d = parse_deferred_line(line)
            if d["gov_id"]:
                # Already carries an owner recorded by an earlier WO --
                # counted separately, not run through the pin ladder.
                counts_by_kind["deferred-file-gov-id"] += 1
                host, _ = host_path_query(d["url"])
                plat = platform_of(host)
                counts_by_kind_platform[plat]["deferred-file-gov-id"] += 1
                rows_out.append(
                    {
                        "file": "tier3_long_meetings_deferred.txt",
                        "url": d["url"],
                        "host": host,
                        "platform": plat,
                        "kind": "deferred-file-gov-id",
                        "detail": "gov_id already recorded in the deferred file",
                        "gov_id": d["gov_id"],
                        "source_url_override": d["source_url"],
                    }
                )
                continue
            audit_url(
                d["url"],
                "tier3_long_meetings_deferred.txt",
                {"source_url_override": d["source_url"]},
            )

    # --- write outputs ---
    fieldnames = [
        "file",
        "url",
        "host",
        "platform",
        "kind",
        "detail",
        "gov_id",
        "source_url_override",
        "strength",
        "match",
        "source",
        "evidence_gov_id_unresolvable",
        "evidence_conflict",
    ]
    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows_out:
            w.writerow(r)

    with open(HAND_READ_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in hand_read:
            w.writerow(r)

    print("\n=== Ownership by kind ===")
    for kind, n in counts_by_kind.most_common():
        print(f"{kind}: {n}")

    print("\n=== By platform x kind ===")
    for plat in sorted(counts_by_kind_platform):
        kinds = counts_by_kind_platform[plat]
        total = sum(kinds.values())
        parts = ", ".join(f"{k}={v}" for k, v in kinds.most_common())
        print(f"{plat} (n={total}): {parts}")

    print(f"\nPins found from evidence: {len(pins_to_write)}")
    print(f"Left for hand-read: {len(hand_read)}")
    print(f"\nFull report: {REPORT_CSV}")
    print(f"Hand-read list: {HAND_READ_CSV}")

    if pins_to_write:
        if args.write:
            write_pins(pins_to_write)
        else:
            print(
                f"\n[DRY RUN] {len(pins_to_write)} pin(s) would be written -- "
                "rerun with --write to append them to tenant_overrides.csv."
            )


def _video_or_path_match(url: str, host: str) -> str:
    """Best-effort per-video match discriminator for a new pin -- the bare
    YouTube 11-char id, the Vimeo numeric id, or (for anything else) the
    path itself, matching the shapes CLAUDE.md's pin-format bullet
    describes."""
    p = urlparse(url)
    if host in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        qs = p.query
        m = re.search(r"(?:^|&)v=([\w-]{11})", qs)
        if m:
            return m.group(1)
        m = re.search(r"/(?:embed|live|shorts)/([\w-]{11})", p.path)
        if m:
            return m.group(1)
    if host == "youtu.be":
        return p.path.strip("/").split("/")[0][:11]
    if "vimeo.com" in host:
        m = re.search(r"/(\d+)", p.path)
        if m:
            return m.group(1)
    # Fallback: path+query as the discriminator (e.g. a Cablecast site= or
    # a Castus tenant-slug path segment).
    return (p.path + (f"?{p.query}" if p.query else "")).lstrip("/")


def write_pins(pins: list[dict]) -> None:
    path = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        for pin in pins:
            w.writerow(
                [
                    pin["tenant_host"],
                    pin["match"],
                    pin["gov_id"],
                    pin["strength"],
                    pin["source"],
                    pin["evidence"],
                ]
            )
    print(f"Appended {len(pins)} new pin(s) to {path}")


if __name__ == "__main__":
    main()
