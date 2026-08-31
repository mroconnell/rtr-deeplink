"""Regression coverage for the Legistar -> city-YouTube-channel video
fallback (WO-30, app/platforms/youtube_channel.py).

The riskiest thing this repo does: a wrong match publishes some other
meeting's video under a real government's name. So the fixtures here are
**real, live-captured channel listings**, not invented ones --
`tests/fixtures/youtube_channel/*.json` are the actual flat listings
yt-dlp returned for the confirmed channels (four on 2026-08-21, plus
Columbus on 2026-08-30, WO-72) (id, title, duration and live_status,
exactly the fields `extract_flat` provides), trimmed to the most recent N
entries. Every assertion below names a real meeting on a real Legistar
instance.

Two of these cases have independently-known right answers, which is what
makes them worth more than the rest:

* Phoenix 2026-07-01 -> `srjuXI5vGuw` is the exact pair BACKLOG.md
  recorded as the motivating example.
* Baltimore 2026-08-05 Public Health & Environment -> `sfIH-uqHpNI` is
  the video **Baltimore itself attached** to that meeting page as a
  "Recording" link, so the matcher's answer can be checked against the
  city's own, not just against a plausible-looking title.

No network: `find_matches()`/`_pick()` are pure functions over listing
entries, which is why they were split out from the yt-dlp call.
"""

import json
from datetime import date

from app.platforms import youtube_channel as yc

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


def _entries(city: str) -> list:
    return json.loads(load_fixture("youtube_channel", f"{city}_channel_listing.json"))[
        "entries"
    ]


def _match(city: str, body: str, day: str):
    entries = [e for e in _entries(city) if yc.is_publishable(e)]
    y, m, d = (int(p) for p in day.split("-"))
    return yc._pick(yc.find_matches(entries, body, date(y, m, d)))


# --------------------------------------------------------------------
# Title date parsing -- the only per-entry date signal a flat listing has
# --------------------------------------------------------------------


def test_parses_every_real_title_date_shape():
    # All four shapes are real titles copied out of the captured listings:
    # Phoenix/Albuquerque/Baltimore write the month out, Philadelphia uses
    # numerics with a two-digit year, and Baltimore's day is sometimes
    # zero-padded, sometimes not.
    cases = {
        "Phoenix City Council Formal Meeting July 1, 2026": date(2026, 7, 1),
        "Land Use, Planning and Zoning Committee Meeting - June 10, 2026": date(
            2026, 6, 10
        ),
        "District 7 Councilor Connect | August 07, 2026": date(2026, 8, 7),
        "Board of Estimates Meeting, August 5, 2026": date(2026, 8, 5),
        "Committee on Finance 06-4-25": date(2025, 6, 4),
        "Stated Meeting of Philadelphia City Council 6-11-26": date(2026, 6, 11),
        "Committee on Rules 6/3/2026": date(2026, 6, 3),
        "Committee on Rules (5-13-26)": date(2026, 5, 13),
    }
    for title, expected in cases.items():
        assert yc.parse_title_date(title) == expected, title


def test_title_with_no_day_never_produces_a_date():
    # Real Baltimore title -- month and year only. It has to yield None
    # rather than guessing a day, or it could match any hearing that month.
    assert (
        yc.parse_title_date("Board of Municipal & Zoning Appeals Hearing; August 2026")
        is None
    )
    assert yc.parse_title_date("Pet Tips | Spaying and Neutering: Part Two") is None


# --------------------------------------------------------------------
# Phoenix -- the motivating case
# --------------------------------------------------------------------


def test_phoenix_finds_the_known_recording_for_the_known_meeting():
    # phoenix.legistar.com EventId 2651, "City Council Formal Meeting" on
    # 2026-07-01, whose page renders `class="audioDownloadNotAvailableLink"`
    # / "Not Available". BACKLOG.md's own recorded answer is this video id.
    assert _match("phoenix", "City Council Formal Meeting", "2026-07-01")["id"] == (
        "srjuXI5vGuw"
    )


def test_phoenix_picks_the_right_one_of_two_meetings_on_the_same_day():
    # Both are real phoenix.legistar.com events on 2026-06-03, and both
    # have a real video on the channel that day -- date alone would be a
    # coin flip.
    assert _match("phoenix", "City Council Formal Meeting", "2026-06-03")["id"] == (
        "4ubQUiLg7wc"
    )
    assert (
        _match("phoenix", "Public Safety and Justice Subcommittee", "2026-06-03")["id"]
        == "PQ4NYJI3aDs"
    )


