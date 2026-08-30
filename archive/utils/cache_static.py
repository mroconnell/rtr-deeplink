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
    # Overrides get_response (async in every modern Starlette), NOT
    # file_response: in the pinned starlette==1.6.0 file_response is a
    # *sync* method, and the original async-override-with-await of it
    # raised TypeError on every request -- a 500 on every static asset
    # on both services, live from the first deploy that carried WO-66
    # (2026-08-30) until this fix. No behavioral difference otherwise:
    # 404/304 responses get the header too, which is harmless-to-correct
    # (a 304 with no-cache still means "revalidate next time").
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response
