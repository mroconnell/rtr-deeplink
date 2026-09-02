"""Route + content tests for the public privacy policy page (/privacy).

The page is a *factual* document about what this app collects, so these
tests deliberately assert on more than a 200. Two of them exist to fail
loudly if the code and the policy drift apart:

- The "last updated" date is required by the page's own terms and is the
  one thing a reader uses to judge whether the policy is current.
- The sale/licensing distinction (public records may be licensed; user
  personal information is never sold) is the section the whole policy
  turns on, and a CCPA "we have not sold in the preceding 12 months"
  statement is a claim with legal weight -- neither should be able to
  disappear in an edit without a test noticing.

Not lawyer-reviewed; see the template's own header comment.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main

resolver_client = TestClient(app.main.app)
archive_client = TestClient(archive.main.app)


def test_privacy_page_renders():
    response = resolver_client.get("/privacy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text


def test_privacy_page_carries_last_updated_date():
    """A privacy policy with no visible effective date is not usable --
    the page says it's the signal for whether the policy is current."""
    response = resolver_client.get("/privacy")
    assert response.status_code == 200
    assert "Last updated: September 2, 2026" in response.text


def test_privacy_page_keeps_the_sale_distinction():
    """The one section a reader must not be able to miss."""
    response = resolver_client.get("/privacy")
    assert "We do not sell or license our users' personal information." in response.text
    assert "have not sold or shared personal information" in response.text


def test_both_footers_link_to_privacy():
    """Every page on the site should reach the policy. The Archive is
    proxied onto the resolver's origin, so a relative href is correct in
    both -- an absolute URL here would be the thing to catch."""
    resolver_page = resolver_client.get("/about")
    assert resolver_page.status_code == 200
    assert '<a href="/privacy">Privacy</a>' in resolver_page.text

    archive_page = archive_client.get("/coverage")
    assert archive_page.status_code == 200
    assert '<a href="/privacy">Privacy</a>' in archive_page.text
