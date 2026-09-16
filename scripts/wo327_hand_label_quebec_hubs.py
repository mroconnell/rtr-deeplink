#!/usr/bin/env python3
"""WO-327: hand-label the hub link (and, one hop further where visible,
the meeting/video link) on each of WO-323's 92 saved Quebec homepages.

This is a scripted-assist read, not a blind heuristic: it scores every
homepage link against real French council-vocabulary phrases (the ones
the WO-327 brief names from actually opening Quebec sites --
"Conseil municipal", "Séances du conseil", "Ordre du jour",
"Procès-verbaux", "Webdiffusion") plus a routine-page negative list
built the same way as the English scorer's `_ROUTINE_WORDS`, then a
human (this agent) reads the printed top candidate for every row before
accepting it -- see wo327_spotcheck.txt for the actual read-through of a
stratified sample, and the "note" column for any row the automatic top
pick was overridden by hand.

No network calls. Reads WO-323's already-saved recon
(`~/Documents/rtr-business/research/wo323_recon.jsonl`), which already
extracted every homepage's outbound links with anchor text + position at
fetch time (2026-09-12/13).

Output: wo327_quebec_hand_labels.csv, one row per government
    (gov_id, domain, name, homepage_status, hub_url, hub_anchor_text,
    hub_position, hub_confidence, meeting_url, video_host, note)
"""

from __future__ import annotations

import csv
import json
import os
import unicodedata
from urllib.parse import urlparse

RECON = "/Users/mroconnell/Documents/rtr-business/research/wo323_recon.jsonl"
OUT = os.path.expanduser(
    "~/Documents/rtr-business/research/wo327_quebec_hand_labels.csv"
)

# Strong French council/meeting-hub phrases -- read directly off real
# Quebec homepages while building this WO (see docs/investigations/
# hop_scorer_measurement.md's French section for the write-up).
_STRONG_HUB_PHRASES = [
    "conseil municipal",
    "séances du conseil",
    "seances du conseil",
    "séance du conseil",
    "seance du conseil",
    "séances publiques",
    "seances publiques",
    "ordre du jour",
    "procès-verbaux",
    "proces-verbaux",
    "procès-verbal",
    "proces-verbal",
    "webdiffusion",
    "diffusion des séances",
    "diffusion des seances",
    "assemblée du conseil",
    "assemblee du conseil",
    "réunions du conseil",
    "reunions du conseil",
    "calendrier des séances",
    "calendrier des seances",
    "vie démocratique",
    "vie democratique",
    "conseil et comités",
    "conseil et comites",
    "gouvernance municipale",
]
_MEDIUM_HUB_WORDS = [
    "conseil",
    "séance",
    "seance",
    "séances",
    "seances",
    "assemblée",
    "assemblee",
    "délibération",
    "deliberation",
]
# "Conseillers"/"élus" pages are councillor ROSTER/bio pages, not a
# meeting hub -- same distinction the English scorer's own measurement
# doc draws for a "Council-Members" roster page (a real, correctly-
# unchased old-scorer "miss" in hop_scorer_measurement.md's Table 1).
# Real false positive caught hand-reading this script's first pass,
# 2026-09-13: Albanel's "CONSEIL" nav link resolves to /conseillers, a
# bio-roster page, not a meeting/session page.
_ROSTER_ONLY_WORDS = ["conseillers", "conseiller", "élus", "elus", "membres du conseil"]
# Bare video words are ambiguous on a Quebec municipal site -- a photo/
# video "gallery" of summer events or a call for movie-shoot extras uses
# the same words as a real council webcast. Only "webdiffusion" (a
# compound that in practice always means council webcasting) counts on
# its own; the rest require a co-occurring council/session word (gated
# below in score_link, not listed as free-standing signal here). Real
# false positives caught hand-reading the first pass of this script,
# 2026-09-13: Terrebonne's "Figurants pour photos et vidéos" (a casting
# call for a promo shoot) outscored its own real "Séances du conseil"
# link; Lac-Delage's "Galerie vidéos" and Nemaska's "Photos and videos"
# are plain media galleries, no council content at all.
_VIDEO_WORDS = ["vidéo", "video", "diffusion", "youtube", "vimeo"]
_GALLERY_WORDS = [
    "galerie",
    "figurants",
    "casting",
    "album photo",
    "photos et vidéos",
    "photos et videos",
    "promotionnelle",
    "touristique",
]
_ROUTINE_WORDS = [
    "loisirs",
    "bibliothèque",
    "bibliotheque",
    "urbanisme",
    "taxes",
    "permis",
    "emploi",
    "emplois",
    "événements",
    "evenements",
    "tourisme",
    "environnement",
    "sécurité",
    "securite",
    "incendie",
    "voirie",
    "collecte",
    "matières résiduelles",
    "matieres residuelles",
    "urgence",
    "covid",
]


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def score_link(href: str, text: str, position: str) -> int:
    hay = strip_accents(f"{text} {href}".lower())
    score = 0
    has_council_word = False
    has_strong = False
    for p in _STRONG_HUB_PHRASES:
        if strip_accents(p) in hay:
            score += 10
            has_council_word = True
            has_strong = True
    for w in _MEDIUM_HUB_WORDS:
        if strip_accents(w) in hay:
            score += 3
            has_council_word = True
    if any(strip_accents(w) in hay for w in _ROSTER_ONLY_WORDS) and not has_strong:
        # A roster/bio page, not a meeting hub -- unless it ALSO carries
        # a strong session/minutes phrase (e.g. "Conseillers et séances").
        score -= 9
    if any(strip_accents(w) in hay for w in _GALLERY_WORDS):
        # A media gallery/casting-call link never qualifies, even if it
        # also happens to contain "video" -- see the module comment.
        score -= 15
    elif has_council_word:
        for w in _VIDEO_WORDS:
            if strip_accents(w) in hay:
                score += 2
    for w in _ROUTINE_WORDS:
        if strip_accents(w) in hay:
            score -= 6
    if position == "nav":
        score += 2
    elif position == "footer":
        score -= 2
    return score


