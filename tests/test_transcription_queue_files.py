"""Well-formedness guards on the auto-transcription queue text files.

These are plain URL lists, appended to by hand and by sweeps of harvested
data, then popped from the top by
`scripts/feed_tier3_auto_transcription.py` /
`scripts/feed_granicus_auto_transcription.py`. Nothing validated them, and
the 2026-08-22 hygiene pass found 52 bad rows in the tier-3 file: URLs
carried in from a Wayback/CDX sweep that had been scraped out of *rendered
page text*, so they arrived with the damage that text wrapping does to a
long URL -- query strings cut off mid-parameter (`...&Me`, `...&MediaPositi`,
`...&CssClas`), hostnames chopped off the front (`cacityca.iqm2.com` for
`santamonicacityca.iqm2.com`), soft hyphens injected mid-token
(`santamon-icacityca`, `Css-Class`), and HTML escape leftovers
(`&amp`, `&quot;`, `%5C`, `%0A`, `%0D`, zero-width joiners).

The damage is invisible to the feeder -- every one of those rows resolves
to *something* (IQM2 and Swagit both wildcard their DNS, so a chopped
hostname still answers) and simply yields no video, so a bad row looks
exactly like a meeting that has aged out. That is what let 52 of them sit
in the queue unnoticed. These tests fail the build instead.

Deliberately shape-only: they assert nothing about whether a meeting is
still *live* (that needs the network and changes under us), only that a
row is structurally a URL this repo's adapters could act on.
"""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.utils.url_normalize import normalize_url

REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE_FILES = [
    REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt",
    REPO_ROOT / "scripts" / "granicus_auto_transcription_queue.txt",
]

# Percent-encoded control/quote characters that only ever arrive by scraping
# a URL out of rendered text or out of an HTML attribute -- never part of a
# real meeting URL.
SCRAPE_ARTIFACTS = {
    "%5C": "backslash",
    "%22": "double quote",
    "%0A": "newline",
    "%0D": "carriage return",
    "%E2%80%8B": "zero-width space",
    "%E2%80%8C": "zero-width non-joiner",
}

# Query keys that legitimately appear with no `=` at all in real rows.
VALUELESS_OK = {
    "Frame",
    "MediaPosition",
    "CssClass",
    "Agenda",
    "path",
    "Print",
    "Search",
    "Options",
}


