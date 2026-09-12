#!/usr/bin/env python3
"""WO-292 step 0: measure a school-board-specific hop-link vocabulary,
the same way scripts/derive_hop_weights.py measured the city/county one
(WO-274) -- see docs/investigations/hop_scorer_measurement.md for that
method's full writeup, which this script follows.

Positives:
  - Every youtube.com/youtu.be/vimeo.com link found on the freshly
    fetched homepage of a us:sd: district already known (via
    jurisdiction_coverage.csv's suspected_video_provider) to run a
    YouTube or Vimeo channel, PLUS the 6 districts with an existing
    Archive page -- "school_channel" positives.
  - The Archive's own real us:sd: page source URLs (pulled live via
    GET /internal/export/pages and filtered to gov_id startswith
    'us:sd:') -- "school_meeting_vendor" positives. Not a fresh sample:
    already-live pages, same population WO-274's own meeting_vendor set
    used (Archive source URLs + the tier-3 queue) for the city/county
    measurement.

Negatives: every OTHER outbound link recorded on those same ~417 fetched
district homepages (school_channel comparison) or on those homepages
plus the same "any ordinary link" pool derive_hop_weights.py itself
uses for its own MEETING(vendor-host) table, when available, else the
homepage-only pool (school_meeting_vendor comparison) -- see "Method"
below for exactly which pool each table uses.

Anchor text: the anchor TEXT of the homepage links that themselves
matched a school_channel positive -- what a real district site calls
the link to its own board's YouTube channel (small sample, same
caution `hop_scorer_measurement.md` gives for its own 81-link anchor
table).

Output: app/utils/jurisdiction_data/hop_link_weights_school.csv, same
five-column shape as hop_link_weights.csv (vocabulary, token_or_bigram,
kind, positives, negatives, lift, weight) so
wo147_access_ladder_sweep.py's _load_hop_weights() reads it unchanged.

No network fetches in this script -- reads scripts/wo292_fetch_vocab_
homepages.py's saved JSON-lines output and reuses derive_hop_weights.py's
tokenizer/lift-table code by importing it as a module (no duplicated
logic).

Run: .venv/bin/python wo292_derive_school_hop_weights.py <homepages.jsonl>
"""

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import derive_hop_weights as dhw  # noqa: E402

OUT_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "hop_link_weights_school.csv"
)

CHANNEL_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")
# BoardDocs/Simbli/Diligent/BoardBook -- the agenda-only hub platforms
# phase 2 (per this WO's own brief) records rather than chases for
# video. A district's own link TO one of these, found on the SAME
# fetched homepages, is real first-party "hub" signal
# (`hop_scorer_measurement.md`'s hub_firstparty category equivalent) --
# jurisdiction_coverage.csv carries no recorded hub URL for any us:sd:
# row, so this is the only real hub-shaped positive set available for
# this measurement (see the printed note in main() about what this
# sample cannot show).
HUB_VENDOR_HOSTS = (
    "boarddocs.com",
    "simbli.eboardsolutions.com",
    "diligent.com",
    "boardbook.org",
)
MIN_SUPPORT = 5  # smaller pool than the city/county measurement (417 homepages, not 713) -- lowered from WO-274's 10 per this WO's own smaller sample; still support-floored, never assumed-negative


def is_channel_link(url: str) -> bool:
    n = urlparse(url).netloc.lower()
    if n.startswith("www."):
        n = n[4:]
    return any(h in n for h in CHANNEL_HOSTS)


def is_hub_vendor_link(url: str) -> bool:
    n = urlparse(url).netloc.lower()
    if n.startswith("www."):
        n = n[4:]
    return any(h in n for h in HUB_VENDOR_HOSTS)


def load_homepages(path):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("outcome") == "fetched":
                records.append(rec)
    return records


def load_archive_sd_urls(path):
    urls = []
    if not Path(path).exists():
        return urls
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            u = (row.get("source_url") or "").strip()
            if u:
                urls.append(u)
    return urls