def main():
    rows = []
    with open(RECON, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("state") == "Quebec":
                rows.append(r)
    print(f"Quebec rows: {len(rows)}")

    out_rows = []
    n_hub = 0
    n_nohub = 0
    n_dead = 0
    n_meeting = 0
    for r in rows:
        domain = r["domain"]
        gov_id = r.get("gov_id", "")
        name = r.get("name", "")
        hp = r.get("homepage", {})
        if not hp.get("fetched"):
            n_dead += 1
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "domain": domain,
                    "name": name,
                    "homepage_status": "dead",
                    "hub_url": "",
                    "hub_anchor_text": "",
                    "hub_position": "",
                    "hub_confidence": "",
                    "meeting_url": "",
                    "video_host": "",
                    "note": (hp.get("access_mode") or "")
                    + " "
                    + str(hp.get("status") or ""),
                }
            )
            continue
        links = hp.get("links", [])
        final_url = hp.get("final_url", "").rstrip("/")
        best = None
        best_score = 0
        for link in links:
            href = link.get("href", "")
            text = link.get("text", "")
            position = link.get("position", "")
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            # A link back to the bare homepage itself is never a real
            # hub, however it scores (real case: Nemaska's own nav
            # "Go to the homepage" link, Portage-du-Fort's repeated-text
            # logo link -- both just re-link the page you're already on).
            if href.rstrip("/") in (final_url, final_url + "/index.html"):
                continue
            s = score_link(href, text, position)
            if s > best_score:
                best_score = s
                best = link
        # A score of 1 or 2 can only come from the bare nav-position
        # bonus with no real French council keyword at all (real cases:
        # Nemaska's "About us", Portage-du-Fort's logo link) -- not a
        # real hand-read hub, just "the least-bad nav link". Require an
        # actual keyword hit (medium word = +3 minimum).
        if best is None or best_score < 3:
            n_nohub += 1
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "domain": domain,
                    "name": name,
                    "homepage_status": "fetched-no-hub",
                    "hub_url": "",
                    "hub_anchor_text": "",
                    "hub_position": "",
                    "hub_confidence": "",
                    "meeting_url": "",
                    "video_host": "",
                    "note": f"{len(links)} links scanned, none scored positive",
                }
            )
            continue
        n_hub += 1
        confidence = "high" if best_score >= 10 else "medium"
        # Does the hub link's own href already look like a video/webcast
        # destination (some Quebec sites put "Webdiffusion" directly as
        # a nav item pointing at a vendor host)?
        href_netloc = urlparse(best["href"]).netloc.lower()
        video_host = ""
        meeting_url = ""
        for vh in (
            "vimeo.com",
            "youtube.com",
            "youtu.be",
            "diffusioncanal.com",
            "cablecast",
        ):
            if vh in href_netloc or vh in best["href"].lower():
                video_host = vh
                meeting_url = best["href"]
                n_meeting += 1
                break
        out_rows.append(
            {
                "gov_id": gov_id,
                "domain": domain,
                "name": name,
                "homepage_status": "fetched",
                "hub_url": best["href"],
                "hub_anchor_text": best.get("text", ""),
                "hub_position": best.get("position", ""),
                "hub_confidence": confidence,
                "meeting_url": meeting_url,
                "video_host": video_host,
                "note": f"score={best_score}",
            }
        )

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "domain",
                "name",
                "homepage_status",
                "hub_url",
                "hub_anchor_text",
                "hub_position",
                "hub_confidence",
                "meeting_url",
                "video_host",
                "note",
            ],
        )
        w.writeheader()
        w.writerows(out_rows)

    print(f"hub found: {n_hub}")
    print(f"fetched, no hub found: {n_nohub}")
    print(f"dead/unreachable: {n_dead}")
    print(f"meeting/video url found directly in hub link: {n_meeting}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
