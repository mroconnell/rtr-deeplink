from datetime import datetime, timezone

import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader

ENV = Environment(loader=FileSystemLoader("archive/templates"), autoescape=True)


def _render(entries, jurisdiction=None):
    tpl = ENV.get_template("feed.xml.jinja")
    return tpl.render(
        base_url="https://redtaperecordings.com",
        feed_url="https://redtaperecordings.com/feed.xml",
        jurisdiction=jurisdiction,
        entries=entries,
    )


def test_feed_is_valid_xml_with_special_characters_in_title():
    # Real bug found while building this feed: select_autoescape() keys off
    # a template's file extension, and "feed.xml.jinja" reports as ".jinja"
    # -- not one of the auto-escaped extensions -- so a real meeting title
    # containing a bare "&" or "<" (e.g. "Planning & Zoning") produced
    # invalid, unparseable XML until every interpolated value was escaped
    # explicitly with `|e`. This pins that down as a regression test.
    entries = [
        {
            "slug": "test-meeting",
            "title": "Planning & Zoning <Special Session>",
            "date": "2026-01-01",
            "jurisdiction": "R & D County",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
    ]
    xml = _render(entries)
    root = ET.fromstring(xml)  # raises if invalid
    title = root.find("./channel/item/title").text
    assert "Planning & Zoning <Special Session>" in title


def test_feed_starts_with_xml_declaration():
    # The Jinja comment documenting the autoescape gotcha must not leave
    # stray whitespace before <?xml ...?> -- XML requires it be the very
    # first thing in the document.
    xml = _render([])
    assert xml.startswith("<?xml version=")


def test_feed_empty_entries_is_still_valid_xml():
    xml = _render([])
    root = ET.fromstring(xml)
    assert root.find("./channel/item") is None


def test_feed_jurisdiction_filter_appears_in_title_and_description():
    xml = _render([], jurisdiction="Simi Valley")
    assert "Simi Valley" in xml
    root = ET.fromstring(xml)  # still valid even with a filter applied
    assert root.find("./channel/title").text == "Red Tape Recordings — Simi Valley"
