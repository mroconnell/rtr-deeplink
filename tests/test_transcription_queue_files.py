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
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [(i, ln) for i, ln in enumerate(text.split("\n"), 1) if ln]


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