def test_phoenix_matches_policy_session_titled_policy_meeting():
    # Phoenix's single Legistar body "City Council Policy Session" is
    # published as "... Policy Session - May 19, 2026" one week and
    # "... Policy Meeting - June 9, 2026" the next. Treating "session" as
    # a distinguishing word declined both of the "Meeting"-titled ones --
    # this is why it's in _GENERIC_TOKENS.
    assert _match("phoenix", "City Council Policy Session", "2026-06-09")["id"] == (
        "Vs-mxvGXYOE"
    )


def test_phoenix_document_only_body_finds_nothing():
    # "General Information Packet" is a real Phoenix Legistar body that
    # publishes documents, never a meeting -- there is no recording of it
    # to find, and the channel has plenty of same-day city videos that a
    # looser matcher could have grabbed.
    assert _match("phoenix", "General Information Packet", "2026-07-02") is None


# --------------------------------------------------------------------
# Baltimore -- ground truth from the city's own attached link
# --------------------------------------------------------------------


def test_baltimore_agrees_with_the_citys_own_attached_recording():
    # baltimore.legistar.com LEGID=5343: Baltimore attached
    # youtu.be/sfIH-uqHpNI to this meeting itself, so this is the one case
    # where the correct answer is known independently of this matcher.
    # Note the body name says "Committee" and the video title doesn't --
    # the soft-token rule exists for exactly this.
    assert (
        _match("baltimore", "Public Health & Environment Committee", "2026-08-05")["id"]
        == "sfIH-uqHpNI"
    )


def test_baltimore_separates_two_different_bodies_on_one_day():
    # LEGID=5267, the same 2026-08-05 as the hearing above. Getting these
    # two swapped is precisely the failure this feature must not have.
    assert _match("baltimore", "Board of Estimates", "2026-08-05")["id"] == (
        "q3s3PKW7NYc"
    )


def test_baltimore_declines_the_adjacent_day_near_miss():
    # Real false positive caught while building this, and the reason the
    # date rule is exact rather than the +/-1 day WO-30 specified: with a
    # one-day window, Baltimore's real 2026-06-01 "Baltimore City Council"
    # meeting matched "City Council Hearing: FY2027 Live Baltimore;
    # June 2, 2026" -- a different hearing that happens to contain the
    # body's own words.
    assert _match("baltimore", "Baltimore City Council", "2026-06-01") is None


def test_baltimore_declines_when_two_real_hearings_tie():
    # Two genuinely different Budget & Appropriations videos on
    # 2026-05-14 ("... FY2027 Taxpayers' Night" and a plain one), against
    # two real Legistar rows for that body that day. Nothing in either
    # title says which is which, so declining is the only honest outcome.
    assert _match("baltimore", "Budget & Appropriations Committee", "2026-05-14") is (
        None
    )


# --------------------------------------------------------------------
# Philadelphia -- numeric dates, and one meeting split across videos
# --------------------------------------------------------------------


def test_philadelphia_picks_one_of_three_committees_meeting_the_same_day():
    # All three are real phila.legistar.com bodies that met on
    # 2025-06-04, each with its own video that day. The Committee on
    # Finance pairing is confirmed against the real MeetingDetail page
    # (ID=1309240, "City of Philadelphia - Meeting of Committee on Finance
    # on 6/4/2025 at 10:00 AM").
    assert _match("phila", "Committee on Finance", "2025-06-04")["id"] == (
        "AMC6xiiJazk"
    )
    assert _match("phila", "Committee on Rules", "2025-06-04")["id"] == "MJ6Myg-TgOs"
    assert _match("phila", "Committee of the Whole", "2025-06-04")["id"] == (
        "RotwiJxxMQc"
    )


def test_philadelphia_takes_part_one_when_a_meeting_is_split():
    # Real: Philadelphia uploaded 2026-06-03's Committee on Finance as
    # "(Part 1)" (3h33m), "(Part 2)" (66s) and "(Part 3)" (206s). These
    # aren't rival candidates, they're one meeting in pieces, so choosing
    # part 1 picks a place in the ordering rather than guessing between
    # meetings.
    assert _match("phila", "Committee on Finance", "2026-06-03")["id"] == (
        "pdBdY8ohffw"
    )


def test_philadelphia_matches_a_slash_formatted_date():
    # Same channel, same week, a different date punctuation entirely.
    assert _match("phila", "Committee on Rules", "2026-06-03")["id"] == "L7cjqbgtwo8"


# --------------------------------------------------------------------
# Albuquerque -- and the specificity floor
# --------------------------------------------------------------------


def test_albuquerque_matches_a_committee_meeting():
    # cabq.legistar.com EventId 3152, 2026-06-10, whose page renders "Not
    # Available" (unlike that instance's full City Council meetings, which
    # do carry a real Granicus link and never reach this code).
    assert (
        _match("cabq", "Land Use, Planning, and Zoning Committee", "2026-06-10")["id"]
        == "r3yOkniCcUQ"
    )


