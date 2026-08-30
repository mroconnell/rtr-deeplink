"""Speech-to-text engine used by the transcription worker.

A small interface (`TranscriptionEngine`) so the concrete implementation
is swappable later without touching worker/main.py's job loop. v1 default
is self-hosted `faster-whisper` (CPU, CTranslate2-based) rather than a
hosted API -- the worker is already a persistent paid process, so this
avoids a second, per-minute-metered vendor on top of it, and it's the same
base WhisperX later builds real diarization on top of (via
pyannote.audio), so this choice doesn't need revisiting to add that --
just extending. No diarization in v1: every segment's `speaker` stays
None.
"""

import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

# Whisper's initial_prompt biases decoding toward this vocabulary --
# real motivation: a live job on a Cupertino meeting (2026-08-08)
# transcribed "this meeting is adjourned" as "this meeting is a joke",
# a meaning-changing error, not a cosmetic one (see BACKLOG.md). Applied
# fresh to every chunk (not just the first), since each chunk is its own
# transcribe() call -- keeps it short and representative rather than a
# full script, since an overly long/suggestive prompt risks the model
# leaning on it past where it's actually relevant.
MEETING_VOCABULARY_PROMPT = (
    "Local government meeting. Common terms: roll call, public comment, "
    "motion, second, aye, nay, abstain, quorum, agenda item, ordinance, "
    "resolution, city council, public hearing, minutes, adjourned."
)

# How large a gap between two consecutive words' real timestamps has to be
# before it's treated as a genuine VAD-skipped silence rather than ordinary
# word-to-word spacing within one continuous utterance -- see
# _split_segment_on_word_gaps()'s own docstring for why this exists at all.
# Tuned against the real North Kingstown RI case (BACKLOG.md's "Fix
# approach prototyped and empirically validated 2026-08-18" entry):
# confirmed hidden gaps of 25s/83s/668s at real VAD-skip boundaries,
# comfortably clear of normal intra-sentence pauses.
_WORD_GAP_SPLIT_SECONDS = 2.0


def _split_segment_on_word_gaps(seg: Any) -> List[Dict[str, Any]]:
    """faster-whisper's vad_filter=True (see FasterWhisperEngine's own
    docstring for why it's on) fixes hallucination-on-silence, but has its
    own confirmed real bug: it can silently merge two genuinely separate
    real speech bursts, on either side of a VAD-skipped silent stretch,
    into one reported segment -- correct *text*, wildly wrong *timestamp
    range* (real case: a lone word ("So") at 67.5s and real content
    resuming at 732.8s reported as one [66.8s-735.9s] segment). Since this
    app's entire product is deep-linking to an exact timestamp, a wrong
    segment boundary is worse than a missing one.

    Re-splits using the model's own real per-word timestamps
    (word_timestamps=True on the transcribe() call) instead of trusting
    segment.start/segment.end, wherever two consecutive words are further
    apart than _WORD_GAP_SPLIT_SECONDS. `seg.words` is a list of Word
    objects (start, end, word -- word already carries its own leading
    space from the tokenizer, hence "".join() below rather than " ".join()
    -- matches how faster-whisper reconstructs segment.text internally).
    """
    words = list(getattr(seg, "words", None) or [])
    if not words:
        text = seg.text.strip()
        return (
            [{"start": seg.start, "end": seg.end, "text": text, "speaker": None}]
            if text
            else []
        )

    runs: List[List[Any]] = [[words[0]]]
    for prev_word, word in zip(words, words[1:]):
        if word.start - prev_word.end > _WORD_GAP_SPLIT_SECONDS:
            runs.append([])
        runs[-1].append(word)

    result = []
    for run in runs:
        text = "".join(w.word for w in run).strip()
        if text:
            result.append(
                {
                    "start": run[0].start,
                    "end": run[-1].end,
                    "text": text,
                    "speaker": None,
                }
            )
    return result


class TranscriptionEngine(ABC):
    @abstractmethod
    async def transcribe_chunk(self, audio_path: Path) -> List[Dict[str, Any]]:
        """Returns chunk-relative segments ({start, end, text}, seconds
        from 0 at this chunk's own start) -- caller shifts them to
        full-meeting-relative via segment_utils.shift_segments()."""
        raise NotImplementedError


