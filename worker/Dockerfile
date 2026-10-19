# ffmpeg/ffprobe are system binaries, not pip packages -- Render's plain
# `runtime: python` buildpack isn't confirmed to include them (most don't),
# so this worker builds as a real Docker image instead, where installing
# them is explicit and verifiable rather than an assumption. Build context
# is the repo root (see render.yaml's `dockerContext: .`), not worker/ --
# this needs app/ and archive/ alongside worker/ itself, since worker/main.py
# imports both directly (see its module docstring for why).
# Pinned to an explicit Debian codename, not the floating `-slim` tag
# (WO-45, 2026-08-23). The floating tag rolled bookworm -> trixie at some
# point with no commit in this repo, which silently moved the ffmpeg this
# worker runs from 5.1.9 to 7.1.5 -- a real behavioural change (see
# app/platforms/media_probe.py's _extract_chunk_once() block comment for
# the measured difference and the 33+ jobs it cost in a day). Pinning
# makes the next such roll a reviewable commit instead of a surprise.
#
# Trixie is deliberately the right side of that roll to be on: bookworm's
# 5.1.9 is strictly worse on the same media (it fails chunk 0 too, where
# 7.1.5 at least gets that far). Only ffmpeg 8.x fixes the underlying
# seek bug, and neither trixie nor trixie-backports carries it yet
# (`apt-cache policy ffmpeg` -> candidate 7:7.1.5-0+deb13u1, no backports
# entry, checked 2026-08-23) -- so revisit this pin when Debian ships 8.x,
# at which point media_probe.py's output-side-seek fallback becomes dead
# weight rather than load-bearing.
FROM python:3.12-slim-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY app app
COPY archive archive
COPY worker worker

# yt-dlp and faster-whisper are deliberately unpinned (WO-11) so the
# workers track upstream -- yt-dlp in particular only works because it's
# continuously maintained against YouTube's blocking. But the pip layer
# above is keyed on requirements.txt's *contents*, so Render's layer
# cache reuses it for as long as that file goes untouched, silently
# freezing both packages at whatever was current at its last edit. This
# layer sits below the code COPYs on purpose: any code-triggered rebuild
# invalidates it, so freshness tracks merge cadence with no manual bump.
# Do not "fix" staleness by pinning these two -- that reverses WO-11.
#
# `av` (PyAV) is upgraded here too, but capped below 19 (WO-1978).
# faster-whisper's decode_audio() calls
# `av.open(..., metadata_errors="ignore")`. PyAV 19.0.0 (released
# 2026-09-29) removed that argument, so with av 19 every chunk fails with
# "open() got an unexpected keyword argument 'metadata_errors'".
# Measured 2026-10-19: av 18.1.0 accepts the call; av 19.0.1 raises.
# faster-whisper 1.2.1 (the newest release) still passes the argument.
# The 2026-10-12 note here had the direction backwards (it blamed an
# OLD av), so adding a bare `av` to this line could not help: it
# installs the newest av, which is 19. Failures began 2026-10-08. Lift
# the cap only after a faster-whisper release stops passing
# metadata_errors; the smoke check below fails the build if that is
# not yet true, so the running workers keep their old image.
RUN pip install --no-cache-dir --upgrade yt-dlp faster-whisper "av<19"

# Build-time smoke check (WO-1978): decode one second of silence through
# faster-whisper's own audio path. A broken faster-whisper/av pair fails
# here, at build time, instead of failing every transcription job after
# deploy (290 failed jobs in the 24 hours before 2026-10-19). Loads no
# model and makes no network request.
RUN python -I -c "import io, wave; from faster_whisper.audio import decode_audio; b = io.BytesIO(); w = wave.open(b, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(32000)); w.close(); b.seek(0); assert len(decode_audio(b)) == 16000; print('faster-whisper audio decode OK')"

CMD ["python", "-m", "worker.main"]
