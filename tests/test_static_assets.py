"""Static mounts actually serve files, with WO-66's revalidation header.

Exists because of a real production incident (2026-08-30): WO-66's
RevalidatingStaticFiles overrode StaticFiles.file_response as async and
awaited super()'s -- but in the pinned starlette==1.6.0 that method is
*sync*, so every static asset on BOTH services 500'd from the first
deploy carrying it, and no test in the suite fetched a single static
file, so 2000+ tests stayed green the whole time. The site rendered
completely unstyled until an unrelated verification pass noticed. These
tests are the missing coverage: one real file per mount per service,
asserting it serves AND carries the Cache-Control the subclass exists
to add.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main

resolver_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def _assert_serves_with_no_cache(client: TestClient, path: str):
    response = client.get(path)
    assert response.status_code == 200, f"{path} -> {response.status_code}"
    assert response.headers.get("cache-control") == "no-cache"
    assert len(response.content) > 0


def test_resolver_own_static_serves():
    _assert_serves_with_no_cache(resolver_client, "/static/icon.svg")


def test_resolver_shared_static_serves():
    _assert_serves_with_no_cache(resolver_client, "/shared-static/clerk_nav.js")


def test_archive_own_static_serves():
    _assert_serves_with_no_cache(archive_client_, "/static/style.css")


def test_archive_shared_static_serves():
    _assert_serves_with_no_cache(archive_client_, "/shared-static/clerk_nav.js")


def test_static_404_still_404s_not_500s():
    # The broken override 500'd on *every* request through the mount --
    # a missing file must come back as a plain 404, proving get_response's
    # non-file path still works through the subclass.
    response = resolver_client.get("/static/does-not-exist.css")
    assert response.status_code == 404
