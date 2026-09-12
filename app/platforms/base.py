import re
from abc import ABC, abstractmethod
from typing import FrozenSet, List, Optional, Tuple, TypedDict
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .models import ResolvedMeeting


class UnsupportedPlatformError(Exception):
    def __init__(self, url: str, detected: str = "unknown"):
        self.url = url
        self.detected = detected
        super().__init__(f"No asset finder for platform '{detected}' ({url})")


class CalendarCandidate(TypedDict):
    title: str
    date: str
    url: str


class CalendarPageError(Exception):
    """Raised when a URL is a calendar/listing page rather than a specific
    meeting -- e.g. Legistar's Calendar.aspx, which lists many meetings each
    with their own video link, rather than one meeting's video. Carries
    enough per-meeting info (title, date, direct URL) for the frontend to
    show the user a pickable list instead of a bare failure.

    `jurisdiction_hint` is optional, page-level (one value for every
    candidate, not per-candidate) -- set by an adapter whose listing page
    itself is a stronger jurisdiction signal than whatever the eventually-
    picked candidate's own platform can guess (CivicPlus's per-tenant
    `{state}-{name}.civicplus.com` subdomain is the first real source,
    2026-08-27 -- see civicplus.py's `_jurisdiction_from_subdomain()`).
    None for any adapter that doesn't have one (Legistar's Calendar.aspx
    today) -- the frontend simply has nothing extra to carry through in
    that case, not an error.
    """

    def __init__(
        self,
        message: str,
        candidates: List[CalendarCandidate],
        jurisdiction_hint: Optional[str] = None,
    ):
        self.candidates = candidates
        self.jurisdiction_hint = jurisdiction_hint
        super().__init__(message)


class NoVideoCandidateFound(Exception):
    """Raised when a calendar/listing page (currently: CivicPlus's own
    AgendaCenter, see civicplus.py) was walked newest-first, up to a
    retry limit, and none of the real (title+date) candidate rows
    checked had a real video link -- a confident, real NEGATIVE result
    ("this government's page(s), checked, likely has no video"), not an
    error and not something a caller should ingest.

    Distinct from `CalendarPageError` above, which signals "here's a
    real pick-list, you choose" -- this signals "already picked as many
    of the most recent real candidates as make sense to try (or found
    none at all), and none had video." Real bug this replaces, confirmed
    2026-09-07: collapsing this case into a bare "zero candidates" empty
    list gave callers no way to tell "this page has no meetings at all"
    apart from "this page has real meetings, just none with video yet"
    -- and `scripts/adhoc_civicplus_pipeline.py`'s zero-candidates
    fallback (a `ResolvedMeeting` keyed to the bare listing-page URL
    itself, with no real title) ingested it as if it were a real
    meeting.

    `candidates_checked` is how many real candidate rows were actually
    walked before giving up -- 0 for the true zero-candidates case (a
    genuinely empty listing page), otherwise `min(retry_limit, number of
    real candidate rows on the page)`. `jurisdiction_hint` carries the
    same page-level jurisdiction signal `CalendarPageError` does (e.g.
    CivicPlus's own subdomain), so a caller doesn't lose it just because
    no video was found.
    """

    def __init__(
        self,
        message: str,
        candidates_checked: int,
        jurisdiction_hint: Optional[str] = None,
    ):
        self.candidates_checked = candidates_checked
        self.jurisdiction_hint = jurisdiction_hint
        super().__init__(message)


class AssetFinder(ABC):
    """One implementation per civic meeting platform (Granicus, Legistar, ...)."""

    platform_name: str

    @abstractmethod
    async def resolve(self, url: str) -> ResolvedMeeting:
        """Given a meeting URL on this platform, find its video + transcript."""
        raise NotImplementedError


