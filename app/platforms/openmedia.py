import re
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich
from ..utils.url_guard import guarded_get, read_capped_text

# open.media (OMP Network) -- confirmed live 2026-08-21 across 6 real
# tenants (Goodyear AZ, Eugene OR, Cortez CO, Santa Barbara CA, Surprise
# AZ, Georgetown CO) via a real per-tenant subdomain
# (`{tenant}.open.media`). Same underlying Drupal 7 template on every
# tenant checked (`<meta name="Generator" content="Drupal 7">`).
#
# Real, confirmed shape: a `/sessions/{id}[/{slug}]` page whose video is a
# YouTube embed -- but NOT reachable as a plain `<iframe src="youtube.com/
# embed/...">` in the raw server-rendered HTML: the visible player iframe
# (`#youtube-mode`) is empty in the raw response and only gets a real
# `<iframe id="ytplayer" src="https://www.youtube.com/embed/{id}?...">`
# injected client-side (confirmed via a real browser DOM read on Eugene).
# What IS present in the raw, un-rendered HTML on every tenant checked is
# an `<meta property="og:video" content="https://www.youtube.com/v/{id}">`
# (or, on Santa Barbara, `https://youtube.com/live/{id}?feature=share`) --
# already a shape `YouTubeAssetFinder.extract_video_id()`'s own regex
# recognizes (the `v/` and `live/` alternatives), so no new video-id regex
# was needed here, just reading the page BEFORE assuming a headless
# browser was required. This is why open.media resolves via a real
# YouTube-embed lookup already, not via a rendered `<iframe>` scan the way
# the module docstring further down might otherwise suggest.
#
# Registered as its own platform (not left to fall through to
# generic_fallback.py's "unknown" handling, which DOES already resolve
# real video + real captions here via the exact same og:video signal)
# for two reasons: (1) so resolves are attributed to "open_media" in
# admin reporting/`/coverage` rather than counted as best-effort/unknown,
# and (2) because generic_fallback.py's own jurisdiction backfill has a
# real, confirmed bug on this exact page shape -- see
# `_extract_title_and_jurisdiction()`'s docstring below.
#
# `open.media` fronts requests with a UA-based bot check -- confirmed
# live 2026-08-21: a bare/default-UA request 403s (curl with no UA, curl's
# own default UA), while a modern desktop Chrome UA gets a clean 200 for
# the identical URL. Same class of gap as `generic_fallback.py`'s own
# cityofsebastopol.gov fix (see that module's docstring) -- scoped to just
# this adapter's own session, not applied sitewide, same reasoning.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_SESSION_ID_RE = re.compile(r"/sessions/(\d+)")

# The vendor's own un-customized default page title, confirmed real and
# live on Cortez, CO (cortez.open.media) -- every other tenant checked
# (Goodyear, Eugene, Santa Barbara, Surprise, Georgetown) has replaced
# this with a real jurisdiction name. A title still carrying this marker
# tells us the tenant never customized it, so the pre-pipe half of
# <title> is vendor boilerplate, not a real jurisdiction -- must not be
# used as one.
_VENDOR_DEFAULT_TITLE_RE = re.compile(r"open\.media software", re.IGNORECASE)


