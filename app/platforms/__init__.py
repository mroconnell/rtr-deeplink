def register_all_finders() -> None:
    """Registers every platform adapter with base.py's registry (get_finder()
    returns nothing for any platform until this runs). Extracted out of
    app/main.py's module body so worker/main.py can call it explicitly too
    -- the worker needs get_finder() (re-resolving a fresh media URL before
    each chunk) without importing app.main itself, which would also pull in
    the FastAPI app/rate limiter/static file mounts as an import side
    effect. Safe to call more than once (register() just overwrites the
    same platform_name key each time).
    """
    from .aurora import AuroraTvAssetFinder
    from .base import register
    from .ca_legislature import CaliforniaLegislatureAssetFinder
    from .cablecast import CablecastAssetFinder
    from .champds import ChampDSAssetFinder
    from .clerkbase import ClerkBaseAssetFinder
    from .civicclerk import CivicClerkAssetFinder
    from .destinyhosted import DestinyHostedAssetFinder
    from .civicweb import CivicWebAssetFinder
    from .civicplus import CivicPlusAssetFinder
    from .escribe import EscribeAssetFinder
    from .generic_fallback import GenericFallbackAssetFinder
    from .granicus import GranicusAssetFinder
    from .hyland import HylandAssetFinder
    from .iqm2 import IQM2AssetFinder
    from .legistar import LegistarAssetFinder
    from .lims import LimsAssetFinder
    from .openmedia import OpenMediaAssetFinder
    from .primegov import PrimeGovAssetFinder
    from .seattlechannel import SeattleChannelAssetFinder
    from .slc import SlcAssetFinder
    from .swagit import SwagitAssetFinder
    from .telvue import TelvueAssetFinder
    from .townhallstreams import TownHallStreamsAssetFinder
    from .viebit import ViebitAssetFinder
    from .youtube import YouTubeAssetFinder

    register(GranicusAssetFinder())
    register(CivicClerkAssetFinder())
    register(DestinyHostedAssetFinder())
    register(SwagitAssetFinder())
    register(EscribeAssetFinder())
    register(CaliforniaLegislatureAssetFinder())
    register(LegistarAssetFinder())
    register(CivicPlusAssetFinder())
    register(YouTubeAssetFinder())
    register(PrimeGovAssetFinder())
    register(ViebitAssetFinder())
    register(LimsAssetFinder())
    register(SlcAssetFinder())
    register(AuroraTvAssetFinder())
    register(CivicWebAssetFinder())
    register(CablecastAssetFinder())
    register(ChampDSAssetFinder())
    register(IQM2AssetFinder())
    register(ClerkBaseAssetFinder())
    register(SeattleChannelAssetFinder())
    register(TelvueAssetFinder())
    register(HylandAssetFinder())
    register(TownHallStreamsAssetFinder())
    register(OpenMediaAssetFinder())
    # Registered under "unknown" -- the exact string detect_platform()
    # already returns for anything unmatched -- so get_finder("unknown")
    # finds this instead of raising UnsupportedPlatformError. Keep this
    # registration last: it's the true fallback, not a real platform.
    register(GenericFallbackAssetFinder())
