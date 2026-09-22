"""Shared human-verification / bot-challenge marker list for sweep scripts.

WO-939 (2026-09-21): nine scripts each carried their own literal copy of
this list (`scripts/wo145_api_first_sweep.py`, `wo147_access_ladder_
sweep.py`, `wo149_county_ladder_sweep.py`, `wo176_path_pilot.py`,
`wo265_school_district_sweep.py`, `wo268_passive_discovery.py`,
`wo270_wordpress_pilot.py`, `wo272_probe_first_party_paths.py`,
`wo273_recon.py`) -- re-counted with `git grep` on 2026-09-21, still 9,
confirming WO-931's earlier recount from 8. WO-278 (2026-09-12) found a
real, live gap while rechecking a WO-273 finding: a Radware/ShieldSquare
bot-management challenge (`validate.perfdrive.com`, `<title>Radware Block
Page</title>`) served with a real HTTP 200 after a 302, recognized only by
`wo273_recon.py`'s own copy -- the other 8 copies (and every script that
inherits from them by import/alias) still couldn't recognize it. Its
redirect URL echoes the requested target back as a query parameter, which
is how a government's own name can leak into a page that never actually
says anything about it -- a real false-positive source for any script that
checks page text against a government's name without first checking
`is_challenge()`.

This module is the "better" fix BACKLOG.md's own entry named: one shared
list every script imports, instead of a 9th (or 10th) hand-copied one.
Deliberately pure-stdlib (no app/archive/requests/bs4 imports) so a script
that imports it stays exactly as dependency-light as it was importing its
own local copy -- several of the 9 originals said so explicitly in their
own comments (e.g. wo268_passive_discovery.py: "kept as a local copy
rather than an import so this detection-only pilot stays free of
app/archive imports and a DB connection"); this module doesn't reintroduce
that cost.

Three MORE files carry a related-but-distinct list of their own
(`app/platforms/generic_fallback.py`'s `_CHALLENGE_MARKERS`, 3 items --
Akamai-specific, not this list; `scripts/hub_sweep_wo126.py` and
`scripts/score_gov_signals.py`'s `_CLOUDFLARE_CHALLENGE_MARKERS`) -- out
of scope here per the BACKLOG entry's own framing ("related", not
"duplicated"); left alone.

Usage:
    from scripts.challenge_markers import CHALLENGE_MARKERS, is_challenge
"""

from __future__ import annotations

CHALLENGE_MARKERS = (
    "just a moment",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-bypass",
    "ddos protection by",
    "sgcaptcha",
    "px-captcha",
    "perimeterx",
    "distil_r_captcha",
    "captcha-delivery",
    "request unsuccessful. incapsula",
    "access to this page has been denied",
    # WO-278 (2026-09-12): confirmed live against co.roseau.mn.us -- a
    # Radware/ShieldSquare bot-management challenge, served with a real
    # HTTP 200 after a 302 through validate.perfdrive.com. See this
    # module's own docstring above for the full story.
    "radware block page",
    "perfdrive.com",
    "shieldsquare",
)


def is_challenge(text: str) -> bool:
    """True if `text` (a fetched page's body, or any other haystack a
    caller wants to check) contains a recognized bot/human-verification
    challenge marker. Case-insensitive, substring match -- the same shape
    every one of the 9 scripts' own local `is_challenge()` used."""
    lower = (text or "").lower()
    return any(marker in lower for marker in CHALLENGE_MARKERS)
