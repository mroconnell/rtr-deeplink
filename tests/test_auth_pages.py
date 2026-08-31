"""Regression tests for the standalone /sign-up and /sign-in pages
(WO-65, 2026-08-28).

Why these routes exist: Clerk's *mounted* (non-modal) SignIn component
renders a "No account? Sign up" link at `signUpUrl`, which defaults to
/sign-up on the app's own origin. Neither /sign-up nor /sign-in existed,
so the inline sign-in form on /account/saved dead-ended in a 404 --
confirmed live on production 2026-08-28, where the rendered link's href
really was https://redtaperecordings.com/sign-up. The SignUp component
has the mirror-image link ("Have an account? Sign in" at `signInUrl`,
default /sign-in), which is why both halves are needed rather than just
the one the bug report named.

At the time, the nav's *modal* (Clerk.openSignIn) was left alone -- it
uses Clerk's virtual router, so its own link renders as the sentinel
"CLERK-ROUTER/VIRTUAL/sign-up" and switches views inside the modal
without navigating. Verified live in the same pass.

That modal turned out to have its own real bug (found 2026-08-31): a
second-factor step (Clerk's default-on Client Trust check, or real
per-user MFA) never renders inside it -- see shared_static/clerk_nav.js's
click handler on #clerk-sign-in-link for the full writeup. The nav link
now navigates to this /sign-in page instead of opening the modal, so
this page is the only sign-in UI left in the app, not just Clerk's own
fallback destination for its cross-links.

These are route/markup-level assertions only. Whether Clerk's own
component renders inside the mount div is a client-side concern with no
server-side signal to assert on -- it was verified separately in-browser
against the real clerk_nav.js.
"""

from fastapi.testclient import TestClient

import app.main

resolver_client = TestClient(app.main.app)


def test_sign_up_page_renders_with_clerk_mount_point():
    response = resolver_client.get("/sign-up")
    assert response.status_code == 200
    # The id clerk_nav.js looks for -- renaming one without the other is
    # exactly the silent breakage this test exists to catch.
    assert 'id="clerk-sign-up"' in response.text


def test_sign_in_page_renders_with_clerk_mount_point():
    response = resolver_client.get("/sign-in")
    assert response.status_code == 200
    # Deliberately NOT "clerk-sign-in" -- that id is already taken by the
    # Archive's inline form on /account/saved, and clerk_nav.js mounts
    # the two with different redirect targets.
    assert 'id="clerk-sign-in-page"' in response.text


def test_auth_pages_are_noindex():
    """Nothing on either page is worth indexing, and a search result
    landing a signed-in visitor on a sign-up form is just confusing."""
    for path in ("/sign-up", "/sign-in"):
        response = resolver_client.get(path)
        assert '<meta name="robots" content="noindex">' in response.text, path