def _rows(path: Path) -> list[tuple[int, str]]:
    """(line number, URL) for every non-blank line.

    A row is a bare URL, or `URL<TAB>SOURCE_URL` when the queued URL is a
    bare video link discovered via a different page (see
    `scripts/feed_tier3_auto_transcription.py`'s `_parse_queue_line()` --
    same split, kept in sync deliberately rather than imported, since this
    module also covers `granicus_auto_transcription_queue.txt`, which the
    tab convention was never extended to). Every shape check below is
    about the video URL itself, never the source-page override.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [(i, ln.split("\t", 1)[0]) for i, ln in enumerate(text.split("\n"), 1) if ln]


def _ids(path: Path) -> str:
    return path.name


@pytest.fixture(params=QUEUE_FILES, ids=_ids)
def queue_file(request) -> Path:
    return request.param


def test_every_row_is_an_absolute_http_url(queue_file: Path) -> None:
    bad = []
    for i, url in _rows(queue_file):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            bad.append(f"{queue_file.name}:{i}: {url}")
    assert not bad, "rows missing a scheme or host:\n" + "\n".join(bad)


def test_no_row_has_leading_or_trailing_whitespace(queue_file: Path) -> None:
    bad = [
        f"{queue_file.name}:{i}: {url!r}"
        for i, url in _rows(queue_file)
        if url != url.strip()
    ]
    assert not bad, "rows with stray whitespace:\n" + "\n".join(bad)


def test_no_row_ends_with_a_dangling_query_separator(queue_file: Path) -> None:
    """A row ending in `?` or `&` lost whatever followed it."""
    bad = [
        f"{queue_file.name}:{i}: {url}"
        for i, url in _rows(queue_file)
        if url.endswith(("?", "&"))
    ]
    assert not bad, "rows ending mid-query-string:\n" + "\n".join(bad)


def test_no_row_carries_html_escape_leftovers(queue_file: Path) -> None:
    """`&amp`/`&quot` in a query string means the URL was read out of HTML."""
    bad = []
    for i, url in _rows(queue_file):
        query = urlparse(url).query
        if re.search(r"(?<![A-Za-z0-9])(amp|quot)(?:$|[=&])", query):
            bad.append(f"{queue_file.name}:{i}: {url}")
    assert not bad, "rows with HTML-escaped separators:\n" + "\n".join(bad)


def test_no_row_carries_scraped_control_characters(queue_file: Path) -> None:
    bad = []
    for i, url in _rows(queue_file):
        upper = url.upper()
        for token, name in SCRAPE_ARTIFACTS.items():
            if token in upper:
                bad.append(f"{queue_file.name}:{i}: stray {name} ({token}): {url}")
    assert not bad, "rows with scrape artifacts:\n" + "\n".join(bad)


def test_no_query_string_ends_mid_parameter(queue_file: Path) -> None:
    """The `...&Me` / `...&MediaPositi` / `...&CssClas` shape.

    A trailing pair with no `=` and a key that is not one of the handful
    that really do appear bare is a query string that was cut off.
    """
    bad = []
    for i, url in _rows(queue_file):
        query = urlparse(url).query
        if not query:
            continue
        last = query.split("&")[-1]
        if "=" not in last and last not in VALUELESS_OK:
            bad.append(f"{queue_file.name}:{i}: truncated '&{last}': {url}")
    assert not bad, "rows whose query string was cut off:\n" + "\n".join(bad)


def test_no_duplicate_rows(queue_file: Path) -> None:
    seen: dict[str, int] = {}
    bad = []
    for i, url in _rows(queue_file):
        if url in seen:
            bad.append(f"{queue_file.name}:{i}: duplicate of line {seen[url]}: {url}")
        else:
            seen[url] = i
    assert not bad, "duplicate rows:\n" + "\n".join(bad)


def test_no_double_slash_in_path(queue_file: Path) -> None:
    """`host//Meeting.aspx` -- a join bug upstream, not a real path."""
    bad = [
        f"{queue_file.name}:{i}: {url}"
        for i, url in _rows(queue_file)
        if "//" in urlparse(url).path
    ]
    assert not bad, "rows with a doubled slash in the path:\n" + "\n".join(bad)


def test_iqm2_rows_carry_a_numeric_meeting_identifier(queue_file: Path) -> None:
    """`app/platforms/iqm2.py` keys off `MeetingID=`/`ID=` being numeric.

    A row that lost it (`...&ID=3410.City`) resolves to the tenant's
    generic portal page rather than a meeting, and yields no video.
    """
    bad = []
    for i, url in _rows(queue_file):
        p = urlparse(url)
        if "iqm2.com" not in (p.netloc or "").lower():
            continue
        q = parse_qs(p.query, keep_blank_values=True)
        meeting = q.get("MeetingID", [""])[0]
        legifile = q.get("ID", [""])[0]
        if not (meeting.isdigit() or legifile.isdigit()):
            bad.append(f"{queue_file.name}:{i}: {url}")
    assert not bad, "IQM2 rows with no usable numeric id:\n" + "\n".join(bad)


def test_escribe_rows_carry_a_full_guid(queue_file: Path) -> None:
    """eScribe's `Id` is a 36-char GUID; a short one is a truncated row."""
    guid = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
    )
    bad = []
    for i, url in _rows(queue_file):
        p = urlparse(url)
        if "escribemeetings.com" not in (p.hostname or ""):
            continue
        ident = parse_qs(p.query, keep_blank_values=True).get("Id", [""])[0]
        if not guid.fullmatch(ident):
            bad.append(f"{queue_file.name}:{i}: Id={ident!r}: {url}")
    assert not bad, "eScribe rows without a full GUID:\n" + "\n".join(bad)


def test_civicclerk_rows_use_the_event_media_shape(queue_file: Path) -> None:
    bad = []
    for i, url in _rows(queue_file):
        p = urlparse(url)
        if "civicclerk.com" not in (p.hostname or ""):
            continue
        if not re.fullmatch(r"/event/\d+/media", p.path):
            bad.append(f"{queue_file.name}:{i}: {url}")
    assert not bad, "CivicClerk rows not shaped /event/<id>/media:\n" + "\n".join(bad)


