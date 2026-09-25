import shutil

import pytest

from app.platforms.embedded_captions import (
    EmbeddedCaptionsBlocked,
    _pick_smallest_variant,
    _variant_pieces,
    cues_from_ts_file,
    extract_embedded_captions,
    has_real_words,
    probe_embedded_captions,
)

from aiohttp_mock import FakeResponse, mock_session
from conftest import FIXTURES_DIR, load_fixture_bytes


def fixture_path(*parts: str) -> str:
    return str(FIXTURES_DIR.joinpath(*parts))


# WO-1065 (2026-09-25): CEA-608 captions embedded directly in an Invintus
# HLS stream, no separate WebVTT/SRT track. See embedded_captions.py's
# own module docstring for the real investigation.

MASTER_URL = (
    "https://api.v3.invintus.com/StreamURI/hls/4879615486/2026091029/media.m3u8"
)

# The real master playlist, fetched live 2026-09-25 (five video variants,
# each with an I-frame trick-play line).
_MASTER_PLAYLIST = load_fixture_bytes(
    "invintus", "master_oregon_eb_2026091029.m3u8"
).decode()

_ASSET = "https://invintus-otfp.global.ssl.fastly.net/4879615486/83b8d1a5df44cffa1718194466a897f35b3a9be9"
_VARIANT_URL = f"{_ASSET}_160p_30fps.m3u8"


# Synthetic variant playlist: the real one's shape (relative piece names,
# #EXTINF lines), shortened to `piece_count` pieces.
def _variant_playlist(piece_count: int) -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:7"]
    for i in range(piece_count):
        lines.append("#EXTINF:6.006,")
        lines.append(f"{_ASSET.rsplit('/', 1)[1]}_160p_30fps-{i + 1}.ts")
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def _piece_url(i: int) -> str:
    return f"{_ASSET}_160p_30fps-{i + 1}.ts"


def test_pick_smallest_variant_ignores_iframe_streams():
    variant = _pick_smallest_variant(_MASTER_PLAYLIST)
    assert variant == _VARIANT_URL


def test_variant_pieces_reads_extinf_uris():
    pieces = _variant_pieces(_variant_playlist(3))
    assert [p.rsplit("-", 1)[1] for p in pieces] == ["1.ts", "2.ts", "3.ts"]


def test_has_real_words_ignores_bare_digits_and_short_tokens():
    cues = [{"start": 0, "end": 1, "text": "4 a I"}]
    assert has_real_words(cues) is False
    cues = [{"start": 0, "end": 1, "text": "4 a little bit of a protest."}]
    assert has_real_words(cues) is True


@pytest.fixture
def oregon_piece_with_words():
    return load_fixture_bytes(
        "invintus", "embedded_oregon_eb_2026091029_seg100_160p.ts"
    )


@pytest.fixture
def wisconsin_piece_silent():
    return load_fixture_bytes(
        "invintus", "no_captions_wisconsineye_2026091067_seg100_160p.ts"
    )