class FasterWhisperEngine(TranscriptionEngine):
    """Loads the model once at construction (worker/main.py instantiates
    this a single time at process startup, reused across every job's every
    chunk) -- reloading a multi-GB-class model per chunk would dominate
    runtime otherwise.

    `model_size` favors speed/memory over chasing the largest/most-accurate
    model: per the product framing behind this feature, most viewers want
    to Ctrl-F to a topic in an otherwise-uncaptioned meeting, not a
    publication-grade transcript. Originally defaulted to "small", but the
    first real deploy OOM-killed on Render's `starter` worker plan (512MB)
    loading it -- confirmed live 2026-08-08, not a hypothetical concern.
    Measured peak RSS locally (isolated venv matching worker/requirements.txt
    exactly, one model per process): "tiny" ~382MB, "base" ~489MB, against a
    67MB baseline with no model loaded at all. "base" was tried first but
    rejected -- only ~23MB of headroom under 512MB locally is too close to
    trust once Render's real container overhead and a different CPU
    architecture are added on top. "tiny" is the real default, with real
    margin (~130MB). Revisit upward only alongside a plan upgrade with
    actual RAM to spare, not by guessing again. `compute_type="int8"` keeps
    CPU memory/time reasonable without a GPU, at some accuracy cost versus
    float16/float32.

    **`vad_filter=True` (Silero VAD), added 2026-08-18 after BACKLOG.md's
    "Fix approach prototyped and empirically validated" entry.** Root
    cause of a confirmed real hallucination pattern (Hermosa Beach,
    Moraine City OH, North Kingstown RI, Redwood City CA and others --
    see that entry and BACKLOG_DONE.md): decoding fixed-length windows
    over genuine dead air/pre-meeting silence with no speech-activity
    gate produces fabricated text once per window (the repeated "Local
    government meeting..."/"Music"/foreign-script loops that pattern),
    not a lower-quality-but-real transcript. `vad_filter=True` is a real
    speech-vs-non-speech classifier (not a volume threshold), so it also
    catches loud-but-non-speech audio (a musical intro), not just literal
    silence -- confirmed live to correctly return zero segments (and run
    ~7x faster, since it skips decoding non-speech at all) on clips that
    previously fabricated content. `condition_on_previous_text=False` is
    defense-in-depth against a hallucination cascading into the next
    window once it starts (confirmed live *not* the cause of the bug
    below, on its own).

    `vad_filter=True` has its own confirmed real bug, independent of the
    fix above: it can silently merge two genuinely separate real speech
    bursts either side of a VAD-skipped silent stretch into one reported
    segment -- correct text, wildly wrong timestamp span (real case: a
    lone word at 67.5s and real content resuming at 732.8s reported as
    one [66.8s-735.9s] segment). Since this app's entire product is
    deep-linking to an exact timestamp, a wrong boundary is worse than a
    missing one -- `word_timestamps=True` plus
    `_split_segment_on_word_gaps()` below fixes this by re-splitting on
    the model's own real per-word timestamps instead of trusting
    `segment.start`/`segment.end`. See that function's own docstring for
    the full validated case.
    """

    def __init__(
        self,
        model_size: str = "tiny",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        language: Optional[str] = None,
    ):
        # Imported lazily so importing this module (e.g. from tests) never
        # requires the real model weights to be downloaded/available.
        from faster_whisper import WhisperModel

        # cpu_threads=0 is CTranslate2's own "let it decide" sentinel (it
        # sizes itself off the visible core count) -- the default here
        # preserves worker/main.py's existing behavior exactly, since that
        # caller never passes this. scripts/transcribe_backlog_locally.py
        # is the one real caller that overrides it, to cap CPU utilization
        # (and the heat that comes with it) on a real Mac running this for
        # hours unattended -- see that script's own --cpu-threads docs for
        # why. Not something worker/main.py's own Render deploy needs: a
        # cloud worker has no fan/thermal concern, and 900s chunks already
        # OOM-constrained model_size down to "tiny" there (see this class's
        # own docstring) rather than needing a CPU-time constraint too.
        # None means faster-whisper's own per-chunk auto-detection, the
        # only behavior this engine had before the parameter existed.
        # A forced code exists because auto-detection decides from the
        # chunk's first seconds and can lock a whole chunk into the wrong
        # language on non-speech openings -- the confirmed Kitchener case
        # (BACKLOG_DONE.md, WO-36 audit): an English meeting transcribed
        # end-to-end as Welsh-script gibberish. worker/main.py never
        # passes this; scripts/transcribe_backlog_locally.py's --language
        # is the one real caller, for operator-chosen re-runs.
        self._language = language
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
        )

    async def transcribe_chunk(self, audio_path: Path) -> List[Dict[str, Any]]:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> List[Dict[str, Any]]:
        segments, _info = self._model.transcribe(
            str(audio_path),
            language=self._language,
            beam_size=5,
            initial_prompt=MEETING_VOCABULARY_PROMPT,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        result: List[Dict[str, Any]] = []
        for seg in segments:
            result.extend(_split_segment_on_word_gaps(seg))
        return result


def build_default_engine() -> TranscriptionEngine:
    return FasterWhisperEngine()


# --- Gemini 3.5 Transcribe engine (local script only, not the cloud worker) -

# Real, live-measured rate, not a guess -- see this class's own docstring
# for the eval that produced these numbers (2026-08-26). 25 audio tokens
# per second of INPUT is Google's published rate
# (ai.google.dev/gemini-api/docs/pricing#gemini-3.5-transcribe).
_GEMINI_AUDIO_TOKENS_PER_SECOND = 25

# Real free-tier ceiling, confirmed live via an actual 429 during that same
# eval: "Quota exceeded for metric: generativelanguage.googleapis.com/
# generate_content_free_tier_input_token_count, limit: 10000". Not
# documented anywhere on ai.google.dev at eval time -- only found by
# hitting it. Tunable via GeminiTranscriptionEngine(tokens_per_minute=...)
# for a paid-tier key, where this ceiling doesn't apply.
_GEMINI_FREE_TIER_TOKENS_PER_MINUTE = 10000

# extract_chunk_audio()/extract_full_audio() (app/platforms/media_probe.py)
# both hardcode `-b:a 32k` mono mp3 -- the only audio this engine is ever
# actually fed in this repo. 32kbps = 4000 bytes/sec, used as a cheap
# pre-call size-based estimate for rate-limiter pacing (no extra ffprobe
# subprocess just to guess a number that only needs to be roughly right --
# see _GeminiRateLimiter's own docstring for why the estimate only has to
# steer the WAIT decision, not be exact).
_MP3_32KBPS_BYTES_PER_SECOND = 4000

# Matches the real error text observed live: "...Please retry in
# 48.034813391s." -- Gemini's own 429 response tells you exactly how long
# to wait, which is a better signal than a generic exponential backoff
# guess. Falls back to backoff only when this doesn't match (a differently
# -worded error, or a non-429 failure).
_RETRY_AFTER_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)

