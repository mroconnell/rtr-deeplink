#!/usr/bin/env python3
"""WO-274 (2026-09-12): re-derive `find_hop_links()`'s scoring vocabulary
from measured data instead of the hand-picked `HOP1_HINT_WORDS` list.

Why (Ryan, 2026-09-12): the conductor measured the old 12-word list
against real data and found it backwards -- "calendar" and singular
"agenda" are near noise on a government's own homepage (lift 2-4x vs
ordinary links), "video"/"stream" almost never appear on a hub page at
all, while the plural/role words the list lacks are the strongest
signal (agendas, meetings, commissioners, supervisors, boards) and named
platform paths are near-perfect (AgendaCenter, Hyland's
ViewMeeting/AgendaOnline). See `docs/investigations/hop_scorer_measurement.md`
for the full writeup and `CLAUDE.md`'s WO-274 entry.

This script re-derives that measurement from data already on disk (no
network fetches) and writes `app/utils/jurisdiction_data/hop_link_weights.csv`,
the data file `scripts/wo147_access_ladder_sweep.py`'s scorer reads at
import time.

Inputs (all read-only, all already on disk from WO-267):
  - `~/Documents/rtr-business/research/jurisdiction_coverage.csv`
    (transcribed=true rows: `example_agenda_or_calendar_url` -> "hub"
    positives, `example_meeting_url` -> "meeting" positives), split into
    first-party (government's own domain) and vendor-host groups.
  - `<scratchpad>/archive_source_urls.csv` (8,483 real Archive page
    source URLs) and `scripts/tier3_auto_transcription_queue.txt`
    (2,259 real queued meeting URLs) -- both overwhelmingly vendor-host,
    used as the "meeting_vendor" positive set.
  - Every saved real HTML page from WO-267's homepage/hub/negative
    fetches (`<scratchpad>/agents/<wo267 agent id>/wo267_raw/*.html` and
    `wo267_raw_neg/*.html`) -- every outbound `<a href>` on these pages,
    MINUS any link that is itself one of the positive URLs above, is the
    "ordinary link" negative pool.

Method: tokenize each URL's path (split on non-letters) and its query
STRING NAMES (not values); compute, per token and per adjacent-token
bigram, how often it appears in a positive URL vs. an ordinary negative
link (+0.5 smoothing, `weight = log(lift)` capped at +/-WEIGHT_CAP,
support floor `MIN_SUPPORT` positive occurrences or the row is dropped
from the output -- an absent token/bigram scores 0 at runtime). Anchor
TEXT words are scored the same way, but only for links whose href
matches a known first-party hub URL (a small, explicitly-flagged sample
-- see the printed summary and the doc).

Run: `.venv/bin/python scripts/derive_hop_weights.py` from the repo
root. Prints every table this WO's investigation doc reproduces, then
writes the CSV.
"""

from __future__ import annotations

import csv
import glob
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "hop_link_weights.csv"

JC_PATH = Path(
    os.path.expanduser("~/Documents/rtr-business/research/jurisdiction_coverage.csv")
)
TIER3_QUEUE_PATH = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

# These two live under the shared session scratchpad, not the repo --
# read-only inputs named in this WO's brief. Overridable via env vars so
# the script still runs (on an empty/zero measurement) outside the
# session that produced them.
SCRATCH_ROOT = os.environ.get(
    "WO274_SCRATCH_ROOT",
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink"
    "--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad",
)
WO267_AGENT_DIR = os.environ.get(
    "WO274_WO267_AGENT_DIR",
    f"{SCRATCH_ROOT}/agents/abaffb34ff89f89c7",
)
ARCHIVE_SOURCE_URLS_CSV = os.environ.get(
    "WO274_ARCHIVE_SOURCE_URLS_CSV",
    f"{SCRATCH_ROOT}/archive_source_urls.csv",
)

MIN_SUPPORT = 10  # positive occurrences required before a token/bigram is trusted
MIN_SUPPORT_ANCHOR = 5  # anchor-text sample is much smaller (~35 matches) -- see doc
WEIGHT_CAP = (
    7.0  # ln(1096) ~= 7.0 -- generous enough for agendacenter/viewmeeting-scale lifts
)

# Same vendor-host substrings `_is_vendor_marketing_apex()` in
# wo147_access_ladder_sweep.py already treats as "not this government's
# own domain" (imported by name below), plus a few more real vendor
# hosts seen in archive_source_urls.csv/the tier-3 queue that script's
# own list doesn't need (it only guards against a marketing-apex FALSE
# POSITIVE, not a general first-party/vendor split).
sys.path.insert(0, str(REPO_ROOT))
from scripts.wo147_access_ladder_sweep import _VENDOR_MARKETING_APEX  # noqa: E402

