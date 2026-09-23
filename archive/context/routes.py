"""Private HTTP routes for the Context research candidate queue.

The router is built with Archive's authentication helpers injected by
``archive.main``.  This keeps this package independent of that large module and
also makes the authorization boundary straightforward to exercise in tests.
"""

import inspect
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from .schemas import ImportRequest, InternalRecheckRequest, NextAction
from ..utils.context_editors import is_context_editor

_MAX_REQUEST_BYTES = 1_000_000
_MAX_CANDIDATE_ID = 9_223_372_036_854_775_807
_MAX_CANDIDATE_ID_DIGITS = len(str(_MAX_CANDIDATE_ID))
_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex",
}
_NEXT_ACTIONS = {
    "new",
    "check_failed",
    "conflict",
    "resolve_needed",
    "recording_needed",
    "ingest_needed",
    "moment_needed",
}


def _store_module():
    # Deferred so the route package can be tested against fakes while the
    # storage package is developed independently in the same milestone.
    from . import store

    return store


def _importer_module():
    from . import importer

    return importer


def _next_action_labels() -> dict[str, str]:
    # status.py owns the wording; deferred for the same independently-tested
    # package boundary as store/importer above.
    from .status import NEXT_ACTION_LABELS

    return NEXT_ACTION_LABELS


def _private_json(content: Any, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content, status_code=status_code, headers=_PRIVATE_HEADERS)


def _private_template(
    templates,
    request: Request,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> Response:
    response = templates.TemplateResponse(
        request,
        "context_candidates.html",
        context,
        status_code=status_code,
    )
    response.headers.update(_PRIVATE_HEADERS)
    return response


def _safe_http_url(value: Any) -> str | None:
    """Return an imported URL only when it is an absolute HTTP(S) URL."""
    if not isinstance(value, str) or value != value.strip():
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    if any(ord(char) < 32 for char in value):
        return None
    return value


def _safe_archive_url(value: Any) -> str | None:
    """Allow HTTP(S), plus the two server-created Archive link families."""
    external = _safe_http_url(value)
    if external:
        return external
    if isinstance(value, str) and not value.startswith("//"):
        if value.startswith("/m/") or value.startswith("/context/"):
            return value
    return None


async def _resolved(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _editor_id(clerk_user_id: Callable[[Request], Any], request: Request):
    try:
        return await _resolved(clerk_user_id(request))
    except Exception:
        # Auth failures fail closed and never disclose provider details.
        return None


async def _token_allowed(token_ok: Callable[[str | None], Any], token: str | None):
    try:
        return bool(await _resolved(token_ok(token)))
    except Exception:
        return False


async def _validated_body(request: Request, model):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_REQUEST_BYTES:
            raise ValueError("invalid request")
        body.extend(chunk)
    if not body:
        raise ValueError("invalid request")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid request") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("invalid request") from exc


def _queue_context(**values: Any) -> dict[str, Any]:
    return {
        "active_account": values.pop("active_account", None),
        "safe_http_url": _safe_http_url,
        "safe_archive_url": _safe_archive_url,
        "next_action_labels": _next_action_labels(),
        **values,
    }


def build_router(*, templates, token_ok, clerk_user_id) -> APIRouter:
    router = APIRouter()

    @router.get("/context/candidates")
    async def candidate_queue(request: Request):
        editor_id = await _editor_id(clerk_user_id, request)
        if not is_context_editor(editor_id):
            return _private_template(
                templates,
                request,
                _queue_context(not_found=True),
                status_code=404,
            )

        raw_page = request.query_params.get("page", "1")
        try:
            page = int(raw_page)
            if page < 1 or str(page) != raw_page:
                raise ValueError
        except (TypeError, ValueError):
            return _private_json({"error": "invalid_page"}, status_code=400)
        next_action: NextAction | None = request.query_params.get("next_action")  # type: ignore[assignment]
        if next_action == "":
            next_action = None
        if next_action is not None and next_action not in _NEXT_ACTIONS:
            return _private_json({"error": "invalid_next_action"}, status_code=400)

        try:
            data = await _store_module().list_candidates(
                page=page, next_action=next_action
            )
        except Exception:
            return _private_template(
                templates,
                request,
                _queue_context(unavailable=True, active_account=editor_id),
                status_code=503,
            )
        return _private_template(
            templates,
            request,
            _queue_context(
                queue=data,
                selected_action=next_action,
                active_account=editor_id,
            ),
        )

    @router.get("/context/candidates/{candidate_id}")
    async def candidate_detail(request: Request, candidate_id: str):
        editor_id = await _editor_id(clerk_user_id, request)
        if not is_context_editor(editor_id):
            return _private_template(
                templates,
                request,
                _queue_context(not_found=True),
                status_code=404,
            )
        if (
            not candidate_id.isascii()
            or not candidate_id.isdecimal()
            or len(candidate_id) > _MAX_CANDIDATE_ID_DIGITS
        ):
            return _private_template(
                templates,
                request,
                _queue_context(not_found=True, active_account=editor_id),
                status_code=404,
            )
        parsed_id = int(candidate_id)
        if parsed_id < 1 or parsed_id > _MAX_CANDIDATE_ID:
            return _private_template(
                templates,
                request,
                _queue_context(not_found=True, active_account=editor_id),
                status_code=404,
            )
        try:
            candidate = await _store_module().get_candidate(parsed_id)
        except Exception:
            return _private_template(
                templates,
                request,
                _queue_context(unavailable=True, active_account=editor_id),
                status_code=503,
            )
        if candidate is None:
            return _private_template(
                templates,
                request,
                _queue_context(not_found=True, active_account=editor_id),
                status_code=404,
            )
        return _private_template(
            templates,
            request,
            _queue_context(candidate=candidate, active_account=editor_id),
        )

    @router.post("/internal/context/candidates/import")
    async def import_candidates(
        request: Request, authorization: str | None = Header(default=None)
    ):
        if not await _token_allowed(token_ok, authorization):
            return _private_json({"detail": "Not Found"}, status_code=404)
        try:
            req = await _validated_body(request, ImportRequest)
        except (ValueError, RuntimeError):
            return _private_json({"error": "invalid_request"}, status_code=422)
        try:
            report = await _importer_module().import_rows(
                req.rows,
                provider=req.provider,
                source_location=req.source_location,
                apply=req.apply,
            )
        except Exception:
            return _private_json(
                {"error": "candidate_service_unavailable"}, status_code=503
            )
        return _private_json(report)

    @router.post("/internal/context/candidates/recheck")
    async def recheck_candidates(
        request: Request, authorization: str | None = Header(default=None)
    ):
        if not await _token_allowed(token_ok, authorization):
            return _private_json({"detail": "Not Found"}, status_code=404)
        try:
            req = await _validated_body(request, InternalRecheckRequest)
        except (ValueError, RuntimeError):
            return _private_json({"error": "invalid_request"}, status_code=422)
        if not is_context_editor(req.clerk_user_id):
            return _private_json({"error": "not_editor"}, status_code=404)

        ids = list(dict.fromkeys(req.ids))
        if any(candidate_id < 1 for candidate_id in ids):
            return _private_json({"error": "invalid_request"}, status_code=422)
        try:
            results = [
                await _store_module().recheck_candidate(candidate_id)
                for candidate_id in ids
            ]
        except Exception:
            return _private_json(
                {"error": "candidate_service_unavailable"}, status_code=503
            )
        return _private_json({"results": results})

    return router