# WO-205 parked 106 long (>90 min) meetings in this file after swapping each
# for a shorter meeting of the same government. WO-212 (2026-09-11): two
# later rebases resolved the queue file as "union of both sides" and put
# 103 of them straight back, next to their substitutes. A line in the
# deferred file is a deliberate deletion; this test makes a union that
# resurrects one fail the build instead of doubling the Whisper hours.
#
# Ryan's rule changed 2026-09-12: length alone no longer defers a line --
# a long-only video now gets queued to tier 3 anyway rather than parked
# here (see CLAUDE.md's preamble "Long-only videos" bullet). This file's
# job has narrowed to WO-266-style parked lines (a government that
# already has a transcript elsewhere) and whatever WO-205/WO-212 already
# parked; it is no longer where a merely-long meeting goes.
#
# WO-280 (2026-09-12): the comparison below used to be a bare string
# match between a queue row's URL and a deferred row's URL. That only
# catches a re-added line when the two files spell the SAME meeting's
# URL identically byte-for-byte. WO-259 part 2's rebase re-added a real
# 2h55m Lake Havasu City, AZ line this way and the guard did not fire --
# the agent's own hand check caught it before it was ever committed, so
# nothing bad landed, but the guard's job is to make that check
# unnecessary. Comparing `normalize_url()`-normalized URLs instead (the
# same identity key `scripts/feed_tier3_auto_transcription.py` already
# uses before every real ingest -- see its own `normalized = normalize_
# url(url)` call) closes the gap: a queue row that differs from a
# deferred row only by scheme (http/https), a trailing slash, or query-
# parameter order is still caught as the same meeting.
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
TIER3_QUEUE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"


def _deferred_urls() -> set[str]:
    if not DEFERRED_FILE.exists():
        return set()
    return {
        ln.split("\t", 1)[0].strip()
        for ln in DEFERRED_FILE.read_text(encoding="utf-8").split("\n")
        if ln.strip() and not ln.startswith("#")
    }


def test_deferred_file_is_well_formed() -> None:
    urls = _deferred_urls()
    assert urls, "deferred file is empty or missing"
    bad = [u for u in urls if urlparse(u).scheme not in ("http", "https")]
    assert not bad, "deferred rows that are not URLs:\n" + "\n".join(bad)


def test_no_tier3_queue_row_is_a_deferred_long_meeting() -> None:
    """A queue row whose URL NORMALIZES the same as a deferred row is the
    same meeting re-added by a union-style rebase, even when the two URL
    strings aren't byte-identical (scheme, trailing slash, query-param
    order). See the module comment above this test for why the match is
    normalized rather than a bare string compare -- WO-280, 2026-09-12.
    """
    deferred_normalized = {normalize_url(u) for u in _deferred_urls()}
    bad = [
        f"{TIER3_QUEUE.name}:{i}: {url}"
        for i, url in _rows(TIER3_QUEUE)
        if normalize_url(url) in deferred_normalized
    ]
    assert not bad, (
        "queue rows that WO-205 deliberately removed (see "
        "scripts/tier3_long_meetings_deferred.txt) are back -- a rebase "
        "took the union of both sides. Drop them again; on a rebase, a "
        "line deleted on main stays deleted:\n" + "\n".join(bad)
    )


def test_deferred_match_is_robust_to_url_form_not_just_exact_string() -> None:
    """Reproduces the real WO-259 part 2 near-miss directly: the real
    deferred Lake Havasu City, AZ line (2h55m, scripts/tier3_long_
    meetings_deferred.txt) re-added to the queue in a differently-SPELLED
    but identical-MEANING form (http instead of https, a trailing
    slash, query params reordered) must still be caught. A bare string
    compare would miss every one of these; normalize_url() must not.
    """
    real_deferred_line = next(
        ln
        for ln in DEFERRED_FILE.read_text(encoding="utf-8").split("\n")
        if "lakehavasucity.granicus.com" in ln and "clip_id=1838" in ln
    )
    real_url = real_deferred_line.split("\t", 1)[0].strip()
    assert real_url == (
        "https://lakehavasucity.granicus.com/MediaPlayer.php?view_id=2&clip_id=1838"
    )

    variants = [
        # scheme-only difference
        "http://lakehavasucity.granicus.com/MediaPlayer.php?view_id=2&clip_id=1838",
        # trailing slash on the path
        "https://lakehavasucity.granicus.com/MediaPlayer.php/?view_id=2&clip_id=1838",
        # query params in a different order
        "https://lakehavasucity.granicus.com/MediaPlayer.php?clip_id=1838&view_id=2",
        # host uppercased
        "https://LAKEHAVASUCITY.granicus.com/MediaPlayer.php?view_id=2&clip_id=1838",
    ]
    deferred_normalized = {normalize_url(real_url)}
    for variant in variants:
        assert normalize_url(variant) in deferred_normalized, (
            f"variant form not recognized as the same meeting: {variant}"
        )
        # the bare string compare the old guard used would have missed
        # every one of these -- that is the bug this WO fixes.
        assert variant != real_url
