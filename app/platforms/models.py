from typing import List, Optional
from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    # Unused by every adapter today (always None) -- forward-compat for a
    # future diarization pass over on-demand-transcribed audio, so that
    # feature won't need another schema touch when it's actually built.
    speaker: Optional[str] = None


class VideoSegment(BaseModel):
    """One playable video file that covers only PART of a meeting -- e.g.
    a Swagit per-agenda-item clip when no single whole-meeting recording
    exists at the source (WO-79; see swagit.py's
    `_parse_swagit_playlist_entries` docstring for the confirmed real
    cases: Yolo County CA, White Plains NY, Apple Valley MN). `seq` is
    the source platform's own real ordering field (Swagit's jwplayer
    playlist `seq`) -- meeting-relative order should be derived from it,
    not from array/document order, which isn't guaranteed to match."""

    url: str
    title: Optional[str] = None
    seq: Optional[int] = None


class AlternateTranscript(BaseModel):
    """A caption track that was found and fetched but not chosen as the
    primary transcript (see `ResolvedMeeting.alternate_transcripts`) --
    typically a different language than TARGET_LANGUAGE. Carries full
    segments (not just a language label) so the frontend can switch the
    displayed transcript client-side with no extra round-trip."""

    language: Optional[str] = (
        None  # ISO 639-1 code detected from actual caption text, same as transcript_language
    )
    segments: List[TranscriptSegment] = []