def main():
    homepages_path = sys.argv[1]
    archive_sd_csv = sys.argv[2] if len(sys.argv) > 2 else None

    homepages = load_homepages(homepages_path)
    print(f"homepages fetched: {len(homepages)}", file=sys.stderr)

    all_links = []  # (href, text)
    channel_positive_urls = []
    channel_positive_keys = set()
    hub_vendor_positive_urls = []
    hub_vendor_positive_keys = set()
    for rec in homepages:
        for link in rec.get("links", []):
            href = link["href"]
            text = link.get("text", "")
            all_links.append((href, text))
            if is_channel_link(href):
                key = dhw.norm_url_key(href)
                if key not in channel_positive_keys:
                    channel_positive_keys.add(key)
                    channel_positive_urls.append(href)
            elif is_hub_vendor_link(href):
                key = dhw.norm_url_key(href)
                if key not in hub_vendor_positive_keys:
                    hub_vendor_positive_keys.add(key)
                    hub_vendor_positive_urls.append(href)

    print(f"total links on fetched homepages: {len(all_links)}", file=sys.stderr)
    print(
        f"distinct youtube/vimeo channel links found on-page: {len(channel_positive_urls)}",
        file=sys.stderr,
    )
    print(
        f"distinct BoardDocs/Simbli/Diligent/BoardBook hub links found on-page: {len(hub_vendor_positive_urls)}",
        file=sys.stderr,
    )

    archive_urls = load_archive_sd_urls(archive_sd_csv) if archive_sd_csv else []
    print(
        f"Archive us:sd: source URLs (live export): {len(archive_urls)}",
        file=sys.stderr,
    )

    meeting_vendor_positives = list(dict.fromkeys(channel_positive_urls + archive_urls))
    all_positive_keys = {
        dhw.norm_url_key(u) for u in meeting_vendor_positives + hub_vendor_positive_urls
    }

    neg_links = [
        (u, t) for u, t in all_links if dhw.norm_url_key(u) not in all_positive_keys
    ]
    neg_urls = [u for u, _t in neg_links]
    print(
        f"ordinary (non-positive) links on these homepages: {len(neg_urls)}",
        file=sys.stderr,
    )

    out_rows = []

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

    print(
        "\n=== SCHOOL MEETING/CHANNEL (vendor-host) token lift, vs ordinary district-homepage links ==="
    )
    table, n_pos, n_neg = dhw.compute_lift_table(
        meeting_vendor_positives, neg_urls, dhw.tokenize_url, MIN_SUPPORT
    )
    print(f"positives(n={n_pos}) vs negatives(n={n_neg})")
    for token, pos_n, neg_n, lift, weight in table[:30]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("school_meeting_vendor", "path", table)

    print("\n=== SCHOOL MEETING/CHANNEL bigram lift ===")
    table_b, n_pos_b, n_neg_b = dhw.compute_lift_table(
        meeting_vendor_positives,
        neg_urls,
        lambda u: dhw.bigrams(dhw.tokenize_url(u)),
        MIN_SUPPORT,
    )
    print(f"positives(n={n_pos_b}) vs negatives(n={n_neg_b})")
    for token, pos_n, neg_n, lift, weight in table_b[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("school_meeting_vendor_bigram", "path", table_b)

    # Anchor text: text of homepage links whose href IS one of the
    # on-page channel positives (Archive source URLs never appear as a
    # homepage href, so this table is scoped to school_channel only).
    matched_texts = []
    other_texts = []
    for href, text in all_links:
        bucket = (
            matched_texts
            if dhw.norm_url_key(href) in channel_positive_keys
            else other_texts
        )
        if text:
            bucket.append(text)
    print(
        f"\n=== SCHOOL CHANNEL anchor text: n={len(matched_texts)} (small sample) ==="
    )
    anchor_table, n_pos_a, n_neg_a = dhw.compute_lift_table(
        matched_texts,
        other_texts,
        lambda t: [
            w for w in __import__("re").findall(r"[a-z]+", t.lower()) if len(w) > 1
        ],
        min(5, MIN_SUPPORT),
    )
    print(f"positives(n={n_pos_a}) vs negatives(n={n_neg_a})")
    for token, pos_n, neg_n, lift, weight in anchor_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("school_channel_anchor_text", "anchor", anchor_table)

    # HUB (agenda-only vendor: BoardDocs/Simbli/Diligent/BoardBook) --
    # the only real first-party "leads to the board's own hub" positive
    # set available (jurisdiction_coverage.csv has no recorded hub URL
    # for any us:sd: row -- see the module docstring). Both the
    # positive URLs' own path tokens AND the anchor text of the
    # homepage links pointing at them are measured, since a BoardDocs
    # tenant path itself carries little vocabulary (`go.boarddocs.com/
    # ca/downey/Board.nsf/...`) but the real anchor text a district
    # writes for that link ("Board Meeting Agenda", "Policies and
    # Procedures") is exactly the missing board/agenda/policy signal.
    print("\n=== SCHOOL HUB (BoardDocs/Simbli/Diligent/BoardBook) token lift ===")
    hub_table, n_pos_h, n_neg_h = dhw.compute_lift_table(
        hub_vendor_positive_urls, neg_urls, dhw.tokenize_url, min(5, MIN_SUPPORT)
    )
    print(f"positives(n={n_pos_h}) vs negatives(n={n_neg_h})")
    for token, pos_n, neg_n, lift, weight in hub_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("school_hub_vendor", "path", hub_table)

    hub_matched_texts = []
    hub_other_texts = []
    for href, text in all_links:
        bucket = (
            hub_matched_texts
            if dhw.norm_url_key(href) in hub_vendor_positive_keys
            else hub_other_texts
        )
        if text:
            bucket.append(text)
    print(
        f"\n=== SCHOOL HUB anchor text: n={len(hub_matched_texts)} (small sample) ==="
    )
    hub_anchor_table, n_pos_ha, n_neg_ha = dhw.compute_lift_table(
        hub_matched_texts,
        hub_other_texts,
        lambda t: [
            w for w in __import__("re").findall(r"[a-z]+", t.lower()) if len(w) > 1
        ],
        min(5, MIN_SUPPORT),
    )
    print(f"positives(n={n_pos_ha}) vs negatives(n={n_neg_ha})")
    for token, pos_n, neg_n, lift, weight in hub_anchor_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("school_hub_anchor_text", "anchor", hub_anchor_table)

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
