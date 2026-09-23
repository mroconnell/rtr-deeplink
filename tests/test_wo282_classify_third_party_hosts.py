"""Fixture-backed coverage for `wo282_classify.is_unresolvable_third_party_host()`
(2026-09-23, Ryan) -- pure logic, no network, per CLAUDE.md's synthetic-test
rule.

Real bug this closes: `homepage_candidates()` fell through to `kind="hub"`
for any link `detect_platform()` didn't recognize, with no check for
WHERE the link actually lives. Confirmed live 2026-09-22's production run
wasted real phase-3 fetches on `vimeo.com/search?q=Ward%20County%20
Commissioners` and `vimeo.com/rockdalegov`, both scored as if they might
be the government's own hub page, because their URL path text happened to
contain real hub-vocabulary words ("commissioners") -- see
wo282_classify.py's own module-level comment on `_THIRD_PARTY_HOST_APEXES`
for the full investigation.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import scripts.wo282_classify as wo282_classify  # noqa: E402


def test_a_vimeo_search_page_is_skipped():
    # The real, confirmed case: Ward County ND's homepage linked this, and
    # its own URL text ("Ward County Commissioners") scored as a real hub
    # candidate before this fix.
    assert wo282_classify.is_unresolvable_third_party_host(
        "https://vimeo.com/search?q=Ward%20County%20Commissioners"
    )


def test_a_bare_vimeo_vanity_channel_is_skipped():
    # The real, confirmed case: Rockdale County GA's homepage linked this.
    assert wo282_classify.is_unresolvable_third_party_host("https://vimeo.com/rockdalegov")


def test_a_recognized_vimeo_video_id_is_not_skipped():
    # A URL shape detect_platform() actually resolves -- real signal, not
    # noise, so it must stay eligible (kind="platform" elsewhere).
    assert not wo282_classify.is_unresolvable_third_party_host("https://vimeo.com/821841258")


def test_a_recognized_youtube_channel_handle_is_not_skipped():
    # detect_platform() already recognizes an @handle channel URL --
    # confirmed live against French Lick, IN's real channel. Must stay
    # eligible; this guard only catches what detect_platform() misses.
    assert not wo282_classify.is_unresolvable_third_party_host(
        "https://www.youtube.com/@townoffrenchlick"
    )


def test_an_ordinary_government_domain_is_never_skipped():
    assert not wo282_classify.is_unresolvable_third_party_host(
        "https://richmondhill-ga.gov/agendacenter"
    )


def test_facebook_and_twitter_profile_pages_are_skipped():
    assert wo282_classify.is_unresolvable_third_party_host(
        "https://www.facebook.com/CityOfExample"
    )
    assert wo282_classify.is_unresolvable_third_party_host("https://twitter.com/CityOfExample")


def test_www_prefix_does_not_evade_the_check():
    assert wo282_classify.is_unresolvable_third_party_host("https://www.vimeo.com/rockdalegov")
