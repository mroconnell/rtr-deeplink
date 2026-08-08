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
    from .base import register
    from .ca_legislature import CaliforniaLegislatureAssetFinder
    from .civicclerk import CivicClerkAssetFinder
    from .civicplus import CivicPlusAssetFinder
    from .escribe import EscribeAssetFinder
    from .granicus import GranicusAssetFinder
    from .legistar import LegistarAssetFinder
    from .primegov import PrimeGovAssetFinder
    from .swagit import SwagitAssetFinder
    from .youtube import YouTubeAssetFinder

    register(GranicusAssetFinder())
    register(CivicClerkAssetFinder())
    register(SwagitAssetFinder())
    register(EscribeAssetFinder())
    register(CaliforniaLegislatureAssetFinder())
    register(LegistarAssetFinder())
    register(CivicPlusAssetFinder())
    register(YouTubeAssetFinder())
    register(PrimeGovAssetFinder())
