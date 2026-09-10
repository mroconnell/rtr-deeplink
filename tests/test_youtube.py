import pytest
import yt_dlp

from app.platforms.youtube import (
    YOUTUBE_CAPTIONS_DISABLED_MARKER,
    YOUTUBE_EMBED_DISABLED_MARKER,
    YOUTUBE_VIDEO_UNAVAILABLE_MARKER,
    YouTubeAssetFinder,
)

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). YouTube's real dependency,
# yt-dlp, is itself out of scope to mock at the network level -- these
# tests monkeypatch YouTubeAssetFinder._extract_info() instead, the exact
# seam resolve_video_id() calls it through, so the yt-dlp call itself
# stays real/untouched and only its *result* is stubbed. The real sample
# data below (video id, title, uploader, upload_date) is the actual
# Oklahoma City PrimeGov meeting resolved live 2026-08-08 -- see
# BACKLOG.md's PrimeGov date/jurisdiction entry.

REAL_VIDEO_ID = "uNDJRR3ywVo"
REAL_TITLE = "Oklahoma City Council Meeting - August 4, 2026"
REAL_UPLOADER = "cityofokc"
REAL_UPLOAD_DATE = "20260805"  # one day after the real meeting -- see BACKLOG.md

MANUAL_VTT = (
    "WEBVTT\n\n"
    "00:00:01.000 --> 00:00:03.000\n"
    "The ticker was appointed.\n\n"
    "00:00:03.000 --> 00:00:06.000\n"
    "Thank you all for joining us today.\n"
)


def _info_with_track(
    *, is_manual: bool, lang: str = "en", vtt: str = MANUAL_VTT
) -> dict:
    return {
        "title": REAL_TITLE,
        "uploader": REAL_UPLOADER,
        "upload_date": REAL_UPLOAD_DATE,
        "_chosen_track": (vtt.encode("utf-8"), lang, is_manual),
    }


def test_extract_video_id_handles_every_real_url_shape():
    cases = {
        f"https://www.youtube.com/watch?v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/watch?feature=share&v={REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://youtu.be/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/embed/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/shorts/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        f"https://www.youtube.com/live/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        # Old Flash-era embed shape -- confirmed live 2026-08-21 on a real
        # open.media page (Goodyear, AZ: goodyearaz.open.media/sessions/
        # 346555), whose own YouTube embed is literally
        # `youtube.com/v/OU-H69iuvLU`, not one of the shapes above.
        f"https://www.youtube.com/v/{REAL_VIDEO_ID}": REAL_VIDEO_ID,
        "https://example.com/not-youtube": None,
    }
    for url, expected in cases.items():
        assert YouTubeAssetFinder.extract_video_id(url) == expected


async def test_resolve_video_id_happy_path_with_manual_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: _info_with_track(is_manual=True),
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://okc.primegov.com/x"
    )

    assert result.platform == "youtube"
    assert result.source_url == "https://okc.primegov.com/x"
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == REAL_TITLE
    # upload_date YYYYMMDD -> ISO. This still falls back to the imperfect
    # upload_date (one day after the real meeting -- see BACKLOG_DONE.md)
    # since _info_with_track() doesn't set release_date -- pins the
    # fallback path specifically, for a video with no release_date at all
    # (e.g. a plain never-live upload). See
    # test_resolve_video_id_prefers_release_date_over_upload_date below
    # for the now-fixed, real-release_date case.
    assert result.date == "2026-08-05"
    # REAL_UPLOADER ("cityofokc") doesn't validate as a real place on its
    # own -- glued, no space, doesn't wordninja-split into anything Census
    # recognizes -- so this is the honest, validated outcome (None), not
    # the old raw-passthrough behavior. See test_jurisdiction_* below for
    # dedicated coverage of _jurisdiction()'s validation logic itself.
    assert result.jurisdiction is None
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.video_format == "youtube"
    assert [s.text for s in result.segments] == [
        "The ticker was appointed.",
        "Thank you all for joining us today.",
    ]
    assert result.transcript_language == "en"
    # Manual captions -- no auto-generated-caption disclaimer.
    assert not any("auto-generated" in w for w in result.transcript_warnings)


