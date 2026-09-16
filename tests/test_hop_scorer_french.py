"""WO-327 (2026-09-13): tests for the French hop-link vocabulary
(`app/utils/jurisdiction_data/hop_link_weights_fr.csv`,
`scripts/wo147_access_ladder_sweep.py`'s `looks_french()` and the French
branch of `_weights_for_gov()`).

Fixtures are real saved homepages from WO-323's passive-discovery-v2
recon (`~/Documents/rtr-business/research/wo323_recon.jsonl`, fetched
2026-09-12/13) -- `mirabel_qc_home.html` and `saint_georges_qc_home.html`
are two of the 70 real Quebec homepages this WO hand-labelled a hub link
on (`wo327_quebec_hand_labels.csv`), `adelaide_metcalfe_on_home.html` is
a real Ontario homepage from the SAME recon batch, used only to prove no
regression on an English-language Canadian government (Ontario
governments carry the same `ca:csd:` gov_id prefix as Quebec ones -- the
`ca:` prefix alone can never gate French scoring; `looks_french()` on
the fetched page itself is the only real gate, which is exactly what
these tests check).
"""

from __future__ import annotations

import os

from scripts.wo147_access_ladder_sweep import find_hop_links, looks_french

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "wo327_french_hop")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def test_looks_french_true_for_real_quebec_homepages():
    assert looks_french(_load("mirabel_qc_home.html")) is True
    assert looks_french(_load("saint_georges_qc_home.html")) is True


def test_looks_french_false_for_real_ontario_homepage():
    assert looks_french(_load("adelaide_metcalfe_on_home.html")) is False


def test_looks_french_false_for_empty_or_missing_text():
    assert looks_french("") is False
    assert looks_french(None) is False  # type: ignore[arg-type]


def test_mirabel_french_vocabulary_surfaces_the_real_council_hub():
    """Real, confirmed finding this WO fixed: without the French
    vocabulary, Mirabel's real "Séances du conseil" hub link
    (mirabel.ca/seances-conseil) does not even place in the top 8 --
    a YouTube channel link, a property-search widget, and a job-listing
    page outrank it, none of which is a real meeting hub. With the
    French vocabulary (gov_id starts `ca:` AND the page is detected
    French), it ranks #1."""
    html = _load("mirabel_qc_home.html")
    final_url = "https://mirabel.ca/"
    gov_id = "ca:csd:2474005"  # Mirabel QC, real gov_id from wo323_recon.jsonl

    top_with_french = find_hop_links(html, final_url, gov_id=gov_id)
    assert top_with_french, "expected at least one ranked candidate"
    assert top_with_french[0] == "https://mirabel.ca/seances-conseil"

    top_without_french = find_hop_links(html, final_url, gov_id="")
    assert "https://mirabel.ca/seances-conseil" not in top_without_french[:3]


def test_saint_georges_french_vocabulary_ranks_both_real_hub_links_first():
    """Real second case, a different site template: both of Saint-
    Georges QC's real council-session pages (a calendar and a session
    list) outrank everything else once French scoring is on."""
    html = _load("saint_georges_qc_home.html")
    final_url = "https://www.saint-georges.ca/"
    gov_id = "ca:csd:2429073"

    top3 = find_hop_links(html, final_url, gov_id=gov_id)[:3]
    assert (
        "https://www.saint-georges.ca/ville/vie-democratique/calendrier-des-seances-du-conseil-municipal"
        in top3
    )
    assert (
        "https://www.saint-georges.ca/ville/vie-democratique/seances-du-conseil" in top3
    )


def test_ontario_homepage_scoring_is_byte_identical_with_and_without_gov_id():
    """The regression guarantee the brief asks for: an English-language
    Canadian government (Ontario, same `ca:csd:` gov_id prefix as
    Quebec) must score EXACTLY the same whether or not its real gov_id
    is passed in, because `looks_french()` on its own real page is
    False. Measured across all 52 real fetched Ontario homepages from
    the same WO-323 recon batch (not just this one fixture) while
    building this WO -- zero differences found."""
    html = _load("adelaide_metcalfe_on_home.html")
    final_url = "https://www.adelaidemetcalfe.on.ca/"
    gov_id = "ca:csd:3539047"  # real Adelaide Metcalfe ON gov_id

    assert find_hop_links(html, final_url, gov_id=gov_id) == find_hop_links(
        html, final_url, gov_id=""
    )


def test_non_canadian_gov_id_never_gets_french_vocabulary_even_if_page_is_french():
    """A `us:` (or any non-`ca:`) row must never pick up the French
    vocabulary, even in the hypothetical case its page reads as French
    (e.g. a Louisiana parish page with French place names) -- the French
    branch is gated on `gov_id.startswith("ca:")` first, `looks_french()`
    second, not `looks_french()` alone."""
    html = _load("mirabel_qc_home.html")  # a real, confirmed-French page
    final_url = "https://mirabel.ca/"
    assert looks_french(html) is True

    top_us = find_hop_links(html, final_url, gov_id="us:place:2255000")
    top_blank = find_hop_links(html, final_url, gov_id="")
    assert top_us == top_blank