def test_single_word_body_is_never_matched():
    # "President" is a real cabq.legistar.com body, listed alongside the
    # City Council meeting on the same date. One common word is too weak a
    # signal to attribute a recording to a government with.
    assert _match("cabq", "President", "2026-06-01") is None


def test_upcoming_livestream_is_never_matched():
    # Real entry captured live: Albuquerque's channel listed
    # "Albuquerque City Council Meeting - September 9, 2026" as
    # `live_status: "is_upcoming"` with a null duration, weeks ahead of
    # time. Matching one would put an unplayable placeholder on the page.
    upcoming = [
        e
        for e in _entries("cabq")
        if e["live_status"] == "is_upcoming" and e["duration"] is None
    ]
    assert upcoming, "fixture should still contain a real upcoming stream"
    assert not any(yc.is_publishable(e) for e in upcoming)
    assert _match("cabq", "City Council", "2026-09-09") is None


# --------------------------------------------------------------------
# Columbus -- WO-72, 2026-08-30. Same precondition as Phoenix/
# Philadelphia/Baltimore: no `a.videolink` anchor at all on a real
# columbus.legistar.com meeting page (confirmed live via a direct fetch
# of MeetingDetail.aspx?ID=1436780, "Columbus City Council" 8/24/2026).
# `columbus_channel_listing.json` is a real, live-captured merged
# `/videos` + `/streams` listing for youtube.com/cityofcolumbus
# (channel_id UCfttJJ9T5_1W1JewiTJqzqA), captured 2026-08-30.
# --------------------------------------------------------------------


def test_columbus_finds_the_known_recording_for_the_known_meeting():
    # columbus.legistar.com ID=1436780, "Columbus City Council" on
    # 2026-08-24, whose page renders no `a.videolink` anchor at all
    # (confirmed live). The matching video is a past livestream under the
    # channel's `/streams` tab, "Columbus City Council Meeting (8/24/26)".
    assert _match("columbus", "Columbus City Council", "2026-08-24")["id"] == (
        "lJR39FcIhM8"
    )


def test_columbus_matches_a_different_date_for_the_same_body():
    # Same body, a different real meeting three weeks earlier -- checks
    # the date half of the match isn't accidentally hardcoded to one day.
    assert _match("columbus", "Columbus City Council", "2026-06-08")["id"] == (
        "DVTazohiOYs"
    )


def test_columbus_matches_a_non_council_body_the_same_channel_carries():
    # "Special Meeting: German Village Commission (08/05/26)" -- a real,
    # different Columbus body on the same channel, confirming the match
    # isn't just "any Columbus City Council video, any date".
    assert (
        _match("columbus", "German Village Commission", "2026-08-05")["id"]
        == "hkA9-0MUi40"
    )


def test_columbus_declines_a_single_word_body():
    # "President" -- too weak a signal to attribute a recording to a
    # government with, same rule as the Albuquerque case above. Not
    # confirmed as a real cabq-style body name on this channel; this
    # exercises the two-significant-token floor with a body name that
    # simply isn't in the real listing at all, so it must always decline.
    assert _match("columbus", "President", "2026-08-24") is None


# --------------------------------------------------------------------
# The second, independent date check
# --------------------------------------------------------------------


def test_video_date_check_tolerates_real_publication_lag():
    # Real measured lag: Philadelphia's "Committee on Finance 06-4-25"
    # was uploaded 2025-06-10, six days after the meeting, and "Committee
    # on Rules 6/3/2026" seven days after. A +/-1 day check here would
    # have rejected two confirmed-correct matches.
    assert yc.video_date_is_plausible("2025-06-04", "2025-06-10")
    assert yc.video_date_is_plausible("2026-06-03", "2026-06-10")


def test_video_date_check_rejects_a_recording_older_than_the_meeting():
    assert not yc.video_date_is_plausible("2026-07-01", "2026-06-20")
    # One day early is allowed: a late-night meeting archived either side
    # of midnight is real, and youtube.py's own release_date/upload_date
    # preference already drifts by a day on live-streamed meetings.
    assert yc.video_date_is_plausible("2026-07-01", "2026-06-30")


def test_video_date_check_accepts_a_missing_date():
    # youtube.py degrades to a dateless result when YouTube blocks the
    # server outright (the real 2026-08-09 incident). The title's own date
    # already had to match exactly by then -- a missing field shouldn't
    # turn that into a rejection.
    assert yc.video_date_is_plausible("2026-07-01", None)


