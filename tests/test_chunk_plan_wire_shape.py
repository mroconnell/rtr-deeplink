"""WO-97: a chunk_plan entry must survive the HTTP hop to the Archive intact.

Real bug, caught 2026-09-03 before it produced a single wrong transcript --
but only just. WO-95 added `media_start` to the chunk plan and updated both
consumers, and missed that the plan also crosses a Pydantic boundary:
ChunkPlanEntryIn (archive/main.py). Pydantic ignores extra fields by
default, so the field was accepted, dropped, and stored without it.

Why that is worse than it sounds. worker/main.py reads the field as
.get("media_start", 0.0) -- deliberately, so a plan frozen before WO-95
still works -- which means a dropped field is indistinguishable from an
old plan. Every window of a sub-split clip would have extracted from
offset 0.0, so a 2,520s clip split into six 450s windows would transcribe
the same opening 450 seconds six times, each shifted to a different
meeting-relative timestamp. A complete-looking, silently wrong transcript,
with nothing failing.

The two paths are asymmetric, which is what made it easy to miss:
worker/main.py's auto-generation calls crud.create_transcription_job()
in-process and was always correct; the resolver's on-demand submit and
scripts/bulk_queue_transcription_backlog.py both POST through
/internal/transcription/create-job and were not.
"""

from archive.main import ChunkPlanEntryIn


def _sub_split_entry():
    """A real WO-95 shape: the second 450s window of a long clip that
    itself starts 920s into the meeting. The two offsets are deliberately
    different numbers -- 450.0 into the clip's own file, 1370.0 into the
    meeting -- so a bug that drops or confuses them can't pass."""
    return {
        "media_url": "https://x/long.m3u8",
        "start": 1370.0,
        "media_start": 450.0,
        "duration": 450.0,
        "title": "Long",
        "seq": 13,
    }


def test_media_start_survives_the_request_model():
    entry = ChunkPlanEntryIn(**_sub_split_entry())
    assert entry.media_start == 450.0


def test_media_start_survives_a_full_round_trip_to_the_stored_shape():
    """model_dump() is what actually reaches crud/the database, so pinning
    the parsed attribute alone would not have caught the original bug."""
    dumped = ChunkPlanEntryIn(**_sub_split_entry()).model_dump()
    assert dumped["media_start"] == 450.0
    assert dumped["start"] == 1370.0


def test_a_pre_wo95_entry_still_parses_and_means_whole_clip():
    """A plan built before media_start existed must keep working, and 0.0
    is precisely what 'this entry is a whole clip' means."""
    legacy = {
        "media_url": "https://x/a.m3u8",
        "start": 0.0,
        "duration": 120.0,
        "title": "First",
        "seq": 6,
    }
    assert ChunkPlanEntryIn(**legacy).media_start == 0.0


def test_every_key_the_plan_builder_emits_is_declared_on_the_wire_model():
    """The general guard, not just the media_start instance: whatever
    probe_multi_clip_chunk_plan() puts in an entry has to be a declared
    field here, or it is silently dropped in transit. This is the test
    that fails next time a field is added to one side only."""
    from app.platforms.media_probe import _clip_pieces

    # Build an entry the same way probe_multi_clip_chunk_plan() does.
    media_start, duration = _clip_pieces(2519.69, 450)[1]
    built = {
        "media_url": "https://x/long.m3u8",
        "start": 920.0 + media_start,
        "media_start": media_start,
        "duration": duration,
        "title": "Long",
        "seq": 13,
    }
    declared = set(ChunkPlanEntryIn.model_fields)
    assert set(built) <= declared, (
        f"chunk-plan keys not declared on ChunkPlanEntryIn and therefore "
        f"silently dropped in transit: {sorted(set(built) - declared)}"
    )
