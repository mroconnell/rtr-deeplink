"""HTTP-level tests for the universal site footer and its new /coverage
placeholder page (app/main.py) -- built 2026-08-10 per the user's request
for a footer with sitemap and a few other links not in the main nav.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main

resolver_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def test_coverage_page_renders():
    response = resolver_client.get("/coverage")
    assert response.status_code == 200
    assert "Coming soon" in response.text


def test_coverage_page_is_noindexed():
    response = resolver_client.get("/coverage")
    assert '<meta name="robots" content="noindex">' in response.text


def test_resolver_footer_has_all_four_links():
    response = resolver_client.get("/")
    for href in ("/sitemap.xml", "/feed.xml", "/coverage", "mailto:ryan@redtaperecordings.com"):
        assert href in response.text


def test_subscribe_page_hides_redundant_prompt_but_keeps_footer_links():
    response = resolver_client.get("/subscribe")
    assert "/sitemap.xml" in response.text
    assert "sign up for updates" not in response.text


def test_archive_footer_has_all_four_links():
    response = archive_client_.get("/this-page-does-not-exist")  # any page renders base.html's footer
    for href in ("/sitemap.xml", "/feed.xml", "/coverage", "mailto:ryan@redtaperecordings.com"):
        assert href in response.text