# How large a gap between two consecutive real WORDS' timestamps counts as
# a genuine pause worth splitting into a separate segment, rather than one
# long run-on segment covering the whole chunk. Same value and same
# reasoning as FasterWhisperEngine's _WORD_GAP_SPLIT_SECONDS above --
# Gemini's `word_info` annotations carry real per-word start/end offsets
# the same way faster-whisper's `word_timestamps=True` does, so the same
# gap heuristic applies. Not re-tuned specifically for Gemini's own timing
# behavior (untested whether its word boundaries are more/less granular
# than faster-whisper's) -- revisit if real deep links built from Gemini
# transcripts turn out to have worse segment boundaries than Whisper's.
_GEMINI_WORD_GAP_SPLIT_SECONDS = _WORD_GAP_SPLIT_SECONDS


def _parse_offset_seconds(offset: str) -> float:
    """Gemini's word_info annotations give offsets as strings like
    "1.200s" -- strip the trailing "s" and parse. Raises ValueError on
    anything else, deliberately: a segment with a wrong or missing
    timestamp is worse than one that fails loudly (this app's whole
    product is deep-linking to an exact timestamp -- see media_probe.py's
    own "wrong boundary is worse than a missing one" note for the same
    principle applied to Whisper's segment-merge bug)."""
    return float(offset.rstrip("sS"))


def _extract_retry_after_seconds(exc: Exception) -> Optional[float]:
    match = _RETRY_AFTER_RE.search(str(exc))
    return float(match.group(1)) if match else None


