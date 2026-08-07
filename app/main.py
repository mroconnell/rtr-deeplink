from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .platforms.base import detect_platform, get_finder, register, CalendarPageError, UnsupportedPlatformError
from .platforms.granicus import GranicusAssetFinder
from .platforms.civicclerk import CivicClerkAssetFinder
from .platforms.swagit import SwagitAssetFinder
from .platforms.escribe import EscribeAssetFinder
from .platforms.ca_legislature import CaliforniaLegislatureAssetFinder
from .platforms.legistar import LegistarAssetFinder
from .platforms.civicplus import CivicPlusAssetFinder

APP_DIR = Path(__file__).parent

app = FastAPI(title="rtr-deeplink")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

register(GranicusAssetFinder())
register(CivicClerkAssetFinder())
register(SwagitAssetFinder())
register(EscribeAssetFinder())
register(CaliforniaLegislatureAssetFinder())
register(LegistarAssetFinder())
register(CivicPlusAssetFinder())


class ResolveRequest(BaseModel):
    url: str


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/resolve")
async def resolve(req: ResolveRequest):
    platform = detect_platform(req.url)
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {
            "error": "unsupported_platform",
            "platform": platform,
            "message": f"We don't support '{platform}' meeting pages yet.",
        }

    try:
        result = await finder.resolve(req.url)
    except CalendarPageError as e:
        return {
            "error": "calendar_page",
            "platform": platform,
            "message": str(e),
            "candidates": e.candidates,
        }
    except Exception as e:
        return {
            "error": "resolve_failed",
            "platform": platform,
            "message": str(e),
        }

    return result.model_dump()


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/meeting")
async def meeting_redirect(request: Request, url: str = ""):
    if not url:
        return RedirectResponse("/")
    return templates.TemplateResponse(
        request,
        "meeting.html",
        {"source_url": url},
    )


@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html", {})
