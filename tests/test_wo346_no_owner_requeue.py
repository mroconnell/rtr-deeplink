"""WO-346: `scripts/feed_tier3_auto_transcription.py::main()` must put a
`[NO-OWNER]` line BACK into the queue rather than drop it -- a missing
`tenant_overrides.csv` pin is a fixable gap, not a dead link, so the
existing "advance the queue regardless of individual outcomes" rule
(which is correct for a genuine dead/wrong video) must not also discard
an ownable-but-not-yet-pinned line.
"""

import scripts.feed_tier3_auto_transcription as mod


async def test_main_requeues_a_no_owner_line_instead_of_dropping_it(
    monkeypatch, tmp_path
):
    queue_file = tmp_path / "queue.txt"
    queue_file.write_text(
        "https://example.granicus.com/player/clip/1\n"
        "https://www.youtube.com/watch?v=noownerid1\n"
        "https://example.granicus.com/player/clip/2\n"
    )
    monkeypatch.setattr(mod, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(mod, "BATCH_SIZE", 3)
    monkeypatch.setattr(mod, "register_all_finders", lambda: None)
    # WO-937: main() now writes a durable per-line log for every call --
    # redirect it, or this test writes to the real tracked CSV.
    monkeypatch.setattr(mod, "FEED_LOG_CSV", tmp_path / "feed_log.csv")

    async def _fake_push(session, url, source_url_override, **kwargs):
        if "noownerid1" in url:
            return f"[NO-OWNER] {url} has no owner"
        return f"[OK] {url} -> /m/fake"

    monkeypatch.setattr(mod, "_push_if_has_video", _fake_push)

    # The "report queue depth to Archive" tail end is best-effort and
    # already wrapped in a broad try/except -- forcing _base_url() to
    # raise keeps this test fast and fully offline rather than actually
    # attempting a network connection that would just be caught anyway.
    def _raise(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(mod, "_base_url", _raise)

    await mod.main()

    remaining = queue_file.read_text()
    assert "noownerid1" in remaining, "the no-owner line must stay in the queue"
    assert "clip/1" not in remaining, "a successfully-processed line is consumed"
    assert "clip/2" not in remaining, "a successfully-processed line is consumed"


async def test_main_leaves_the_queue_untouched_when_nothing_is_ownerless(
    monkeypatch, tmp_path
):
    queue_file = tmp_path / "queue.txt"
    queue_file.write_text("https://example.granicus.com/player/clip/1\n")
    monkeypatch.setattr(mod, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(mod, "BATCH_SIZE", 12)
    monkeypatch.setattr(mod, "register_all_finders", lambda: None)
    monkeypatch.setattr(mod, "FEED_LOG_CSV", tmp_path / "feed_log.csv")

    async def _fake_push(session, url, source_url_override, **kwargs):
        return f"[OK] {url} -> /m/fake"

    monkeypatch.setattr(mod, "_push_if_has_video", _fake_push)

    def _raise(*a, **k):
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(mod, "_base_url", _raise)

    await mod.main()

    assert queue_file.read_text() == ""
