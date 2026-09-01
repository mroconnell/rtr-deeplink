from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder, CalendarPageError, resolve_via_platform
from .generic_fallback import GenericFallbackAssetFinder
from .models import ResolvedMeeting
from ..utils.url_guard import guarded_get

_CIVICLIVE_HOST_SUFFIXES = (".hosted.civiclive.com", ".hosted2.civiclive.com")


def is_civiclive_host(netloc: str) -> bool:
    """Same suffix check `detect_platform()` uses -- exposed here too so
    `resolve()` can re-check a URL's host *after* following redirects
    without importing back into `base.py` (which itself calls into this
    module -- see that function's own docstring for why the import is
    function-level)."""
    netloc = netloc.lower()
    return any(netloc.endswith(suffix) for suffix in _CIVICLIVE_HOST_SUFFIXES)


class CivicLiveAssetFinder(AssetFinder):
    """CivicLive (Intrafinity, formerly West Corp) is a real, distinct
    municipal CMS -- 1000+ customers -- with no video product of its own,
    the same "agenda/content CMS that delegates video elsewhere" shape as
    CivicPlus (`civicplus.py`) and Destiny AgendaQuick
    (`destinyhosted.py`). Real footer credit confirmed on every live
    tenant checked: "Powered by Civiclive".

    Built 2026-09-01 (WO-92) from a same-day pilot
    (`~/Documents/rtr-business/research/ENUMERATION_METHODS.md` §44's
    2026-09-01 addendum) that found ~77% of a search-biased n=13 CivicLive
    tenant sample had real, usable meeting video -- mostly YouTube,
    occasionally CivicClerk (already supported, `civicclerk.py`) or a
    local cable-access channel (not yet supported -- see below).

    **Real structural findings this adapter is built from** (all fetched
    live, plain `aiohttp`, no JS execution, 2026-09-01):

    - Auburn, WA (`auburn.hosted.civiclive.com`): its own "Agendas &
      Minutes" nav link (`/city_hall/agendas___minutes`) is a genuine,
      plain HTTP **302 redirect straight to
      `auburnwa.portal.civicclerk.com`** -- CivicClerk's public portal
      home, not a specific meeting. Confirmed via `curl -I`: a real
      `Location:` header, no JS involved. This is the same "wrapper
      delegates via a plain redirect/link" shape CivicPlus/DestinyHosted
      already established, just via a redirect instead of an in-page
      `<a href>`.
    - Escalon, CA (`escalon.hosted.civiclive.com`): its own City Council
      "Agendas & Minutes" listing page has **no per-meeting video link at
      all** -- unlike CivicPlus's `td.media` per-row shape, the real
      Date/Time/Meeting/Agenda/Packet/Minutes table carries no video
      column. The only video reference on the page is a single, page-wide
      "City of Escalon YouTube Channel" link
      (`youtube.com/channel/UCnj5AyZbMnaFmpNtaAxXRMA`) -- channel-level,
      not a specific meeting. See
      `tests/fixtures/civiclive/escalon_city_council_agendas.html` (a
      real, raw-saved page, `<script>`/`<style>`/comment-stripped).
    - Also confirmed on Auburn: the calendar's own per-meeting event
      detail (a `/cms/one.aspx?...&objectId...` popup) is loaded via a
      client-side AJAX call -- its "Watch LIVE" link
      (`youtube.com/@watchauburn`) is a channel/handle URL, not a video
      id, and isn't even present in the page's raw, un-rendered HTML.
      **CivicLive's real per-meeting agenda/video table content is
      client-rendered and invisible to a plain fetch** -- confirmed on
      both Auburn's calendar widget and Escalon's own agenda table (the
      real meeting rows textually visible in a browser are simply absent
      from the raw HTML `aiohttp` sees). No headless-browser escalation is
      attempted here (out of scope -- see the LIMS/SLC Cloudflare-gate
      precedent in `generic_fallback.py` for why that's env-gated off in
      production, and this isn't even Cloudflare-gated, just plain
      client-rendering).
    - Crystal, MN (`crystal.hosted.civiclive.com`): links out to
      `ccxmedia.org`, a real local cable-access video platform this
      project does NOT yet support -- an honest per-tenant negative for
      now (`detect_platform()` returns "unknown" for it, same as any
      other unsupported host), not a bug.

    **What this means for `resolve()`, concretely**: there's no confirmed
    real per-meeting video link embedded anywhere in a plain-fetched
    CivicLive page -- so, unlike CivicPlus's own row-scraper, this doesn't
    write one. The two real, confirmed-live value adds are (1) following
    a genuine off-domain HTTP redirect to an already-supported platform
    (the Auburn/CivicClerk shape) with the CORRECT final URL -- fetching
    with `url`'s own final destination, not the original CivicLive URL,
    matters here specifically because a same-page relative link on the
    destination platform's page would otherwise resolve against the wrong
    base and any self-referencing link on that destination page would
    wrongly look like "a new platform to delegate to" (since
    `find_platform_link()`'s own-platform exclusion keys off the URL
    passed in, not the URL actually fetched) -- and (2) delegating
    whatever's left to `GenericFallbackAssetFinder`'s existing tiers
    (same thin-wrapper shape as `destinyhosted.py`), which already
    extracts a real embedded YouTube video when one is server-rendered
    directly into the page, and already excludes a channel/handle/
    playlist link structurally (`YouTubeAssetFinder`'s own
    `_VIDEO_ID_RE` only matches `watch?v=`/`embed/`/`shorts/`/`live/`/
    `v/`/`youtu.be/` shapes with a real 11-character id -- a bare
    `@handle` or `playlist?list=` URL never matches it, so Auburn's/
    Escalon's real channel-only links are correctly never mistaken for a
    specific meeting's video).
    """

    platform_name = "civiclive"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }
        self._delegate = GenericFallbackAssetFinder()

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with guarded_get(
                session, url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)

        if not is_civiclive_host(urlparse(final_url).netloc):
            # Left civiclive.com entirely via a real HTTP redirect (the
            # confirmed Auburn -> CivicClerk shape) -- delegate to
            # whatever real platform is now at `final_url`. Deliberately
            # does NOT reset `source_url` back to the original CivicLive
            # URL afterward -- matches civicplus.py's own identical
            # redirect-delegation branch, a known, documented quirk (see
            # CLAUDE.md) rather than a new inconsistency introduced here.
            #
            # CalendarPageError is let through unchanged (a real, expected
            # pick-list outcome, same as CivicPlus's identical branch) --
            # any OTHER exception is caught, though, which civicplus.py's
            # own branch doesn't do. That's a deliberate, evidence-backed
            # difference, not an inconsistency: confirmed live 2026-09-01,
            # Auburn WA's real "Agendas & Minutes" redirect lands on
            # CivicClerk's bare portal HOME (auburnwa.portal.civicclerk.com,
            # no event id in the path at all), and CivicClerkAssetFinder.
            # resolve() raises a bare ValueError for that shape rather than
            # declining gracefully -- a real, common outcome for THIS
            # adapter specifically (a redirect off-domain routinely lands
            # on a platform's portal home, not a specific meeting, since
            # CivicLive's own per-meeting linking is client-rendered and
            # invisible to the plain fetch that produced this redirect in
            # the first place -- see this class's own docstring). Degrades
            # to an honest "found a redirect, not a specific meeting"
            # result instead of a raw crash.
            try:
                return await resolve_via_platform(final_url)
            except CalendarPageError:
                raise
            except Exception as exc:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "This page redirects to "
                        f"{urlparse(final_url).netloc}, but we couldn't find a "
                        "specific meeting there -- it may be a general portal "
                        f"page rather than one meeting ({exc!r})."
                    ],
                )

        # Still on civiclive.com -- delegate wholesale to
        # GenericFallbackAssetFinder's own tiers (same thin-wrapper shape
        # as destinyhosted.py), only claiming the "civiclive" identity
        # when nothing deeper resolved, so a successful inner delegation
        # (e.g. a real embedded YouTube video) is never masked.
        resolved = await self._delegate.resolve(final_url)
        if resolved.platform == "unknown":
            resolved.platform = self.platform_name
        return resolved