async def test_resolve_video_id_prefers_release_date_over_upload_date(monkeypatch):
    # Real bug fixed 2026-08-12: confirmed on this exact real OKC video
    # (id uNDJRR3ywVo, a livestreamed-then-archived meeting, was_live=True)
    # that yt-dlp's real upload_date ("20260805") is one day after the
    # real meeting, while its real release_date ("20260804") matches the
    # video's own title ("...August 4, 2026") exactly -- confirmed on a
    # second independent real sample (Columbus, OH) too, both was_live.
    info = _info_with_track(is_manual=True)
    info["release_date"] = "20260804"
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", lambda video_id: info)

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.date == "2026-08-04"


async def test_resolve_video_id_flags_auto_generated_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: _info_with_track(is_manual=False),
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert any("auto-generated" in w for w in result.transcript_warnings)


async def test_resolve_video_id_flags_non_english_captions(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: _info_with_track(is_manual=True, lang="es"),
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.transcript_language == "es"
    assert any("'es'" in w and "'en'" in w for w in result.transcript_warnings)


async def test_resolve_video_id_no_captions_available(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": REAL_TITLE,
            "uploader": REAL_UPLOADER,
            "upload_date": REAL_UPLOAD_DATE,
        },
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.segments == []
    assert result.transcript_language is None
    assert any("no captions found" in w.lower() for w in result.transcript_warnings)


async def test_resolve_video_id_flags_channel_disabled_captions(monkeypatch):
    # WO-135, 2026-09-09. Real, confirmed-live sample (2026-09-09): Salt
    # Lake City, UT's own YouTube video xA_MRdCBaF4 (an Archive page with
    # no transcript at the time) really has BOTH `subtitles` and
    # `automatic_captions` completely empty in yt-dlp's own metadata --
    # this is the genuine "the channel has captions disabled" signal, not
    # just "nothing in English" (that's the older, more generic
    # test_resolve_video_id_no_captions_available case above, which
    # doesn't set no_captions_at_all at all and must keep getting the
    # older, more generic message).
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": REAL_TITLE,
            "uploader": REAL_UPLOADER,
            "upload_date": REAL_UPLOAD_DATE,
            "playable_in_embed": True,
            "no_captions_at_all": True,
        },
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        "xA_MRdCBaF4", source_url="https://example.com"
    )

    assert result.segments == []
    assert result.transcript_warnings == [YOUTUBE_CAPTIONS_DISABLED_MARKER]


async def test_resolve_video_id_flags_embed_disabled(monkeypatch):
    # Real, confirmed-live sample (2026-09-09): video id 5IoXmnqr72Y (an
    # Archive page with no transcript at the time) really has
    # `playable_in_embed: False` while ALSO having real automatic
    # captions available (`automatic_captions` non-empty, `subtitles`
    # empty) -- confirming embedding restriction and caption availability
    # are independent facts, not "no captions means no embed" or vice
    # versa. The chosen-track VTT content itself is still the fixture's
    # synthetic sample text (this test isolates the embed-disabled wiring,
    # not caption content), but the video id and the playable_in_embed/
    # captions-exist combination are real and observed, not invented.
    info = _info_with_track(is_manual=False)
    info["playable_in_embed"] = False
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", lambda video_id: info)

    result = await YouTubeAssetFinder.resolve_video_id(
        "5IoXmnqr72Y", source_url="https://example.com"
    )

    assert result.video_warnings == [YOUTUBE_EMBED_DISABLED_MARKER]
    # Unaffected: a real caption track is still returned even when the
    # video can't be embedded -- embed restriction and caption
    # availability are independent facts.
    assert result.segments


async def test_resolve_video_id_marks_removed_video_unavailable(monkeypatch):
    # WO-135, 2026-09-09. Real, confirmed-live yt-dlp error message
    # (2026-09-09) for one of the 96 real no-transcript YouTube pages:
    # video id `_RZBcYEbQr4` (an Archive page under
    # /m/2026-05-19-agenda-center) raised exactly this DownloadError.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] _RZBcYEbQr4: This video has been removed by the uploader"
        )

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(
        "_RZBcYEbQr4", source_url="https://example.com"
    )

    assert result.segments == []
    assert result.transcript_warnings == [YOUTUBE_VIDEO_UNAVAILABLE_MARKER]
    assert result.video_url == "https://www.youtube.com/embed/_RZBcYEbQr4"