# A vendor's own corporate/marketing/login host is never a per-government
# tenant -- for every platform detect_platform() recognizes by a bare
# domain/subdomain match below, not just CivicPlus. WO-162 (2026-09-10)
# found and fixed this for CivicPlus alone: nearly every CivicPlus-hosted
# government site's own page footer carries a "Government Websites by
# CivicPlus®" credit linking to `https://connect.civicplus.com/referral`
# (a real, live redirect to CivicPlus's own marketing site, not a
# government page), and a link-scan reaching that footer link before the
# government's own real content got a bogus "no video found"/403 --
# confirmed live on Temple City, CA. WO-163 (2026-09-10) generalizes the
# same fix to every other platform below that shares the same shape: a
# bare "vendorhost.com in netloc" substring check with no path/subdomain
# narrowing, which also matches the vendor's own homepage, login portal,
# or referral subdomain.
#
# Each host below was confirmed real by one honest fetch of the vendor's
# own homepage (2026-09-10, WO-163) -- a realistic User-Agent, one host
# at a time, 2 seconds apart, following redirects -- never invented.
# Several turned up real, load-bearing evidence beyond "the homepage
# answers": `legistar.com`, `primegov.com`, `swagit.com` and `iqm2.com`
# all now redirect straight to `granicus.com` (all four products were
# acquired by Granicus and folded into its own marketing site);
# `www.civicclerk.com` redirects to a CivicPlus marketing page (CivicClerk
# is also a CivicPlus product; the bare `civicclerk.com` doesn't resolve
# at all); `www.viebit.com` redirects to `www.leightronix.com` (Viebit's
# real corporate parent); the bare `suiteonemedia.com` redirects to
# `getsuiteone.com` (a rebrand); `www.diligentoneplatform.com` redirects
# to a real `oidc.diligentoneplatform.com` single-sign-on login host.
# None of these are guesses -- each is the literal `curl -L` redirect
# target seen live.
#
# Two platforms in this function share the bare-substring shape but are
# deliberately NOT here: `clerkshq.com` (ClerkBase) and
# `townhallstreams.com` both address real tenants directly on the BARE
# vendor domain -- a tenant is a path segment
# (`clerkshq.com/YellowSprings-OH`) or a query parameter
# (`townhallstreams.com/stream.php?location_id=...`), not a subdomain --
# so excluding the bare host would break every real tenant, not just a
# marketing page. `clerkshq.com`'s own `www` subdomain IS a separate,
# real, non-tenant host (confirmed live to answer distinctly from the
# bare tenant-hosting domain) and is excluded below under "clerkbase";
# `townhallstreams.com` has no confirmed distinct marketing host at all,
# so nothing is excluded for it -- see BACKLOG.md for this residual gap
# on both. `auroratv.org` is Aurora, CO's own single-tenant government
# site (not a multi-tenant vendor), so there's no separate corporate host
# to exclude. Cablecast (`cablecast.tv`), Castus (`castus.tv`) and Vimeo
# are unaffected by this bug in the first place -- each already requires
# a specific path/URL shape rather than a bare domain substring, so a
# marketing homepage never matches -- left unchanged per this WO's scope.
#
# A host in this map is never classified as its platform by
# `detect_platform()` below (see `_ALL_CORPORATE_HOSTS`'s use there), and
# is skipped outright by `find_platform_link()`'s own link-scan too.
# `CIVICPLUS_CORPORATE_HOSTS` (WO-162's original name) is kept as an
# alias for `CORPORATE_HOSTS_BY_PLATFORM["civicplus"]` so `scripts/
# wo134_confirmed_hits_ingest.py` and the two `adhoc_school_district_
# retry_*.py` scripts keep working unchanged.
CORPORATE_HOSTS_BY_PLATFORM: dict[str, FrozenSet[str]] = {
    "civicplus": frozenset(
        {"civicplus.com", "www.civicplus.com", "connect.civicplus.com"}
    ),
    "granicus": frozenset({"granicus.com", "www.granicus.com"}),
    "legistar": frozenset({"legistar.com", "www.legistar.com"}),
    # `civicclerk.com` itself doesn't resolve at all (confirmed: DNS
    # lookup failure) -- only `www.civicclerk.com` is a real, distinct
    # host, and it redirects straight to a CivicPlus marketing page.
    "civicclerk": frozenset({"www.civicclerk.com"}),
    "primegov": frozenset({"primegov.com", "www.primegov.com"}),
    "swagit": frozenset({"swagit.com", "www.swagit.com"}),
    "escribe": frozenset({"escribemeetings.com", "www.escribemeetings.com"}),
    "civicweb": frozenset(
        {
            "civicweb.net",
            "www.civicweb.net",
            "diligentoneplatform.com",
            "www.diligentoneplatform.com",
            "oidc.diligentoneplatform.com",
        }
    ),
    "iqm2": frozenset({"iqm2.com", "www.iqm2.com"}),
    # ClerkBase/ClerkHQ tenants live on the BARE `clerkshq.com` domain
    # (path-based -- see the module comment above) -- only `www` is a
    # real, separate, non-tenant host, confirmed live.
    "clerkbase": frozenset({"www.clerkshq.com"}),
    "champds": frozenset({"champds.com", "www.champds.com"}),
    "destinyhosted": frozenset({"destinyhosted.com", "www.destinyhosted.com"}),
    "telvue": frozenset({"telvue.com", "www.telvue.com"}),
    "viebit": frozenset({"viebit.com", "www.viebit.com"}),
    "suiteone": frozenset({"suiteonemedia.com", "www.suiteonemedia.com"}),
    # Wistia's own marketing site -- confirmed live 2026-09-10 (WO-161) --
    # is never a per-government tenant, same reasoning as every host
    # above; a real government tenant always lives on a subdomain
    # (`amsva.wistia.com`), never the bare/`www` host. Wistia's own
    # infrastructure/API hosts (`fast.wistia.com`, `embed-ssl.wistia.com`,
    # etc) are excluded separately, in wistia.py's own
    # `is_wistia_account_host()`, since those are subdomains a bare-host
    # set like this one can't distinguish from a real tenant subdomain.
    "wistia": frozenset({"wistia.com", "www.wistia.com"}),
}

CIVICPLUS_CORPORATE_HOSTS = CORPORATE_HOSTS_BY_PLATFORM["civicplus"]

_ALL_CORPORATE_HOSTS: FrozenSet[str] = frozenset().union(
    *CORPORATE_HOSTS_BY_PLATFORM.values()
)

# A DIFFERENT list from the one above, for a different problem (WO-210).
# `CORPORATE_HOSTS_BY_PLATFORM` is a vendor's own marketing/login host,
# which is never a real government tenant at all. `MULTI_GOV_HOSTS` is
# the opposite shape: a host that IS a real tenant host, just one shared
# by many unrelated governments at once -- youtube.com, vimeo.com,
# clerkshq.com -- so it may only be pinned per-video/per-channel, never
# as a whole-host catch-all (Ryan's rule: "if youtu.be without a channel
# match, pin to NULL").
#
# The canonical definition lives in `app/utils/gov_registry/registry.py`
# instead of here, on purpose: that module is plain-stdlib (its own
# `__init__.py` docstring makes this an explicit, deliberate import
# constraint), which is what lets `archive/db/crud.py` import it without
# pulling this file's `bs4` dependency across the app/archive service
# boundary -- `archive/requirements.txt` has no `beautifulsoup4`, and a
# module-level import failure there would crash the whole service, not
# just one endpoint (the same reasoning `archive/utils/video_thumbnail.py`
# gives for duplicating a YouTube id regex rather than importing this
# module). Re-exported here purely so a reader of this file's own host
# lists finds it next to `CORPORATE_HOSTS_BY_PLATFORM`.
from ..utils.gov_registry.registry import (  # noqa: E402, F401
    MULTI_GOV_HOSTS,
    is_multi_gov_host,
)