def _group_gemini_words_into_segments(
    words: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Turns Gemini's flat `word_info` annotation list into chunk-relative
    segments, splitting on the same real-silence-gap heuristic
    _split_segment_on_word_gaps() uses for Whisper's per-word timestamps
    (see that function's docstring for the original real bug this
    defends against: a VAD/silence gap getting reported as one segment
    spanning it, which is a wrong deep-link target, not just an
    imprecise one).

    Each `words` entry is already `{"start": float, "end": float, "text":
    str}` (offsets pre-parsed by the caller). Word text is joined with a
    plain space -- unlike faster-whisper's `.word` (which carries its own
    leading space from the tokenizer), Gemini's `word_info.text` is not
    confirmed either way from the one real response inspected during this
    engine's own eval (2026-08-26) to carry embedded leading/trailing
    whitespace, so plain `" ".join()` is the safer default. Flagging this
    per this repo's convention for a schema-confirmed-but-content-
    unconfirmed detail (see CLAUDE.md's "don't claim a caption/data path
    works without a positive example" bullet) -- if a real transcript
    comes out with doubled or missing spaces around punctuation, this is
    the first place to check.
    """
    if not words:
        return []

    runs: List[List[Dict[str, Any]]] = [[words[0]]]
    for prev_word, word in zip(words, words[1:]):
        if word["start"] - prev_word["end"] > _GEMINI_WORD_GAP_SPLIT_SECONDS:
            runs.append([])
        runs[-1].append(word)

    result = []
    for run in runs:
        text = " ".join(w["text"] for w in run).strip()
        if text:
            result.append(
                {
                    "start": run[0]["start"],
                    "end": run[-1]["end"],
                    "text": text,
                    "speaker": None,
                }
            )
    return result


class _GeminiRateLimiter:
    """Client-side leaky-bucket pacing against Gemini's free-tier
    input-token-per-minute quota (see _GEMINI_FREE_TIER_TOKENS_PER_MINUTE's
    own comment for the real 429 that revealed the real limit).
    Proactive, not just reactive-after-a-429 -- lets an unattended batch
    run smoothly against the real ceiling instead of bouncing off it every
    few chunks. `GeminiTranscriptionEngine._transcribe_sync()` still keeps
    a 429 retry as a backstop (see its own docstring) for whenever the
    pre-call size estimate this pacing decision is based on undershoots
    the real per-call token count, or the account's real quota is lower
    than the default assumes.

    Sequential-caller-only: `transcribe_meeting()`'s chunk loop awaits one
    `transcribe_chunk()` at a time, never concurrently, so a simple
    unlocked rolling window is safe here -- this is not meant to be safe
    against concurrent callers.

    Synchronous (`time.sleep`, not `asyncio.sleep`): only ever called from
    `_transcribe_sync()`, which already runs inside `asyncio.to_thread()`
    -- its own dedicated thread, no event loop of its own -- so there is
    no event loop here to yield back to and a plain blocking sleep is both
    correct and simpler than spinning up a throwaway one via
    `asyncio.run()` just to await one coroutine.
    """

    def __init__(self, tokens_per_minute: int):
        self._budget = tokens_per_minute
        self._window: List[tuple] = []  # (monotonic_time, tokens), last 60s

    def _prune(self, now: float) -> None:
        self._window = [(t, n) for t, n in self._window if now - t < 60.0]

    def wait_if_needed(self, estimated_tokens: int) -> None:
        now = time.monotonic()
        self._prune(now)
        used = sum(n for _, n in self._window)
        if used + estimated_tokens <= self._budget:
            return
        # +1s safety margin past the theoretical window edge -- the same
        # reasoning as this file's other real-world margins (e.g.
        # FasterWhisperEngine's RAM headroom): the window boundary is a
        # calculation, not a guarantee, and a call that lands 0.1s early
        # just re-triggers the exact 429 this pacing exists to avoid.
        oldest_time = self._window[0][0] if self._window else now
        wait = 60.0 - (now - oldest_time) + 1.0
        if wait > 0:
            time.sleep(wait)
        self._prune(time.monotonic())

    def record(self, actual_tokens: int) -> None:
        """Logged AFTER a successful call, with the real
        `usage.total_input_tokens` from the response -- not the pre-call
        estimate -- so the ledger self-corrects over a run even though
        the wait decision above only ever had a cheap size-based guess to
        work with."""
        self._window.append((time.monotonic(), actual_tokens))


class GeminiTranscriptionEngine(TranscriptionEngine):
    """Evaluated 2026-08-26 (see CLAUDE_BACKLOG.md's "On-demand
    transcription follow-ups" entry for the full writeup) against real
    audio from two live meetings: got a real, live, currently-shipped
    Whisper `tiny` bug wrong in 9/9 windows ("ADU" heard as "80 use"/"80
    user"/"ADO") that Gemini got right in every window that completed,
    WITHOUT needing `custom_vocabulary` -- the base model already handles
    it, and skipping custom_vocabulary is what keeps real word-level
    timestamps in the response (Gemini's API rejects a request that sets
    both `custom_vocabulary` and `timestamp_granularities` together with a
    400 "custom_vocabulary is incompatible with timestamps" -- confirmed
    live, not documented). Since this app's entire product is deep-linking
    to an exact timestamp, that made the choice easy: this engine never
    sends custom_vocabulary, only ever requests word timestamps.

    **Local-backlog-script use only, not the cloud worker.** The free
    tier's real per-minute token ceiling (see
    _GEMINI_FREE_TIER_TOKENS_PER_MINUTE) makes it a genuine fit for
    `scripts/transcribe_backlog_locally.py`'s occasional, manual,
    much-lower-volume catch-up runs -- real measured cloud-pipeline volume
    the same day (508 meetings / ~4.06M seconds of audio in 14 days, see
    the CLAUDE_BACKLOG.md entry) would blow through the free tier almost
    immediately and isn't what this was built for.

    `tokens_per_minute` defaults to the real observed free-tier ceiling;
    pass a higher value for a paid-tier key (no meaningful cap there at
    this project's realistic scale -- see the CLAUDE_BACKLOG.md entry's
    cost math, ~$345 for that same 14-day cloud-pipeline volume).
    """

    def __init__(
        self,
        model: str = "gemini-3.5-transcribe",
        api_key: Optional[str] = None,
        tokens_per_minute: int = _GEMINI_FREE_TIER_TOKENS_PER_MINUTE,
        max_retries: int = 6,
    ):
        # Imported lazily, same reasoning as FasterWhisperEngine's own
        # lazy `from faster_whisper import WhisperModel` -- importing this
        # module should never require google-genai installed unless this
        # engine is actually constructed.
        from google import genai

        import os

        if not (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        ):
            raise RuntimeError(
                "GeminiTranscriptionEngine needs an API key -- set GEMINI_API_KEY "
                "(or GOOGLE_API_KEY) in the repo's .env, or pass api_key= explicitly. "
                "Get one at https://aistudio.google.com"
            )
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._model = model
        self._limiter = _GeminiRateLimiter(tokens_per_minute)
        self._max_retries = max_retries

    async def transcribe_chunk(self, audio_path: Path) -> List[Dict[str, Any]]:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> List[Dict[str, Any]]:
        import random

        estimated_seconds = audio_path.stat().st_size / _MP3_32KBPS_BYTES_PER_SECOND
        estimated_tokens = int(estimated_seconds * _GEMINI_AUDIO_TOKENS_PER_SECOND)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            self._limiter.wait_if_needed(estimated_tokens)
            try:
                audio_file = self._client.files.upload(file=str(audio_path))
                interaction = self._client.interactions.create(
                    model=self._model,
                    input=[
                        {
                            "type": "audio",
                            "uri": audio_file.uri,
                            "mime_type": audio_file.mime_type,
                        }
                    ],
                    generation_config={
                        "transcription_config": {
                            "language_codes": ["en-US"],
                            # Deliberately no custom_vocabulary -- see this
                            # class's own docstring for why.
                            "mode": {
                                "type": "verbatim",
                                "timestamp_granularities": ["word"],
                            },
                        }
                    },
                )
            except Exception as e:
                last_error = e
                if attempt == self._max_retries - 1:
                    raise
                retry_after = _extract_retry_after_seconds(e)
                if retry_after is not None:
                    delay = retry_after + 2.0  # real margin past the API's own hint
                else:
                    # Same shape as app/utils/retry.py's backoff_delay(),
                    # inlined rather than imported -- app/ deliberately
                    # never depends on worker/, and the reverse isn't true
                    # either (see media_probe.py's docstring for the
                    # one-way rule this preserves), so importing that
                    # helper here would be the wrong direction. A fixed
                    # 60s base (not the media-call constants' 10s) matches
                    # the real observed 429 wait times (26-48s) with
                    # margin, since this failure mode is a token quota
                    # window, not a flaky CDN.
                    delay = min(180.0, 60.0 * (2**attempt) * random.uniform(0.5, 1.5))
                time.sleep(delay)
                continue

            usage = getattr(interaction, "usage", None)
            actual_input_tokens = (
                getattr(usage, "total_input_tokens", None) or estimated_tokens
            )
            self._limiter.record(actual_input_tokens)

            dump = interaction.model_dump()
            steps = dump.get("steps") or []
            if not steps or not steps[0].get("content"):
                # No speech detected in this chunk (silence/non-speech) --
                # a real, valid outcome, not a failure. Matches Whisper's
                # vad_filter=True returning zero segments for the same
                # case (see FasterWhisperEngine's own docstring).
                return []
            annotations = steps[0]["content"][0].get("annotations") or []
            words = [
                {
                    "start": _parse_offset_seconds(a["start_offset"]),
                    "end": _parse_offset_seconds(a["end_offset"]),
                    "text": a["text"],
                }
                for a in annotations
                if a.get("type") == "word_info"
            ]
            return _group_gemini_words_into_segments(words)

        # Unreachable (the loop above always returns or raises), kept as a
        # real value rather than relying on that for the same reason
        # retry_async's own trailing return exists.
        raise last_error or RuntimeError(
            "Gemini transcription failed with no error recorded"
        )