async def test_resolve_video_id_marks_private_video_unavailable(monkeypatch):
    # Real, confirmed-live yt-dlp error message (2026-09-09) for two
    # separate real Archive pages (video ids VGCR9XxsIVw and
    # Eh1JO9zT_u0) -- both raised this identical DownloadError shape.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] VGCR9XxsIVw: Private video. If the owner of this "
            "video has granted you access, please sign in."
        )

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(
        "VGCR9XxsIVw", source_url="https://example.com"
    )

    assert result.transcript_warnings == [YOUTUBE_VIDEO_UNAVAILABLE_MARKER]


async def test_resolve_video_id_does_not_mark_scheduled_live_event_as_unavailable(
    monkeypatch,
):
    # Real, confirmed-live yt-dlp error message (2026-09-09) for a real
    # Archive page (bossier-city-la-...-jul-07-2026, video id
    # 6I6Mk2SlgaI) whose meeting is simply scheduled but hasn't started
    # streaming yet -- NOT a permanent failure (the exact same video will
    # resolve fine once it goes live), so this must degrade to the
    # existing generic "blocked" message, never the permanent marker.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] 6I6Mk2SlgaI: This live event will begin in a few moments."
        )

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(
        "6I6Mk2SlgaI", source_url="https://example.com"
    )

    assert result.transcript_warnings != [YOUTUBE_VIDEO_UNAVAILABLE_MARKER]
    assert any(
        "blocking automated caption requests" in w for w in result.video_warnings
    )


async def test_resolve_video_id_missing_upload_date_leaves_date_none(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": REAL_TITLE,
            "uploader": REAL_UPLOADER,
            "upload_date": None,
        },
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.date is None


async def test_resolve_video_id_degrades_to_playable_meeting_on_download_error(
    monkeypatch,
):
    # Real production incident, 2026-08-09 (see BACKLOG.md): YouTube's
    # anti-bot check blocks Render's server IP outright, regardless of
    # which internal yt-dlp client is used. Previously any DownloadError
    # here raised and killed the whole resolve -- now it degrades to a
    # real, playable ResolvedMeeting instead, since embedding only ever
    # needed the video id, never yt-dlp. This also lets a delegating
    # adapter's own metadata (e.g. lims.py) still get used -- resolve_
    # video_id() failing outright previously threw that away too.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError("Sign in to confirm you're not a bot")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.video_format == "youtube"
    assert result.title is None
    assert result.segments == []
    assert any(
        "blocking automated caption requests" in w for w in result.video_warnings
    )
    assert any("No transcript available" in w for w in result.transcript_warnings)


async def test_resolve_video_id_degrades_on_caption_fetch_http_error(monkeypatch):
    # Real, live-reproduced 2026-08-29 (BACKLOG_DONE.md): a week after the
    # 2026-08-22 bulk-resolve YouTube IP-block incident, a single,
    # isolated resolve() still hit yt_dlp.networking.exceptions.HTTPError
    # (429 Too Many Requests) from _pick_caption_track()'s own
    # `ydl.urlopen(...).read()` call for the caption track file -- a
    # different exception type than the anti-bot DownloadError above, but
    # from the same real cause (YouTube blocking this app's requests),
    # previously uncaught since it's raised by a direct network call the
    # extractor makes *after* extract_info() itself succeeds, not part of
    # extraction. Must degrade the same way DownloadError does, not crash
    # the whole resolve. Uses the shared yt_dlp.utils.YoutubeDLError base
    # directly (both DownloadError and the real HTTPError subclass it)
    # rather than constructing a real HTTPError, which needs a real
    # Response object -- the except clause catches the base class
    # specifically so it doesn't matter which subclass is raised.
    def _raise(video_id):
        raise yt_dlp.utils.YoutubeDLError("HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)

    result = await YouTubeAssetFinder.resolve_video_id(
        REAL_VIDEO_ID, source_url="https://example.com"
    )

    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.video_format == "youtube"
    assert result.segments == []
    assert any(
        "blocking automated caption requests" in w for w in result.video_warnings
    )


async def test_resolve_video_id_raises_when_no_info_returned(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", lambda video_id: None)

    with pytest.raises(ValueError, match="no info returned by yt-dlp"):
        await YouTubeAssetFinder.resolve_video_id(
            REAL_VIDEO_ID, source_url="https://example.com"
        )


async def test_resolve_delegates_to_resolve_video_id_for_a_standalone_url(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: _info_with_track(is_manual=True),
    )

    url = f"https://www.youtube.com/watch?v={REAL_VIDEO_ID}"
    result = await YouTubeAssetFinder().resolve(url)

    # A standalone YouTube URL keeps itself as source_url (no delegating
    # platform involved), unlike PrimeGov's override.
    assert result.source_url == url


async def test_resolve_raises_for_a_non_youtube_url():
    with pytest.raises(ValueError, match="Could not find a YouTube video ID"):
        await YouTubeAssetFinder().resolve("https://example.com/not-youtube")


# check_permanent_failure() -- the metadata-only precheck WO-135
# (2026-09-09) added for scripts/fetch_youtube_transcripts.py to use
# BEFORE any real (rate-limited) transcript request. Reuses the exact
# same _extract_info()/_is_permanently_gone() seams as resolve_video_id()
# itself, so these tests mirror the ones above rather than duplicating
# real samples.


def test_check_permanent_failure_flags_captions_disabled(monkeypatch):
    # Real, confirmed-live sample -- same xA_MRdCBaF4 (Salt Lake City, UT)
    # video as test_resolve_video_id_flags_channel_disabled_captions above.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": REAL_TITLE,
            "playable_in_embed": True,
            "no_captions_at_all": True,
        },
    )
    transcript_marker, video_marker = YouTubeAssetFinder.check_permanent_failure(
        "xA_MRdCBaF4"
    )
    assert transcript_marker == YOUTUBE_CAPTIONS_DISABLED_MARKER
    assert video_marker is None


