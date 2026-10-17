"""Fetch a meeting's agenda (or packet) and turn it into plain text (WO-1966).

A port of `rtr-upcoming`'s `app/agenda_text.py`, which already survived
contact with 108 real Bay Area jurisdictions. The traps it solved are kept,
each with the measurement that found it (see
`docs/investigations/agenda_text_versioned_asset.md` for the full list):

* **Sniff the bytes, never the URL.** ~70% of agenda links are PDF and 18%
  HTML (44 real links, measured there 2026-08-24). CivicPlus's
  `/AgendaCenter/ViewFile/Agenda/...` returns `application/pdf` with no
  `.pdf` in the link, and a content type can lie (Martinez serves a .docx
  as `application/msword`).
* **Never truncate a body.** A PDF's cross-reference table is at the END of
  the file, so a sliced PDF is corrupt, not partial. A body over the cap is
  refused, never shortened.
* **A zero-byte body means "not published yet"**, not "unreadable".
* **pypdf first, pdfplumber only on detected damage.** Ligature and space
  loss (`parBcipate`, `reportedRequest`) break search. pdfplumber reads the
  three real damage cases cleanly (Cloverdale 19 mangled words -> 0, Colma
  25 -> 0, Oakley 94 -> 0) at about 3x the time, so it is a fallback.
* **A scan is labelled, not OCR'd.** One scanned document across 108
  jurisdictions.
* **A login page is not an agenda** (`looks_like_shell`): PrimeGov once
  stored a 116-character "Sign In" page as every agenda.
* **A document from another year is not this meeting's**
  (`wrong_document`): 12% of CivicClerk documents read through its untyped
  path were off by a year or more.
* **A PDF is parsed in a throwaway child process** under a memory ceiling
  (`app/agenda_extract_worker.py`). An 81 MB packet peaked at 2.3 GB in one
  process there. Here the parse runs inside the Archive web service, so a
  heavy document must only ever take down its own child.

Only two platforms are wired today, CivicPlus and CivicClerk
(`candidates_for()`); every other `agenda_link` is ignored until a real
sample of it has been checked.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import io
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("rtr_deeplink.agenda_text")

# Stored on every AgendaVersion row. Bump EXTRACTOR_VERSION whenever a
# change here could change the text of a document already stored, so a
# later re-read that differs only because WE extract better can be told
# apart from a jurisdiction really amending its agenda (rtr-upcoming's
# "improving extraction must not itself read as an amendment" trap).
EXTRACTOR_NAME = "rtr-agenda-text"
EXTRACTOR_VERSION = 1

# Packets are huge: the agenda plus every staff report. Measured in
# rtr-upcoming: Morgan Hill 27 MB, Los Gatos 61 MB, Oakley 81 MB, Gilroy
# 90 MB. Over this cap the document is refused, never truncated.
MAX_BYTES = 100 * 1024 * 1024

SCAN_FORMAT = "pdf (scanned image, no text layer)"


def _env_int(name: str, default: int) -> int:
    """An integer setting that falls back rather than crashing the import:
    a typo in a dashboard field must not take the service down."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# The ceiling for ONE PDF parse, in its own child process. The Archive runs
# on a 2 GB instance with two workers, and only one parse runs at a time per
# instance (see _EXTRACT_LOCK_PATH), so the child gets about half of it.
# A document that needs more is recorded as too heavy and skipped.
EXTRACT_MEMORY_MB = _env_int("AGENDA_EXTRACT_MEMORY_MB", 1000)
# rtr-upcoming's slowest real document: Berkeley's 97 MB packet, about 100
# seconds on a laptop.
EXTRACT_TIMEOUT_S = _env_int("AGENDA_EXTRACT_TIMEOUT_S", 300)
FETCH_TIMEOUT_S = 120
# Both Archive workers share this file, so a burst of ingests runs one PDF
# parse at a time on the instance instead of one per worker.
_EXTRACT_LOCK_PATH = os.path.join(tempfile.gettempdir(), "rtr-agenda-extract.lock")
# Same exit status rtr-upcoming's worker uses for "memory ceiling reached".
EXIT_MEMORY = 3


