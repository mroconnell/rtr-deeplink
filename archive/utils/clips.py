"""Turning stored `agenda_items` into schema.org `Clip` "key moments".

Specifically: working out each clip's `endOffset`, which is the one part
of the Clip markup the source data does not hand over directly.

**The real problem this exists for.** A Google Search Console URL
Inspection of a real page (2026-08-21,
/m/san-carlos-ca-2017-11-13-city-council-regular-meeting) reported 12
non-critical `Missing field "endOffset" (optional)` warnings. All 12 were
one consent-calendar block: IQM2 gave the whole block a single timestamp,
so twelve consecutive agenda items all carry `start == 982`, each with
`end` equal to its own `start`. The template's `{% if item.end and
item.end > item.start %}` guard then dropped `endOffset` from every one of
them. Only the *last* item in the run escaped, because the next distinct
item finally advanced the clock to 1056.

**The fix, and why it is more accurate rather than merely quieter.** For
a run of items sharing one start, the next *distinct* start is the real
end of that run -- those twelve consent items genuinely do span 982-1056
collectively, which is exactly what the last item in the run already
claimed on its own. So every item in the run gets 1056, and nothing is
invented.

**Why a Python helper rather than a few more Jinja tags.** The template
already builds `clip_items` inline, so keeping this there was the
smaller-looking option. It loses on both counts that matter: the
computation is a look-ahead over a list (Jinja can express that only via
`loop.index`-plus-slice contortions, in the middle of hand-built JSON that
is already the fiddliest markup in the file), and a template expression
cannot be unit-tested directly -- whereas this function is covered
straightforwardly in tests/test_meeting_page_structured_data.py. The
`clips_unreliable` guard deliberately stays in the template: it is a
duplicate of the visible agenda section's own `unreliable_timestamps`
check, and those two are meant to be read side by side.
"""

from typing import Optional


def clip_entries(agenda_items: Optional[list]) -> list[dict]:
    """`[{"start": int, "end": int|None, "text": str}, ...]` for the
    VideoObject `hasPart` block, in the input's own order.

    `end` resolution, in priority order:

    1. The item's own `end`, when it is genuinely after its `start` --
       the normal case, and the most accurate one (a real 100-200s item
       followed by a gap should end at 200, not at whenever the next item
       happens to begin).
    2. Otherwise the next *distinct* start offset anywhere later in the
       list -- the shared-timestamp run case described in this module's
       docstring.
    3. Otherwise None, and the caller omits `endOffset` entirely. This is
       the genuinely-unknowable tail: the final item of a meeting, whose
       source gave it no real end and which nothing follows. Emitting a
       guess there (the video's duration, say) would be inventing data --
       and this app does not store a duration on the page anyway.

    Items with a missing/non-numeric `start` are skipped rather than
    coerced to 0: a Clip claiming a key moment at 0:00 that isn't one is
    false navigation, the same reasoning behind the template's
    `clips_unreliable` guard.
    """
    normalized: list[dict] = []
    for item in agenda_items or []:
        try:
            start = int(float(item.get("start")))
        except (AttributeError, TypeError, ValueError):
            continue
        if start < 0:
            continue
        try:
            raw_end = item.get("end")
            end = int(float(raw_end)) if raw_end is not None else None
        except (TypeError, ValueError):
            end = None
        normalized.append({"start": start, "end": end, "text": item.get("text") or ""})

    starts = [entry["start"] for entry in normalized]
    for index, entry in enumerate(normalized):
        if entry["end"] is not None and entry["end"] > entry["start"]:
            continue
        entry["end"] = next(
            (later for later in starts[index + 1 :] if later > entry["start"]), None
        )
    return normalized
