"""Tests for scripts/bulk_ingest.py's WO-156 gate: _ingest() now runs
WO-144's queue_probe.probe_queue_entry() on any payload that carries a
video_url, before POSTing to the Archive, and refuses a reject-dead/
reject-short verdict. Before this WO, only the tier-3 queue
(feed_tier3_auto_transcription.py) and the worker's claim-time check
(worker/main.py) had any duration/dead-link gate at all -- every
tier-1/2 sweep result (scripts/wo134_confirmed_hits_ingest.py and the
~9 scripts that share _ingest() with it) walked straight past both. A
59-second "Larry J. Dix Boardroom" camera clip became a real county page
this exact way (WO-149, 2026-09-10, deleted by hand) -- see
BACKLOG_DONE.md's WO-156 entry.

Two of the tests below (`test_ingest_refuses_a_real_shaped_dead_hls_link`,
`test_ingest_refuses_a_real_shaped_too_short_hls_clip`) reuse the exact
HLS master/variant playlist *shape* tests/test_queue_probe.py's own
`test_probe_hls_accepts_a_real_shaped_master_plus_variant` already
confirmed against real Granicus/Swagit/Cablecast pages during WO-144 --
only the made-up numbers/urls here are synthetic, not the shape (per
CLAUDE.md's synthetic-test convention). The rest stub `probe_queue_entry`
directly, the same way tests/test_feed_tier3_auto_transcription.py
already does for the identical reason: these tests are about _ingest()'s
own gating logic (which verdicts it refuses, when it skips the probe,
what it logs), not about queue_probe.py's per-platform recipes, which
tests/test_queue_probe.py already covers.
"""

import csv

import aiohttp
import pytest

import scripts.bulk_ingest as bulk_ingest
from app.platforms.queue_probe import ProbeResult
from scripts.bulk_ingest import IngestGateRejected, _ingest, process_one
from tests.aiohttp_mock import FakeResponse, mock_session

_ARCHIVE_BASE = "https://archive.example.test"
_INGEST_URL = f"{_ARCHIVE_BASE}/internal/ingest"

_ACCEPT_JSON = '{"slug": "x", "url": "/m/x", "created": true}'

# Synthetic HLS master+variant shape -- confirmed real (WO-143/WO-144,
# see tests/test_queue_probe.py's own comment) against Granicus/Swagit/
# Cablecast: the master playlist alone always carries zero #EXTINF
# entries, the variant it names carries the real segment list.
_SYNTHETIC_MASTER_PLAYLIST = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
chunklist.m3u8
"""

# ~3.5 minutes -- an ordinary, plausible meeting length.
_SYNTHETIC_LONG_VARIANT_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION=10
#EXTINF:10.0,
seg0.ts
#EXTINF:10.0,
seg1.ts
#EXTINF:10.0,
seg2.ts
#EXTINF:10.0,
seg3.ts
#EXTINF:10.0,
seg4.ts
#EXTINF:10.0,
seg5.ts
#EXTINF:5.5,
seg6.ts
"""