# --- text extraction (pure: bytes in, text out) ------------------------------


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Words with a capital wedged inside, which is what a mis-extracted PDF
# produces: ligature loss ("parBcipate", "submiLed") and space loss
# ("reportedRequest"). The letter class is deliberately narrow (B/L/M/R)
# and both sides need two lowercase letters, so ordinary camel case
# ("eScribe", "McDonald") does not trip it.
MANGLED_RE = re.compile(r"\b[a-z]{2,}[BLMR][a-z]{2,}\b")
MANGLED_THRESHOLD = 5


def mangled_count(text: Optional[str]) -> int:
    return len(MANGLED_RE.findall(text or ""))


def _from_pdf_plumber(data: bytes) -> Optional[str]:
    """Second-opinion extraction, used only when the first looks damaged."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover - declared in requirements
        return None
    try:
        out = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for pg in pdf.pages:
                out.append(pg.extract_text() or "")
                # pdfplumber caches every parsed character on the page
                # object; dropping it as we go is the difference between a
                # few hundred MB and 2.3 GB on an 81 MB packet (measured in
                # rtr-upcoming).
                if hasattr(pg, "flush_cache"):
                    pg.flush_cache()
                if hasattr(pg, "close"):
                    pg.close()
        return _clean("\n".join(out))
    except MemoryError:
        raise  # the child's memory ceiling: reported as "too heavy"
    except Exception:
        return None


def _is_scan(reader) -> bool:
    """True when a PDF carries no text layer at all: no page declares a
    `/Font` resource. Confirmed in rtr-upcoming on Vallejo's Beautification
    Commission agenda (0 characters, 488 KB of images)."""
    try:
        for page in reader.pages[:5]:
            res = page.get("/Resources") or {}
            if "/Font" in res:
                return False
        return True
    except Exception:
        return False


def _from_pdf(data: bytes) -> tuple[Optional[str], str]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        return None, "pdf (pypdf not installed)"
    try:
        reader = PdfReader(io.BytesIO(data))
        scanned = _is_scan(reader)
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except MemoryError:
                raise
            except Exception:
                pages.append("")
        text = _clean("\n\n".join(pages))
        if not text and scanned:
            return None, SCAN_FORMAT
        damage = mangled_count(text)
        if damage >= MANGLED_THRESHOLD:
            # Release pypdf's parse before pdfplumber builds its own.
            reader = pages = None
            gc.collect()
            alt = _from_pdf_plumber(data)
            # Keep whichever result MEASURES better, so a fallback that is
            # somehow worse cannot make things worse.
            if alt and mangled_count(alt) < damage:
                return alt, "pdf"
        return text, "pdf"
    except MemoryError:
        raise  # the child's memory ceiling: reported as "too heavy"
    except Exception:
        return None, "pdf (unreadable)"


def _from_html(data: bytes) -> tuple[Optional[str], str]:
    from bs4 import BeautifulSoup, Comment

    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    # Word's HTML export leaves conditional-comment markup behind
    # (Millbrae's agenda carried "supportLists" 58 times). Not agenda text.
    for node in soup.find_all(string=lambda t: isinstance(t, Comment)):
        node.extract()
    return _clean(soup.get_text("\n")), "html"


def _from_rtf(data: bytes) -> tuple[Optional[str], str]:
    txt = data.decode("latin-1", "replace")
    txt = re.sub(r"\\'[0-9a-fA-F]{2}", " ", txt)
    txt = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", txt)
    txt = txt.replace("{", " ").replace("}", " ")
    return _clean(txt), "rtf"


def _from_docx(data: bytes) -> tuple[Optional[str], str]:
    """Word .docx: a zip of XML, so no new dependency is needed."""
    import zipfile
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [
                n
                for n in ("word/document.xml", "word/document2.xml")
                if n in z.namelist()
            ]
            if not names:
                return None, "docx (no document.xml)"
            xml = z.read(names[0])
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ElementTree.fromstring(xml)
        paras = []
        for para in root.iter(f"{ns}p"):
            runs = [t.text or "" for t in para.iter(f"{ns}t")]
            if runs:
                paras.append("".join(runs))
        return _clean("\n".join(paras)), "docx"
    except Exception:
        return None, "docx (unreadable)"


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip()[:5] == b"%PDF-" or b"%PDF-" in data[:2048]


def extract(data: bytes, content_type: str = "") -> tuple[Optional[str], str]:
    """(text, format). `text` is None when nothing readable came back.

    The parser is picked from the BYTES first; the content type is only a
    tie-breaker for formats with no magic number (HTML, plain text)."""
    ct = (content_type or "").split(";")[0].strip().lower()
    head = data[:1024].lstrip()

    if head[:5] == b"%PDF-":
        return _from_pdf(data)
    if head[:5] == b"{\\rtf":
        return _from_rtf(data)
    if head[:2] == b"PK":
        return _from_docx(data)
    if b"%PDF-" in data[:2048]:
        # PDF magic after a BOM or leading junk.
        return _from_pdf(data)
    if ct.startswith("text/html") or head[:15].lower().startswith(
        (b"<!doctype", b"<html")
    ):
        return _from_html(data)
    if ct.startswith("text/") or ct in ("", "application/octet-stream"):
        try:
            return _clean(data.decode("utf-8")), "text"
        except UnicodeDecodeError:
            return None, ct or "unknown"
    return None, ct or "unknown"


# --- guards: is this text really this meeting's agenda? ---------------------

SHELL_MARKERS = re.compile(r"sign in|log ?in|password|forgot password", re.I)
AGENDA_MARKERS = re.compile(
    r"call to order|roll call|public comment|adjourn|consent|"
    r"agenda|minutes|motion|resolution|ordinance|staff report",
    re.I,
)


def looks_like_shell(text: str) -> Optional[str]:
    """A reason this text is a login page or viewer shell, or None."""
    if len(text) < 400 and SHELL_MARKERS.search(text):
        return "login/viewer shell"
    if len(text) < 250 and not AGENDA_MARKERS.search(text):
        return "too short, no agenda language"
    if (
        re.match(r"\s*archive center\b", text, re.I)
        and "civicengage" in text[:400].lower()
    ):
        return "CivicPlus Archive Center wrapper, not the document"
    return None


_MONTHS: dict[str, int] = {}
for _i, _m in enumerate(
    "January February March April May June July August September October "
    "November December".split(),
    start=1,
):
    _MONTHS[_m.lower()] = _i
    _MONTHS[_m[:3].lower()] = _i
_MONTHS["sept"] = 9

_MON = r"[A-Za-z]{3,9}\.?"
# Every pattern is a real string seen on a real government page (ported
# from rtr-upcoming's app/dates.py).
_DATE_PATTERNS = [
    (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"), "ymd"),
    (re.compile(rf"\b({_MON})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b"), "mdy"),
    (
        re.compile(
            rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s-]+({_MON}),?[\s-]+(20\d{{2}})\b"
        ),
        "dmy",
    ),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b"), "num"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b"), "num2"),
]

HEAD_CHARS = 1500
# Below this gap a differing date is ordinary (last meeting's minutes, a
# fiscal year). Above it, every sample inspected in rtr-upcoming was a
# document from another meeting entirely.
WRONG_DOCUMENT_DAYS = 300


def _safe_date(y: int, m: Optional[int], d: int) -> Optional[date]:
    try:
        return date(y, m, d) if m else None
    except (ValueError, TypeError):
        return None


def dates_in(text: str, chars: int = HEAD_CHARS) -> list[date]:
    """Every date in the document's masthead, in order, deduped.

    One change from rtr-upcoming, which only covers California: a numeric
    date ("03/04/2026") is read BOTH ways when both are real dates, because
    CivicPlus and CivicClerk also serve Canadian governments. Reading both
    can only make `wrong_document` reject less, never more.
    """
    head = re.sub(r"\s+", " ", (text or "")[:chars])
    found: list[date] = []
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(head):
            g = m.groups()
            options: list[Optional[date]] = []
            if order == "ymd":
                options = [_safe_date(int(g[0]), int(g[1]), int(g[2]))]
            elif order == "mdy":
                options = [
                    _safe_date(
                        int(g[2]), _MONTHS.get(g[0].strip(".").lower()), int(g[1])
                    )
                ]
            elif order == "dmy":
                options = [
                    _safe_date(
                        int(g[2]), _MONTHS.get(g[1].strip(".").lower()), int(g[0])
                    )
                ]
            else:
                y = int(g[2]) if order == "num" else 2000 + int(g[2])
                options = [
                    _safe_date(y, int(g[0]), int(g[1])),
                    _safe_date(y, int(g[1]), int(g[0])),
                ]
            for when in options:
                if when and when not in found:
                    found.append(when)
    return found


def wrong_document(text: str, meeting_date: Optional[str]) -> Optional[str]:
    """A reason this document is not this meeting's, or None.

    Deliberately conservative: only a document whose masthead dates are ALL
    more than 300 days from the meeting is rejected. 23% of real, correct
    agendas do not restate the meeting date in their first 1,500 characters
    (rtr-upcoming's measurement), so an undated masthead passes."""
    if not text or not meeting_date:
        return None
    try:
        target = date.fromisoformat(str(meeting_date)[:10])
    except ValueError:
        return None
    found = dates_in(text)
    if not found or target in found:
        return None
    gap = min(abs((f - target).days) for f in found)
    if gap <= WRONG_DOCUMENT_DAYS:
        return None
    nearest = min(found, key=lambda f: abs((f - target).days))
    return (
        f"document is dated {nearest.isoformat()}, "
        f"{gap} days from the {target.isoformat()} meeting"
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- which documents to read, per platform ----------------------------------


@dataclass(frozen=True)
class Candidate:
    """One address to try for one document.

    `doc_role` is "agenda" or "packet" (the agenda plus every staff report).
    `mode` is "civicclerk_plaintext" for CivicClerk's own text conversion
    (a JSON `{"blobUri": ...}` pointing at a .txt) and "file" for a document
    whose bytes we extract ourselves."""

    doc_role: str
    url: str
    mode: str = "file"


_CIVICPLUS_VIEWFILE = re.compile(r"/AgendaCenter/ViewFile/Agenda/", re.I)
_CIVICCLERK_FILE = re.compile(r"/v1/Meetings/GetMeetingFile(?:Stream)?\(", re.I)


def _civicplus_candidates(doc_role: str, url: str) -> list[Candidate]:
    """CivicPlus `td.downloads` renditions (real Durham NC fixture, PR #640):
    a bare ViewFile link is the PDF, `?html=true` an HTML copy of the
    agenda, `?packet=true` the packet. The PDF is tried first: it is the
    shape rtr-upcoming measured as the real document, while the HTML
    rendition has not been checked against a real body yet. The HTML copy
    is the fallback for the agenda only."""
    p = urlparse(url)
    pdf = urlunparse(p._replace(query=""))
    if doc_role == "packet":
        return [Candidate("packet", url)]
    out = [Candidate("agenda", pdf)]
    if "html=true" in (p.query or "").lower():
        out.append(Candidate("agenda", url))
    return out


def _civicclerk_candidates(doc_role: str, url: str) -> list[Candidate]:
    """CivicClerk `publishedFiles` URLs look like
    `https://{t}.api.civicclerk.com/v1/Meetings/GetMeetingFile(fileId=N,plainText=false)`
    (real Clovis CA / Emporia KS fixtures).

    Two reads, in order:
    1. `GetMeetingFile(...,plainText=true)`: JSON `{"blobUri": ...}` to a
       .txt of the document. Confirmed live in this repo on Los Altos Hills
       CA (2026-08-16) and Moraine OH / Merrill WI (2026-09-29, WO-1159).
       No PDF parse needed.
    2. `GetMeetingFileStream(...,plainText=false)`: the document's own
       bytes. Confirmed in rtr-upcoming on Milpitas (39 KB PDF) and Morgan
       Hill (6.8 MB). rtr-upcoming found `plainText=true` returns 0 bytes
       on the Stream endpoint, which is why the two are not mixed here.

    Since 2026-10-16 the API's `url` is null and the adapter stores
    `streamUrl`, a `GetMeetingFileStream(...)` link: that is read as the
    file, with no plain-text try (the old `GetMeetingFile(...)` route now
    answers 404, and the Stream route has no plain-text form). A legacy
    `GetMeetingFile(...)` link already stored on a page still gets both
    tries; the first now 404s and the Stream read follows.
    """
    if re.search(r"GetMeetingFileStream\(", url, re.I):
        return [
            Candidate(
                doc_role, re.sub(r"plainText=true", "plainText=false", url, flags=re.I)
            )
        ]
    plain = re.sub(r"plainText=false", "plainText=true", url, flags=re.I)
    if "plaintext=true" not in plain.lower():
        plain = None
    stream = re.sub(r"GetMeetingFile\(", "GetMeetingFileStream(", url, flags=re.I)
    stream = re.sub(r"plainText=true", "plainText=false", stream, flags=re.I)
    out = []
    if plain:
        out.append(Candidate(doc_role, plain, "civicclerk_plaintext"))
    out.append(Candidate(doc_role, stream))
    return out


def platform_of_link(url: Optional[str]) -> Optional[str]:
    """ "civicplus", "civicclerk" or None, from the link's own shape.

    By shape, not by the page's `platform`: a CivicPlus page whose video is
    on Granicus is stored with `platform="granicus"` (CLAUDE.md's
    delegation quirk), but its agenda link is still CivicPlus's own, and a
    CivicPlus site often runs on the government's own domain."""
    if not url:
        return None
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if host.endswith(".api.civicclerk.com") and _CIVICCLERK_FILE.search(p.path):
        return "civicclerk"
    if _CIVICPLUS_VIEWFILE.search(p.path):
        return "civicplus"
    return None


def candidates_for(
    agenda_link: Optional[str], packet_link: Optional[str]
) -> list[Candidate]:
    """Every address to try, agenda first, then packet. Empty when neither
    link is a shape this module has been wired for."""
    out: list[Candidate] = []
    for role, link in (("agenda", agenda_link), ("packet", packet_link)):
        if not link:
            continue
        platform = platform_of_link(link)
        if platform == "civicplus":
            out.extend(_civicplus_candidates(role, link))
        elif platform == "civicclerk":
            out.extend(_civicclerk_candidates(role, link))
    return out


# --- fetching and the child-process parse ------------------------------------


@dataclass
class ReadResult:
    """What one document read produced. Exactly one of `text` / `error` is
    set. `not_published` marks CivicClerk's zero-byte "not posted yet"."""

    doc_role: str
    source_url: str
    text: Optional[str] = None
    format: Optional[str] = None
    content_hash: Optional[str] = None
    resolved_url: Optional[str] = None
    error: Optional[str] = None
    not_published: bool = False


class TooHeavy(Exception):
    """The child parse hit its memory or time ceiling, or died."""


def _worker_cmd(path: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.agenda_extract_worker",
        path,
        str(EXTRACT_MEMORY_MB),
    ]


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _acquire_instance_lock():
    """One PDF parse at a time across every worker process on the instance.
    An advisory `flock` on a shared temp file, polled so the event loop is
    never blocked."""
    import fcntl

    fd = os.open(_EXTRACT_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            await asyncio.sleep(0.5)


def _release_instance_lock(fd: int) -> None:
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


async def extract_pdf_isolated(path: str) -> tuple[Optional[str], str]:
    """`extract()` on a PDF file, run in a throwaway child process.

    The child runs the same function, so the text and its hash are the same
    byte for byte as an in-process parse would give. Raises `TooHeavy` when
    the child hit its memory or time ceiling or died."""
    fd = await _acquire_instance_lock()
    try:
        proc = await asyncio.create_subprocess_exec(
            *_worker_cmd(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_REPO_ROOT,
        )
        try:
            out, _err = await asyncio.wait_for(proc.communicate(), EXTRACT_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TooHeavy(f"took longer than {EXTRACT_TIMEOUT_S} seconds") from None
    finally:
        _release_instance_lock(fd)
    if proc.returncode == EXIT_MEMORY:
        raise TooHeavy(f"needs more than {EXTRACT_MEMORY_MB} MB of memory")
    if proc.returncode != 0:
        rc = proc.returncode or 0
        how = f"killed by signal {-rc}" if rc < 0 else f"exit status {rc}"
        raise TooHeavy(f"the extractor stopped ({how})")
    try:
        got = json.loads(out)
        return got["text"], got["format"]
    except (ValueError, KeyError, TypeError):
        raise TooHeavy("the extractor returned nothing readable") from None


async def _download_to_file(response, fh) -> int:
    """Stream the body to `fh` with a running cap, so a 90 MB packet never
    sits in this process's memory. Returns the byte count, or -1 when the
    body went over MAX_BYTES (the file is then incomplete and must not be
    parsed)."""
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        return -1
    total = 0
    async for chunk in response.content.iter_chunked(256 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            return -1
        fh.write(chunk)
    return total


def _finish(
    result: ReadResult, text: Optional[str], fmt: str, meeting_date: Optional[str]
):
    result.format = fmt
    if not text or len(text) < 40:
        result.error = f"no readable text ({fmt})"
        return result
    bad = looks_like_shell(text) or wrong_document(text, meeting_date)
    if bad:
        result.error = f"not this meeting's document ({bad})"
        return result
    result.text = text
    result.content_hash = content_hash(text)
    return result


async def _read_file(session, cand: Candidate, meeting_date, headers) -> ReadResult:
    from app.utils.url_guard import guarded_get

    result = ReadResult(doc_role=cand.doc_role, source_url=cand.url)
    timeout = _client_timeout()
    async with guarded_get(session, cand.url, timeout=timeout, headers=headers) as resp:
        if resp.status != 200:
            result.error = f"HTTP {resp.status}"
            return result
        result.resolved_url = str(resp.url)
        ctype = resp.headers.get("Content-Type", "")
        fd, path = tempfile.mkstemp(prefix="agenda-", suffix=".bin")
        try:
            with os.fdopen(fd, "wb") as fh:
                size = await _download_to_file(resp, fh)
            if size < 0:
                result.error = (
                    f"document too large (cap {MAX_BYTES // (1024 * 1024)} MB)"
                )
                return result
            if size == 0:
                result.error = "empty document (0 bytes, not published yet)"
                result.not_published = True
                return result
            with open(path, "rb") as fh:
                head = fh.read(2048)
            if is_pdf(head):
                try:
                    text, fmt = await extract_pdf_isolated(path)
                except TooHeavy as e:
                    result.error = (
                        f"document too heavy to extract ({e}; {size / 1048576:.0f} MB)"
                    )
                    return result
            else:
                # Not a PDF: HTML/text/docx/rtf are cheap and bounded by the
                # same byte cap, so they stay in-process.
                with open(path, "rb") as fh:
                    data = fh.read()
                text, fmt = extract(data, ctype)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    return _finish(result, text, fmt, meeting_date)


async def _read_civicclerk_plaintext(
    session, cand: Candidate, meeting_date, headers
) -> ReadResult:
    from app.utils.url_guard import guarded_get, read_capped_bytes

    result = ReadResult(doc_role=cand.doc_role, source_url=cand.url)
    timeout = _client_timeout()
    async with guarded_get(session, cand.url, timeout=timeout, headers=headers) as resp:
        if resp.status != 200:
            result.error = f"HTTP {resp.status}"
            return result
        raw = await read_capped_bytes(resp, 1024 * 1024)
    if not raw.strip():
        # Not "not published": an empty answer from the plain-text route
        # says nothing about the document, so the file route is tried next.
        result.error = "empty answer from CivicClerk's plain-text route"
        return result
    blob_uri = (json.loads(raw) or {}).get("blobUri")
    if not blob_uri:
        result.error = "no blobUri in CivicClerk's plain-text answer"
        return result
    async with guarded_get(session, blob_uri, timeout=timeout, headers=headers) as resp:
        if resp.status != 200:
            result.error = f"HTTP {resp.status} on the plain-text file"
            return result
        # The blob URL is SAS-signed (a short-lived key in its query), so
        # only its path is kept; the signed link is never stored.
        result.resolved_url = urlunparse(urlparse(str(resp.url))._replace(query=""))
        data = await read_capped_bytes(resp, 20 * 1024 * 1024)
    if not data.strip():
        # Fall through to the file route, which is the one that can tell
        # "not published yet" (0 bytes) from "published".
        result.error = "empty plain-text file from CivicClerk"
        return result
    return _finish(
        result,
        _clean(data.decode("utf-8", "replace")),
        "text (civicclerk)",
        meeting_date,
    )


def _client_timeout():
    import aiohttp

    return aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S)


async def read_documents(
    agenda_link: Optional[str],
    packet_link: Optional[str],
    meeting_date: Optional[str] = None,
    *,
    skip_roles: frozenset = frozenset(),
    session=None,
) -> list[ReadResult]:
    """Read the agenda and the packet, one request at a time.

    Returns one ReadResult per document role tried: the first candidate
    that produced text, or the last failure. Never raises: a failure here
    must never break an ingest."""
    cands = [
        c
        for c in candidates_for(agenda_link, packet_link)
        if c.doc_role not in skip_roles
    ]
    if not cands:
        return []
    from app.utils import robots_check

    headers = {"User-Agent": robots_check.USER_AGENT}
    results: dict[str, ReadResult] = {}
    own_session = session is None
    if own_session:
        import aiohttp

        session = aiohttp.ClientSession()
    try:
        for cand in cands:
            done = results.get(cand.doc_role)
            if done is not None and (done.text or done.not_published):
                continue
            try:
                # Ryan, 2026-10-02: honor any matching robots.txt Disallow.
                # Always enforced here: this is a new kind of read.
                allowed, _rule = await robots_check.check_url(cand.url)
                if not allowed:
                    results[cand.doc_role] = ReadResult(
                        doc_role=cand.doc_role,
                        source_url=cand.url,
                        error="robots.txt disallows this address",
                    )
                    continue
                if cand.mode == "civicclerk_plaintext":
                    got = await _read_civicclerk_plaintext(
                        session, cand, meeting_date, headers
                    )
                else:
                    got = await _read_file(session, cand, meeting_date, headers)
            except Exception as e:  # never let one document break the rest
                got = ReadResult(
                    doc_role=cand.doc_role,
                    source_url=cand.url,
                    error=f"{type(e).__name__}: {e}"[:200],
                )
            results[cand.doc_role] = got
    finally:
        if own_session:
            await session.close()
    return list(results.values())