async def test_probe_stops_at_first_piece_with_words(
    monkeypatch, oregon_piece_with_words
):
    # 4 pieces -> probe checks indices for 25/50/75%, i.e. piece 1, 2, 3.
    # Piece 1 (the first checked) already has real words, so pieces 2/3
    # must never be fetched.
    fetched = []

    async def fake_cues_from_ts_file(path):
        fetched.append(path)
        return [{"start": 0, "end": 1, "text": "a little bit of a protest"}]

    monkeypatch.setattr(
        "app.platforms.embedded_captions.cues_from_ts_file", fake_cues_from_ts_file
    )
    monkeypatch.setattr(
        "app.platforms.embedded_captions.asyncio.to_thread",
        lambda fn, *a: fn(*a),
    )

    routes = {
        MASTER_URL: FakeResponse(status=200, text=_MASTER_PLAYLIST, url=MASTER_URL),
        _VARIANT_URL: FakeResponse(
            status=200, text=_variant_playlist(4), url=_VARIANT_URL
        ),
        _piece_url(1): FakeResponse(
            status=200, raw=oregon_piece_with_words, url=_piece_url(1)
        ),
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            result = await probe_embedded_captions(session, MASTER_URL)

    assert result is True
    assert len(fetched) == 1


async def test_probe_returns_false_after_three_silent_pieces(monkeypatch):
    async def fake_cues_from_ts_file(path):
        return []

    monkeypatch.setattr(
        "app.platforms.embedded_captions.cues_from_ts_file", fake_cues_from_ts_file
    )
    monkeypatch.setattr(
        "app.platforms.embedded_captions.asyncio.to_thread",
        lambda fn, *a: fn(*a),
    )

    piece_count = 4
    routes = {
        MASTER_URL: FakeResponse(status=200, text=_MASTER_PLAYLIST, url=MASTER_URL),
        _VARIANT_URL: FakeResponse(
            status=200, text=_variant_playlist(piece_count), url=_VARIANT_URL
        ),
    }
    for i in range(piece_count):
        routes[_piece_url(i)] = FakeResponse(
            status=200, raw=b"fake-ts-bytes", url=_piece_url(i)
        )

    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            result = await probe_embedded_captions(session, MASTER_URL)

    assert result is False


async def test_probe_returns_none_on_403_and_stops(monkeypatch):
    calls = []

    async def fake_cues_from_ts_file(path):
        calls.append(path)
        return []

    monkeypatch.setattr(
        "app.platforms.embedded_captions.cues_from_ts_file", fake_cues_from_ts_file
    )

    routes = {
        MASTER_URL: FakeResponse(status=403, text="", url=MASTER_URL),
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            result = await probe_embedded_captions(session, MASTER_URL)

    assert result is None
    assert calls == []


async def test_extract_raises_blocked_on_429_with_no_further_requests(monkeypatch):
    routes = {
        MASTER_URL: FakeResponse(status=200, text=_MASTER_PLAYLIST, url=MASTER_URL),
        _VARIANT_URL: FakeResponse(
            status=200, text=_variant_playlist(2), url=_VARIANT_URL
        ),
        _piece_url(0): FakeResponse(status=429, text="", url=_piece_url(0)),
    }

    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            with pytest.raises(EmbeddedCaptionsBlocked):
                await extract_embedded_captions(session, MASTER_URL)


async def test_extract_deletes_temp_file(
    monkeypatch, oregon_piece_with_words, tmp_path
):
    async def fake_cues_from_ts_file(path):
        # File must still exist while ffmpeg (here, the fake) runs on it.
        import os

        assert os.path.exists(path)
        return [{"start": 0, "end": 1, "text": "a little bit of a protest"}]

    monkeypatch.setattr(
        "app.platforms.embedded_captions.cues_from_ts_file", fake_cues_from_ts_file
    )
    monkeypatch.setattr(
        "app.platforms.embedded_captions.asyncio.to_thread",
        lambda fn, *a: fn(*a),
    )

    routes = {
        MASTER_URL: FakeResponse(status=200, text=_MASTER_PLAYLIST, url=MASTER_URL),
        _VARIANT_URL: FakeResponse(
            status=200, text=_variant_playlist(1), url=_VARIANT_URL
        ),
        _piece_url(0): FakeResponse(
            status=200, raw=oregon_piece_with_words, url=_piece_url(0)
        ),
    }

    work_dir = str(tmp_path)
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            cues = await extract_embedded_captions(
                session, MASTER_URL, work_dir=work_dir
            )

    assert len(cues) == 1
    # The temp file created in work_dir must have been cleaned up.
    import os

    assert os.listdir(work_dir) == []


async def test_extract_raises_when_a_piece_cannot_be_fetched():
    # A failed download must not read as "no captions" -- the worker
    # falls back to Whisper only on a real "no words".
    routes = {
        MASTER_URL: FakeResponse(status=200, text=_MASTER_PLAYLIST, url=MASTER_URL),
        _VARIANT_URL: FakeResponse(
            status=200, text=_variant_playlist(2), url=_VARIANT_URL
        ),
        _piece_url(0): FakeResponse(status=500, text="", url=_piece_url(0)),
    }
    with mock_session(routes):
        import aiohttp

        async with aiohttp.ClientSession() as session:
            with pytest.raises(RuntimeError):
                await extract_embedded_captions(session, MASTER_URL)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs real ffmpeg")
def test_cues_from_ts_file_real_oregon_piece_has_real_words():
    path = fixture_path("invintus", "embedded_oregon_eb_2026091029_seg100_160p.ts")
    cues = cues_from_ts_file(path)
    texts = " ".join(c["text"] for c in cues)
    assert "protest" in texts
    assert has_real_words(cues) is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs real ffmpeg")
def test_cues_from_ts_file_real_wisconsin_piece_has_no_words():
    path = fixture_path(
        "invintus", "no_captions_wisconsineye_2026091067_seg100_160p.ts"
    )
    cues = cues_from_ts_file(path)
    assert has_real_words(cues) is False