def detect_platform(url: str) -> str:
    """Classify a meeting URL by hosting platform, based on domain/path shape.

    Mirrors the dispatch pattern used by the civic-scraper OSS tool: one
    adapter per platform, not per city, since cities on the same platform
    share the same page structure.
    """
    # Function-level to break a real import cycle: `vimeo.py` imports
    # `AssetFinder`/`CalendarPageError` from this module, so this module
    # can't import it at the top. Vimeo is the one platform whose
    # detection needs real URL-shape parsing rather than a domain match
    # (see its case below for why), and that parsing belongs with the
    # adapter, not copy-pasted here.
    from .vimeo import is_vimeo_host, is_vimeo_listing, parse_vimeo_video
    from .proudcity import PROUDCITY_KNOWN_DOMAINS
    from .invintus import is_invintus_meeting_url
    from .az_legislature import is_az_legislature_video_url
    from .wistia import parse_wistia_account_url
    from .boxcast import parse_boxcast_id

    netloc = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if netloc in _ALL_CORPORATE_HOSTS:
        # A vendor's own corporate/marketing/login host is never a
        # per-government tenant -- see CORPORATE_HOSTS_BY_PLATFORM's own
        # comment above (WO-163, 2026-09-10, generalizing WO-162's
        # CivicPlus-only fix). Checked once, up front, rather than inside
        # each platform branch below, since the honest answer ("unknown")
        # is the same regardless of which vendor's corporate host this
        # is -- none of the checks below would match it either.
        return "unknown"

    if "granicus.com" in netloc:
        return "granicus"
    if "legistar.com" in netloc:
        return "legistar"
    if "legistar.council.nyc.gov" in netloc:
        # NYC Council runs Legistar on its own nyc.gov domain rather than
        # *.legistar.com -- confirmed live 2026-08-08, real 87-row
        # calendar page, same underlying Legistar software. Hardcoded
        # rather than detecting by page structure since this is the only
        # confirmed custom-domain Legistar instance so far -- see
        # BACKLOG.md and the collect-edge-case-urls memory for why this
        # isn't generalized from one example. NYC's video links use a
        # Telerik JS modal (`onclick="OpenTelerikWindow(...)"`) rather
        # than a plain href/window.open like every other Legistar city --
        # LegistarAssetFinder recognizes that onclick shape too now, and
        # its server-side redirect chain lands on a Viebit URL, delegated
        # to ViebitAssetFinder below.
        return "legistar"
    if "civicclerk.com" in netloc:
        return "civicclerk"
    if "civicplus.com" in netloc or "civicplus" in netloc:
        # CivicPlus's own corporate/marketing hosts (connect.civicplus.com
        # etc.) already returned "unknown" above, via _ALL_CORPORATE_HOSTS
        # -- this branch is only reached for a real per-government tenant.
        return "civicplus"
    if "primegov.com" in netloc:
        return "primegov"
    if "swagit.com" in netloc or "swagit-video-player" in path:
        # The swagit.com-domain case covers direct Swagit URLs. The
        # path-based check covers city sites that iframe-embed Swagit at
        # their own domain (e.g. dublin.ca.gov/swagit-video-player) --
        # detection works for these, but SwagitAssetFinder itself hasn't
        # been verified against that embed pattern (no live sample found
        # in testing; see BACKLOG.md).
        return "swagit"
    if "escribemeetings.com" in netloc:
        return "escribe"
    if "destinyhosted.com" in netloc:
        # Destiny Software's "AgendaQuick" -- confirmed live 2026-08-21 to
        # be a pure agenda/minutes CMS across 61 real tenants, not a
        # video host of its own (see destinyhosted.py's own docstring and
        # BACKLOG_DONE.md for the full enumeration). Registered as a
        # distinct platform (not left as "unknown") so find_platform_link()
        # follows a destinyhosted.com link found on some OTHER wrapper's
        # page as a real one-more-hop delegation target, rather than
        # skipping it -- confirmed necessary live: Roswell, NM's CivicPlus
        # AgendaCenter, self-hosted on roswell-nm.gov rather than
        # *.civicplus.com, links straight to a destinyhosted.com URL.
        return "destinyhosted"
    if "civicweb.net" in netloc or "diligentoneplatform.com" in netloc:
        # iCompass/CivicWeb (a Diligent brand) -- confirmed live 2026-08-12
        # to be a YouTube-delegating platform, not a video host of its own
        # -- see civicweb.py's own module docstring. The
        # diligentoneplatform.com domain is "Diligent Community", a second,
        # real, live rebrand of this exact same software -- confirmed live
        # 2026-08-27 against a real Winthrop, MN tenant
        # (winthropminnesota.community.diligentoneplatform.com) with a real
        # populated video link (see civicweb.py's own module docstring/
        # _MEETING_ID_RE comments). CivicWebAssetFinder already handles this
        # domain's URL shape (case-insensitive id=/Id= matching, and the
        # MeetingExternalMinutesLinkUrl fallback) -- what was missing was
        # routing here, so URLs on this domain fell through to "unknown"
        # and got generic_fallback.py treatment instead. Real gap hit by a
        # real current jurisdiction: Nevada's statewide public-meeting-
        # notice index (notice.nv.gov) lists live "Washoe County School
        # District" meetings whose outbound link is
        # washoeschools.community.diligentoneplatform.com/Portal/
        # MeetingInformation.aspx?Org=Cal&Id={id}. See BACKLOG_DONE.md.
        return "civicweb"
    if "assembly.ca.gov" in netloc or "senate.ca.gov" in netloc:
        return "ca_legislature"
    if "youtube.com" in netloc or "youtu.be" in netloc:
        return "youtube"
    if "telvue.com" in netloc or netloc.endswith("peg.tv"):
        # TelVue -- found 2026-08-16 via generic_fallback already having
        # resolved real customer meetings (2 videoplayer.telvue.com pages,
        # 1 u.peg.tv shortlink) with platform="unknown". peg.tv is
        # confirmed live to be a plain HTTP redirect straight to a
        # videoplayer.telvue.com page (u.peg.tv/s/{code} -> 200 on the
        # telvue URL) -- same "wrapper" pattern as Legistar/CivicPlus's
        # Granicus delegation, not a distinct platform needing its own
        # adapter. See telvue.py's own docstring for the real page
        # structure this was built against.
        return "telvue"
    if "viebit.com" in netloc:
        # The real video platform underneath NYC Council's Legistar
        # instance, reached by delegation (see the legistar.council.nyc.gov
        # case above) -- confirmed live 2026-08-08. Not yet confirmed
        # whether any city links to Viebit directly rather than through a
        # Legistar wrapper.
        return "viebit"
    if "lims.minneapolismn.gov" in netloc:
        # Minneapolis's own "Legislative Information Management System" --
        # confirmed live 2026-08-09 to need a real headless-browser fetch
        # (see headless_browser.py), not the plain aiohttp GET every other
        # adapter here uses. Not yet confirmed whether "LIMS" is a white-
        # labeled product other cities use under different domains -- see
        # BACKLOG.md.
        return "lims"
    if netloc.endswith("slc.gov") and "-meeting-recap" in path:
        # Salt Lake City's own council meeting-recap pages -- confirmed
        # live 2026-08-09 to also need a real headless-browser fetch (same
        # Cloudflare-challenge blocker as Minneapolis LIMS above, a real
        # recurring platform-coverage gap, not two unrelated ones -- see
        # BACKLOG.md). Scoped to the specific "-meeting-recap" path
        # pattern confirmed across four real pages, not the whole
        # slc.gov domain, since most of that site is ordinary city-
        # government content this app has no reason to try to resolve.
        return "slc"
    _cablecast_bare_show_id = (
        path[len("/show/") :].split("/")[0] if path.startswith("/show/") else ""
    )
    if "cablecast.tv" in netloc and (
        "/internetchannel/show/" in path
        or _cablecast_bare_show_id.isdigit()
        or "/cablecastpublicsite/show/" in path
    ):
        # Detroit, MI's Cablecast video portal -- confirmed live
        # 2026-08-12, see cablecast.py's own module docstring for why
        # this is scoped to specific URL shapes (Remix.js portal
        # templates) rather than any *.cablecast.tv domain -- Charlotte,
        # NC's confirmed Cablecast site uses a visibly different template
        # this adapter doesn't handle. The bare "/show/{id}" form (no
        # "/internetchannel" prefix) is a newer template variant, added
        # 2026-08-18 after confirming live that this routing check was
        # the reason `cablecast.py`'s own already-correct handling for it
        # (root-page fallback + string-normalized showId, see that
        # module's docstring) was unreachable through the real
        # detect_platform() -> get_finder() -> resolve() path every
        # production caller actually uses -- a fix verified only by
        # calling the finder directly bypasses this exact gap, which is
        # what happened here until this was caught by re-testing through
        # the real pipeline. Still scoped to specific `/show/{id}`-shaped
        # paths, not the whole domain, so the other confirmed
        # out-of-scope templates (a login-gated FrontDoor.aspx ASP.NET
        # portal, a legacy ASP.NET "WebSchedule" print-schedule generator
        # with no per-show links at all) remain correctly unclaimed. The
        # third path variant added here, "/CablecastPublicSite/show/{id}",
        # is what an earlier version of this comment called "a fully
        # client-rendered SPA with no embedded state" -- true of the
        # *page*, but a real, open JSON API sits underneath it, found
        # 2026-08-29 (see cablecast.py's own module docstring on
        # `_PUBLICSITE_SHOW_ID_RE` for the real API shape) -- so it's in
        # scope now, just resolved differently (two JSON calls, no HTML
        # scraping) from the other two.
        return "cablecast"
    if "clerkshq.com" in netloc:
        # ClerkBase ("ClerkHQ") -- confirmed live 2026-08-14 against one
        # real customer (Yellow Springs, OH) -- see clerkbase.py's own
        # module docstring for the landing-page/document-page shapes and
        # how video is found (a wrapper link straight to a YouTube embed).
        return "clerkbase"
    if "champds.com" in netloc:
        # CHAMP/ChampDS -- confirmed live 2026-08-13 against 6 independent
        # real customers (Atlanta GA, Auburn NY, Gillette WY, Marlborough
        # MA, Saco ME, Worcester MA), all sharing this exact
        # play.champds.com domain with the customer as a path segment,
        # not a subdomain -- see champds.py's own module docstring.
        return "champds"
    if "iqm2.com" in netloc:
        # IQM2 -- confirmed live 2026-08-13 against two real customers
        # (Atlanta GA's atlantacityga.iqm2.com, Santa Clara County CA's
        # sccgov.iqm2.com), each on its own subdomain with the customer as
        # the subdomain itself -- see iqm2.py's own module docstring.
        return "iqm2"
    if (
        netloc.endswith("seattlechannel.org")
        and path == "/videos"
        and "videoid" in parse_qs(urlparse(url).query)
    ):
        # Seattle Channel -- confirmed live 2026-08-14, scoped narrowly to
        # the `/videos?videoid={id}` shape (single video, no ambiguity) --
        # see seattlechannel.py's own module docstring for why the older
        # feed-style index pages and a bare `/videos` (no videoid) are
        # deliberately left to generic_fallback.py instead.
        return "seattle_channel"
    if "auroratv.org" in netloc:
        # Aurora, CO's own Drupal-built council video site -- confirmed
        # live 2026-08-12, found during a Wave 2 platform-coverage pass
        # (see BACKLOG.md). Plain aiohttp GET works (no Cloudflare
        # challenge like the two cases above), but its underlying video/
        # caption hosts' response to Render's specific cloud IP is
        # genuinely unconfirmed -- see aurora.py's own module docstring.
        return "aurora_tv"
    if "/meetings/viewmeeting" in path:
        # Hyland "OnBase Agenda Online" -- confirmed live 2026-08-16 across
        # 3 real customer domains (tucsonaz.hylandcloud.com, mccobagenda.
        # databankcloud.com, agendanet.saccounty.gov), each a different
        # reseller/hosting domain AND a different product-name path segment
        # ("221agendaonline"/"AgendaOnline"/"BoardofSupervisors") serving
        # the identical vendor template -- an earlier version of this check
        # required "agendaonline" in the path too, which real-world-tested
        # false on Sacramento's `/BoardofSupervisors/Meetings/ViewMeeting`
        # shape (caught via bulk_ingest.py --dry-run against the real URL,
        # not by inspection). `/Meetings/ViewMeeting` alone, confirmed
        # identical and specific across all 3, is the right fingerprint --
        # see hyland.py's own module docstring for the rest of the
        # investigation.
        return "hyland"
    if path.startswith("/agendacenter"):
        # CivicPlus "AgendaCenter" -- identical shape to Hyland's path
        # check just above: most real CivicPlus tenants are white-labeled
        # onto the government's OWN domain (confirmed live, see
        # civicplus.py's module docstring for the enumeration), not a
        # *.civicplus.com subdomain, so the netloc-based "civicplus"
        # branch above never fires for them. Placed AFTER every netloc
        # check in this function (this is the last path-only check, right
        # after Hyland's) so an explicit vendor-host match always wins --
        # this only fires once nothing above has already claimed the URL.
        # WO-272 (2026-09-12) mined the real scale of this gap with zero
        # fetches, from URLs already on file: 1,209 jurisdiction_
        # coverage.csv rows across 1,205 distinct self-hosted hosts, plus
        # 250 already-archived Archive pages across 245 distinct
        # governments, whose source_url is a bare, self-hosted
        # `/AgendaCenter` URL -- every one of those pages exists only
        # because a dedicated sweep script called civicplus.py directly,
        # bypassing this function entirely. Confirmed real self-hosted
        # examples: welcometoatmore.com/AgendaCenter, www.voluntown.gov/
        # AgendaCenter (bare listings), www.waynecountyny.gov/
        # AgendaCenter/ViewFile/Minutes/_09022026-1555 (a single document
        # link, same host prefix) -- see BACKLOG_DONE.md's WO-275 entry
        # and docs/investigations/url_shape_mining.md for the rest of the
        # investigation. This is a routing fix only: CivicPlus AgendaCenter
        # sites are already measured at ~80% agenda-only/no video, so this
        # doesn't create new video pages on its own -- it just makes a
        # self-hosted AgendaCenter URL reached through any OTHER path
        # (a hop-link scorer, passive discovery, a reader's own paste)
        # get civicplus.py's dedicated category-listing walk instead of
        # generic_fallback.py.
        return "civicplus"
    if "castus.tv" in netloc and "/vod/" in path:
        # Castus -- a real PEG/government-access video platform, confirmed
        # live 2026-08-21 (WO-19) against one real customer, Billings, MT's
        # comm7tv channel (cloud.castus.tv/vod/comm7tv/video/{id}). Scoped
        # to the confirmed `/vod/{tenant}/video/{id}` template specifically
        # (not the bare domain), the same static-shell-over-a-real-JSON-API
        # shape as champds.py -- see castus.py's own module docstring for
        # the full investigation (the SPA's webpack bundles, not a headless
        # browser, are what solved the tenant-slug -> channel-id mapping).
        return "castus"
    if "townhallstreams.com" in netloc:
        # A small, real, multi-town government video vendor -- confirmed
        # live 2026-08-19/20 across 7 real towns, found by accident (not
        # this repo's usual enumeration methods) -- see
        # townhallstreams.py's own module docstring and BACKLOG.md for the
        # investigation.
        return "townhallstreams"
    if netloc.endswith("open.media") or netloc.endswith("ompnetwork.org"):
        # `ompnetwork.org` is the same product on a second vendor domain,
        # not a different platform -- added 2026-08-23 (WO-46) after Ryan
        # found real Santa Barbara council meetings there while reviewing
        # skipped pages. Confirmed live on both
        # `santabarbaraca.ompnetwork.org/sessions/346145` and `/346146`:
        # this adapter resolves them unchanged, returning a real title,
        # jurisdiction ("City of Santa Barbara, CA"), date, and **1,787
        # real caption segments** on the regular meeting -- so these pages
        # need no transcription at all, they already have captions.
        # Without this line they fall through to generic_fallback, which
        # does find the video but hits exactly the title/jurisdiction
        # swap bug described below.
        #
        # Note this does NOT by itself fix Santa Barbara's archived pages:
        # those were ingested from `docs.santabarbaraca.gov/OnBaseAgenda
        # Online`, an OnBase agenda host with no video on it at all. The
        # video living on a separate system from the agenda is a
        # jurisdiction-level source-mapping problem -- see BACKLOG.md.
        #
        # open.media (OMP Network) -- confirmed live 2026-08-21 across 6
        # real tenant subdomains (goodyearaz, eugene, cortez,
        # santabarbaraca, surpriseaz, townofgeorgetown). Already resolved
        # correctly via generic_fallback.py's own YouTube-embed detection
        # before this was registered (the real video id is present in a
        # raw, un-rendered `<meta property="og:video">` tag on every
        # tenant checked, not only in the client-rendered `<iframe>` the
        # visible player injects) -- registered as its own platform so
        # these resolves are attributed to "open_media" rather than
        # counted as generic/unknown, and so a real, confirmed
        # jurisdiction-extraction bug (generic_fallback.py's
        # `_TITLE_TAG_PIPE_RE` assumes the opposite title-tag order from
        # this platform's real "{Jurisdiction} | {Meeting title}" shape)
        # gets its own correct extractor instead of silently swapping
        # title and jurisdiction -- see openmedia.py's own module
        # docstring for the full investigation.
        return "open_media"
    if "chicityclerkelms.chicago.gov" in netloc:
        # Chicago's City Clerk "ELMS" legislative portal -- a real,
        # single-tenant city platform (not a vendor product), confirmed
        # live 2026-08-10/11/12 and built out 2026-08-21 (WO-29). Its
        # video is injected client-side from a separate public JSON API
        # (the raw page HTML has zero mention of the real Vimeo link) --
        # see chicago_elms.py's own module docstring.
        return "chicago_elms"
    if is_vimeo_host(netloc) and (
        parse_vimeo_video(url) is not None or is_vimeo_listing(url)
    ):
        # Vimeo, registered 2026-08-21 (WO-29) after full playback support
        # landed in app/static/player.js -- before that, a Vimeo link was
        # only ever a dead-end "we think the video is here" pointer from
        # generic_fallback.py (which still handles the pointer case for
        # any Vimeo shape this doesn't claim).
        #
        # Deliberately NOT a bare "vimeo.com in netloc" check, unlike
        # every vendor-domain case above: vimeo.com is a general-purpose
        # video host, so a city site's "vimeo.com/cityname" footer link
        # is a real, confirmed false-positive class (the same one that
        # makes "youtube" an excluded platform in
        # `generic_fallback._try_delegate_to_known_platform()`). Only URL
        # shapes that carry a real video id, or one of the two listing
        # shapes confirmed to server-render a real meeting list, are
        # claimed -- see vimeo.py's own module docstring.
        return "vimeo"
    if "suiteonemedia.com" in netloc:
        # SuiteOne Media -- a small, real, multi-tenant civic video vendor,
        # confirmed live 2026-08-21 across 6 real tenants (pacificgroveca,
        # lorainoh, tuscaloosaal, camaswa, holladayut, stmarysga) -- see
        # suiteone.py's own module docstring for the real page structure
        # this was built against.
        return "suiteone"
    if netloc == "apps.tampagov.net":
        # Tampa, FL City Council's own real-time-captioning transcript
        # webapp ("CTTV") -- confirmed live 2026-08-30 (WO-73). See
        # tampa.py's own module docstring for the real page structure
        # (a paired YouTube video embedded directly on every transcript
        # detail page, no cross-referencing against the paginated listing
        # grid needed).
        return "tampa"
    if netloc.endswith(".hosted.civiclive.com") or netloc.endswith(
        ".hosted2.civiclive.com"
    ):
        # CivicLive (Intrafinity, formerly West Corp) -- a real, distinct
        # municipal CMS with 1000+ customers and no video product of its
        # own, confirmed live 2026-09-01 (WO-92). Both `hosted` and
        # `hosted2` are genuinely Cloudflare-wildcarded at the DNS/TLS
        # level (a nonsense subdomain resolves to the same catch-all IPs
        # and gets a real `*.hosted[2].civiclive.com` wildcard cert) --
        # so unlike civicplus.com/primegov.com, subdomain existence alone
        # never confirms a real tenant. `hosted.civiclive.com` degrades
        # cleanly at the HTTP layer instead (a clean 404
        # `errors/FileNotFound.aspx` for an unknown name); `hosted2.
        # civiclive.com` returns a 200 either way, discriminated instead
        # by a real, distinct ~24KB "Home - Intrafinity" default-tenant
        # page vs. a real tenant's much larger page carrying a genuine
        # "Powered by Civiclive" footer credit -- see civiclive.py's own
        # module docstring for the full investigation this was built
        # from, including why a third+ `hostedN` shape doesn't exist
        # (hosted3-5 don't even resolve).
        return "civiclive"
    if netloc in PROUDCITY_KNOWN_DOMAINS:
        # ProudCity (WordPress `wp-proud-meeting` plugin) -- no shared apex
        # domain across tenants (white-labeled onto each city's own
        # .gov/.org domain, same problem Hyland had), so this is a
        # curated, human-verified domain set rather than a general rule --
        # see proudcity.py's own module docstring for the full evidence
        # trail and BACKLOG_DONE.md's 2026-08-26 entry.
        return "proudcity"
    if netloc.endswith("municodemeetings.com"):
        # Municode Meetings -- a real, multi-tenant civic agenda/minutes
        # CMS (Drupal-based, "MCC Portal"), confirmed live 2026-09-01
        # across bristol-ri, hamburg-mi, and fairoaksranch-tx. Like
        # Legistar/CivicPlus/CivicWeb, it's not a video host of its own --
        # see municode_meetings.py's own module docstring for the real
        # page structure (a Drupal Views meetings table on the tenant
        # homepage, delegating to a meeting detail page's own
        # `#mcc_agenda_video` iframe, confirmed both YouTube and Vimeo
        # destinations).
        return "municode_meetings"
    if netloc.endswith("utah.gov") and "/pmn/sitemap/notice/" in path:
        # Utah's statutory Public Notice Website -- confirmed live
        # 2026-09-08 via a full statewide enumeration pilot
        # (`scripts/pmn_utah_pilot.py`, ENUMERATION_METHODS.md §105).
        # Scoped to the specific `/pmn/sitemap/notice/{id}.html` detail-
        # page shape (one real notice = exactly one meeting, never a
        # listing) rather than the whole utah.gov domain, which is
        # mostly unrelated state-government content -- see
        # utah_pmn.py's own module docstring for the two real media
        # shapes this handles.
        return "utah_pmn"
    if is_invintus_meeting_url(url):
        # Invintus -- a general-purpose government webcasting platform
        # (state legislatures, county boards, city councils), confirmed
        # live 2026-09-08 against real tenants in three different states
        # (University Place WA, Clark County WA, Leon County FL), found
        # via a real gap on University Place's CivicPlus AgendaCenter
        # page -- see invintus.py's own module docstring and
        # `rtr-business/research/ENUMERATION_METHODS.md` §102 for the
        # full investigation. Deliberately NOT a bare "invintus.com in
        # netloc" check, the same reasoning Vimeo's own scoping gives:
        # only claimed when a real `clientID`+`eventID` pair is present,
        # so an unrelated page on the same apex domain (e.g.
        # `hostedevents.invintus.com`'s one-off branded landing pages)
        # is never claimed here.
        return "invintus"
    if is_az_legislature_video_url(url):
        # Arizona State Legislature (azleg.gov) -- found 2026-09-09 while
        # chasing the Invintus prevalence sweep above: clientID
        # 6361162879 (a real, large, sustained Invintus client) turned
        # out to belong to azleg.gov's own `/videoplayer/?eventID=`
        # wrapper pages, confirmed live -- see az_legislature.py's own
        # module docstring for the full investigation. A delegation
        # platform like Legistar/CivicPlus, not a direct video host: the
        # wrapper page's own markup carries no real title/date at all,
        # only an embedded Invintus clientID+eventID this module extracts
        # and hands to InvintusAssetFinder via resolve_via_platform().
        return "az_legislature"
    if parse_wistia_account_url(url) is not None:
        # Wistia -- confirmed live 2026-09-10 (WO-161) against RegionalWebTV/
        # Advanced Media Solutions of Virginia's shared `amsva.wistia.com`
        # account (Warrenton VA, Manassas VA, Fredericksburg VA, Stafford
        # County VA). Deliberately NOT a bare "wistia.com in netloc" check,
        # the same reasoning Vimeo's own scoping gives above: wistia.com is
        # a general-purpose video host, so only a real `/medias/{id}` or
        # `/channel/{id}` URL on a real per-account subdomain is claimed --
        # see wistia.py's own module docstring for the full investigation
        # and why a delegating government page (which carries none of
        # these URL shapes itself) is handled inside the adapter's own
        # resolve(), not detected here.
        return "wistia"
    if parse_boxcast_id(url) is not None:
        # BoxCast -- registered as a real, standalone platform 2026-09-11
        # (WO-227), confirmed live across four independent government
        # tenants (Wilmington OH, St. Louis County - Clayton MO, Hondo TX,
        # Atlantic City NJ). Scoped to the three confirmed real URL shapes
        # `boxcast.tv/view/{id}`, `boxcast.tv/view-embed/{id}` and
        # `boxcast.tv/channel/{id}` -- see boxcast.py's own module
        # docstring for the full investigation, including why the id
        # itself is never trusted to say whether it's a broadcast or a
        # channel (the real API is asked instead).
        return "boxcast"
    return "unknown"