VENDOR_HOST_SUBSTRINGS = set(_VENDOR_MARKETING_APEX) | {
    "destinyhosted.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "wistia.com",
    "wistia.net",
    "hylandcloud.com",
    "databankcloud.com",
    "suiteonemedia.com",
    "viebit.com",
    "townhallstreams.com",
    "boxcast.tv",
    "castus.tv",
    "proudcity.com",
    "invintus.com",
    "legistar.council.nyc.gov",
    "chicityclerkelms.chicago.gov",
    # NOT included: meetings.municode.com. Real regression caught
    # measuring this WO's own 180-homepage comparison (Eustis FL):
    # `meetings.municode.com/adaHtmlDocument/...` is an ADA-accessible
    # MIRROR of a meeting entry already reachable at
    # `<tenant>.municodemeetings.com/bc-.../page/...` on the tenant's own
    # domain -- treating it as "a different platform found" outranked
    # the tenant's own real, better-shaped listing entries. Not measured
    # data to begin with (a guess added while writing this list), and
    # demonstrably wrong once measured against a real page.
}


def is_vendor_host(netloc: str) -> bool:
    n = (netloc or "").lower()
    if n.startswith("www."):
        n = n[4:]
    return any(h in n for h in VENDOR_HOST_SUBSTRINGS)


def norm_url_key(url: str) -> str:
    """Normalizes a URL for positive/negative de-duplication: lowercase
    host without www, path without a trailing slash, query dropped (a
    same-page anchor differing only in query noise is still "the same
    link" for this purpose)."""
    try:
        p = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return url.strip().lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    return f"{host}{path}".lower()


_TOKEN_SPLIT_RE = re.compile(r"[a-z]+")

# Generic calendar/notification-WIDGET query-param names and page-type
# words -- excluded from tokenization entirely, never scored either
# direction. Real, confirmed contamination found building this table
# (WO-274, 2026-09-12): `jurisdiction_coverage.csv`'s own recorded
# `example_agenda_or_calendar_url` is not always a real meeting hub --
# some rows still carry a bare calendar list-view or a CivicPlus
# "CivicAlerts" news-board page, a residual of the exact WO-228 bug this
# WO's own module comment describes ("358 governments ... a calendar-
# shaped hub as a direct result"): the OLD scorer found and got accepted
# a calendar shell for some governments before WO-228 shipped, and the
# research file was never swept to correct those rows afterward. Their
# query params (`day=`, `month=`, `year=`, `CID=`, `AID=`) leaked into
# the HUB positive set as if they were real signal, and confirmed live
# in this WO's own regression tests: it ranked Madison County TN's bare
# `calendar.aspx?...CID=...` list view above its own real dated
# committee entries, and a Cleveland County OK CivicAlerts.aspx PRESS
# RELEASE (`AID=122`, "Board of County Commissioners Response to Call
# for Special Election" -- a news item, not a meeting) above the
# government's real Legistar link, purely on these tokens. Stoplisted
# rather than hand-reintroducing a word list, since the fix is "this
# specific measured contamination," not "second-guess the method."
_STOPWORD_TOKENS = {
    "day",
    "month",
    "year",
    "cid",
    "aid",
    "tid",
    "view",
    "list",
    "civicalerts",
}


def tokenize_url(url: str) -> list[str]:
    """Splits the path on non-letters, plus query-string NAMES (not
    values, so `?Id=4478` contributes the token `id`, not `4478`)."""
    try:
        p = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return []
    tokens = _TOKEN_SPLIT_RE.findall(p.path.lower())
    for name, _value in parse_qsl(p.query, keep_blank_values=True):
        tokens.extend(_TOKEN_SPLIT_RE.findall(name.lower()))
    # drop tokens under 3 letters -- almost entirely split artifacts and
    # generic query-param names ("id", "si") that are common on ordinary
    # links too and would otherwise pass the support floor on noise
    # alone (confirmed while building this table: "id" cleared
    # MIN_SUPPORT purely from the small meeting_firstparty sample) -- and
    # the specific calendar/alert-widget stopwords above.
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORD_TOKENS]


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a}-{b}" for a, b in zip(tokens, tokens[1:])]