# ~12 seconds -- a "camera check"-shaped clip, well under the 60s
# meeting-plausibility floor (media_probe.MIN_PLAUSIBLE_MEETING_SECONDS)
# -- the real WO-149 "Larry J. Dix Boardroom" shape this WO exists for.
_SYNTHETIC_TOO_SHORT_VARIANT_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION=6
#EXTINF:6.0,
seg0.ts
#EXTINF:6.0,
seg1.ts
"""


@pytest.fixture(autouse=True)
def _fake_archive(monkeypatch):
    monkeypatch.setattr(bulk_ingest, "_base_url", lambda: _ARCHIVE_BASE)
    monkeypatch.setattr(bulk_ingest, "_headers", lambda: {})


def _probe_stub(verdict, reason=None, duration=1200.0):
    async def _stub(url, *, video_url=None, source_page_url=None, platform=None):
        return ProbeResult(
            url=url,
            platform=platform,
            probe_method="test-stub",
            duration_seconds=duration if verdict != "reject-dead" else None,
            date=None,
            size_bytes=None,
            verdict=verdict,
            reason=reason,
            probe_seconds=0.01,
            over_nine_minutes=duration > 9 * 60,
        )

    return _stub


def _noop_append_probe_row(sidecar_path, result, *, caller=""):
    pass


# --- reject-dead / reject-short refuse the ingest, before any POST -------


async def test_ingest_refuses_reject_dead_payload(monkeypatch):
    monkeypatch.setattr(
        bulk_ingest,
        "probe_queue_entry",
        _probe_stub("reject-dead", "yt-dlp: video removed"),
    )
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/dead.mp4",
        "source_url": "https://example.gov/meeting/1",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={}):
        with pytest.raises(IngestGateRejected) as exc_info:
            await _ingest(None, payload, "https://example.gov/meeting/1")
    assert str(exc_info.value) == "[SKIP] reject-dead: yt-dlp: video removed"


async def test_ingest_refuses_reject_short_payload(monkeypatch):
    monkeypatch.setattr(
        bulk_ingest,
        "probe_queue_entry",
        _probe_stub("reject-short", "duration 59.0s is below the 60s floor", 59.0),
    )
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/short.mp4",
        "source_url": "https://example.gov/meeting/2",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={}):
        with pytest.raises(IngestGateRejected) as exc_info:
            await _ingest(None, payload, "https://example.gov/meeting/2")
    assert str(exc_info.value).startswith("[SKIP] reject-short:")


# --- flag-long and accept both proceed to a real POST --------------------


async def test_ingest_accepts_flag_long_payload(monkeypatch):
    monkeypatch.setattr(
        bulk_ingest, "probe_queue_entry", _probe_stub("flag-long", None, 30000.0)
    )
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/anaheim.m3u8",
        "source_url": "https://example.gov/meeting/3",
        "platform": "granicus",
        "segments": [],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            response = await _ingest(session, payload, "https://example.gov/meeting/3")
    assert response == {"slug": "x", "url": "/m/x", "created": True}


async def test_ingest_accepts_ordinary_payload(monkeypatch):
    monkeypatch.setattr(bulk_ingest, "probe_queue_entry", _probe_stub("accept"))
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/ordinary.mp4",
        "source_url": "https://example.gov/meeting/4",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            response = await _ingest(session, payload, "https://example.gov/meeting/4")
    assert response == {"slug": "x", "url": "/m/x", "created": True}


# --- real fixture: a dead HLS link and a too-short HLS clip --------------
# Synthetic payloads (per CLAUDE.md's convention): the master/variant
# *shape* is the one WO-143/WO-144 confirmed real, only the urls/numbers
# here are made up.


async def test_ingest_refuses_a_real_shaped_dead_hls_link(monkeypatch):
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    master_url = "https://example.granicus.com/path/master.m3u8"
    payload = {
        "video_url": master_url,
        "source_url": "https://example.gov/MediaPlayer.php?clip_id=1",
        "platform": "granicus",
        "segments": [],
    }
    with mock_session({master_url: FakeResponse(status=404, text="")}, post_routes={}):
        with pytest.raises(IngestGateRejected) as exc_info:
            await _ingest(
                None, payload, "https://example.gov/MediaPlayer.php?clip_id=1"
            )
    assert "reject-dead" in str(exc_info.value)
    assert "404" in str(exc_info.value)


async def test_ingest_refuses_a_real_shaped_too_short_hls_clip(monkeypatch):
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    master_url = "https://example.granicus.com/path2/master.m3u8"
    variant_url = "https://example.granicus.com/path2/chunklist.m3u8"
    payload = {
        "video_url": master_url,
        "source_url": "https://example.gov/MediaPlayer.php?clip_id=2",
        "platform": "granicus",
        "segments": [],
    }
    with mock_session(
        {
            master_url: FakeResponse(status=200, text=_SYNTHETIC_MASTER_PLAYLIST),
            variant_url: FakeResponse(
                status=200, text=_SYNTHETIC_TOO_SHORT_VARIANT_PLAYLIST
            ),
        },
        post_routes={},
    ):
        with pytest.raises(IngestGateRejected) as exc_info:
            await _ingest(
                None, payload, "https://example.gov/MediaPlayer.php?clip_id=2"
            )
    assert "reject-short" in str(exc_info.value)
    assert "12.0" in str(exc_info.value)


async def test_ingest_accepts_a_real_shaped_ordinary_hls_clip(monkeypatch):
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    master_url = "https://example.granicus.com/path3/master.m3u8"
    variant_url = "https://example.granicus.com/path3/chunklist.m3u8"
    payload = {
        "video_url": master_url,
        "source_url": "https://example.gov/MediaPlayer.php?clip_id=3",
        "platform": "granicus",
        "segments": [],
    }
    with mock_session(
        {
            master_url: FakeResponse(status=200, text=_SYNTHETIC_MASTER_PLAYLIST),
            variant_url: FakeResponse(
                status=200, text=_SYNTHETIC_LONG_VARIANT_PLAYLIST
            ),
        },
        post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)},
    ):
        async with aiohttp.ClientSession() as session:
            response = await _ingest(
                session, payload, "https://example.gov/MediaPlayer.php?clip_id=3"
            )
    assert response == {"slug": "x", "url": "/m/x", "created": True}


# --- no video_url at all (agenda-only payload) skips the gate entirely ---


async def test_ingest_skips_gate_entirely_when_no_video_url(monkeypatch):
    probe_called = False

    async def _should_not_be_called(*args, **kwargs):
        nonlocal probe_called
        probe_called = True
        raise AssertionError("probe_queue_entry should not run with no video_url")

    monkeypatch.setattr(bulk_ingest, "probe_queue_entry", _should_not_be_called)
    payload = {
        "video_url": None,
        "source_url": "https://example.gov/meeting/agenda-only",
        "platform": "civicclerk",
        "segments": [],
        "agenda_items": [{"title": "Item 1"}],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            response = await _ingest(
                session, payload, "https://example.gov/meeting/agenda-only"
            )
    assert not probe_called
    assert response == {"slug": "x", "url": "/m/x", "created": True}


# --- already_probed=True only skips the probe when segments are present --


async def test_already_probed_with_segments_skips_the_probe(monkeypatch):
    probe_called = False

    async def _should_not_be_called(*args, **kwargs):
        nonlocal probe_called
        probe_called = True

    monkeypatch.setattr(bulk_ingest, "probe_queue_entry", _should_not_be_called)
    payload = {
        "video_url": "https://example.com/real.mp4",
        "source_url": "https://example.gov/meeting/5",
        "platform": "civicclerk",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            response = await _ingest(
                session,
                payload,
                "https://example.gov/meeting/5",
                already_probed=True,
            )
    assert not probe_called
    assert response == {"slug": "x", "url": "/m/x", "created": True}


async def test_already_probed_without_segments_still_probes(monkeypatch):
    """A tier-3 (video, no captions) payload is exactly WO-149's incident
    shape -- already_probed=True alone must not be enough to skip the
    gate when there are no real segments backing it up."""
    monkeypatch.setattr(
        bulk_ingest, "probe_queue_entry", _probe_stub("reject-short", "too short", 10)
    )
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/tier3.mp4",
        "source_url": "https://example.gov/meeting/6",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={}):
        with pytest.raises(IngestGateRejected):
            await _ingest(
                None,
                payload,
                "https://example.gov/meeting/6",
                already_probed=True,
            )


async def test_ingest_default_probes_a_tier1_2_payload_never_probed_before(
    monkeypatch,
):
    """The real gap this WO closes: a tier-1/2 sweep result (real
    segments) was never probed anywhere before reaching _ingest() --
    wo134_confirmed_hits_ingest.py's own _candidate_passes_probe() only
    runs WO-144's probe on a *tier-3* (video, no segments) candidate.
    Without already_probed=True, the default here must still probe a
    segments-bearing payload."""
    monkeypatch.setattr(
        bulk_ingest,
        "probe_queue_entry",
        _probe_stub("reject-short", "59-second camera check clip", 59.0),
    )
    monkeypatch.setattr(bulk_ingest, "append_probe_row", _noop_append_probe_row)
    payload = {
        "video_url": "https://example.com/boardroom.mp4",
        "source_url": "https://example.gov/meeting/7",
        "platform": "civicclerk",
        "segments": [{"start": 0, "end": 1, "text": "hello"}],
    }
    with mock_session({}, post_routes={}):
        with pytest.raises(IngestGateRejected) as exc_info:
            await _ingest(None, payload, "https://example.gov/meeting/7")
    assert "reject-short" in str(exc_info.value)


# --- caller column is logged to the sidecar CSV --------------------------


async def test_ingest_logs_caller_to_sidecar(monkeypatch, tmp_path):
    sidecar = tmp_path / "probe_sidecar.csv"
    monkeypatch.setattr(bulk_ingest, "DEFAULT_SIDECAR_PATH", sidecar)
    monkeypatch.setattr(bulk_ingest, "probe_queue_entry", _probe_stub("accept"))
    payload = {
        "video_url": "https://example.com/ordinary.mp4",
        "source_url": "https://example.gov/meeting/8",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            await _ingest(
                session,
                payload,
                "https://example.gov/meeting/8",
                caller="wo134_confirmed_hits_ingest",
            )
    with sidecar.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["caller"] == "wo134_confirmed_hits_ingest"
    assert rows[0]["verdict"] == "accept"


async def test_ingest_defaults_caller_to_bulk_ingest(monkeypatch, tmp_path):
    sidecar = tmp_path / "probe_sidecar2.csv"
    monkeypatch.setattr(bulk_ingest, "DEFAULT_SIDECAR_PATH", sidecar)
    monkeypatch.setattr(bulk_ingest, "probe_queue_entry", _probe_stub("accept"))
    payload = {
        "video_url": "https://example.com/ordinary2.mp4",
        "source_url": "https://example.gov/meeting/9",
        "platform": "civicclerk",
        "segments": [],
    }
    with mock_session({}, post_routes={_INGEST_URL: FakeResponse(text=_ACCEPT_JSON)}):
        async with aiohttp.ClientSession() as session:
            await _ingest(session, payload, "https://example.gov/meeting/9")
    with sidecar.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["caller"] == "bulk_ingest"


# --- process_one() (bulk_ingest.py's own driver, and the same pipeline
# feed_granicus_auto_transcription.py shells out to) surfaces a gate
# rejection as a clean, loggable failure ------------------------------


async def test_process_one_reports_the_gate_rejection(monkeypatch):
    """feed_granicus_auto_transcription.py has no gate of its own -- it
    shells out to `python scripts/bulk_ingest.py <batch file>`
    (subprocess.run, see that script's main()), which runs this exact
    process_one()/_ingest() pipeline. So proving process_one() refuses a
    reject-dead/reject-short verdict here also proves the Granicus feed
    path is gated, with no change needed in that script."""
    import scripts.bulk_ingest as mod

    class _FakeResult:
        platform = "granicus"
        segments = []
        agenda_items = []
        agenda_link = None
        video_url = "https://example.com/dead.m3u8"

        def model_dump(self):
            return {
                "video_url": self.video_url,
                "source_url": "https://example.gov/meeting/10",
                "platform": self.platform,
                "segments": self.segments,
            }

    class _FakeFinder:
        async def resolve(self, url):
            return _FakeResult()

    monkeypatch.setattr(mod, "detect_platform", lambda url: "granicus")
    monkeypatch.setattr(mod, "get_finder", lambda platform: _FakeFinder())
    monkeypatch.setattr(
        mod,
        "probe_queue_entry",
        _probe_stub("reject-dead", "HLS master playlist returned HTTP 404"),
    )
    monkeypatch.setattr(mod, "append_probe_row", _noop_append_probe_row)

    with mock_session({}, post_routes={}):
        result = await process_one(
            None, "https://example.gov/meeting/10", dry_run=False
        )

    assert result["status"] == "failed"
    assert "[SKIP] reject-dead" in result["detail"]
    assert "HTTP 404" in result["detail"]
