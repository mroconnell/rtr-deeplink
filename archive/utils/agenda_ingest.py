"""Read a page's agenda and packet once at ingest, and keep each new text
(WO-1966).

Called from `/internal/ingest` as a BackgroundTask, after the response, so
a slow government server or a 90 MB packet never delays the resolver's
push. Ryan, 2026-10-16: store agendas AND packets; no nightly re-read. An
Archive page is created once the meeting has a video, so reading at ingest
already is "when the meeting happens". A re-ingest reads again (so an
amended agenda is caught) unless the same document was read in the last
AGENDA_RECHECK_HOURS, which keeps a busy page from re-reading on every
resolver recheck.

Never raises. Every failure is logged and the ingest is untouched.
"""

from __future__ import annotations

import logging
from typing import Optional

from app import agenda_text

from ..db import agenda_versions

logger = logging.getLogger("rtr_archive.agenda_ingest")

AGENDA_RECHECK_HOURS = 24


def wanted(agenda_link: Optional[str], packet_link: Optional[str]) -> bool:
    """True when either link is a shape `app/agenda_text.py` is wired for
    (CivicPlus or CivicClerk today). Cheap: no network, no database."""
    return bool(agenda_text.candidates_for(agenda_link, packet_link))


async def read_and_store(
    page_id: int,
    agenda_link: Optional[str],
    packet_link: Optional[str],
    meeting_date: Optional[str],
) -> list[dict]:
    """Read and store. Returns one summary dict per document role tried
    (for tests and logs); never raises."""
    summary: list[dict] = []
    try:
        if not wanted(agenda_link, packet_link):
            return summary
        fresh = await agenda_versions.roles_checked_since(
            page_id, agenda_versions.recheck_cutoff(AGENDA_RECHECK_HOURS)
        )
        results = await agenda_text.read_documents(
            agenda_link, packet_link, meeting_date, skip_roles=frozenset(fresh)
        )
        for role in sorted(fresh):
            summary.append({"doc_role": role, "outcome": "recently_checked"})
        # CivicPlus answers `?packet=true` with the agenda itself when a
        # meeting has no packet (seen live on Barron and Amityville,
        # 2026-10-17, office-Mac A2 check). A "packet" whose text is this
        # page's agenda is not a packet, so it is not stored twice.
        agenda_hashes = {
            r.content_hash for r in results if r.doc_role == "agenda" and r.text
        }
        for r in results:
            if not r.text:
                outcome = "not_published" if r.not_published else "failed"
                logger.info(
                    "agenda text: page %s %s %s: %s (%s)",
                    page_id,
                    r.doc_role,
                    outcome,
                    r.error,
                    r.source_url,
                )
                summary.append(
                    {"doc_role": r.doc_role, "outcome": outcome, "error": r.error}
                )
                continue
            if r.doc_role == "packet" and (
                r.content_hash in agenda_hashes
                or await agenda_versions.has_text(page_id, "agenda", r.content_hash)
            ):
                logger.info(
                    "agenda text: page %s packet is the agenda itself (%s)",
                    page_id,
                    r.source_url,
                )
                summary.append({"doc_role": r.doc_role, "outcome": "same_as_agenda"})
                continue
            outcome = await agenda_versions.store_agenda_version(
                page_id,
                doc_role=r.doc_role,
                text=r.text,
                content_hash=r.content_hash,
                fmt=r.format,
                source_url=r.source_url,
                resolved_url=r.resolved_url,
                extractor=agenda_text.EXTRACTOR_NAME,
                extractor_version=agenda_text.EXTRACTOR_VERSION,
            )
            logger.info(
                "agenda text: page %s %s %s (%s chars, %s)",
                page_id,
                r.doc_role,
                outcome,
                len(r.text),
                r.format,
            )
            summary.append(
                {"doc_role": r.doc_role, "outcome": outcome, "chars": len(r.text)}
            )
    except Exception:
        logger.warning("agenda text: page %s read failed", page_id, exc_info=True)
        summary.append({"outcome": "error"})
    return summary
