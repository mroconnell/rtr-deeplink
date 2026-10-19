"""WO-1978: keep PyAV below 19 for the transcription worker.

faster-whisper's decode_audio() calls
`av.open(..., metadata_errors="ignore")`. PyAV 19.0.0 removed that
argument, and from 2026-10-08 every cloud transcription job failed on
chunk 0 with "open() got an unexpected keyword argument
'metadata_errors'" (290 failed jobs in the 24 hours before 2026-10-19).
Measured 2026-10-19 against faster-whisper 1.2.1: av 18.1.0 decodes,
av 19.0.1 raises.

The cap lives in two places that a routine edit could drop: the
hand-appended block of worker/requirements.txt (a `pip-compile` re-run
rewrites the file) and the Dockerfile's upgrade line (WO-11 keeps it
unpinned on purpose). These tests fail if either loses it while
faster-whisper still passes the argument.
"""

import io
import re
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_worker_requirements_cap_av_below_19():
    lines = (ROOT / "worker" / "requirements.txt").read_text().splitlines()
    assert "av<19" in [line.strip() for line in lines]


def test_worker_dockerfile_upgrade_line_caps_av_below_19():
    dockerfile = (ROOT / "worker" / "Dockerfile").read_text()
    upgrade = [
        line
        for line in dockerfile.splitlines()
        if "pip install" in line and "--upgrade" in line
    ]
    assert upgrade, "the Dockerfile's upgrade line is gone"
    assert any('"av<19"' in line for line in upgrade)
    # A bare `av` on the upgrade line would install the newest av (19+).
    assert not any(re.search(r"\sav(\s|$)", line) for line in upgrade)


def test_worker_dockerfile_runs_decode_smoke_check():
    dockerfile = (ROOT / "worker" / "Dockerfile").read_text()
    assert "from faster_whisper.audio import decode_audio" in dockerfile


def test_faster_whisper_decodes_audio_with_installed_av():
    """The same check the Dockerfile runs at build time. Skipped where
    faster-whisper is not installed (CI does not install the worker's
    requirements); meaningful on a worker image or a local Whisper venv."""
    audio = pytest.importorskip("faster_whisper.audio")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(32000))
    buf.seek(0)
    assert len(audio.decode_audio(buf)) == 16000
