// Shared t/line/version deep-link mechanics for both the resolver's
// ephemeral /meeting page (app/static/player.js) and the Archive's
// permanent /m/{slug} page (archive/static/meeting_page.js). Extracted
// 2026-08-08 -- previously duplicated verbatim in both files, kept in
// sync only by a comment, a real risk given a past fix (t/line seek
// precedence) already had to land in both places by hand. New
// precedent for this repo: served from its own top-level shared_static/
// directory, mounted by *both* app/main.py and archive/main.py at
// /shared-static (see each file's mount call) -- one file on disk, two
// independent StaticFiles mounts, so either service can serve it
// whether reached directly or through the resolver's reverse proxy.
// Must load before player.js / meeting_page.js, which both call these
// functions but no longer define them.

let segments = [];
// Only ever toggled on the resolver's page (its "Auto-scroll: On/Off"
// button, #toggleAutoScrollBtn in player.js) -- the Archive page has no
// such toggle and never changes this, so highlightSegment() below always
// respects scrollIntoView alone there, same as before this file existed.
let autoScrollEnabled = true;

function getQueryParams() {
  return new URLSearchParams(window.location.search);
}

function getDeepLinkTime() {
  const t = getQueryParams().get('t');
  return t !== null ? Number(t) : null;
}

function getDeepLinkLine() {
  const raw = getQueryParams().get('line');
  if (!raw) return null;
  if (/^seg-\d+$/.test(raw)) return raw;
  if (/^\d+$/.test(raw)) return `seg-${raw}`;
  return null;
}

// Only ever meaningful on the Archive's permanent page (a TranscriptVersion
// id) -- the resolver's ephemeral page has no version concept, so this is
// always null there, which applyDeepLink() below treats as "no version
// info available, trust `line` as-is" rather than a mismatch.
function getDeepLinkVersion() {
  return getQueryParams().get('version');
}

function updateUrlParams({ t = null, line = null }) {
  const params = getQueryParams();
  if (t !== null) params.set('t', String(Math.floor(t)));
  if (line !== null) params.set('line', line);
  // document.body.dataset.versionId is set server-side by the Archive's
  // meeting_page.html (from active_version.id) -- absent on the resolver's
  // meeting.html, so `params.set` is simply skipped there. Automatic on
  // every call site rather than something each caller has to remember to
  // pass, so a future new "copy link" button can't forget it.
  const versionId = document.body.dataset.versionId;
  if (versionId) params.set('version', versionId);
  const newUrl = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, '', newUrl);
}

function findActiveSegment(currentTime) {
  for (let i = segments.length - 1; i >= 0; i--) {
    if (segments[i].start <= currentTime) return `seg-${i}`;
  }
  return null;
}

function highlightSegment(segId, scrollIntoView) {
  document.querySelectorAll('.transcript-segment.playing').forEach((el) => el.classList.remove('playing'));
  const el = document.getElementById(segId);
  if (!el) return;
  el.classList.add('playing');
  if (scrollIntoView && autoScrollEnabled) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function getOffsetSeconds() {
  return 0; // reserved for future offset calibration, per rtr-transcripts PDR
}

function applyDeepLink(video) {
  const line = getDeepLinkLine();
  const t = getDeepLinkTime();
  const linkVersion = getDeepLinkVersion();
  const currentVersion = document.body.dataset.versionId || null;

  // A `line` (raw segment index) is only trustworthy against the exact
  // TranscriptVersion it was generated from -- if that version was later
  // replaced, index N could now point at a completely different line (see
  // BACKLOG.md's deep-link versioning entry). No version info on either
  // side (an old link generated before this fix, or the resolver's page,
  // which has no version concept at all) is treated as trusting `line` --
  // only an explicit mismatch between the URL's version and the page's
  // current one triggers the time-proximity fallback below.
  const lineTrustworthy = !!line && (!linkVersion || !currentVersion || linkVersion === currentVersion);

  // `t` (exact seconds) always wins for the actual seek position -- `line`
  // only decides which row to highlight. Previously `line`, when present,
  // seeked to that segment's *start* and silently discarded a more precise
  // `t` in the same URL -- see BACKLOG_DONE.md for that fix's history.
  if (t !== null) {
    video.currentTime = t;
    // findActiveSegment(t) is the time-proximity fallback: the segment
    // whose own start is closest at-or-before `t`, used both when `line`
    // is untrustworthy and when it's simply absent.
    const segId = lineTrustworthy ? line : findActiveSegment(t);
    if (segId) highlightSegment(segId, true);
    return;
  }
  if (line && lineTrustworthy) {
    const el = document.getElementById(line);
    if (el) {
      const start = Number(el.dataset.start || '0');
      video.currentTime = Math.max(0, start - getOffsetSeconds());
      highlightSegment(line, true);
    }
  }
  // `line` present, untrustworthy, and no `t` to fall back on: nothing
  // reliable to seek to (no time-proximity target without a real `t`) --
  // leave playback at its default start rather than jumping to a possibly
  // wrong old index.
}