class OpenMediaAssetFinder(AssetFinder):
    """open.media -- see module docstring above for the real, confirmed
    tenant investigation this was built from.

    Delegates video + caption resolution entirely to `YouTubeAssetFinder`
    (this platform doesn't host video itself, the same "wrapper platform"
    shape as CivicWeb/PrimeGov/LIMS -- see CLAUDE.md's "when a platform
    turns out to be a wrapper around another" convention), passing the
    original open.media URL through as `source_url` so "view original
    source" keeps pointing at the real open.media session page rather
    than YouTube.
    """

    platform_name = "open_media"

    async def resolve(self, url: str) -> ResolvedMeeting:
        html = await self._fetch(url)
        if html is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "Could not load this open.media page -- it may be temporarily "
                    "unreachable."
                ],
            )

        video_id = YouTubeAssetFinder.extract_video_id(html)
        if not video_id:
            resolved = ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["No video found for this open.media session."],
            )
        else:
            resolved = await YouTubeAssetFinder.resolve_video_id(
                video_id, source_url=url
            )

        title, jurisdiction = self._extract_title_and_jurisdiction(html, url)
        if title:
            resolved.title = title
        # Unlike `title` (only filled when the page has a real one),
        # `jurisdiction` is always set from the page/subdomain rather than
        # ever left as whatever YouTubeAssetFinder.resolve_video_id() put
        # there -- that's `info.get("uploader")`, a channel name, not a
        # jurisdiction (the exact same class of bug already fixed for
        # PrimeGov/CivicWeb/LIMS -- see CLAUDE.md's `app/db/outcomes.py`
        # bullet and civicweb.py's own comment on this same override).
        resolved.jurisdiction = jurisdiction

        session_id_match = _SESSION_ID_RE.search(urlparse(url).path)
        if session_id_match:
            resolved.external_id = (
                f"open_media:{urlparse(url).netloc.lower()}:{session_id_match.group(1)}"
            )

        agenda_link = self._find_agenda_link(html, url)
        if agenda_link:
            resolved.agenda_link = agenda_link

        return resolved

    @staticmethod
    async def _fetch(url: str) -> Optional[str]:
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with guarded_get(
                    session, url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        return None
                    return await read_capped_text(response)
        except Exception:
            return None

    @staticmethod
    def _extract_title_and_jurisdiction(
        html: str, url: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Real, confirmed `<title>` shape across every tenant checked
        (Goodyear, Eugene, Santa Barbara, Surprise, Georgetown):
        "{Jurisdiction} | {Meeting title}" -- e.g. "City of Goodyear,
        Arizona | Planning & Zoning Commission - 08/19/2026", "Eugene, OR
        | City Council Work Session: July 15, 2026".

        This is the REVERSE order from `generic_fallback.py`'s own
        `_TITLE_TAG_PIPE_RE` (built for CRRMA's "{Org} | {Jurisdiction}"
        shape) -- reusing that regex's group assignment here would (and,
        confirmed live during this investigation, DID) silently swap the
        two, storing the real meeting title into `jurisdiction` and
        vice versa. That's exactly why this is its own extractor rather
        than a call into generic_fallback.py's helper.

        Meeting title comes from `og:title` instead of the post-pipe
        `<title>` half -- also real and confirmed on every tenant, and
        strictly cleaner (no leftover "- 08/19/2026" date suffix baked
        into the string) plus independent of whether yt-dlp's own title
        extraction is blocked (a real, documented risk from Render's IP --
        see youtube.py's own docstring).

        Jurisdiction is NOT trusted from `<title>` when the tenant has
        never customized it -- confirmed real and live on Cortez, CO
        (cortez.open.media), whose `<title>` is still the vendor's own
        un-customized default, "Cortez Open.Media Software | ...". In
        that case (and only in that case) this falls back to the tenant
        subdomain itself, run through the same validated-subdomain
        extraction eScribe/Granicus already use
        (`jurisdiction_enrich.validated_subdomain_extract()` -- declines
        rather than guessing when the label doesn't validate against the
        real Census place/county tables) and then the shared
        state-filling pass every other adapter here uses
        (`enrich_jurisdiction_text()`).
        """
        soup = BeautifulSoup(html, "html.parser")

        title = None
        og_title = soup.find("meta", attrs={"property": "og:title"})
        if og_title and og_title.get("content", "").strip():
            title = og_title["content"].strip()

        jurisdiction = None
        title_tag = soup.title.get_text(strip=True) if soup.title else None
        if title_tag and "|" in title_tag:
            pre_pipe = title_tag.split("|", 1)[0].strip()
            if pre_pipe and not _VENDOR_DEFAULT_TITLE_RE.search(pre_pipe):
                jurisdiction = pre_pipe

        netloc = urlparse(url).netloc
        if not jurisdiction:
            jurisdiction = jurisdiction_enrich.validated_subdomain_extract(url)

        if jurisdiction:
            page_text = soup.get_text(" ", strip=True)
            jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
                jurisdiction, netloc=netloc, page_text=page_text
            )

        return title, jurisdiction

    @staticmethod
    def _find_agenda_link(html: str, url: str) -> Optional[str]:
        """The agenda iframe (`id="document"`), confirmed present and in
        this exact position on every real tenant page checked. Two real
        shapes found: a direct link to another platform's own agenda page
        (Goodyear links straight to a destinyhosted.com AgendaQuick page,
        already a registered platform in its own right -- see
        `base.py`'s `detect_platform()`), or a same-tenant pdf.js viewer
        wrapping a direct S3-hosted PDF as its `?file=` query param
        (confirmed on Eugene, Cortez, Santa Barbara, Surprise) -- the
        raw PDF URL is unwrapped from that param rather than pointed at
        the pdf.js viewer page itself, so `agenda_link` is always a
        direct document link, consistent with every other adapter's own
        `agenda_link` field.

        `id="interactive-html-agenda"` (a second, separate iframe on
        every page checked) is deliberately ignored -- empty or
        self-referential (the *same* session URL) on every real example
        found, never a real document.
        """
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.find("iframe", id="document")
        if not iframe or not iframe.get("src"):
            return None
        src = iframe["src"].strip()
        if not src:
            return None
        query = parse_qs(urlparse(src).query)
        file_param = query.get("file")
        if file_param and file_param[0]:
            return file_param[0]
        return src
