"""WO-49: a real quote in the meta description, and per-meeting-body
diversity on a jurisdiction hub.

Two unrelated changes tested together because both are small extensions
of machinery the state/hub rebuild already built (`meeting_highlights`
and `crud._build_featured()`'s diversity caps).
"""

from archive.db.crud import _build_featured
from archive.utils.highlights import META_DESCRIPTION_CHARS, meta_description


def _entry_pages(specs):
    """(id, title, meeting_body, jurisdiction) -> the page dicts
    _build_featured() consumes."""
    return [
        {
            "id": i,
            "slug": f"slug-{i}",
            "title": title,
            "jurisdiction": jurisdiction,
            "meeting_body": body,
            "date": "2026-08-01",
        }
        for i, title, body, jurisdiction in specs
    ]


def _highlights(ids, topics=()):
    return {
        i: {
            "start": 10.0 * i,
            "text": f"A quotable sentence from meeting {i}.",
            "topics": list(topics),
            "topic_moments": {},
        }
        for i in ids
    }


# --- meta description ---------------------------------------------------


def test_short_quote_passes_through_with_excerpt_ellipses():
    out = meta_description("we are here about the flock cameras tonight")
    # display_text() marks it as an excerpt at both ends.
    assert out.startswith("…")
    assert out.endswith("…")
    assert "flock cameras" in out


def test_long_quote_is_cut_on_a_word_boundary():
    text = ("the council considered the proposed data center application " * 8).strip()
    out = meta_description(text)

    assert len(out) <= META_DESCRIPTION_CHARS + 1  # +1 for the ellipsis
    assert out.endswith("…")
    # Cut between words, never mid-word.
    assert not out[:-1].endswith(" ")
    assert out[:-1].split()[-1] in text.split()


def test_never_returns_markup():
    """meta/og content cannot carry tags -- this must use display_text(),
    never highlight_html()."""
    out = meta_description("residents raised concerns about data center noise")
    assert "<" not in out and ">" not in out


# --- per-body diversity on a hub ---------------------------------------


def test_body_cap_mixes_in_other_bodies_on_a_hub():
    """One government, many bodies: six City Council cards where the
    Planning Commission and school board were also available is a worse
    page for someone looking for the body that decides their issue."""
    pages = _entry_pages(
        [
            (1, "Council A", "City Council", "City of Testville, CA"),
            (2, "Council B", "City Council", "City of Testville, CA"),
            (3, "Council C", "City Council", "City of Testville, CA"),
            (4, "Council D", "City Council", "City of Testville, CA"),
            (5, "Planning A", "Planning Commission", "City of Testville, CA"),
            (6, "School A", "Board of Education", "City of Testville, CA"),
        ]
    )
    featured = _build_featured(
        pages, _highlights(range(1, 7)), None, 4, None, max_per_body=2
    )

    bodies = [f["meeting_body"] for f in featured]
    assert len(featured) == 4
    assert bodies.count("City Council") == 2
    assert "Planning Commission" in bodies
    assert "Board of Education" in bodies


def test_body_cap_never_shrinks_the_set():
    """A hub whose meetings genuinely are all one body still fills up --
    the second pass backfills from what the cap skipped."""
    pages = _entry_pages(
        [
            (i, f"Council {i}", "City Council", "City of Testville, CA")
            for i in range(1, 7)
        ]
    )
    featured = _build_featured(
        pages, _highlights(range(1, 7)), None, 6, None, max_per_body=2
    )
    assert len(featured) == 6


def test_body_cap_is_off_by_default():
    """State pages must not get it: a dozen cards from a dozen cities are
    nearly all "City Council", and capping there would exclude most of
    the state to manufacture meaningless variety."""
    pages = _entry_pages(
        [
            (i, f"Council {i}", "City Council", f"City of Town{i}, CA")
            for i in range(1, 7)
        ]
    )
    featured = _build_featured(pages, _highlights(range(1, 7)), None, 6, None)

    assert len(featured) == 6
    assert all(f["meeting_body"] == "City Council" for f in featured)


def test_missing_body_is_never_constrained():
    """Same reasoning as an untagged card under the topic cap -- a page
    with no recorded body cannot cluster, and excluding it would bias the
    hub toward meetings that happen to have the column filled in."""
    pages = _entry_pages(
        [(i, f"Untitled body {i}", None, "City of Testville, CA") for i in range(1, 6)]
    )
    featured = _build_featured(
        pages, _highlights(range(1, 6)), None, 5, None, max_per_body=1
    )
    assert len(featured) == 5


def test_jurisdiction_cap_available_for_multi_government_pools():
    """The mirror image, built here so the national feed can use it: cap
    per government where the risk is six meetings from whichever city was
    ingested last."""
    pages = _entry_pages(
        [
            (1, "Big City A", "City Council", "City of Bigtown, CA"),
            (2, "Big City B", "City Council", "City of Bigtown, CA"),
            (3, "Big City C", "City Council", "City of Bigtown, CA"),
            (4, "Small Town", "City Council", "City of Smalltown, CA"),
            (5, "Other Town", "City Council", "City of Othertown, CA"),
        ]
    )
    featured = _build_featured(
        pages, _highlights(range(1, 6)), None, 3, None, max_per_jurisdiction=1
    )
    assert [f["jurisdiction"] for f in featured] == [
        "City of Bigtown, CA",
        "City of Smalltown, CA",
        "City of Othertown, CA",
    ]