def test_only_the_five_confirmed_tenants_have_a_channel():
    # The registry is deliberately a short, human-verified list -- every
    # other Legistar instance keeps the pre-existing "no video found"
    # behavior untouched.
    assert yc.has_channel_fallback("phoenix.legistar.com")
    assert yc.has_channel_fallback("PHILA.LEGISTAR.COM")
    assert yc.has_channel_fallback("columbus.legistar.com")
    assert not yc.has_channel_fallback("charlottenc.legistar.com")
    assert not yc.has_channel_fallback("legistar.council.nyc.gov")


async def test_find_channel_match_logs_a_listing_failure(monkeypatch, caplog):
    # 2026-08-28: find_channel_match()'s `except Exception` around
    # _list_channel() used to be silent -- a real production concern
    # given this module's own docstring on the Render-IP-block asymmetry.
    def _boom(channel_id):
        raise RuntimeError("simulated yt-dlp failure")

    monkeypatch.setattr(yc, "_list_channel", _boom)

    with caplog.at_level("WARNING"):
        result = await yc.find_channel_match(
            "phoenix.legistar.com", "City Council Formal Meeting", "2026-07-01"
        )

    assert result is None
    assert any("YouTube channel listing failed" in r.message for r in caplog.records)


# --------------------------------------------------------------------
# Atom feed date corroboration -- WO-30 residual, added 2026-08-29
#
# Synthetic fixtures below (not fetched from a real customer meeting):
# the XML shape -- <entry> carrying sibling <yt:videoId>/<published> tags
# -- is real, confirmed live against Phoenix's actual public feed
# (channel_id=UCx7FQNzOFCbtExt_gRub9JQ,
# https://www.youtube.com/feeds/videos.xml?channel_id=...) on 2026-08-29;
# only the specific video ids/timestamps here are made up for the test.
# --------------------------------------------------------------------

PHOENIX_CHANNEL_ID = "UCx7FQNzOFCbtExt_gRub9JQ"
ATOM_FEED_URL = (
    f"https://www.youtube.com/feeds/videos.xml?channel_id={PHOENIX_CHANNEL_ID}"
)


def _atom_feed(entries: list) -> str:
    items = "\n".join(
        f"<entry><yt:videoId>{video_id}</yt:videoId>"
        f"<published>{published}</published></entry>"
        for video_id, published in entries
    )
    return f"<feed>{items}</feed>"


async def test_fetch_atom_published_date_finds_a_real_shaped_match():
    xml = _atom_feed(
        [
            ("QBkbY4E5GoA", "2026-08-28T17:00:23+00:00"),
            ("srjuXI5vGuw", "2026-07-01T19:04:11+00:00"),
        ]
    )
    routes = {ATOM_FEED_URL: FakeResponse(status=200, text=xml)}

    with mock_session(routes):
        result = await yc._fetch_atom_published_date(PHOENIX_CHANNEL_ID, "srjuXI5vGuw")

    assert result == "2026-07-01"


async def test_fetch_atom_published_date_none_when_video_not_in_feed():
    # Real, binding limit: the feed only carries ~15 most recent uploads,
    # so a video resolved even slightly late won't be there at all.
    xml = _atom_feed([("QBkbY4E5GoA", "2026-08-28T17:00:23+00:00")])
    routes = {ATOM_FEED_URL: FakeResponse(status=200, text=xml)}

    with mock_session(routes):
        result = await yc._fetch_atom_published_date(PHOENIX_CHANNEL_ID, "srjuXI5vGuw")

    assert result is None


async def test_fetch_atom_published_date_none_on_non_200():
    routes = {ATOM_FEED_URL: FakeResponse(status=503, text="")}

    with mock_session(routes):
        result = await yc._fetch_atom_published_date(PHOENIX_CHANNEL_ID, "srjuXI5vGuw")

    assert result is None


async def test_fetch_atom_published_date_none_on_malformed_xml():
    routes = {
        ATOM_FEED_URL: FakeResponse(
            status=200, text="<entry><yt:videoId>srjuXI5vGuw</yt:videoId></entry>"
        )
    }

    with mock_session(routes):
        result = await yc._fetch_atom_published_date(PHOENIX_CHANNEL_ID, "srjuXI5vGuw")

    assert result is None


async def test_find_channel_match_includes_atom_corroboration(monkeypatch):
    entries = [e for e in _entries("phoenix") if yc.is_publishable(e)]
    monkeypatch.setattr(yc, "_list_channel", lambda channel_id: entries)
    xml = _atom_feed([("srjuXI5vGuw", "2026-07-01T19:04:11+00:00")])
    routes = {ATOM_FEED_URL: FakeResponse(status=200, text=xml)}

    with mock_session(routes):
        match = await yc.find_channel_match(
            "phoenix.legistar.com", "City Council Formal Meeting", "2026-07-01"
        )

    assert match.video_id == "srjuXI5vGuw"
    assert match.atom_published_date == "2026-07-01"
