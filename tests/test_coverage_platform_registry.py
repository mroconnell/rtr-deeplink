"""The /coverage page's *coverage of itself* (WO-35, 2026-08-21).

Deliberately modelled on `tests/test_adapter_canary.py`'s
`test_every_registered_platform_is_canaried_or_explicitly_excluded`
(WO-26), because it guards against the same failure mode one layer over:
an adapter ships, produces real rows, and nothing anywhere notices that a
second place needed updating too.

The concrete history. `archive/db/crud.py`'s `get_platform_coverage()`
buckets each archived page with an `if platform in DIRECT_PLATFORMS /
elif platform == "youtube" / elif platform in CUSTOM_PLATFORMS` chain --
a platform in *neither* dict matches no branch at all and is silently
dropped from the page, with no error and no empty row to notice. That
already happened once to six adapters (champds, iqm2, clerkbase,
seattle_channel, telvue, hyland -- see BACKLOG.md's "[JUST-DO-IT]
/coverage's 'By platform' section should list more platforms"), and then
happened *again*, to four more, within two days of the first batch being
fixed: destinyhosted (PR #244), suiteone (#263), castus (#264) and
open_media (#265) were all confirmed missing from the live production
page on 2026-08-21. Three of four adapter PRs forgetting the same file is
a process gap, not four independent mistakes -- hence a CI guard rather
than another round of manual fixes.

No network, no database, no fixtures: this only compares in-process sets.
"""

from app.platforms import base, register_all_finders
from archive.db.crud import (
    COVERAGE_EXCLUSIONS,
    CUSTOM_PLATFORMS,
    DIRECT_PLATFORMS,
    _IFRAME_EMBED_VIDEO_FORMATS,
    _YOUTUBE_DELEGATING_PLATFORMS,
)


def _registered_platforms() -> set[str]:
    # base._REGISTRY read directly, for exactly the reason
    # test_adapter_canary.py gives: its keys *are* the
    # `AssetFinder.platform_name` values `get_finder()` resolves against,
    # and are the same strings that end up stored as
    # `MeetingPage.platform` on a real ingested page -- which is what
    # get_platform_coverage() branches on. Deriving the list any other way
    # (parsing __init__.py, globbing app/platforms/*.py) could drift from
    # what's actually registered, which is the whole thing this test
    # exists to prevent.
    #
    # Read out of a *temporarily emptied* registry rather than the live
    # one, though: `base._REGISTRY` is process-global and other tests
    # register throwaway finders into it without cleaning up (e.g.
    # tests/test_base.py's "fake_test_platform"), which made this
    # assertion fail in a full-suite run while passing in isolation --
    # a real false positive found while writing this. Restoring the
    # previous contents afterwards keeps that leak someone else's
    # problem, not a new one this file creates.
    # register_all_finders() is safe to call repeatedly -- register()
    # just overwrites the same keys.
    saved = dict(base._REGISTRY)
    base._REGISTRY.clear()
    try:
        register_all_finders()
        return set(base._REGISTRY)
    finally:
        base._REGISTRY.clear()
        base._REGISTRY.update(saved)
        register_all_finders()


def test_every_registered_platform_has_a_coverage_decision():
    """A platform registered by `register_all_finders()` must appear in
    exactly one of `DIRECT_PLATFORMS`, `CUSTOM_PLATFORMS`, or
    `COVERAGE_EXCLUSIONS`. Anything else falls through
    `get_platform_coverage()`'s if/elif chain and disappears from
    /coverage without a trace.
    """
    uncovered = (
        _registered_platforms()
        - set(DIRECT_PLATFORMS)
        - set(CUSTOM_PLATFORMS)
        - set(COVERAGE_EXCLUSIONS)
    )

    assert not uncovered, (
        f"Platform(s) {sorted(uncovered)} are registered in "
        "register_all_finders() but have no /coverage decision, so "
        "get_platform_coverage() will silently drop their rows. Add each "
        "to DIRECT_PLATFORMS (a shared, multi-tenant vendor product) or "
        "CUSTOM_PLATFORMS (a bespoke scraper this app wrote for one "
        "government) in archive/db/crud.py, or to COVERAGE_EXCLUSIONS "
        "there with the real reason it can never have a row."
    )


def test_coverage_keys_are_real_registered_platform_names():
    # Keys must be the registered `AssetFinder.platform_name` -- the same
    # string stored as MeetingPage.platform -- not a prettier label,
    # otherwise the test above would pass while the row it "covers" never
    # matches anything. Several real keys are non-obvious ("aurora_tv",
    # "seattle_channel", "open_media", "chicago_elms", "unknown"). This
    # also catches a platform being renamed or dropped out from under a
    # stale coverage entry.
    registered = _registered_platforms()

    assert not set(DIRECT_PLATFORMS) - registered
    assert not set(CUSTOM_PLATFORMS) - registered
    assert not set(COVERAGE_EXCLUSIONS) - registered


def test_no_platform_is_both_shown_and_excluded():
    assert not set(DIRECT_PLATFORMS) & set(COVERAGE_EXCLUSIONS)
    assert not set(CUSTOM_PLATFORMS) & set(COVERAGE_EXCLUSIONS)
    assert not set(DIRECT_PLATFORMS) & set(CUSTOM_PLATFORMS)


def test_every_coverage_exclusion_states_a_reason():
    # The reason is the whole point of the exclusion set: it's what lets a
    # later session tell "structurally can never have a row" apart from
    # "somebody silenced this to make the test pass." Same assertion
    # test_adapter_canary.py makes about CANARY_EXCLUSIONS.
    for platform, reason in COVERAGE_EXCLUSIONS.items():
        assert reason.strip(), f"{platform} is excluded with no reason given"


def test_every_platform_has_a_non_empty_label():
    for platform, label in {**DIRECT_PLATFORMS, **CUSTOM_PLATFORMS}.items():
        assert label.strip(), f"{platform} has no display label"


def test_youtube_delegating_platforms_all_have_a_row():
    # _YOUTUBE_DELEGATING_PLATFORMS only does anything for a key that has
    # a row to be attributed to -- a key here but in neither platform dict
    # would recover an identity and then throw it away.
    assert not _YOUTUBE_DELEGATING_PLATFORMS - (
        set(DIRECT_PLATFORMS) | set(CUSTOM_PLATFORMS)
    )


def test_iframe_embed_video_formats_covers_the_known_embed_platforms():
    # Not derived from the registry (video_format is a per-resolve value,
    # not a platform name), so this is a deliberate, hand-maintained list
    # -- but the three real cases as of 2026-08-21 are worth pinning:
    # every one stores an iframe embed *page* as `video_url`, so ffprobe
    # can never read it and /coverage must not claim on-demand Whisper is
    # possible. Confirmed by grepping every adapter's `video_format=`
    # assignment: all other stored values (mp4/m3u8/mp3/wav) are genuine
    # fetchable media URLs.
    assert _IFRAME_EMBED_VIDEO_FORMATS == {"youtube", "vimeo", "viebit"}
