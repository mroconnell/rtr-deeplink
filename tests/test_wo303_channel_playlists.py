"""Tests for the `--playlists` mode added to the shared channel-listing
helper in `scripts/wo235_channel_pilot.py` (WO-303, 2026-09-12) --
BACKLOG.md's "playlist-organised channels" entry (filed by WO-279).

Real fixtures, no live YouTube calls: `tests/fixtures/wo303_playlists/`
holds a trimmed (id/title/url only) capture of each government's real
`/playlists` tab, fetched ONE time live 2026-09-12 --

* `watertown_sd_playlists.json` -- Watertown city, SD
  (youtube.com/channel/UCIslXYgiw39n0iPfGV9nP1A/playlists, 47 real
  playlists). Its real "City Council Meetings" family is interleaved
  with several OTHER real per-body playlists on the same channel (Work
  Session, Board of Adjustment, Planning/Plan Commission) -- exactly the
  shape `find_governing_body_playlist()` has to isolate correctly, not
  just detect "some playlist contains a body word."
* `groton_ct_playlists.json` -- Groton city, CT
  (youtube.com/channel/UCBk-9Ahudi4nbh26x3jZxlA/playlists, 50 real
  playlists, page 1 of what the channel actually has). Its only
  `("town council",)`-matching playlists are three real "Meet the
  Candidates ... Town Council <year>" CANDIDATE-FORUM playlists, not
  meetings -- a real, differently-shaped false lead this function must
  decline, not guess from.

See BACKLOG.md's own entry for why only these two real examples exist
and its Constraint against over-fitting a fix to just these two shapes.
"""

import json
from pathlib import Path

import pytest

from scripts.wo235_channel_pilot import (
    channel_tab_url,
    find_governing_body_playlist,
)

FIXTURES = Path(__file__).parent / "fixtures" / "wo303_playlists"


def _load(name: str) -> dict:
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_channel_tab_url_playlists_kind():
    assert channel_tab_url("https://www.youtube.com/channel/UCabc", "playlists") == [
        "https://www.youtube.com/channel/UCabc/playlists"
    ]
    # Trailing slash tolerated, same as the existing "videos"/"playlist"
    # kinds.
    assert channel_tab_url("https://www.youtube.com/channel/UCabc/", "playlists") == [
        "https://www.youtube.com/channel/UCabc/playlists"
    ]


def test_finds_watertown_newest_city_council_meetings_playlist():
    listing = _load("watertown_sd_playlists.json")
    match = find_governing_body_playlist(listing, body_keywords=("city council",))
    assert match is not None
    assert match["title"] == "2026 City Council Meetings"
    assert match["id"] == "PLlEYWaErgdNwoC-k3ZtwmYS9P2Z1ZkxG_"


def test_does_not_confuse_city_council_with_other_real_body_playlists():
    # Real, confirmed sibling playlists on the SAME channel that must
    # NOT be picked: Work Session, Board of Adjustment, Planning/Plan
    # Commission all also contain a generic body-shaped word.
    listing = _load("watertown_sd_playlists.json")
    for keywords in (
        ("work session",),
        ("board of adjustment",),
        ("planning commission",),
    ):
        match = find_governing_body_playlist(listing, body_keywords=keywords)
        assert match is not None
        assert "city council" not in match["title"].lower()


def test_declines_groton_town_council_candidate_forum_playlists():
    # The only real "town council"-matching playlists on Groton's real
    # channel are three "Meet the Candidates" forums from three
    # different years, embedded mid-title -- not the government's real
    # meetings, and not collapsible into one group the way Watertown's
    # leading-year playlists are. Must decline, not guess one.
    listing = _load("groton_ct_playlists.json")
    match = find_governing_body_playlist(listing, body_keywords=("town council",))
    assert match is None


def test_declines_when_nothing_matches_the_body_keywords_at_all():
    listing = _load("groton_ct_playlists.json")
    match = find_governing_body_playlist(
        listing, body_keywords=("representative town meeting",)
    )
    assert match is None


def test_declines_on_an_empty_or_missing_listing():
    assert find_governing_body_playlist(None, body_keywords=("city council",)) is None
    assert find_governing_body_playlist({}, body_keywords=("city council",)) is None
    assert (
        find_governing_body_playlist({"entries": []}, body_keywords=("city council",))
        is None
    )


@pytest.mark.parametrize(
    "fixture,keywords,expected_title",
    [
        (
            "watertown_sd_playlists.json",
            ("city council",),
            "2026 City Council Meetings",
        ),
    ],
)
def test_real_positive_controls(fixture, keywords, expected_title):
    listing = _load(fixture)
    match = find_governing_body_playlist(listing, body_keywords=keywords)
    assert match is not None
    assert match["title"] == expected_title