def test_check_permanent_failure_flags_video_gone(monkeypatch):
    # Real, confirmed-live yt-dlp error -- same _RZBcYEbQr4 sample as
    # test_resolve_video_id_marks_removed_video_unavailable above.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] _RZBcYEbQr4: This video has been removed by the uploader"
        )

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    transcript_marker, video_marker = YouTubeAssetFinder.check_permanent_failure(
        "_RZBcYEbQr4"
    )
    assert transcript_marker == YOUTUBE_VIDEO_UNAVAILABLE_MARKER
    assert video_marker is None


def test_check_permanent_failure_does_not_flag_scheduled_live_event(monkeypatch):
    # Real, confirmed-live yt-dlp error -- same 6I6Mk2SlgaI sample as
    # test_resolve_video_id_does_not_mark_scheduled_live_event_as_unavailable
    # above: a transient, not-yet-started scheduled stream must never be
    # recorded as a permanent failure.
    def _raise(video_id):
        raise yt_dlp.utils.DownloadError(
            "ERROR: [youtube] 6I6Mk2SlgaI: This live event will begin in a few moments."
        )

    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _raise)
    transcript_marker, video_marker = YouTubeAssetFinder.check_permanent_failure(
        "6I6Mk2SlgaI"
    )
    assert transcript_marker is None
    assert video_marker is None


def test_check_permanent_failure_flags_embed_disabled(monkeypatch):
    # Real, confirmed-live sample -- same 5IoXmnqr72Y video as
    # test_resolve_video_id_flags_embed_disabled above (playable_in_embed
    # False, real automatic captions present so no_captions_at_all False).
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {"playable_in_embed": False, "no_captions_at_all": False},
    )
    transcript_marker, video_marker = YouTubeAssetFinder.check_permanent_failure(
        "5IoXmnqr72Y"
    )
    assert transcript_marker is None
    assert video_marker == YOUTUBE_EMBED_DISABLED_MARKER


def test_check_permanent_failure_returns_none_for_a_healthy_video(monkeypatch):
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: _info_with_track(is_manual=True),
    )
    assert YouTubeAssetFinder.check_permanent_failure(REAL_VIDEO_ID) == (None, None)


