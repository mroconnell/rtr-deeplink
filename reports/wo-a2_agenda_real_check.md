# A2 check. Agenda and packet text on real documents, 2026-10-16

## What was tested and why

PR #2088 (WO-1966) added agenda and packet text extraction, but the cloud could not reach any government site. So I ran the ingest path (`archive/utils/agenda_ingest.read_and_store`) from this Mac, on `main` at `240a1e6`. Each case used its own throwaway SQLite `DATABASE_URL`, never the shared database. Requests went one at a time, with 3 seconds between cases, and the YouTube guard was on.

Cases: 3 CivicPlus cities (Barron WI, St. James Parish LA, Amityville NY) and 3 CivicClerk cities (Anacortes WA, Alpharetta GA, Alamogordo NM). Each had an agenda and a packet link. CivicClerk links were given in the `GetMeetingFile(...)` form the adapter used to store (see the problem below).

## Result

| City | Document | Characters stored | Reads correctly? | Parser | Time (both docs) | Peak memory (parse child) | Guard fired? |
|---|---|---|---|---|---|---|---|
| Barron WI (CivicPlus) | agenda | 3,071 | Yes ("Regular Meeting of the Common Council, City of Barron, WI") | pdf | 2.7 s | 47 MB | No |
| Barron WI | packet | 3,071 | Same text as the agenda (see problem 2) | pdf | | | No |
| St. James Parish LA (CivicPlus) | agenda (27.7 MB PDF) | 0 | No text layer | pdf: "scanned image, no text layer" | 3.6 s | 99 MB | Scan check, correctly |
| St. James Parish LA | packet | 0 | Same file as the agenda | pdf | | | Scan check |
| Amityville NY (CivicPlus) | agenda | 4,530 | Yes ("Board of Trustee Meeting Agenda, September 14, 2026") | docx | 0.9 s | n/a (no child) | No |
| Amityville NY | packet | 4,530 | Same text as the agenda (see problem 2) | docx | | | No |
| Anacortes WA (CivicClerk) | agenda | 3,296 | Yes (agenda items, contract awards) | pdf, via `GetMeetingFileStream` | 8.2 s | 111 MB | No |
| Anacortes WA | packet (315 pages) | 605,945 | Yes ("Page 133 of 315", contractor details) | pdf, via `GetMeetingFileStream` | | | No |
| Alpharetta GA (CivicClerk) | agenda | 6,896 | Yes ("City Council Meeting & Public Hearing, September 22, 2025") | pdf, via `GetMeetingFileStream` | 1.1 s | 45 MB | No |
| Alpharetta GA | packet | 0 | Not read | | | | Size cap, "document too large (cap 100 MB)" |
| Alamogordo NM (CivicClerk) | agenda | 5,529 | Yes ("City Commission Regular Meeting Agenda, September 24, 2024") | pdf, via `GetMeetingFileStream` | 3.1 s | 112 MB | No |
| Alamogordo NM | packet | 94,363 | Yes (capital project lines) | pdf, via `GetMeetingFileStream` | | | No |

The wrong-date guard and the login-page guard did not fire on any of the six cases. That is correct: every document was the real one for its date.

## Problems

**1. CivicClerk: the adapter no longer gets any agenda or packet link. This blocks A2 for CivicClerk.**
- CivicClerk's API now returns `"url": null` on every `publishedFiles` entry. Only `streamUrl` (`GetMeetingFileStream(...)`) is filled in. I saw this on all 5 live events I read, including two events whose saved test fixtures still have `url` (Kaysville UT 823, Ingleside TX 597).
- The old `GetMeetingFile(fileId=N,plainText=true|false)` address now answers **404** (tested on Anacortes fileId 4213). So the plain-text route returned nothing in every case, and all CivicClerk text above came from `GetMeetingFileStream`.
- What this breaks:
  - `CivicClerkAssetFinder._published_file_url()` reads only `url`, so `agenda_link` and `packet_link` come out empty on every new resolve.
  - `_fetch_agenda_text()` builds on the same link.
  - `agenda_text._CIVICCLERK_FILE` only matches `GetMeetingFile(` and not `GetMeetingFileStream(`, so a stored stream link would not be read either.
- The fix: read `streamUrl` when `url` is null, and accept `GetMeetingFileStream(` links in `agenda_text`. Drop the dead plain-text route, or keep it as a no-op fallback. The fixtures need a fresh capture. Not done here, as the brief asked for no PR.

**2. CivicPlus: when a meeting has no packet, `?packet=true` returns the agenda itself.** Barron and Amityville stored the same text twice, once as "agenda" and once as "packet". The two have the same content hash. Fix: skip a packet whose hash matches the agenda's.

**3. Scanned documents get no text.** St. James Parish's "agenda" is a 27.7 MB scanned PDF. The code says so plainly and stores nothing, which is the intended behaviour (no OCR).

**4. Big packets hit the 100 MB cap.** Alpharetta's packet is over 100 MB and is skipped, as designed. Anacortes's 315-page packet (about 606,000 characters) took about 8 s and 111 MB of memory, which is fine.

**5. This Mac's venv is missing the PDF libraries.** `pypdf` and `pdfplumber` are in `requirements.txt` but not installed here. Without them every PDF fails with "pypdf not installed". For this test I installed the pinned versions into a scratch folder; the shared venv is unchanged. Render installs from `requirements.txt`, so production is not affected. Barron's CivicPlus site answers only on `http://`, and its stored link is `http://`, so that works.

## Recommendation

Safe to deploy for CivicPlus. For CivicClerk, nothing will be read until problem 1 is fixed. That is a small adapter change, but it needs fresh fixtures. Problem 2 is a small fix and worth doing in the same change.