class ResolvedMeeting(BaseModel):
    platform: str
    source_url: str
    external_id: Optional[str] = (
        None  # namespaced by host, e.g. "granicus:napacity.granicus.com:52945" --
        # must include the host for any multi-tenant platform (a bare
        # per-customer clip/event number collides across customers, see
        # civicclerk.py's/granicus.py's own external_id comments); None
        # until an adapter populates it
    )
    title: Optional[str] = None
    date: Optional[str] = None
    jurisdiction: Optional[str] = None
    # The governing body this specific meeting belongs to ("City
    # Council", "Board of Supervisors"), when the platform exposes it as
    # its own field rather than only inside free text -- Granicus's RSS
    # channel title is the first adapter source (2026-08-23). Flows to
    # the Archive's MeetingPage.meeting_body column, where it beats the
    # jurisdiction-string-split fallback finalize_jurisdiction()
    # produces; None leaves that fallback in charge.
    meeting_body: Optional[str] = None
    # A real, usable street address for where the meeting physically took
    # place, when the platform exposes one AND it actually looks
    # address-shaped -- Legistar's MeetingDetail.aspx "Meeting location"
    # field is the first adapter source (2026-08-30). That field is NOT
    # always an address (confirmed live across four real Legistar
    # customers: Mesa AZ and Naperville carry a meeting-type/room
    # descriptor instead, Chapel Hill has no field at all, only Santa
    # Clara carries a real street address) -- see
    # legistar.py's `_looks_like_street_address()` for the heuristic that
    # decides which is which. None whenever no adapter found one, or the
    # field it found didn't look like a real address. Archive's ingest
    # model silently drops unknown fields (see `video_link`'s own comment
    # below), so no Archive schema change is needed for this field to
    # exist here.
    meeting_location: Optional[str] = None
    video_url: Optional[str] = (
        None  # m3u8/mp4 URL playable by hls.js/<video>, OR a youtube.com/embed/{id} URL
    )
    video_format: Optional[str] = (
        # "m3u8" | "mp4" | "youtube" | "vimeo" | "viebit" | None.
        # "youtube" and "vimeo" each need their own iframe + cross-frame
        # Player API pathway rather than <video>, and "viebit" needs a
        # plain iframe reloaded with ?t= (no API exists there at all) --
        # see app/static/player.js's initVideo() for all four branches.
        None
    )
    segments: List[TranscriptSegment] = []
    # Agenda/chapter markers (Granicus's AgendaViewer.php, CivicClerk's
    # eventBookmarks, Swagit's .playerControl) -- kept separate from
    # `segments` so they're never mistaken for a real transcript.
    # Populated independently of whether a real transcript exists, so a
    # meeting with both shows both (agenda above transcript on the page).
    agenda_items: List[TranscriptSegment] = []
    # A single raw agenda-document URL (not a sentence) -- e.g.
    # generic_fallback.py's best-effort "found a link that looks like the
    # agenda" result. Kept separate from agenda_items (a real per-item
    # timestamp list) so it's never mistaken for one; the frontend renders
    # it as a plain "we think we found an agenda here: <link>" line rather
    # than the clickable timestamp table agenda_items gets.
    agenda_link: Optional[str] = None
    # The fuller "packet" rendition of the same agenda -- the agenda plus
    # every staff report/attachment -- when a source distinguishes it
    # from the plain agenda as a separate document (confirmed real on
    # CivicPlus: `?packet=true` vs. the bare/`?html=true` agenda link,
    # 2026-08-31). Deliberately never conflated with `agenda_link`: a
    # packet can run into the tens of megabytes (rtr-upcoming's own
    # measurement, a sister project solving the same problem, found one
    # real packet at 90 MB), so it needs a plain outbound link rather
    # than the inline iframe `agenda_link` gets. None when a platform
    # doesn't distinguish a packet at all -- most don't, and that's not
    # a gap to fill by guessing.
    packet_link: Optional[str] = None
    # A video we found but cannot play -- no adapter/frontend support for
    # its host (e.g. a Vimeo page link), or just a video-shaped link on a
    # page where nothing playable was found. NEVER placed in `video_url`,
    # which must stay playable (a page URL in video_url breaks the native
    # <video> path silently). Resolver-page-only by design: a link-only
    # result never satisfies the archive push gate (app/main.py's
    # `segments or agenda_items or agenda_link` check), and the Archive's
    # ingest model silently drops unknown fields, so no archive schema
    # change is needed. `video_link_recognized` drives the two-tier UI
    # copy (user's own framing, 2026-08-14): True = the host is a known
    # video platform ("we recognize {host} as a regular video host"),
    # False = a looser video-shaped guess ("we don't recognize {host}...
    # so proceed with caution").
    video_link: Optional[str] = None
    video_link_recognized: bool = False
    # Populated only when an adapter found more than one real video file
    # that together make up the WHOLE meeting, in meeting-relative order,
    # with no single combined recording available at the source (WO-79;
    # confirmed so far: some Swagit tenants, see swagit.py). Empty for
    # every ordinary single-video meeting -- video_url/video_format above
    # still carry the first segment for basic playback either way, so no
    # other platform or existing caller of this field is affected. The
    # on-demand transcription pipeline (app/main.py's submit/feasibility
    # routes, worker/main.py's auto-generation) uses this to build a
    # per-clip chunk plan instead of the usual fixed chunk_size_seconds
    # windows -- see app/platforms/media_probe.py's
    # `probe_multi_clip_chunk_plan()`.
    video_segments: List[VideoSegment] = []
    transcript_language: Optional[str] = (
        None  # ISO 639-1 code detected from actual caption text
    )
    # Other real caption tracks found on the page but not chosen as
    # `segments` -- lets the frontend offer a language switcher instead of
    # silently discarding every track but the best-matching one. Empty
    # when only one usable track was found (the common case).
    alternate_transcripts: List[AlternateTranscript] = []
    # Split so the frontend can place video issues near the player and
    # caption/transcript issues near the transcript, instead of dumping
    # everything into one block above the video regardless of relevance.
    video_warnings: List[str] = []
    transcript_warnings: List[str] = []
    # True only for generic_fallback.py's best-effort results (whether or
    # not it delegated to YouTubeAssetFinder, whose own `platform` field
    # is "youtube", not "unknown" -- checking `platform == "unknown"`
    # alone would silently miss the delegated case, which is actually the
    # *most* common real outcome here). The frontend uses this, not
    # `platform`, to decide whether to show the "we're trying our best,
    # nothing here is guaranteed" framing (see meeting.html/player.js).
    best_effort: bool = False