def _is_internal(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return True
    if url.startswith("/m/"):
        return True
    if "redtaperecordings.com/m/" in url:
        return True
    return False


def load_jc_positives():
    """Returns (hub_firstparty, hub_vendor, meeting_firstparty, meeting_vendor)
    -- four lists of real URLs from jurisdiction_coverage.csv rows with
    transcribed=true."""
    hub_fp, hub_vendor, meet_fp, meet_vendor = [], [], [], []
    with open(JC_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("transcribed") or "").strip().lower() != "true":
                continue
            agenda = (row.get("example_agenda_or_calendar_url") or "").strip()
            if agenda and not _is_internal(agenda):
                netloc = urlparse(
                    agenda if "://" in agenda else f"https://{agenda}"
                ).netloc
                (hub_vendor if is_vendor_host(netloc) else hub_fp).append(agenda)
            meeting = (row.get("example_meeting_url") or "").strip()
            if meeting and not _is_internal(meeting):
                netloc = urlparse(
                    meeting if "://" in meeting else f"https://{meeting}"
                ).netloc
                (meet_vendor if is_vendor_host(netloc) else meet_fp).append(meeting)
    return hub_fp, hub_vendor, meet_fp, meet_vendor


def load_vendor_meeting_urls():
    """archive_source_urls.csv (8,483 real Archive page source URLs) +
    the tier-3 queue (2,259 real queued meeting URLs) -- overwhelmingly
    vendor-host, used as the larger `meeting_vendor` positive set (the
    same population the conductor's own TOKEN FREQUENCY/LIFT-over-ALL
    tables in conductor_state.md are built from)."""
    urls = []
    p = Path(ARCHIVE_SOURCE_URLS_CSV)
    if p.exists():
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                u = (row.get("source_url") or "").strip()
                if u and u.lower() != "source_url":
                    urls.append(u)
    if TIER3_QUEUE_PATH.exists():
        for line in TIER3_QUEUE_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def _load_manifest_final_urls(*manifest_paths):
    out = {}
    for mp in manifest_paths:
        mp = Path(mp)
        if not mp.exists():
            continue
        with open(mp, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw_file = row.get("raw_file")
                if not raw_file:
                    continue
                out[raw_file] = row.get("final_url") or row.get("url") or ""
    return out


def load_all_links():
    """Every outbound <a href> on every real saved WO-267 page (homepages,
    hub pages, and negative-control homepages), resolved to an absolute
    URL against that page's own final_url, deduplicated per page.
    Returns (pages_parsed, all_links) as a list of (href_url, anchor_text)
    -- callers decide how to split this into positive/negative pools."""
    final_urls = _load_manifest_final_urls(
        f"{WO267_AGENT_DIR}/wo267_manifest.csv",
        f"{WO267_AGENT_DIR}/wo267_manifest_neg_diffplat.csv",
        f"{WO267_AGENT_DIR}/wo267_manifest_neg_unknown.csv",
    )
    html_files = sorted(
        glob.glob(f"{WO267_AGENT_DIR}/wo267_raw/*.html")
        + glob.glob(f"{WO267_AGENT_DIR}/wo267_raw_neg/*.html")
    )
    all_links: list[tuple[str, str]] = []  # (href_url, anchor_text)
    seen_per_page: set[tuple[str, str]] = set()
    pages_parsed = 0
    for path in html_files:
        fname = os.path.basename(path)
        base = final_urls.get(fname, "")
        try:
            html_text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception:  # noqa: BLE001 -- a garbled saved page is skipped, not fatal
            continue
        pages_parsed += 1
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            full = urljoin(base, href) if base else href
            if urlparse(full).scheme not in ("http", "https"):
                continue
            key = norm_url_key(full)
            page_key = (fname, key)
            if page_key in seen_per_page:
                continue
            seen_per_page.add(page_key)
            text = (a.get_text() or "").strip()
            all_links.append((full, text))
    return pages_parsed, all_links


def doc_freq(urls: list[str], extractor) -> tuple[Counter, int]:
    """Counts, per token/bigram, how many DISTINCT URLs contain it at
    least once (not raw occurrence count)."""
    counts: Counter = Counter()
    for u in urls:
        for t in set(extractor(u)):
            counts[t] += 1
    return counts, len(urls)


def compute_lift_table(pos_urls, neg_urls, extractor, min_support):
    pos_counts, n_pos = doc_freq(pos_urls, extractor)
    neg_counts, n_neg = doc_freq(neg_urls, extractor)
    rows = []
    for token, pos_n in pos_counts.items():
        if pos_n < min_support:
            continue
        neg_n = neg_counts.get(token, 0)
        pos_rate = (pos_n + 0.5) / (n_pos + 0.5)
        neg_rate = (neg_n + 0.5) / (n_neg + 0.5)
        lift = pos_rate / neg_rate
        weight = max(-WEIGHT_CAP, min(WEIGHT_CAP, math.log(lift)))
        rows.append((token, pos_n, neg_n, lift, weight))
    rows.sort(key=lambda r: -r[3])
    return rows, n_pos, n_neg


def main():
    print(f"Reading jurisdiction_coverage.csv from {JC_PATH}", file=sys.stderr)
    hub_fp, hub_vendor, meet_fp, meet_vendor_jc = load_jc_positives()
    vendor_meeting_urls = load_vendor_meeting_urls()
    meet_vendor = list(dict.fromkeys(meet_vendor_jc + vendor_meeting_urls))

    print(
        f"positives: hub_firstparty={len(hub_fp)} hub_vendor={len(hub_vendor)} "
        f"meeting_firstparty={len(meet_fp)} meeting_vendor={len(meet_vendor)}",
        file=sys.stderr,
    )

    positive_keys = {
        norm_url_key(u) for u in hub_fp + hub_vendor + meet_fp + meet_vendor
    }
    pages_parsed, all_links = load_all_links()
    # Negative pools EXCLUDE anything that is itself a known positive URL
    # (exact match on the normalized host+path) -- used only for the
    # lift/support computation below, never for the anchor-text pass,
    # which needs the matches, not their absence.
    neg_links = [(u, t) for u, t in all_links if norm_url_key(u) not in positive_keys]
    all_link_urls = [u for u, _t in neg_links]
    fp_link_urls = [u for u, _t in neg_links if not is_vendor_host(urlparse(u).netloc)]
    print(
        f"parsed {pages_parsed} real saved pages; {len(all_links)} total "
        f"outbound links, {len(neg_links)} ordinary (non-positive) links, "
        f"{len(fp_link_urls)} first-party-only",
        file=sys.stderr,
    )

    out_rows = []  # vocabulary, token_or_bigram, kind, positives, negatives, lift, weight

    def emit(vocabulary, kind, table):
        for token, pos_n, neg_n, lift, weight in table:
            out_rows.append(
                {
                    "vocabulary": vocabulary,
                    "token_or_bigram": token,
                    "kind": kind,
                    "positives": pos_n,
                    "negatives": neg_n,
                    "lift": round(lift, 3),
                    "weight": round(weight, 3),
                }
            )

    print("\n=== HUB (first-party) token lift, vs first-party ordinary links ===")
    hub_fp_table, n_pos, n_neg = compute_lift_table(
        hub_fp, fp_link_urls, tokenize_url, MIN_SUPPORT
    )
    print(f"positives(n={n_pos}) vs negatives(n={n_neg})")
    for token, pos_n, neg_n, lift, weight in hub_fp_table[:25]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("hub_firstparty", "path", hub_fp_table)

    print("\n=== HUB (first-party) bigram lift, vs first-party ordinary links ===")
    hub_bigram_table, n_pos_b, n_neg_b = compute_lift_table(
        hub_fp, fp_link_urls, lambda u: bigrams(tokenize_url(u)), MIN_SUPPORT
    )
    print(f"positives(n={n_pos_b}) vs negatives(n={n_neg_b})")
    for token, pos_n, neg_n, lift, weight in hub_bigram_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("hub_firstparty_bigram", "path", hub_bigram_table)

    print("\n=== MEETING (first-party) token lift, vs first-party ordinary links ===")
    meet_fp_table, n_pos_m, n_neg_m = compute_lift_table(
        meet_fp, fp_link_urls, tokenize_url, MIN_SUPPORT
    )
    print(f"positives(n={n_pos_m}) vs negatives(n={n_neg_m})")
    for token, pos_n, neg_n, lift, weight in meet_fp_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("meeting_firstparty", "path", meet_fp_table)

    print("\n=== MEETING (vendor-host) token lift, vs ALL ordinary links ===")
    meet_vendor_table, n_pos_v, n_neg_v = compute_lift_table(
        meet_vendor, all_link_urls, tokenize_url, MIN_SUPPORT
    )
    print(f"positives(n={n_pos_v}) vs negatives(n={n_neg_v})")
    for token, pos_n, neg_n, lift, weight in meet_vendor_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("meeting_vendor", "path", meet_vendor_table)

    # Anchor text: links whose href matches a KNOWN first-party hub URL.
    hub_fp_keys = {norm_url_key(u) for u in hub_fp}
    matched_texts = []
    other_texts = []
    for href, text in all_links:
        bucket = matched_texts if norm_url_key(href) in hub_fp_keys else other_texts
        if text:
            bucket.append(text)
    print(
        f"\n=== ANCHOR TEXT for links matching a known hub URL: "
        f"n={len(matched_texts)} (small sample -- do not over-claim) ==="
    )
    anchor_table, n_pos_a, n_neg_a = compute_lift_table(
        matched_texts,
        other_texts,
        lambda t: [w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 1],
        MIN_SUPPORT_ANCHOR,
    )
    print(f"positives(n={n_pos_a}) vs negatives(n={n_neg_a})")
    for token, pos_n, neg_n, lift, weight in anchor_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("hub_anchor_text", "anchor", anchor_table)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "vocabulary",
                "token_or_bigram",
                "kind",
                "positives",
                "negatives",
                "lift",
                "weight",
            ],
        )
        w.writeheader()
        for row in out_rows:
            w.writerow(row)
    print(f"\nwrote {len(out_rows)} rows to {OUT_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
