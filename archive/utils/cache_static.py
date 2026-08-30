"""StaticFiles subclass that forces revalidation instead of relying on
browser heuristic freshness -- deliberately duplicated in
app/utils/cache_static.py (same reasoning as this app's other
duplicated utils, see url_normalize.py's own header comment). If you
change one, change both.

Why this exists (WO-66, 2026-08-28): the mounts using this already emit
ETag/Last-Modified but previously sent no Cache-Control at all, so
browsers fell back to RFC 9111 §4.2.2 heuristic freshness and could serve
a stale asset for a long time without ever asking the server. Confirmed
live: right after a deploy, a browser that had visited before it kept
executing the *old* shared_static/clerk_nav.js while the server was
serving the new one -- transferSize: 0, straight from cache, no
revalidation. `no-cache` (despite the name) means "revalidate before
use" -- with the existing ETags that's a cheap 304 in the common case,
not a re-download.
"""

from starlette.responses import Response
from starlette.staticfiles import StaticFiles


class RevalidatingStaticFiles(StaticFiles):
    async def file_response(self, *args, **kwargs) -> Response:
        response = await super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