_REGISTRY: dict[str, AssetFinder] = {}


def register(finder: AssetFinder) -> None:
    _REGISTRY[finder.platform_name] = finder


def get_finder(platform: str) -> AssetFinder:
    if platform not in _REGISTRY:
        raise UnsupportedPlatformError(url="", detected=platform)
    return _REGISTRY[platform]


async def resolve_via_platform(url: str) -> ResolvedMeeting:
    """Detect a URL's platform and delegate to its registered finder.

    Used by wrapper platforms like Legistar, which don't host video/captions
    themselves but redirect or link to a platform that does (usually
    Granicus) -- resolving the linked URL should go through that platform's
    real adapter, not be treated as a dead end.
    """
    platform = detect_platform(url)
    finder = get_finder(platform)
    return await finder.resolve(url)


_DELEGATABLE_LINK_TAGS = ("a", "iframe", "video", "source")

# First single/double-quoted string argument of a JS function call, e.g.
# `someFunc('https://...')` or `someFunc("https://...", 2)` -- matches
# legistar.py's own narrower `(?:window\.open|OpenTelerikWindow)\('...'`
# but without hardcoding a function name, since this is a shared helper
# used by more than one onclick-modal shape (see find_platform_link()).
_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")


def find_platform_link(
    html: str, page_url: str, *, exclude: FrozenSet[str] = frozenset()
) -> Optional[Tuple[str, str]]:
    """Scans every <a href>/<iframe src>/<video src>/<source src> on a page
    for a link to a platform `detect_platform()` recognizes, returning
    `(absolute_url, platform)` for the first match, or None.

    Built 2026-08-10 for `generic_fallback.py`'s delegation to an
    already-supported platform found as a plain link (e.g. Austin, TX's
    council pages linking out to their Swagit-hosted video). Reused by
    `legistar.py` for the same real gap on a different page shape:
    Baltimore's Legistar instance puts its video link in an attachments
    table as a plain `<a>Recording</a>` pointing at YouTube, not the
    `a.videolink` shape `_find_video_links()` looks for -- Legistar's own
    adapter claims the domain and gives up before generic_fallback.py ever
    gets a chance to run its own version of this same scan.

    `exclude` matters specifically for "youtube": `detect_platform()`'s
    broad `"youtube.com" in netloc` check also matches a bare channel/user
    link (a real false positive confirmed live on Aurora, CO's "Watch Us
    on YouTube" footer icon) -- callers that already have a tighter,
    video-ID-validated YouTube check of their own (both `generic_fallback.
    py` and `legistar.py` do, via `YouTubeAssetFinder.extract_video_id()`)
    should exclude "youtube" here and rely on that instead.

    Real bug, confirmed live 2026-08-12: a same-page anchor -- most
    commonly a bare `#fragment` href like an accessibility "skip to
    content" link, which every Legistar page has -- resolves back to
    `page_url` itself via `urljoin()`. If that URL's own platform isn't in
    `exclude` (true for whatever platform is *currently* being resolved,
    since `exclude` only ever covered "youtube"), this returns the current
    page as its own "match," and the caller delegates to that platform's
    `resolve()` on the same page it's already resolving -- which hits the
    same skip-link again, and recurses without bound (confirmed on a real
    Columbus, OH Legistar meeting with no video link at all). Skipping any
    candidate that resolves to the same URL as `page_url` closes this at
    the root, for every caller, independent of what they pass as `exclude`.

    Same root problem, one level less exact: a candidate on a *different*
    page of the same platform as `page_url` itself -- e.g. a destinyhosted.
    com agenda page's own pagination/print/month-nav links, which are
    also destinyhosted.com URLs and (since destinyhosted.com became its
    own registered platform, not "unknown") would otherwise match before
    the real onclick video link further down the DOM is ever reached.
    Confirmed live 2026-08-21: this silently broke every destinyhosted
    resolve the moment destinyhosted.com stopped being "unknown", exactly
    the class of bug the exact-URL check above already exists to prevent.
    Skipping any candidate whose own detected platform equals `page_url`'s
    closes this the same general way, for every caller -- a same-platform
    link is internal navigation, never a real delegation target.
    """
    soup = BeautifulSoup(html, "html.parser")
    page_url_no_fragment = urlparse(page_url)._replace(fragment="").geturl()
    own_platform = detect_platform(page_url)
    for tag in soup.find_all(_DELEGATABLE_LINK_TAGS):
        values = []
        href_or_src = tag.get("href") or tag.get("src")
        if href_or_src:
            values.append(href_or_src.strip())
        # A real, recurring shape beyond Legistar's own window.open()/
        # OpenTelerikWindow() onclick handling (legistar.py's own
        # _find_video_links()): a plain `href="#"` paired with
        # `onclick="someFunc('https://...')"` that never appears as a
        # literal href/src at all -- confirmed live 2026-08-21 on Destiny
        # AgendaQuick (destinyhosted.com)'s `onclick="swagitPlay('https://
        # {tenant}.swagit.com/videos/{id}#{fragment}')"` video links. Tried
        # as an additional candidate per tag (not a replacement), so an
        # href="#" that fails the same-page check below still gets a
        # chance via onclick instead of being skipped outright.
        onclick = tag.get("onclick")
        if onclick:
            match = _ONCLICK_URL_RE.search(onclick)
            if match:
                values.append(match.group(1).strip())
        for value in values:
            if not value:
                continue
            candidate = urljoin(page_url, value)
            if (
                urlparse(candidate)._replace(fragment="").geturl()
                == page_url_no_fragment
            ):
                continue
            if urlparse(candidate).netloc.lower() in _ALL_CORPORATE_HOSTS:
                # Explicit skip, not just relying on detect_platform()
                # returning "unknown" for these hosts -- see
                # CORPORATE_HOSTS_BY_PLATFORM's own comment (WO-162 for
                # CivicPlus, generalized to every vendor in WO-163,
                # 2026-09-10) for the real bug this closes: a
                # government's own page reaching a vendor's corporate/
                # marketing/login link (e.g. CivicPlus's own "Government
                # Websites by CivicPlus" footer credit) before its real
                # content link.
                continue
            platform = detect_platform(candidate)
            if platform == "unknown" or platform in exclude or platform == own_platform:
                continue
            return candidate, platform
    return None
