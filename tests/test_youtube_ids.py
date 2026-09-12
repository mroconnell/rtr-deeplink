import importlib
import sys

# WO-250, 2026-09-12: `scripts/backfill_video_channel.py` crashed on the
# Archive's Render shell with `ModuleNotFoundError: No module named
# 'yt_dlp'` -- the Archive service's requirements deliberately don't
# include yt-dlp (Archive never calls YouTube itself), but the script
# imported `app.platforms.youtube` just to reach its one pure regex
# method, `YouTubeAssetFinder.extract_video_id()`. That method now
# delegates to `app.platforms.youtube_ids.extract_video_id()`, a module
# with no `yt_dlp` import anywhere in its own code. This test blocks
# `yt_dlp` the same way it's genuinely absent on the Archive's Render
# shell (`sys.modules["yt_dlp"] = None`, which makes any `import yt_dlp`
# raise `ImportError` immediately), forces a fresh import of
# `app.platforms.youtube_ids` under that condition, and runs id
# extraction on the same real URL shapes
# `tests/test_youtube.py::test_extract_video_id_handles_every_real_url_
# shape` already covers for the adapter itself -- proving both that the
# module is really yt-dlp-free and that it still extracts correctly.
#
# Uses monkeypatch (not a bare module-level assignment) so the blocked
# state is undone at test teardown -- several other test files
# (test_youtube.py, test_primegov.py, test_civicclerk.py, ...) import
# `yt_dlp` themselves, and a leaked `None` entry in `sys.modules` would
# break every one of them for the rest of the pytest session.

# Real Oklahoma City PrimeGov meeting video id, same sample used in
# tests/test_youtube.py.
REAL_VIDEO_ID = "uNDJRR3ywVo"


def test_extract_video_id_works_with_yt_dlp_unimportable(monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    sys.modules.pop("app.platforms.youtube_ids", None)
    try:
        module = importlib.import_module("app.platforms.youtube_ids")
        extract_video_id = module.extract_video_id

        cases = {
            f"https://www.youtube.com/watch?v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
            f"https://www.youtube.com/watch?feature=share&v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
            f"https://youtu.be/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
            f"https://www.youtube.com/embed/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
            f"https://www.youtube.com/shorts/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
            f"https://www.youtube.com/live/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
            # Old Flash-era embed shape -- see tests/test_youtube.py for
            # the real page this was confirmed against (Goodyear, AZ).
            f"https://www.youtube.com/v/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
            "https://example.com/not-youtube": None,
            "": None,
        }
        for url, expected in cases.items():
            assert extract_video_id(url) == expected
    finally:
        # Force a clean re-import for whatever test runs next, rather
        # than leaving this test's yt-dlp-blocked import cached.
        sys.modules.pop("app.platforms.youtube_ids", None)
