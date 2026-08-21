from .base import AssetFinder
from .generic_fallback import GenericFallbackAssetFinder
from .models import ResolvedMeeting


class DestinyHostedAssetFinder(AssetFinder):
    """Destiny Software's "AgendaQuick" product (destinyhosted.com) is a
    pure agenda/minutes CMS, not a video host -- like Legistar/CivicPlus,
    it just links out to whatever video platform a tenant already uses.
    Confirmed live 2026-08-21 across 61 real tenants (enumerated via
    Wayback CDX, see BACKLOG_DONE.md): mostly Swagit (18/61, via a real
    built-in AgendaQuick<->Swagit integration -- swagit_meeting_list.cfm/
    swagit_return_data.cfm endpoints, a per-tenant
    `/{id}/agenda/assets/js/swagit.js`), some YouTube/Granicus/Cablecast-
    Castus/other, several with no video at all -- a genuine per-tenant
    negative, not a gap.

    Registered as its own platform (rather than left undetected as
    "unknown") specifically so `base.find_platform_link()` -- used by
    OTHER wrapper pages that link out to a destinyhosted.com URL one hop
    away from their own page -- recognizes it as a real delegation target
    instead of silently skipping it. Confirmed live 2026-08-21: Roswell,
    NM runs CivicPlus's AgendaCenter self-hosted on its own domain
    (roswell-nm.gov/AgendaCenter/...) rather than *.civicplus.com, which
    `detect_platform()`'s civicplus check never matches -- so this never
    even reaches `CivicPlusAssetFinder`, and lands here as an ordinary
    `GenericFallbackAssetFinder` resolve of the roswell-nm.gov page
    itself, which needs to recognize its outbound
    `public.destinyhosted.com/76793/agenda/...` link as a valid one-more-
    hop delegation target -- exactly what this registration enables.

    Delegates its own page's video/caption extraction unchanged to
    `GenericFallbackAssetFinder` (same tiers, including the onclick-modal
    handling `find_platform_link()` needed for AgendaQuick's own
    `onclick="swagitPlay('...')"` links -- see base.py) rather than
    duplicating that logic; only overrides `platform` when nothing deeper
    was found, so a successful inner delegation (e.g. to "swagit") is
    never masked by this wrapper's own identity.
    """

    platform_name = "destinyhosted"

    def __init__(self):
        self._delegate = GenericFallbackAssetFinder()

    async def resolve(self, url: str) -> ResolvedMeeting:
        resolved = await self._delegate.resolve(url)
        if resolved.platform == "unknown":
            resolved.platform = self.platform_name
        return resolved
