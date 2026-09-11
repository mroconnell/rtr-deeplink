#!/usr/bin/env python3
"""WO-154 (2026-09-10): fingerprint a government website's CMS family.

Ryan's idea: about 9,600 governments in the research file are recorded
`no-platform-link-found` -- their site loaded for a plain client, but no
meeting/video platform link was visible, usually because the site's menu
is drawn by JavaScript. Headless browsing finds those links but is slow.
The cheaper route is to learn the **website CMS family** a government's
site was built on (CivicPlus, Revize, OpenCities/Granicus GovAccess,
ProudCity, CivicLive, Municode's meetings module, Town Web, WordPress
(added WO-176, 2026-09-10 -- ProudCity is itself a WordPress build and
keeps its own more specific rule/family name), ...) from
pages where the family is already known, then, for each family, record
where its meetings page usually lives so a plain client can go straight
there instead of guessing.

This module does ONE thing: given a page's HTML (and, optionally, its
response headers and the URL it came from), return the CMS family with
the real evidence that decided it. It does not fetch anything by
default -- `fetch_once()` is a thin, honest-headers helper for the CLI
and for scripts/wo154 harnesses, kept separate so `classify()` itself
stays a pure function that's trivial to unit test against a saved page.

Every rule below is backed by a real page, fetched once with honest
headers 2026-09-10 while building this module (see
`scripts/wo154_family_sample_300.csv`'s sibling training-set notes in
`~/Documents/rtr-business/research/wo154_methods_section.md` for the
full list) -- the URL and date are in each rule's own comment. A rule
with zero real confirming pages is not included; `Unknown` is the
correct answer for a page whose evidence doesn't clear that bar, and the
signature table (`app/utils/jurisdiction_data/cms_families.csv`) says so
plainly rather than guessing.

Order matters: rules are tried top to bottom, most specific first, and
classification stops at the first match. A page can carry more than one
vendor's fingerprint (e.g. a CivicPlus AgendaCenter site whose footer
also links to Municode's meetings module) -- the first rule to match
wins, and `evidence` records exactly what fired so a human can see why.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlparse

import requests

# Identical values to `~/Documents/rtr-business/research/
# wo141_access_ladder_pilot.py`'s HONEST_HEADERS -- same convention this
# repo's CLAUDE.md and every sweep script in `scripts/` already follow: a
# real UA string naming the project and a contact URL, never a browser
# claim, for a plain fetch.
HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}

REQUEST_TIMEOUT = 10  # seconds -- real government hosts, bounded


@dataclass
class FingerprintResult:
    family: str  # "unknown" when nothing matched
    rule_id: str
    evidence: str
    url: str = ""
    headers_used: List[str] = field(default_factory=list)


def fetch_once(url: str, timeout: int = REQUEST_TIMEOUT):
    """One honest-headers GET. Returns (html, headers, status, final_url)
    on success, or (None, {}, None, str(exc)) on a network-level failure.
    Callers are responsible for their own pacing between hosts -- this
    function makes exactly one request and does not sleep, so a caller
    fetching many pages must add its own delay (2s between requests to
    the *same* host, per this repo's standing politeness convention;
    scripts/wo154_* harnesses that used this during WO-154's own data
    collection did so from a shared per-host clock)."""
    try:
        resp = requests.get(
            url, headers=HONEST_HEADERS, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException as exc:
        return None, {}, None, str(exc)
    return resp.text, dict(resp.headers), resp.status_code, resp.url


_META_GENERATOR_RE = re.compile(
    r'<meta\b[^>]*name=["\']generator["\'][^>]*content=["\']([^"\']*)["\']', re.I
)
_META_GENERATOR_RE_ALT = re.compile(
    r'<meta\b[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']generator["\']', re.I
)
_META_AUTHOR_RE = re.compile(
    r'<meta\b[^>]*name=["\']author["\'][^>]*content=["\']([^"\']*)["\']', re.I
)


def _meta_generator(html: str) -> str:
    m = _META_GENERATOR_RE.search(html) or _META_GENERATOR_RE_ALT.search(html)
    return m.group(1) if m else ""


def _meta_author(html: str) -> str:
    m = _META_AUTHOR_RE.search(html)
    return m.group(1) if m else ""


# --- Known ProudCity tenants, imported by string rather than a hard
# import of app/platforms/proudcity.py (this script runs standalone,
# outside the FastAPI app, and the two lists should stay independently
# maintainable) -- kept in sync by hand; see that module's own comment
# for how PROUDCITY_KNOWN_DOMAINS was built. Confirmed live again here
# 2026-09-10 (fresh fetch, see wo154_family_sample notes): every one of
# these six still serves the same `proudcity.com/js/app.min.js` /
# `proudcity-theme` markers this rule below also checks for directly.
PROUDCITY_KNOWN_DOMAINS = frozenset(
    {
        "townoffairfaxca.gov",
        "www.cityofbelvedere.org",
        "www.cityofsanrafael.org",
        "www.somervillenj.org",
        "www.holyoke.org",
        "cityofmiamisburg.com",
    }
)


def _rule_civiclive(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # CivicLive (Intrafinity) -- host suffix `*.hosted[2].civiclive.com`,
    # or (when the government's own domain masks that, which is the usual
    # case -- see civiclive.py's own docstring) an asset host reference to
    # `hosted[2].civiclive.com`, or the literal footer credit. Real,
    # already-shipped evidence: `app/platforms/civiclive.py`'s own
    # confirmed tenants (Auburn WA `auburn.hosted.civiclive.com`, Escalon
    # CA `escalon.hosted.civiclive.com`, footer "Powered by Civiclive" on
    # every live tenant checked there, 2026-09-01). Independently
    # reconfirmed for WO-154 2026-09-10 on Lynn, MA
    # (`https://www.lynnma.gov/`, which is NOT itself a civiclive.com
    # host -- the CMS is invisible from the domain alone, only from its
    # own asset host `cdnsm1-hosted2.civiclive.com` inside the page).
    if netloc.endswith(".hosted.civiclive.com") or netloc.endswith(
        ".hosted2.civiclive.com"
    ):
        return FingerprintResult(
            "civiclive", "civiclive-host-suffix", f"host={netloc}", url
        )
    # WO-179 (2026-09-10): this regex used to open with an UNBOUNDED
    # `[a-z0-9.-]*` immediately before a literal that often fails to
    # match ("hosted2?\.civiclive\.com") -- classic catastrophic-
    # backtracking shape. Confirmed live: a real 10MB government
    # homepage (Sherman, IL, shermanil.org, 2026-09-10) hung this rule
    # for minutes -- long runs of dot/dash/alnum characters (an inlined
    # base64 asset, a minified-JS hash) give `re.search` many candidate
    # start positions inside the same run, each one backtracking through
    # the whole run trying the literal, which is quadratic in the length
    # of that run. Fixed two ways: (1) a plain substring pre-check, so
    # the regex only ever runs on a page that actually contains the
    # literal at least once, and (2) bounding BOTH quantifiers (a real
    # DNS label is under 63 chars; the trailing asset-path tail is capped
    # generously at 200) so even a pathological page can't make either
    # side unbounded.
    if "hosted.civiclive.com" in lower_html or "hosted2.civiclive.com" in lower_html:
        m = re.search(
            r"[a-z0-9.-]{0,63}hosted2?\.civiclive\.com[^\s\"'<>]{0,200}", html, re.I
        )
        if m:
            return FingerprintResult(
                "civiclive", "civiclive-asset-host", m.group(0), url
            )
    if "powered by civiclive" in lower_html:
        return FingerprintResult(
            "civiclive", "civiclive-footer-credit", "footer: Powered by Civiclive", url
        )
    return None


def _rule_proudcity(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # ProudCity -- confirmed live 2026-09-10 on townoffairfaxca.gov and
    # www.cityofbelvedere.org (both PROUDCITY_KNOWN_DOMAINS): asset paths
    # `proudcity.com/js/app.min.js`, a `proudcity-theme` body/theme class,
    # and a GCS upload path shaped `.../proudcity/{tenant}/uploads/...`.
    # See app/platforms/proudcity.py's own module docstring for the
    # deeper evidence trail (source-verified against the actual WordPress
    # plugin/theme code, 2026-08-26).
    if netloc in PROUDCITY_KNOWN_DOMAINS:
        return FingerprintResult(
            "proudcity", "proudcity-known-domain", f"domain={netloc}", url
        )
    if re.search(r"proudcity\.com/js/(app|libraries)\.min\.js", html, re.I):
        return FingerprintResult(
            "proudcity",
            "proudcity-asset-path",
            "proudcity.com/js/app.min.js or libraries.min.js",
            url,
        )
    if "proudcity-theme" in lower_html or re.search(
        r"/proudcity/[a-z0-9_-]+/uploads/", html, re.I
    ):
        return FingerprintResult(
            "proudcity",
            "proudcity-theme-or-upload-path",
            "proudcity-theme class or /proudcity/{tenant}/uploads/ path",
            url,
        )
    return None


def _rule_opencities(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # OpenCities (Granicus GovAccess) -- `<meta name="generator"
    # content="OpenCities - https://granicus.com/product/opencities">`.
    # Confirmed live 2026-09-10 on 10 real governments during this
    # module's training pass: San Fernando CA (sanfernando.gov/Home),
    # Richland County SC, Allegheny County PA, Batesville AR, Littleton
    # CO, Syracuse NY, and 4 more (full list in
    # wo154_family_sample_300.csv's sibling training notes). This is the
    # SAME generator tag `app/platforms/base.py`'s own comment (WO-163)
    # cites for Columbus, OH ("OpenCities - https://granicus.com/product/
    # opencities") as a case that must NOT be read as a real Granicus
    # video tenant link -- here it is read correctly, as a website-CMS
    # signature, which is exactly what it actually is.
    generator = _meta_generator(html)
    if "opencities" in generator.lower():
        return FingerprintResult(
            "opencities", "opencities-generator-meta", f'generator="{generator}"', url
        )
    return None


def _rule_govoffice(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # GovOffice -- the government's own domain IS the vendor's own shared
    # domain (govoffice.com / govoffice2.com / govoffice3.com), per
    # WO-179 (2026-09-10), so this is a plain, 100%-reliable netloc
    # suffix check -- no content signature needed, unlike every other
    # rule in this file. About 220 governments in the UScityURL address
    # list name one of these three hosts directly (research/
    # uscityurl_raw.csv). Confirmed live on 10 real tenants while
    # building this rule (evansdale.govoffice.com IA, goodview.govoffice.
    # com MN, ball.govoffice2.com LA, vintontx.govoffice2.com TX,
    # hallowell.govoffice.com ME, pottsboro.govoffice2.com TX,
    # panhandletx.govoffice2.com TX, blountstownfl.govoffice3.com FL,
    # slayton.govoffice.com MN, custer.govoffice.com SD). No single
    # meetings-page path recurs across tenants -- see cms_families.csv
    # for what was tried instead (nav-link scan, sitemap).
    if netloc.endswith(".govoffice.com") or netloc.endswith(
        (".govoffice2.com", ".govoffice3.com")
    ):
        return FingerprintResult(
            "govoffice", "govoffice-domain-suffix", f"host={netloc}", url
        )
    return None


def _rule_municipalimpact(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # Municipal Impact -- same shape as GovOffice above: the government's
    # own domain is the vendor's shared `municipalimpact.com` domain, a
    # plain netloc suffix check. Confirmed live 2026-09-10 on 9 of 10
    # real tenants sampled (townofdelhi LA, townofdoublesprings AL,
    # townofelton LA, cityofcoalhillar AR, cityofamericus KS,
    # fountaincity IN, villageofparks LA, cityoffrost TX, cityofcollins
    # IA -- villageofkirkwood IL returned "site_not_found", not yet
    # provisioned). Unlike GovOffice, this vendor DOES have a reliably
    # recurring meetings path: 8 of those 9 real tenants serve both
    # `/agendas` and `/minutes` as real, directly guessable pages (the
    # 9th, townofdoublesprings, has neither built yet -- a real content
    # gap, not a path miss). See cms_families.csv.
    if netloc.endswith(".municipalimpact.com"):
        return FingerprintResult(
            "municipalimpact", "municipalimpact-domain-suffix", f"host={netloc}", url
        )
    return None


def _rule_in_gov_towns_portal(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # Indiana's own shared "in.gov/towns/{slug}/" portal -- one of
    # WO-179's three "state-hosted template" families (2026-09-10).
    # Distinct from a town having its own `{name}.in.gov` domain (those
    # turned out, when fetched, to already be recognised WordPress or
    # CivicPlus tenants in this WO's own 9-government sample -- see
    # cms_families.csv's "state-hosted" row for the full breakdown) --
    # this rule only fires for towns with NO domain of their own, hosted
    # directly under the state's own `www.in.gov` apex. Confirmed live
    # on Georgetown, IN (`www.in.gov/towns/georgetown/`, redirected there
    # from `georgetown.in.gov`): `/towns/georgetown/meetings` is a real,
    # populated agenda-PDF listing page -- the exact same path shape
    # (`/towns/{slug}/meetings`) is expected to generalise to every other
    # town on this same portal, though only this one tenant has been
    # confirmed so far.
    if netloc in ("www.in.gov", "in.gov") and re.match(
        r"^/towns/[a-z0-9-]+/?", urlparse(url).path, re.I
    ):
        return FingerprintResult(
            "in_gov_towns_portal",
            "in-gov-towns-path",
            f"path={urlparse(url).path}",
            url,
        )
    return None


def _rule_wv_local_gov(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # West Virginia's own shared SharePoint portal
    # (`local.wv.gov/{slug}/`) -- WO-179's second confirmed state-hosted
    # sub-family (2026-09-10). Confirmed live on 3 real towns (all
    # redirect their own `{name}.wv.gov`-style row in the population to
    # this shared host): Williamstown, Madison, Fayetteville. Recognised
    # from the host itself, or from the `Microsoft SharePoint` generator
    # meta tag plus a `cdn.wvegov.com` asset reference (belt-and-braces,
    # in case a future tenant is reached by a different alias domain).
    # **No meetings-page path is confirmed** -- the homepage's nav is
    # SharePoint script-rendered and a plain-HTTP fetch found zero
    # meeting-word links on any of the 3 tenants checked; treat this
    # family the same honest way as CivicLive/Town Web above (recognised,
    # but route through the generic path/sitemap list rather than a
    # guessed vendor path).
    if netloc == "local.wv.gov":
        return FingerprintResult(
            "wv_local_gov", "wv-local-gov-host", f"host={netloc}", url
        )
    if (
        "microsoft sharepoint" in _meta_generator(html).lower()
        and "cdn.wvegov.com" in lower_html
    ):
        return FingerprintResult(
            "wv_local_gov",
            "wv-local-gov-sharepoint-signature",
            "generator=Microsoft SharePoint + cdn.wvegov.com",
            url,
        )
    return None


def _rule_revize(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # Revize -- asset host `cms{N}.revize.com/revize/{tenant}/...` (the
    # `og:image` logo URL every Revize tenant carries) or a `/revize/
    # plugins/...` stylesheet path. Confirmed live 2026-09-10 on 15 real
    # governments: Adel IA, Decatur AL, Huron SD, Soledad CA, Corcoran MN,
    # Manassas VA, Cramerton NC, Pearsall TX, Edinburg TX, Villa Rica GA,
    # Delavan WI, Dade City FL, Kronenwetter WI, San Dimas CA, Rochester
    # Hills MI -- the single most common non-CivicPlus family found in
    # this sample.
    m = re.search(r"cms\d*\.revize\.com/revize/[^\s\"'<>]*", html, re.I)
    if m:
        return FingerprintResult("revize", "revize-cdn-asset", m.group(0), url)
    if re.search(r"/revize/plugins/[^\s\"'<>]*", html, re.I):
        return FingerprintResult(
            "revize", "revize-plugins-path", "/revize/plugins/...", url
        )
    return None


def _rule_municode_web(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # Municode's meetings module -- a link on the government's own
    # domain to `https://{slug}.municodemeetings.com/`. This is narrower
    # than a full website-CMS family (the parent site's own CMS varies --
    # WordPress, custom, CivicPlus) but it is the one signal that matters
    # for WO-155's purpose: it names the meetings-page path directly.
    # Confirmed live 2026-09-10 on 9 real governments: Jackson MO (whose
    # main site is CivicPlus and links out to
    # jackson-mo.municodemeetings.com in its footer), Austell GA, Kaukauna
    # WI, Dundee FL, Rochelle IL, Ballwin MO, Moncks Corner SC, Norman OK,
    # Kronenwetter WI.
    m = re.search(r"https?://([a-z0-9-]+)\.municodemeetings\.com", html, re.I)
    if m:
        return FingerprintResult(
            "municode_web", "municode-meetings-link", m.group(0), url
        )
    return None


def _rule_townweb(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # Town Web -- confirmed live 2026-09-10 two ways: a `cdn.townweb.com`
    # dns-prefetch link (Glen Cove, NY --
    # glencoveny.gov/city-council-meeting-livestream) and a literal
    # `<meta name="author" content="Town Web | SK">` tag (Olean, NY --
    # cityofolean.gov/live-stream). Deliberately narrower than a bare
    # "town web" substring match -- an early version of this rule matched
    # that phrase and false-positived on Batesville, IN's own marketing
    # copy ("...best small town websites"), which has nothing to do with
    # the vendor.
    if "cdn.townweb.com" in lower_html:
        return FingerprintResult("townweb", "townweb-cdn-host", "cdn.townweb.com", url)
    author = _meta_author(html)
    if "town web" in author.lower():
        return FingerprintResult(
            "townweb", "townweb-meta-author", f'author="{author}"', url
        )
    return None


def _rule_wordpress(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # WordPress -- a general-purpose CMS, not a government-specific
    # vendor, so this rule runs LAST of the WordPress-family checks
    # (after ProudCity, which is itself a WordPress build with its own
    # more specific signature and must be reported as "proudcity", not
    # this generic fallback). Recognise it from `<meta name="generator"
    # content="WordPress ...">`, a `/wp-content/` asset path, or a
    # `/wp-json/` REST endpoint reference (also in the `Link:` response
    # header on some tenants -- checked by the pilot script, not here,
    # since this function only sees the HTML). Confirmed live 2026-09-10
    # (WO-176's own 600-government pilot): 175 of 600 real
    # no-platform-link governments fingerprinted as WordPress this way --
    # by far the most common single family in that sample, ahead of
    # CivicPlus (23) and Revize (32) combined. Its meetings page is not
    # one fixed path (unlike CivicPlus's `/AgendaCenter`) -- see
    # `cms_families.csv`'s own `meetings_page_path_patterns` for the
    # measured path/feed hit rates that make `/?s=agenda` (WordPress's
    # own built-in search) the one that actually works at scale.
    generator = _meta_generator(html)
    if "wordpress" in generator.lower():
        return FingerprintResult(
            "wordpress", "wordpress-generator-meta", f'generator="{generator}"', url
        )
    if "/wp-content/" in lower_html or "/wp-json/" in lower_html:
        return FingerprintResult(
            "wordpress", "wordpress-asset-path", "/wp-content/ or /wp-json/ path", url
        )
    return None


def _rule_civicplus(
    html: str, lower_html: str, netloc: str, url: str
) -> Optional[FingerprintResult]:
    # CivicPlus's own CMS -- an AgendaCenter or CivicAlerts.aspx module
    # mounted on the government's own domain, a `cp-civicplusuniversity2.
    # civicplus.com` asset reference (the CivicPlus University widget
    # embedded on every real tenant checked), or the literal footer badge
    # "Government Websites by CivicPlus". All four confirmed live
    # 2026-09-10 across dozens of pages in this training pass (e.g. Eugene,
    # OR -- eugene-or.gov/AgendaCenter -- carries the exact footer text
    # "Government Websites by CivicPlus&reg;"). This is a website-CMS
    # signature, distinct from `app/platforms/base.py`'s
    # `detect_platform()`, which classifies a *meeting URL* by platform,
    # not a home page by CMS -- the two agree on CivicPlus most of the
    # time (CivicPlus sells both), which is expected, not circular: this
    # rule fires on page content, that one on URL shape.
    if (
        "government websites by civicplus" in lower_html
        or "powered by civicplus" in lower_html
    ):
        return FingerprintResult(
            "civicplus",
            "civicplus-footer-badge",
            "footer: Government Websites by CivicPlus",
            url,
        )
    if "cp-civicplusuniversity" in lower_html:
        return FingerprintResult(
            "civicplus",
            "civicplus-university-widget",
            "cp-civicplusuniversity2.civicplus.com",
            url,
        )
    if re.search(r"/agendacenter\b", html, re.I) or "civicalerts.aspx" in lower_html:
        return FingerprintResult(
            "civicplus",
            "civicplus-path-shape",
            "/AgendaCenter or CivicAlerts.aspx",
            url,
        )
    return None


# Order matters: most specific / least ambiguous first. A page can carry
# more than one vendor's fingerprint (e.g. a CivicPlus AgendaCenter site
# whose footer also links to Municode's meetings module) -- the first
# rule to match wins. CivicPlus is deliberately last: its weakest signal
# (the bare `/AgendaCenter` path) is also the most common substring
# elsewhere (any site can menu-link the word "agenda"), so every
# stronger, narrower vendor signal gets first look.
RULES = [
    # Domain-suffix / host+path rules first -- these are deterministic
    # (the government's own domain literally IS the vendor's or state's
    # shared domain), zero false-positive risk, so ordering them ahead
    # of the content-sniffed rules below costs nothing and can't shadow
    # a real content signal for a different family.
    _rule_govoffice,
    _rule_municipalimpact,
    _rule_in_gov_towns_portal,
    _rule_wv_local_gov,
    _rule_civiclive,
    _rule_proudcity,
    _rule_opencities,
    _rule_revize,
    _rule_municode_web,
    _rule_townweb,
    _rule_civicplus,
    _rule_wordpress,
]


def classify(
    html: str, headers: Optional[dict] = None, url: str = ""
) -> FingerprintResult:
    """Return the CMS family for one page's HTML. `headers` (a dict of
    real response headers) and `url` are optional but improve a few
    rules (host-suffix checks need the URL; a bare HTML string without
    either still classifies on the DOM-only rules)."""
    headers = headers or {}
    netloc = urlparse(url).netloc.lower() if url else ""
    lower_html = html.lower()

    for rule in RULES:
        result = rule(html, lower_html, netloc, url)
        if result is not None:
            return result

    return FingerprintResult("unknown", "no-rule-matched", "", url)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="Fetch this URL once (honest headers) and classify it."
    )
    parser.add_argument(
        "--file", help="Classify a saved HTML file instead of fetching."
    )
    parser.add_argument("--json", action="store_true", help="Print the result as JSON.")
    args = parser.parse_args(argv)

    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        result = classify(html, url=args.url or "")
    elif args.url:
        html, headers, status, final_url = fetch_once(args.url)
        if html is None:
            print(f"fetch failed: {final_url}", file=sys.stderr)
            return 1
        result = classify(html, headers, final_url)
    else:
        parser.error("pass --url or --file")
        return 2

    if args.json:
        print(json.dumps(result.__dict__))
    else:
        print(
            f"family={result.family} rule={result.rule_id} evidence={result.evidence!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
