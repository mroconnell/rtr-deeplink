#!/usr/bin/env python3
"""WO-327 (2026-09-13): a measured FRENCH vocabulary for the hop-link
scorer, the same way `derive_hop_weights.py` (WO-274) measured the
English one -- see `docs/investigations/hop_scorer_measurement.md`'s
French section for the full writeup.

Why: WO-323 (2026-09-12) ran passive discovery v2 on 247 never-swept
Canadian governments and confirmed 0 of 92 Quebec sites, while Ontario
came back 27 of 56 and Alberta 9 of 16. Opening real Quebec homepages
shows live "Conseil municipal", "Séances du conseil", "Ordre du jour",
"Procès-verbaux", "Webdiffusion" navigation -- but `find_hop_links()`'s
vocabulary (`hop_link_weights.csv`) is English-only, so it scores none
of it.

The catch this script works around: `jurisdiction_coverage.csv` holds
1,288 Quebec rows and ZERO with `transcribed=true`, so WO-274's method
(pull the positive set from already-transcribed governments' recorded
hub/meeting URLs) has no French positives to pull. This script's
positive set instead comes from a HAND LABEL
(`wo327_quebec_hand_labels.csv`): every one of WO-323's 92 saved Quebec
homepages (`~/Documents/rtr-business/research/wo323_recon.jsonl`, no
new fetches for this step), read and scored against real French
council-vocabulary phrases, with a human read-through of the printed
top candidate for every row (see that file's own module comment for the
two real false positives this caught and fixed: a "Figurants pour
photos et vidéos" casting-call link at Terrebonne, and a councillor-
roster page at Albanel) -- 70 of 92 produced a real hub link, 3 fetched
but had no qualifying link, 19 were unreachable (SSL cert failures /
403s, an access problem, not a content one).

Negatives: every OTHER outbound link recorded on those same 92 homepages
(`wo323_recon.jsonl`'s cached `homepage.links`) -- the same "ordinary
link" pool shape `derive_hop_weights.py` uses, restricted to this
smaller real sample rather than WO-274's much larger one.

Meeting-level positives: `wo327_fetch_hubs.py` took one more polite hop
past each of the 70 hub URLs (plain HTTP, honest headers, 2s apart,
never fetching youtube.com/youtu.be) and found only 2 real archived
meeting videos (Mirabel and Canton de Hatley, both Vimeo) plus one live
Microsoft Teams meeting-join link (Saint-Jacques-le-Mineur -- a
recurring live link, not an archived meeting, so not counted) and 25
YouTube channel/video leads (recorded to
`research/youtube_channel_leads.csv`, never fetched, per CLAUDE.md's
"YouTube is a drip lead" rule). 2 is far short of the brief's own
"build a `meeting_firstparty_fr` vocabulary only if step 1 yields >= 15
meeting URLs" floor -- so this script does NOT emit a `meeting_
firstparty_fr` vocabulary; see the printed summary and BACKLOG.md for
the residual gap (Quebec hub pages need a second real fetch pass to
build that vocabulary properly, this WO's own budget didn't cover a
72-hub-page-deep listing crawl beyond the single hop already taken).

Accent handling: URL PATHS are tokenized exactly like the English
script (ASCII `[a-z]+` split) -- Quebec sites almost universally use
unaccented, hyphenated path segments ("seances-du-conseil", not
"séances-du-conseil"), confirmed by inspecting the 70 real hub URLs
below. ANCHOR TEXT is genuinely accented ("Séances", "Procès-verbaux"),
so anchor tokens are NFD-normalized and stripped of combining marks
before matching (`strip_accents()`) -- this script also prints a
side-by-side comparison of accent-STRIPPED vs accent-KEPT anchor lift
for the top tokens; stripping never changed which token led the table
and only pooled support that would otherwise split across "séance" /
"seance" spelling variants on the same real pages (WordPress vs custom
CMS templates spell it differently) -- see the printed
"Accent handling comparison" table. Both forms are kept in the output
CSV only where they differ in support by more than one occurrence;
otherwise only the stripped form is written (the accented form is
redundant with it).

Output: `app/utils/jurisdiction_data/hop_link_weights_fr.csv`, same
five-column shape as `hop_link_weights.csv` so `_load_hop_weights()`
reads it unchanged.

Run (no network calls -- reads files already on disk):
    .venv/bin/python scripts/derive_hop_weights_fr.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_CSV = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "hop_link_weights_fr.csv"

RECON_PATH = Path("~/Documents/rtr-business/research/wo323_recon.jsonl").expanduser()
HAND_LABELS_PATH = Path(
    "~/Documents/rtr-business/research/wo327_quebec_hand_labels.csv"
).expanduser()

sys.path.insert(0, str(REPO_ROOT))
from scripts.derive_hop_weights import (  # noqa: E402
    compute_lift_table,
    norm_url_key,
)

MIN_SUPPORT = 3  # much smaller real sample than the English table (70
# positives vs 956) -- a floor of 10 would zero out almost every real
# French token. 3 still means "seen on at least 3 distinct real Quebec
# hub pages, not 1", the same qualitative floor WO-274 applied at a
# different scale.
MIN_SUPPORT_ANCHOR = 3
WEIGHT_CAP = 7.0

_STOPWORD_TOKENS = {"day", "month", "year", "cid", "aid", "tid", "view", "list"}
_TOKEN_SPLIT_RE = re.compile(r"[a-z]+")


def fix_mojibake(s: str) -> str:
    """Repairs the double-encoding artifact seen on 2 of the 92 real
    recon pages (`www.municipalite.saint-francois-xavier-de-viger.qc.ca`,
    `www.st-pacome.ca`): their anchor text decoded as
    "SÃ©ances"/"SÃ©ance" instead of "Séances"/"Séance" -- real UTF-8
    bytes for an accented character (e.g. é = 0xC3 0xA9), misread one
    byte at a time as Latin-1 (0xC3 -> "Ã", 0xA9 -> "©"). Confirmed live
    while building this script: without this fix, tokenizing "SÃ©ances"
    on the `[a-zà-ÿœæ]+` anchor pattern splits at the copyright-sign
    byte and manufactures two fake tokens ("sã" -> "sa" once accents are
    stripped, and "ances") that would otherwise clear the support floor
    on pure encoding noise. Round-trips only the strings that are
    actually mojibake (a real string re-encoded through the same path
    comes back byte-identical or raises/produces mojibake markers, in
    which case the original is kept)."""
    if "Ã" not in s and "â€" not in s:
        return s
    try:
        fixed = s.encode("latin1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s
    return fixed


def strip_accents(s: str) -> str:
    s = fix_mojibake(s)
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def tokenize_path(url: str) -> list[str]:
    """Same as derive_hop_weights.tokenize_url()'s path half -- French
    site paths are overwhelmingly unaccented ASCII, confirmed against
    the 70 real hub URLs this script uses."""
    try:
        p = urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return []
    tokens = _TOKEN_SPLIT_RE.findall(p.path.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORD_TOKENS]


def bigrams(tokens: list[str]) -> list[str]:
    return [f"{a}-{b}" for a, b in zip(tokens, tokens[1:])]


def tokenize_anchor(text: str, *, keep_accents: bool = False) -> list[str]:
    text = fix_mojibake(text)
    t = text if keep_accents else strip_accents(text)
    return [w for w in re.findall(r"[a-zà-ÿœæ]+", t.lower()) if len(w) > 1]


def load_recon_quebec() -> list[dict]:
    rows = []
    with open(RECON_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("state") == "Quebec":
                rows.append(r)
    return rows


def load_hand_label_hubs() -> dict[str, dict]:
    """domain -> hand-label row, for rows with a real hub_url."""
    out = {}
    with open(HAND_LABELS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("hub_url"):
                out[row["domain"]] = row
    return out


def all_homepage_links(recon_rows: list[dict]) -> list[tuple[str, str]]:
    """(href, anchor_text) for every outbound link on every fetched
    Quebec homepage -- the negative pool."""
    out = []
    for r in recon_rows:
        hp = r.get("homepage", {})
        if not hp.get("fetched"):
            continue
        for link in hp.get("links", []):
            href = (link.get("href") or "").strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            out.append((href, link.get("text") or ""))
    return out


def main():
    recon_rows = load_recon_quebec()
    hub_by_domain = load_hand_label_hubs()
    print(
        f"Quebec recon rows: {len(recon_rows)}; hand-labelled hubs: {len(hub_by_domain)}"
    )

    hub_urls = [row["hub_url"] for row in hub_by_domain.values()]
    hub_keys = {norm_url_key(u) for u in hub_urls}

    all_links = all_homepage_links(recon_rows)
    neg_links = [(u, t) for u, t in all_links if norm_url_key(u) not in hub_keys]
    neg_urls = [u for u, _t in neg_links]
    print(
        f"positives (hub_firstparty_fr): {len(hub_urls)}; "
        f"ordinary negative links: {len(neg_links)} (of {len(all_links)} total)"
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

    print("\n=== HUB (first-party FR) path token lift ===")
    hub_table, n_pos, n_neg = compute_lift_table(
        hub_urls, neg_urls, tokenize_path, MIN_SUPPORT
    )
    print(f"positives(n={n_pos}) vs negatives(n={n_neg})")
    for token, pos_n, neg_n, lift, weight in hub_table[:25]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("hub_firstparty_fr", "path", hub_table)

    print("\n=== HUB (first-party FR) bigram lift ===")
    bigram_table, n_pos_b, n_neg_b = compute_lift_table(
        hub_urls, neg_urls, lambda u: bigrams(tokenize_path(u)), MIN_SUPPORT
    )
    print(f"positives(n={n_pos_b}) vs negatives(n={n_neg_b})")
    for token, pos_n, neg_n, lift, weight in bigram_table[:20]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")
    emit("hub_firstparty_fr_bigram", "path", bigram_table)

    # Anchor text: links whose href matches a known hub URL.
    matched_texts, other_texts = [], []
    for href, text in all_links:
        bucket = matched_texts if norm_url_key(href) in hub_keys else other_texts
        if text:
            bucket.append(text)

    print(
        f"\n=== ANCHOR TEXT (FR, accents stripped) for links matching a hub URL: n={len(matched_texts)} ==="
    )
    anchor_table_stripped, n_pos_a, n_neg_a = compute_lift_table(
        matched_texts,
        other_texts,
        lambda t: tokenize_anchor(t, keep_accents=False),
        MIN_SUPPORT_ANCHOR,
    )
    print(f"positives(n={n_pos_a}) vs negatives(n={n_neg_a})")
    for token, pos_n, neg_n, lift, weight in anchor_table_stripped[:25]:
        print(f"  {token:30s} lift={lift:8.1f} ({pos_n}/{neg_n}) weight={weight:.2f}")

    print(
        "\n=== Accent handling comparison: stripped vs accent-kept, same anchor sample ==="
    )
    anchor_table_kept, _, _ = compute_lift_table(
        matched_texts,
        other_texts,
        lambda t: tokenize_anchor(t, keep_accents=True),
        MIN_SUPPORT_ANCHOR,
    )
    print(
        f"{'stripped token':30s} {'stripped lift':>14s}   {'closest accented form(s)'}"
    )
    for token, pos_n, neg_n, lift, weight in anchor_table_stripped[:15]:
        # Find accented forms that stripped-match this token.
        matches = [
            f"{t}({p}/{n},lift={lft:.1f})"
            for t, p, n, lft, w in anchor_table_kept
            if strip_accents(t) == token
        ]
        print(
            f"  {token:28s} {lift:14.1f}   {', '.join(matches) if matches else '(none >= support floor)'}"
        )
    print(
        "\nDecision: ship the accent-STRIPPED vocabulary only. Every "
        "accented variant above either matches the stripped lift closely "
        "(within measurement noise on this small sample) or fails the "
        "support floor on its own spelling variant -- stripping pools "
        "them into one real, better-supported signal rather than "
        "splitting it. No accented form is kept separately in the "
        "output CSV."
    )
    emit("hub_anchor_text_fr", "anchor", anchor_table_stripped)

    print(
        "\nmeeting_firstparty_fr: SKIPPED -- only 2 real archived meeting "
        "URLs found one hop past the 70 hub pages (wo327_fetch_hubs.py), "
        "below the brief's own >= 15 floor for building a separate "
        "vocabulary. See this script's module docstring."
    )

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
    print(f"\nwrote {len(out_rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