# _jurisdiction() coverage. Real, live examples throughout -- a CivicPlus
# AgendaCenter multi-candidate scan (2026-08-27) surfaced real government
# channels shaped both ways ("Roosevelt City", "Village of Angel Fire, New
# Mexico") and real *wrong*-video incidents whose uploader name would have
# gone straight onto a public page unvalidated before this fix: a tenant's
# page linked CivicPlus's own recruiting video ("CivicPlus"), a community
# advocacy org's video instead of an official meeting ("Hamden Action
# NOW"), and a local news station's clip ("KSAT 12") -- see BACKLOG_DONE.md.
@pytest.mark.parametrize(
    "uploader,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        # Glued channel-handle shape -- doesn't wordninja-split into
        # anything Census recognizes, so this is an honest decline, not a
        # bug (matches vimeo.py's own "cityofokc"-shaped precedent).
        ("cityofokc", None),
        # Already well-formed, validates as-is.
        ("Roosevelt City", "Roosevelt City"),
        ("City Of Avenal", "City Of Avenal, CA"),
        # Glued with a real entity prefix -- validated_label_extract()
        # strips "County of" and resolves the real place underneath.
        ("CountyofJackson", "Jackson"),
        # Already "Name, State" shaped -- the comma-branch, checked
        # directly against real place/county data rather than run through
        # the glued-label path (which rejects any comma outright).
        (
            "Village of Angel Fire, New Mexico",
            "Village of Angel Fire, New Mexico",
        ),
        # The real incidents this fix exists for -- a vendor's own
        # channel, an unrelated community org, a news station. All three
        # previously flowed straight through as `jurisdiction` verbatim.
        ("CivicPlus", None),
        ("Hamden Action NOW", None),
        ("KSAT 12", None),
        # A comma-shaped name whose base doesn't validate as a real place
        # -- the comma alone isn't enough to trust it.
        ("Some Random Channel, Not A Place", None),
        # WO-70 (2026-08-30, BACKLOG.md's "already 'X, State'-shaped"
        # entry): "Medina" alone is real in 6 states (MN, ND, OH, TN, WA,
        # NY per places.csv), so it fails the base-validates-on-its-own
        # branch above -- but the channel name already names its own
        # state directly, and Minnesota genuinely is one of Medina's 6
        # real states, so `resolve_claimed_state()` accepts it. Modeled
        # on the real, confirmed-live Vimeo account "City of Medina,
        # Minnesota" (vimeo.com/user23531710) -- YouTube itself has no
        # confirmed real "Medina" channel yet, so this specific pairing
        # is synthetic, built from that same real, verified place/state
        # fact rather than an invented one.
        ("City of Medina, Minnesota", "City of Medina, Minnesota"),
        # Same bare name, an INCORRECT claimed state -- "Medina" is not a
        # real incorporated place in Texas at all (confirmed: places.csv
        # has no TX row for it; only Medina COUNTY is real there, per
        # counties.csv). Must still decline, not false-accept off the
        # back of the same-named county.
        ("City of Medina, Texas", None),
        # Institutional-suffix reuse, added 2026-08-29: these are the
        # exact real account names that motivated
        # jurisdiction_enrich.strip_institutional_suffix() on the Vimeo
        # side (BACKLOG_DONE.md) -- a YouTube channel's `uploader` name is
        # the identical kind of free-text account display name, so the
        # same national K-12 naming convention applies here too, not just
        # on Vimeo.
        ("Peters Township School District", "Peters Township"),
        ("Hopkins Public Schools", "Hopkins"),
        ("Jefferson Parish Schools", "Jefferson Parish"),
    ],
)
def test_jurisdiction_validates_before_trusting_the_uploader_name(uploader, expected):
    assert YouTubeAssetFinder._jurisdiction(uploader) == expected


async def test_resolve_video_id_jurisdiction_is_validated_end_to_end(monkeypatch):
    """Confirms _jurisdiction() is actually wired into resolve_video_id()
    -- the parametrized test above covers the validation logic itself in
    isolation, this pins that the real path uses it."""
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Working at CivicPlus",
            "uploader": "CivicPlus",
            "upload_date": "20161202",
        },
    )

    result = await YouTubeAssetFinder.resolve_video_id(
        "7TFZ6k6vbAk", source_url="https://example.com"
    )

    assert result.jurisdiction is None


def test_first_cue_start_logs_a_parse_failure(monkeypatch, caplog):
    # 2026-08-28: _first_cue_start()'s except Exception used to be silent.
    import app.platforms.youtube as youtube_module

    def _boom(text):
        raise ValueError("simulated parse failure")

    monkeypatch.setattr(youtube_module, "parse_vtt", _boom)

    with caplog.at_level("WARNING"):
        result = YouTubeAssetFinder._first_cue_start(
            b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi"
        )

    assert result is None
    assert any("first-cue-start parse failed" in r.message for r in caplog.records)
