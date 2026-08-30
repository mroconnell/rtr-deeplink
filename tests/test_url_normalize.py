"""Tests for normalize_url() -- deliberately duplicated between
app/utils/url_normalize.py and archive/utils/url_normalize.py (kept in
sync manually, per each module's own comment), so this file imports and
tests both to catch either one drifting.
"""

from app.utils.url_normalize import normalize_url as app_normalize_url
from archive.utils.url_normalize import normalize_url as archive_normalize_url

import pytest

IMPLEMENTATIONS = [app_normalize_url, archive_normalize_url]


@pytest.mark.parametrize("normalize_url", IMPLEMENTATIONS)
def test_http_and_https_collapse_to_the_same_identity(normalize_url):
    # Real gap found 2026-08-29 investigating the Coralville, IA
    # Cablecast triplicate (BACKLOG_DONE.md): two of its three duplicate
    # archived pages -- https://cityofcoralvilleiowa.cablecast.tv/show/2907
    # and http://cityofcoralvilleiowa.cablecast.tv/show/2907?site=1 --
    # differed by scheme (and a query-string variant, which stays
    # untouched -- see the query-param test below).
    assert normalize_url(
        "https://cityofcoralvilleiowa.cablecast.tv/show/2907"
    ) == normalize_url("http://cityofcoralvilleiowa.cablecast.tv/show/2907")


@pytest.mark.parametrize("normalize_url", IMPLEMENTATIONS)
def test_scheme_collapse_still_strips_the_right_default_port(normalize_url):
    # The default-port strip has to run against the URL's REAL scheme
    # before canonicalizing it -- an https:// URL on :443 and a plain
    # https:// URL (no explicit port) must still match, and likewise for
    # http:// on :80.
    assert normalize_url("https://example.com:443/show/1") == normalize_url(
        "https://example.com/show/1"
    )
    assert normalize_url("http://example.com:80/show/1") == normalize_url(
        "http://example.com/show/1"
    )
    assert normalize_url("http://example.com/show/1") == normalize_url(
        "https://example.com/show/1"
    )


@pytest.mark.parametrize("normalize_url", IMPLEMENTATIONS)
def test_a_non_default_port_is_still_a_different_identity(normalize_url):
    # Coralville's actual third URL (coralvision.cablecast.tv:8080) is a
    # genuine cross-host migration, not just a scheme/port variant -- a
    # non-default port must NOT collapse into the bare-host identity, or
    # this fix would silently merge two different real hosts.
    assert normalize_url("http://example.com:8080/show/1") != normalize_url(
        "http://example.com/show/1"
    )


@pytest.mark.parametrize("normalize_url", IMPLEMENTATIONS)
def test_query_params_are_still_untouched(normalize_url):
    # Deliberately NOT part of this fix -- several platforms' identity
    # lives entirely in query strings (Granicus's ?view_id=&clip_id=), so
    # a URL with a real extra param must stay a distinct identity from
    # one without it.
    assert normalize_url("https://example.com/show/1") != normalize_url(
        "https://example.com/show/1?site=1"
    )
    # Existing behavior preserved: query params are still sorted for
    # stable ordering regardless of scheme.
    assert normalize_url("http://example.com/show/1?b=2&a=1") == normalize_url(
        "https://example.com/show/1?a=1&b=2"
    )


@pytest.mark.parametrize("normalize_url", IMPLEMENTATIONS)
def test_a_non_http_scheme_is_left_alone(normalize_url):
    # The collapse is scoped to http/https specifically -- an unrelated
    # scheme (or none at all) shouldn't be silently rewritten.
    assert normalize_url("ftp://example.com/file") == normalize_url(
        "ftp://example.com/file"
    )
    assert normalize_url("ftp://example.com/file").startswith("ftp://")
