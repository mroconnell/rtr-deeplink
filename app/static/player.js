// hls.js setup, click-to-seek, and everything else specific to the
// resolver's ephemeral page -- t/line/version deep-link mechanics
// (getQueryParams, updateUrlParams, findActiveSegment, highlightSegment,
// applyDeepLink, segments, autoScrollEnabled, etc.) now live in
// /shared-static/deep_link.js, loaded before this file (see meeting.html),
// shared with the Archive's meeting_page.js.

const sourceUrl = document.body.dataset.sourceUrl;
// Every caption track that was actually fetched (the chosen one plus any
// alternates -- see ResolvedMeeting.alternate_transcripts), so the language
// picker can switch `segments` client-side with no second /api/resolve call.
let transcriptTracks = [];

// Every other platform hands us a direct m3u8/mp4 URL playable in a plain
// <video>. YouTube doesn't -- playback needs an embedded iframe + the
// YouTube IFrame Player API instead, a structurally different control
// surface (seekTo() instead of currentTime=, no native timeupdate event,
// async player creation). Rather than branching every call site on video
// format, initVideo() wraps whichever one is active behind this same
// {currentTime get/set, play, pause, addEventListener} shape, set once
// the player exists -- so transcript click-to-seek, "Copy link to
// current time", "Go to time", and applyDeepLink() all work unchanged
// against `activeVideoAdapter` regardless of which platform this is.
let activeVideoAdapter = null;

// Drops a leading "City of "/"City " for display -- user request
// 2026-08-12: almost everything archived is a city, so labeling every
// row that way ("City of Napa, CA") reads as redundant. Reserves the
// explicit label for the real exceptions ("County of X"/"X County",
// state-legislature-style body names), left unchanged. JS mirror of
// archive/utils/jurisdiction_format.py's format_jurisdiction_display() --
// this is the resolver's own client-rendered page, which has no server-
// side Jinja pass to apply that Python version through.
function formatJurisdictionDisplay(jurisdiction) {
  if (!jurisdiction) return jurisdiction;
  // Real consolidated city-counties (San Francisco, Denver) must never
  // hit the plain "City " strip below -- see jurisdiction_format.py's
  // Python twin for the live bug this guards against.
  if (jurisdiction.toLowerCase().startsWith('city and county of ')) {
    return jurisdiction;
  }
  for (const prefix of ['The City of ', 'City of ', 'City ']) {
    if (jurisdiction.toLowerCase().startsWith(prefix.toLowerCase())) {
      return jurisdiction.slice(prefix.length);
    }
  }
  return jurisdiction;
}

function formatTime(seconds) {
  seconds = Math.floor(seconds || 0);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

// Live playhead readout shown where the transcript would be, for
// meetings with no transcript/agenda to click through -- makes clear
// we're still tracking the exact moment even with nothing to scan.
// A no-op when #noTranscriptTime doesn't exist (transcript present, or
// not on the meeting page at all), so callers don't need to guard.
function updateNoTranscriptTime(adapter) {
  const el = document.getElementById('noTranscriptTime');
  if (el) el.textContent = formatTime(adapter.currentTime);
}

const LINK_ICON_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M6.5 9.5a.75.75 0 0 0 1 .06l.06-.06 3-3a.75.75 0 0 0-1-1.12l-.06.06-3 3a.75.75 0 0 0 0 1.06z"/><path fill="currentColor" d="M5.72 11.03a2.5 2.5 0 0 1 0-3.54l1.5-1.5a.75.75 0 0 1 1.06 1.06l-1.5 1.5a1 1 0 0 0 1.42 1.42l1.5-1.5a.75.75 0 1 1 1.06 1.06l-1.5 1.5a2.5 2.5 0 0 1-3.54 0z"/><path fill="currentColor" d="M9.72 4.97a2.5 2.5 0 0 1 3.54 3.54l-1.5 1.5a.75.75 0 1 1-1.06-1.06l1.5-1.5a1 1 0 0 0-1.42-1.42l-1.5 1.5A.75.75 0 1 1 8.22 6.5l1.5-1.5z"/></svg>';

const CASSETTE_REEL_SVG = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7" fill="#fff" stroke="#bbb" stroke-width="2"/><circle cx="9" cy="9" r="2.2" fill="#bbb"/></svg>';

// data.transcript_language / alternate_transcripts[].language are ISO
// 639-1 codes (e.g. "es"), not display names -- Intl.DisplayNames gives a
// real language name in the browser's own locale; falls back to the raw
// code on an unrecognized/unsupported one rather than throwing.
function languageDisplayName(code) {
  if (!code) return 'Unknown language';
  try {
    return new Intl.DisplayNames([navigator.language || 'en'], { type: 'language' }).of(code) || code;
  } catch (e) {
    return code;
  }
}

// Builds the "Language: [ ]" picker next to the Transcript heading from
// the chosen track plus any alternates the resolver found but didn't pick
// (see ResolvedMeeting.alternate_transcripts) -- hidden entirely when
// there's nothing to switch between, the common case.
function setupTranscriptLanguagePicker(primaryLanguage, primarySegments, alternates) {
  transcriptTracks = [{ language: primaryLanguage, segments: primarySegments }, ...alternates];
  const picker = document.getElementById('transcriptLanguagePicker');
  const select = document.getElementById('transcriptLanguageSelect');
  if (transcriptTracks.length < 2) {
    picker.hidden = true;
    return;
  }

  select.innerHTML = transcriptTracks
    .map((track, index) => `<option value="${index}">${escapeHtml(languageDisplayName(track.language))}</option>`)
    .join('');
  select.value = '0';
  picker.hidden = false;

  select.onchange = () => {
    const track = transcriptTracks[Number(select.value)];
    segments = track.segments;
    renderTranscript(segments);
    // Old matches belong to the DOM this just replaced; let the user
    // re-search rather than showing a stale count against the new track.
    const searchInput = document.getElementById('transcriptSearchInput');
    const searchCount = document.getElementById('transcriptSearchCount');
    if (searchInput) searchInput.value = '';
    if (searchCount) searchCount.textContent = '';
  };
}

function renderTranscript(segs) {
  const container = document.getElementById('transcriptList');
  container.innerHTML = '';
  segs.forEach((seg, index) => {
    const segId = `seg-${index}`;
    const div = document.createElement('div');
    div.className = 'transcript-segment';
    div.id = segId;
    div.dataset.start = seg.start;
    div.innerHTML = `<a href="#${segId}" class="segment-timestamp" data-start="${seg.start}" data-seg-id="${segId}">[${formatTime(seg.start)}]</a>` +
      `<button class="segment-link-btn" data-start="${seg.start}" data-seg-id="${segId}" title="Copy link to this line" aria-label="Copy link to this line">${LINK_ICON_SVG}</button>` +
      ` <span class="segment-text">${escapeHtml(seg.text)}</span>`;
    container.appendChild(div);
  });

  container.querySelectorAll('.segment-timestamp').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const start = Number(a.dataset.start || '0');
      const segId = a.dataset.segId;
      if (activeVideoAdapter) activeVideoAdapter.currentTime = Math.max(0, start - 1);
      highlightSegment(segId, false);
      updateUrlParams({ t: start, line: segId });
    });
  });

  // A dedicated "copy link" affordance next to each line -- the timestamp
  // link already jumps + copies, but that dual behavior wasn't discoverable
  // (only the timestamp itself was clickable, no visual hint it copies a
  // link). This button is copy-only, doesn't move playback, so it's safe
  // to click while listening without interrupting anything.
  container.querySelectorAll('.segment-link-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const start = Number(btn.dataset.start || '0');
      const segId = btn.dataset.segId;
      updateUrlParams({ t: start, line: segId });
      try {
        await navigator.clipboard.writeText(window.location.href);
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1200);
      } catch (err) {
        // clipboard API unavailable; URL is already updated in the address bar
      }
    });
  });
}

// Agenda items (chapter markers) get the same click-to-seek + copy-link
// interactions as transcript lines, reusing the same markup/CSS classes
// for visual consistency, but deliberately don't participate in
// findActiveSegment()/highlightSegment()'s "currently playing" tracking
// or the `line=` deep-link param -- those are transcript-specific
// (segments are short/fine-grained, agenda items are coarse chapters,
// less suited to continuous "which one is active right now" tracking),
// and agenda_items is a separate list from `segments` so id collisions
// aren't a concern (agenda-N vs seg-N).
function renderAgenda(items) {
  const container = document.getElementById('agendaList');
  container.innerHTML = '';

  // Some sources (confirmed: several CivicClerk cities' eventBookmarks)
  // report every agenda item at the exact same instant -- 26 different
  // items can't all genuinely start at 0:00. Rendering those as normal
  // clickable [0:00] links falsely implies real per-item navigation, so
  // fall back to a plain, unlinked outline instead. A single item at
  // 0:00 is normal (the first topic starting at the top of the video) --
  // only suppress when there's more than one item and they're all
  // identical.
  const unreliableTimestamps = items.length > 1 && items.every((item) => item.start === items[0].start);

  if (unreliableTimestamps) {
    const note = document.createElement('p');
    note.className = 'subtitle';
    note.textContent = "This source doesn't provide real per-item timestamps, so these agenda items aren't clickable.";
    container.appendChild(note);
  }

  items.forEach((item, index) => {
    const itemId = `agenda-${index}`;
    const div = document.createElement('div');
    div.className = 'transcript-segment';
    div.id = itemId;
    if (unreliableTimestamps) {
      div.innerHTML = `<span class="segment-text">${escapeHtml(item.text)}</span>`;
    } else {
      div.dataset.start = item.start;
      div.innerHTML = `<a href="#${itemId}" class="segment-timestamp" data-start="${item.start}">[${formatTime(item.start)}]</a>` +
        `<button class="segment-link-btn" data-start="${item.start}" title="Copy link to this item" aria-label="Copy link to this item">${LINK_ICON_SVG}</button>` +
        ` <span class="segment-text">${escapeHtml(item.text)}</span>`;
    }
    container.appendChild(div);
  });

  if (unreliableTimestamps) {
    return;
  }

  container.querySelectorAll('.segment-timestamp').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const start = Number(a.dataset.start || '0');
      if (activeVideoAdapter) activeVideoAdapter.currentTime = Math.max(0, start - 1);
      updateUrlParams({ t: start });
    });
  });

  container.querySelectorAll('.segment-link-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const start = Number(btn.dataset.start || '0');
      updateUrlParams({ t: start });
      try {
        await navigator.clipboard.writeText(window.location.href);
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1200);
      } catch (err) {
        // clipboard API unavailable; URL is already updated in the address bar
      }
    });
  });
}

let searchMatches = [];
let searchMatchIndex = -1;
let transcriptSearchWired = false;

// Mirrors browser Ctrl+F: highlights every match, cycles through them with
// Enter/Shift+Enter or the prev/next buttons, shows a "N/M" count.
function setupTranscriptSearch() {
  const input = document.getElementById('transcriptSearchInput');
  const countEl = document.getElementById('transcriptSearchCount');
  const prevBtn = document.getElementById('transcriptSearchPrev');
  const nextBtn = document.getElementById('transcriptSearchNext');
  if (!input || transcriptSearchWired) return;
  transcriptSearchWired = true;

  function updateCount() {
    if (!input.value.trim()) { countEl.textContent = ''; return; }
    countEl.textContent = searchMatches.length ? `${searchMatchIndex + 1}/${searchMatches.length}` : '0 matches';
  }

  function goToMatch(idx) {
    if (!searchMatches.length) return;
    document.querySelectorAll('.search-match.current').forEach((el) => el.classList.remove('current'));
    searchMatchIndex = ((idx % searchMatches.length) + searchMatches.length) % searchMatches.length;
    const el = document.getElementById(searchMatches[searchMatchIndex]);
    if (el) {
      el.classList.add('current');
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    updateCount();
  }

  function runSearch() {
    const query = input.value.trim();
    searchMatches = [];
    searchMatchIndex = -1;

    segments.forEach((seg, index) => {
      const el = document.querySelector(`#seg-${index} .segment-text`);
      if (!el) return;
      const text = seg.text || '';
      if (!query) {
        el.textContent = text;
        return;
      }
      const lower = text.toLowerCase();
      const q = query.toLowerCase();
      let html = '';
      let pos = 0;
      let idx;
      while ((idx = lower.indexOf(q, pos)) !== -1) {
        html += escapeHtml(text.slice(pos, idx));
        const matchId = `search-match-${searchMatches.length}`;
        html += `<mark id="${matchId}" class="search-match">${escapeHtml(text.slice(idx, idx + q.length))}</mark>`;
        searchMatches.push(matchId);
        pos = idx + q.length;
      }
      html += escapeHtml(text.slice(pos));
      el.innerHTML = html;
    });

    updateCount();
    if (searchMatches.length) goToMatch(0);
  }

  input.addEventListener('input', runSearch);
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (searchMatches.length) goToMatch(searchMatchIndex + (e.shiftKey ? -1 : 1));
  });
  prevBtn.addEventListener('click', () => goToMatch(searchMatchIndex - 1));
  nextBtn.addEventListener('click', () => goToMatch(searchMatchIndex + 1));
}

// Mirrors archive/utils/transcript_export.py's to_srt()/to_txt() -- this
// page has no server-side persistence to download from (no accounts/DB is
// the whole point of the resolver, per README), so export has to happen
// client-side from the `segments` array already in memory.
let currentMeetingTitle = 'meeting';

function srtTimestamp(seconds) {
  const totalMs = Math.round(seconds * 1000);
  const hours = Math.floor(totalMs / 3600000);
  const minutes = Math.floor((totalMs % 3600000) / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  const pad = (n, len) => String(n).padStart(len, '0');
  return `${pad(hours, 2)}:${pad(minutes, 2)}:${pad(secs, 2)},${pad(ms, 3)}`;
}

function segmentsToSrt(segs) {
  return segs.map((seg, i) =>
    `${i + 1}\n${srtTimestamp(seg.start)} --> ${srtTimestamp(seg.end)}\n${seg.text}\n`
  ).join('\n');
}

function segmentsToTxt(segs) {
  return segs.map((seg) => `[${formatTime(seg.start)}] ${seg.text}`).join('\n');
}

function downloadTranscript(format) {
  if (!segments.length) return;
  const body = format === 'srt' ? segmentsToSrt(segments) : segmentsToTxt(segments);
  const slug = currentMeetingTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'meeting';
  const blob = new Blob([body], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${slug}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function wireTranscriptExport() {
  document.getElementById('exportTxtBtn').addEventListener('click', () => downloadTranscript('txt'));
  document.getElementById('exportSrtBtn').addEventListener('click', () => downloadTranscript('srt'));
}

function wireTranscribeForm() {
  const toggleWrap = document.getElementById('transcribeToggleWrap');
  const toggle = document.getElementById('transcribeToggle');
  const form = document.getElementById('transcribeForm');
  const checkStatusEl = document.getElementById('transcribeCheckStatus');
  const emailStep = document.getElementById('transcribeEmailStep');
  const cancelBtn = document.getElementById('transcribeCancel');
  const statusEl = document.getElementById('transcribeStatus');
  if (!toggle || !form) return;

  let feasibilityOk = false;

  function resetForm() {
    form.hidden = true;
    toggleWrap.hidden = false;
    checkStatusEl.textContent = '';
    checkStatusEl.className = 'transcribe-status';
    emailStep.hidden = true;
    statusEl.textContent = '';
    statusEl.className = 'transcribe-status';
    feasibilityOk = false;
  }

  // Shared by both the manual email-form submit handler and (previously)
  // an auto-submit path for signed-in visitors -- kept as its own
  // function since it's still the one real submit path.
  async function submitRequest(email) {
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    statusEl.className = 'transcribe-status';
    // Real gap fixed 2026-08-11: this request re-runs the whole
    // feasibility check server-side (see /api/transcription/submit's own
    // docstring -- never trusts a client-supplied "it passed" flag), so
    // it can genuinely take several seconds on a real meeting, not the
    // instant round-trip the previous blank statusEl implied. Reuses the
    // same spinning-reel loading state init() already shows during the
    // real resolve fetch, so a long-running request reads as "working,"
    // not "hung."
    statusEl.innerHTML = '<span class="status-loading">' +
      `<span class="cassette-reel spinning">${CASSETTE_REEL_SVG}</span>` +
      `<span class="cassette-reel spinning">${CASSETTE_REEL_SVG}</span>` +
      '<span>Requesting your transcript — this can take a few seconds.</span>' +
      '</span>';

    try {
      const res = await fetch('/api/transcription/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: sourceUrl, email }),
      });
      const data = await res.json();
      if (res.ok) {
        emailStep.hidden = true;
        statusEl.className = 'transcribe-status success';
        statusEl.textContent = data.status === 'pending_confirmation'
          ? 'Check your email to confirm — first-time requests need one click.'
          : `Request received — we'll email you at ${email} when it's ready. This can take a while for long meetings.`;
      } else {
        statusEl.textContent = data.message || 'Something went wrong — please try again.';
        statusEl.className = 'transcribe-status error';
      }
    } catch (err) {
      statusEl.textContent = 'Something went wrong — please try again.';
      statusEl.className = 'transcribe-status error';
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  // User request 2026-08-11, corrected same day: the sign-in *prompt*
  // (a button that opened Clerk's modal from this spot) is gone for good
  // -- that's the part that proved unreliable across several rounds of
  // fixing Clerk's own redirect behavior. But a visitor who's *already*
  // signed in when they click the toggle should still skip re-entering
  // their email entirely, same as before that whole redirect saga --
  // this was never meant to go, only the modal-opening shortcut was.
  // primaryEmailAddress can be null (phone-only or some OAuth-only
  // sign-ups), so this still falls back to the manual field rather than
  // submitting a blank email in that case.
  //
  // Friction is intentional (see BACKLOG.md's abuse-control notes): the
  // feasibility check always fires immediately on toggle, before any email
  // field appears, so a request that can't actually be transcribed never
  // gets that far.
  async function runFeasibilityCheck() {
    form.hidden = false;
    toggleWrap.hidden = true;
    emailStep.hidden = true;
    checkStatusEl.textContent = 'Checking for a usable audio or video source…';
    checkStatusEl.className = 'transcribe-status';

    try {
      const res = await fetch('/api/transcription/check-feasibility', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: sourceUrl }),
      });
      const data = await res.json();
      if (res.status === 429) {
        // Real bug fixed 2026-08-12: slowapi's rate-limit response has no
        // `ok`/`message` keys (its body is `{"error": "Rate limit
        // exceeded: ..."}`), so this used to fall through to the generic
        // "couldn't find a usable audio or video source" message below --
        // reading exactly like a real resolution failure with no hint the
        // actual cause was "you've already requested several transcripts
        // this hour." Checked before `data.ok` specifically so a real
        // rate limit is never mistaken for that.
        checkStatusEl.textContent = "You've requested a few transcripts already this hour — please try again a bit later.";
        checkStatusEl.className = 'transcribe-status error';
      } else if (data.ok) {
        feasibilityOk = true;
        const clerkEmail = window.RTRClerk && window.RTRClerk.isSignedIn() && window.Clerk.user && window.Clerk.user.primaryEmailAddress
          ? window.Clerk.user.primaryEmailAddress.emailAddress
          : null;
        if (clerkEmail) {
          checkStatusEl.textContent = '';
          await submitRequest(clerkEmail);
        } else {
          checkStatusEl.textContent = 'We found a workable audio file — share your email so we can notify you when the transcript is complete.';
          emailStep.hidden = false;
        }
      } else {
        checkStatusEl.innerHTML = linkifyWarning(data.message || "We couldn't find a usable audio or video source for this meeting.");
        checkStatusEl.className = 'transcribe-status error';
      }
    } catch (err) {
      checkStatusEl.textContent = 'Something went wrong — please try again.';
      checkStatusEl.className = 'transcribe-status error';
    }
  }

  toggle.addEventListener('click', runFeasibilityCheck);

  cancelBtn.addEventListener('click', resetForm);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!feasibilityOk) return;
    await submitRequest(document.getElementById('transcribeEmail').value);
  });
}

function wireReportProblemForm() {
  const toggleWrap = document.getElementById('reportProblemToggleWrap');
  const toggle = document.getElementById('reportProblemToggle');
  const form = document.getElementById('reportProblemForm');
  const cancelBtn = document.getElementById('reportProblemCancel');
  if (!toggle || !form) return;

  toggle.addEventListener('click', () => {
    form.hidden = false;
    toggleWrap.hidden = true;
  });
  cancelBtn.addEventListener('click', () => {
    form.hidden = true;
    toggleWrap.hidden = false;
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const statusEl = document.getElementById('reportProblemStatus');
    const submitBtn = form.querySelector('button[type="submit"]');
    const issueType = document.getElementById('reportProblemType').value;
    if (!issueType) return;

    submitBtn.disabled = true;
    statusEl.textContent = '';
    statusEl.className = 'report-problem-status';

    try {
      const res = await fetch('/api/report-problem', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: sourceUrl,
          issue_type: issueType,
          details: document.getElementById('reportProblemDetails').value,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        statusEl.textContent = 'Thanks — we’ll take a look.';
        statusEl.className = 'report-problem-status success';
        form.reset();
        setTimeout(() => { form.hidden = true; toggleWrap.hidden = false; }, 2000);
      } else {
        statusEl.textContent = data.message || 'Something went wrong — please try again.';
        statusEl.className = 'report-problem-status error';
      }
    } catch (err) {
      statusEl.textContent = 'Something went wrong — please try again.';
      statusEl.className = 'report-problem-status error';
    } finally {
      submitBtn.disabled = false;
    }
  });
}

function initVideo(videoUrl, videoFormat) {
  const section = document.getElementById('videoSection');

  if (!videoUrl) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  if (videoFormat === 'youtube') {
    initYouTubeVideo(videoUrl);
  } else if (videoFormat === 'viebit') {
    initViebitVideo(videoUrl);
  } else {
    initNativeVideo(videoUrl, videoFormat);
  }
}

function createNativeAdapter(videoEl) {
  return {
    get currentTime() { return videoEl.currentTime; },
    set currentTime(t) { videoEl.currentTime = t; },
    play: () => videoEl.play(),
    pause: () => videoEl.pause(),
    addEventListener: (evt, handler) => videoEl.addEventListener(evt, handler),
  };
}

function initNativeVideo(videoUrl, videoFormat) {
  const video = document.getElementById('meetingVideo');
  const errorEl = document.getElementById('videoError');
  const bigPlayBtn = document.getElementById('bigPlayButton');

  try {
    if (videoFormat === 'm3u8' && window.Hls && Hls.isSupported()) {
      const hls = new Hls();
      hls.loadSource(videoUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (data.fatal) {
          errorEl.textContent = 'Video failed to load; source link only.';
          errorEl.hidden = false;
        }
      });
    } else if (videoFormat === 'm3u8' && video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = videoUrl; // Safari native HLS
    } else {
      video.src = videoUrl;
    }
  } catch (e) {
    document.getElementById('videoSection').hidden = true;
    return;
  }

  // The native <video> control bar's play triangle is small and easy to
  // miss, especially against a busy poster-frame image (a real complaint
  // from live review). Show a large, obvious overlay play button instead;
  // it defers to the native controls once playback has started. YouTube's
  // embedded player has its own play button, so this is native-only.
  bigPlayBtn.hidden = false;
  bigPlayBtn.addEventListener('click', () => video.play());
  video.addEventListener('play', () => { bigPlayBtn.hidden = true; });
  video.addEventListener('pause', () => { bigPlayBtn.hidden = false; });

  // Warm up playback once metadata is available: briefly muted-play-then-
  // pause forces the browser to decode and render the first real frame
  // (instead of a blank black box) and pre-buffers the initial segments,
  // so the *next* play the user actually triggers starts instantly instead
  // of visibly waiting to buffer -- addresses the "awkward pause after
  // clicking play" complaint from live review.
  //
  // Careful: applyDeepLink() (called below) sets currentTime before
  // metadata is loaded, which per spec just queues it as the "default
  // playback position" and takes effect once metadata is ready -- so by
  // the time this fires, currentTime may already reflect a pending
  // deep-link seek. Capture and restore that value rather than resetting
  // to 0, or a deep link would get silently clobbered back to the start.
  video.addEventListener('loadedmetadata', () => {
    const targetTime = video.currentTime;
    const wasMuted = video.muted;
    video.muted = true;
    const playPromise = video.play();
    if (playPromise && playPromise.then) {
      playPromise.then(() => {
        video.pause();
        video.currentTime = targetTime;
        video.muted = wasMuted;
      }).catch(() => {
        video.muted = wasMuted; // autoplay blocked -- nothing to undo, just restore mute state
      });
    }
  }, { once: true });

  const adapter = createNativeAdapter(video);
  activeVideoAdapter = adapter;
  wireSharedControls(adapter);
  applyDeepLink(adapter);
}

// --- YouTube (PrimeGov delegates here too) -- no direct video file URL
// exists, so playback goes through an embedded iframe + the YouTube
// IFrame Player API instead of the native <video>/hls.js pathway above.
let _youtubeApiLoadPromise = null;

function loadYouTubeIframeApi() {
  if (window.YT && window.YT.Player) return Promise.resolve();
  if (_youtubeApiLoadPromise) return _youtubeApiLoadPromise;
  _youtubeApiLoadPromise = new Promise((resolve) => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof previous === 'function') previous();
      resolve();
    };
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  });
  return _youtubeApiLoadPromise;
}

function extractYouTubeVideoId(embedUrl) {
  const match = /\/embed\/([A-Za-z0-9_-]{11})/.exec(embedUrl || '');
  return match ? match[1] : null;
}

function createYouTubeAdapter(ytPlayer) {
  const listeners = { play: [], pause: [], timeupdate: [] };
  let pollHandle = null;
  const fire = (name) => listeners[name].forEach((fn) => fn());

  ytPlayer.addEventListener('onStateChange', (e) => {
    if (e.data === YT.PlayerState.PLAYING) {
      fire('play');
      if (!pollHandle) pollHandle = setInterval(() => fire('timeupdate'), 250);
    } else {
      fire('pause');
      if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
    }
  });

  return {
    get currentTime() { return ytPlayer.getCurrentTime(); },
    set currentTime(t) { ytPlayer.seekTo(t, true); },
    play: () => ytPlayer.playVideo(),
    pause: () => ytPlayer.pauseVideo(),
    addEventListener: (evt, handler) => { if (listeners[evt]) listeners[evt].push(handler); },
  };
}

async function initYouTubeVideo(embedUrl) {
  const videoId = extractYouTubeVideoId(embedUrl);
  const container = document.getElementById('youtubePlayerContainer');
  const errorEl = document.getElementById('videoError');
  if (!videoId || !container) {
    errorEl.textContent = 'Could not load this YouTube video.';
    errorEl.hidden = false;
    return;
  }

  document.getElementById('meetingVideo').hidden = true;
  document.getElementById('bigPlayButton').hidden = true;
  container.hidden = false;

  try {
    await loadYouTubeIframeApi();
  } catch (e) {
    errorEl.textContent = 'Video failed to load; source link only.';
    errorEl.hidden = false;
    return;
  }

  new YT.Player(container, {
    videoId,
    // buildYouTubePlayerVars() (shared_static/deep_link.js) folds in the
    // deep-link time as `start` -- see its own comment for why this
    // matters. applyDeepLink() below still runs in onReady regardless --
    // still needed for the line-only case (no t) and for highlighting
    // the matching transcript row -- its own seekTo() call in the
    // t-present case is now redundant but harmless (the position is
    // already correctly cued by then).
    playerVars: buildYouTubePlayerVars({ rel: 0, playsinline: 1 }),
    events: {
      // Unlike the native <video> path (where currentTime can be set,
      // queued, before metadata loads), the player isn't usable at all
      // until onReady fires -- the adapter, shared control wiring, and
      // deep-link seek all wait for it.
      onReady: (event) => {
        const adapter = createYouTubeAdapter(event.target);
        activeVideoAdapter = adapter;
        wireSharedControls(adapter);
        applyDeepLink(adapter);
      },
      onError: () => {
        errorEl.textContent = 'Video failed to load; source link only.';
        errorEl.hidden = false;
      },
    },
  });
}

// Viebit (NYC Council, via Legistar delegation) -- iframe-embedded, not
// native <video>/hls.js (see viebit.py's module docstring for why: the
// raw master.m3u8 is CDN-gated). Genuinely no cross-frame API exists on
// Viebit's embed page at all (confirmed by pulling its real player
// bundle directly -- no postMessage, nothing) -- the *only* control
// available is the `?t={seconds}` query param the embed page itself
// reads once on load, seeking there after playback starts. That means
// "seeking" here is really "reload the iframe with a new t=", and
// there's no way to read the iframe's actual current playback position
// from outside it -- see wireSharedControls' liveTracking option, which
// this adapter is built to be used with as `{ liveTracking: false }`.
function createViebitAdapter(iframeEl, baseEmbedUrl) {
  // Tracks only "the last position we explicitly told the iframe to seek
  // to", never real playback position -- correct for the getter's one
  // legitimate use (the initial "Share video at" label before
  // wireSharedControls hides that control entirely for liveTracking:false),
  // and irrelevant everywhere else since nothing else reads it.
  let lastSetTime = 0;
  return {
    get currentTime() { return lastSetTime; },
    set currentTime(t) {
      lastSetTime = Math.max(0, Math.floor(t));
      const url = new URL(baseEmbedUrl);
      url.searchParams.set('t', String(lastSetTime));
      iframeEl.src = url.toString();
    },
    // No cross-frame control exists for either -- iframe playback can
    // only be paused/played via its own visible native controls.
    play: () => {},
    pause: () => {},
    // No events are observable from outside the iframe either -- a
    // silent no-op rather than throwing, so wireSharedControls' calls
    // (harmless, liveTracking:false skips the ones that would matter)
    // don't need their own Viebit-specific guard.
    addEventListener: () => {},
  };
}

function initViebitVideo(embedUrl) {
  const iframe = document.getElementById('viebitFrame');
  const errorEl = document.getElementById('videoError');
  if (!iframe) {
    errorEl.textContent = 'Could not load this video.';
    errorEl.hidden = false;
    return;
  }

  document.getElementById('meetingVideo').hidden = true;
  document.getElementById('bigPlayButton').hidden = true;
  iframe.hidden = false;
  iframe.src = embedUrl;

  const adapter = createViebitAdapter(iframe, embedUrl);
  activeVideoAdapter = adapter;
  wireSharedControls(adapter, { liveTracking: false });
  // Still needed for the initial seek (applyDeepLink sets adapter.currentTime,
  // which reloads the iframe with ?t=) and the one-time highlight of the
  // matching transcript line -- neither depends on live position reading.
  applyDeepLink(adapter);
}

// Controls shared by both the native <video> and YouTube adapters --
// "Copy link to current time", auto-scroll toggle, the "Go to time" box,
// and highlighting the active transcript line as playback advances. Each
// initializer builds its own adapter (native wraps <video> directly;
// YouTube polls getCurrentTime() since there's no native timeupdate
// event) and calls this once, so this logic only needs to be written once.
// liveTracking=false (Viebit only, see createViebitAdapter -- there's no
// cross-frame API of any kind, so adapter.currentTime can't reflect real
// playback position once playback has moved past whatever time it was
// last explicitly set to) skips every affordance that would read
// adapter.currentTime to construct or display a link -- "currently
// playing" transcript highlighting, the live playhead readout, and
// "copy link to current time"/"copy link to this moment" -- rather than
// silently showing/copying a stale position. Explicit seeks (a
// transcript-line click, "Go to time") still work fully either way,
// since those only ever need a known target time, never a read.
function wireSharedControls(adapter, { liveTracking = true } = {}) {
  // Gently suggests the current transcript line is deep-linkable (its
  // link icon shows without a hover) when paused -- suppressed during
  // playback so it doesn't flicker from line to line as the highlighted
  // segment advances.
  adapter.addEventListener('play', () => document.body.classList.remove('video-at-rest'));
  adapter.addEventListener('pause', () => document.body.classList.add('video-at-rest'));

  const linkToCurrentLabel = document.getElementById('linkToCurrentLabel');
  const linkToCurrentBtn = document.getElementById('linkToCurrentBtn');
  const noTranscriptLinkBtn = document.getElementById('noTranscriptLinkBtn');

  if (!liveTracking) {
    // Hide rather than wire-but-disable -- a visible-but-broken "Share
    // video at 0:00" that never updates would look like a bug, not a
    // deliberate limitation.
    if (linkToCurrentBtn) linkToCurrentBtn.hidden = true;
    if (noTranscriptLinkBtn) noTranscriptLinkBtn.hidden = true;
  } else {
    adapter.addEventListener('timeupdate', () => {
      const segId = findActiveSegment(adapter.currentTime);
      if (segId) highlightSegment(segId, autoScrollEnabled, 'nearest');
      updateNoTranscriptTime(adapter);
      // Live "Share video at X:XX" -- reads more naturally than a static
      // "Copy link to current time" label, and doubles as a real-time
      // playhead readout even before anyone clicks it.
      if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;
    });

    // linkToCurrentBtn's label is now a live timestamp (above), so it can't
    // also be borrowed for "Copied!" text the way it used to be -- a
    // separate fading toast confirms the copy instead. noTranscriptLinkBtn
    // has no live label to protect, so it keeps the simpler swap-the-text
    // behavior unchanged.
    if (linkToCurrentBtn) {
      const toast = document.getElementById('linkToCurrentToast');
      let toastTimer = null;
      linkToCurrentBtn.addEventListener('click', async () => {
        const t = adapter.currentTime;
        const segId = findActiveSegment(t) || null;
        updateUrlParams({ t, line: segId });
        trackEvent('copy_link_to_time');
        try {
          await navigator.clipboard.writeText(window.location.href);
          if (toast) {
            toast.textContent = 'Copied to clipboard';
            toast.classList.add('visible');
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => toast.classList.remove('visible'), 5000);
          }
        } catch (e) {
          // clipboard API unavailable; URL is already updated in the address bar
        }
      });
    }

    if (noTranscriptLinkBtn) {
      const label = noTranscriptLinkBtn.querySelector('.cassette-label');
      const defaultText = label.textContent;
      noTranscriptLinkBtn.addEventListener('click', async () => {
        const t = adapter.currentTime;
        const segId = findActiveSegment(t) || null;
        updateUrlParams({ t, line: segId });
        trackEvent('copy_link_to_time');
        try {
          await navigator.clipboard.writeText(window.location.href);
          label.textContent = 'Copied!';
          setTimeout(() => { label.textContent = defaultText; }, 1500);
        } catch (e) {
          // clipboard API unavailable; URL is already updated in the address bar
        }
      });
    }

    // Reflects the initial position immediately (deep-linked or not),
    // rather than waiting for the first timeupdate -- matters most for
    // YouTube, where timeupdate is only polled while actually playing, so
    // a paused/autoplay-blocked load would otherwise show a stale "0:00".
    updateNoTranscriptTime(adapter);
    if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;
  }

  const toggleBtn = document.getElementById('toggleAutoScrollBtn');
  const stateSpan = document.getElementById('autoScrollState');
  toggleBtn.addEventListener('click', () => {
    autoScrollEnabled = !autoScrollEnabled;
    stateSpan.textContent = autoScrollEnabled ? 'On' : 'Off';
  });

  // Deep-linking to an exact moment is this app's primary goal -- the
  // transcript is a nice-to-have -- so jumping to a timestamp must work
  // even when there's no transcript to click a line in.
  const seekForm = document.getElementById('seekForm');
  const seekInput = document.getElementById('seekInput');
  seekForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const t = parseTimeInput(seekInput.value);
    if (t === null) {
      seekInput.setCustomValidity('Enter a time like 1:23:45, 12:34, or seconds');
      seekInput.reportValidity();
      return;
    }
    seekInput.setCustomValidity('');
    adapter.currentTime = t;
    const segId = findActiveSegment(t);
    if (segId) highlightSegment(segId, true);
    updateUrlParams({ t, line: segId || null });
  });
}

function parseTimeInput(raw) {
  const value = (raw || '').trim();
  if (!value) return null;
  if (/^\d+$/.test(value)) return Number(value);
  const parts = value.split(':').map((p) => p.trim());
  if (parts.length < 2 || parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return null;
  const nums = parts.map(Number);
  let seconds = 0;
  for (const n of nums) seconds = seconds * 60 + n;
  return seconds;
}

function renderCalendarPage(data) {
  const statusEl = document.getElementById('statusMessage');
  const metaEl = document.getElementById('meta');
  document.getElementById('pageTitle').textContent = 'This is a calendar, not a meeting | Red Tape Recordings';
  statusEl.textContent = '';
  metaEl.innerHTML = `<h1>This looks like a calendar page</h1>` +
    `<p>${escapeHtml(data.message || 'This URL lists multiple meetings rather than pointing to one specific meeting.')}` +
    ` Pick a meeting below, or paste a link to a specific meeting instead.</p>`;

  const candidates = data.candidates || [];
  const section = document.getElementById('transcriptSection');
  section.hidden = false;
  document.getElementById('transcriptWarnings').innerHTML = '';
  const list = document.getElementById('transcriptList');
  document.querySelector('#transcriptSection h2').textContent = 'Meetings found on this page';

  if (!candidates.length) {
    list.innerHTML = '<p>No individual meeting links could be found on this page.</p>';
    return;
  }

  list.innerHTML = candidates.map((c) => {
    const href = `/meeting?url=${encodeURIComponent(c.url)}`;
    return `<div class="calendar-candidate"><a href="${href}">${escapeHtml(c.title || 'Untitled meeting')}</a>` +
      (c.date ? ` <span class="calendar-candidate-date">${escapeHtml(c.date)}</span>` : '') +
      `</div>`;
  }).join('');
}

async function init() {
  const statusEl = document.getElementById('statusMessage');
  const metaEl = document.getElementById('meta');

  if (!sourceUrl) {
    statusEl.textContent = 'No meeting URL provided.';
    return;
  }

  wireTranscriptExport();
  wireReportProblemForm();
  wireTranscribeForm();
  wireNoTranscriptManualLink();

  statusEl.innerHTML = '<span class="status-loading">' +
    `<span class="cassette-reel spinning">${CASSETTE_REEL_SVG}</span>` +
    `<span class="cassette-reel spinning">${CASSETTE_REEL_SVG}</span>` +
    '<span>Please wait while we fetch the video and transcript from the government page. This usually takes less than 20 seconds.</span>' +
    '</span>';

  let data;
  try {
    const res = await fetch('/api/resolve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: sourceUrl }),
    });
    data = await res.json();
  } catch (e) {
    statusEl.textContent = `Failed to reach the resolver: ${e}`;
    return;
  }

  // This meeting already has a permanent Archive page -- send the browser
  // there instead of rendering here, preserving any deep-link params so a
  // shared /meeting?...&t=630&line=seg-4 link still lands on the right
  // moment. .replace() (not .href) so this transient page doesn't sit in
  // back-history between the referrer and the permanent page.
  if (data.redirect_url) {
    const params = getQueryParams();
    params.delete('url');
    const target = params.toString() ? `${data.redirect_url}?${params.toString()}` : data.redirect_url;
    window.location.replace(target);
    return;
  }

  if (data.error === 'calendar_page') {
    renderCalendarPage(data);
    return;
  }

  if (data.error) {
    statusEl.textContent = data.message || 'This meeting could not be resolved.';
    // Still worth letting someone report this -- "it wouldn't resolve at
    // all" is itself a useful signal, arguably more so than a report on a
    // meeting that resolved fine.
    document.getElementById('reportProblemToggleWrap').hidden = false;
    return;
  }

  statusEl.textContent = '';
  currentMeetingTitle = data.title || 'meeting';
  document.getElementById('reportProblemToggleWrap').hidden = false;
  document.getElementById('transcribeToggleWrap').hidden = false;
  // Viebit is confirmed (2026-08-08) to only be reached via NYC Council's
  // Legistar instance so far -- see ViebitAssetFinder's docstring. A cheap,
  // accurate-enough signal for "this is an NYC Council meeting" without
  // needing a real per-meeting cross-link to citymeetings.nyc (whose own
  // coverage isn't guaranteed to include this specific meeting).
  document.getElementById('nycCrosslink').hidden = data.platform !== 'viebit';
  document.getElementById('pageTitle').textContent = `${data.title || 'Meeting'} | Red Tape Recordings`;

  // Not data.platform === 'unknown' -- a best-effort result that delegated
  // to YouTubeAssetFinder carries platform: "youtube" (that finder's own
  // identity, unchanged regardless of caller), which is actually the most
  // common real outcome here. best_effort is the backend's real signal for
  // "nothing on this page is guaranteed" -- see ResolvedMeeting's own
  // docstring.
  const bestEffort = !!data.best_effort;

  metaEl.innerHTML = `<h1>${escapeHtml(data.title || 'Meeting')}</h1>` +
    `<p class="source-link"><a href="${escapeHtml(data.source_url)}" target="_blank" rel="noopener noreferrer">View original source &#8599;</a></p>` +
    (bestEffort ? `<p>This government website isn't supported yet, so we're going to try our best.</p>` : '') +
    `<p>${escapeHtml(formatJurisdictionDisplay(data.jurisdiction) || '')}${data.date ? ' &middot; ' + escapeHtml(data.date) : ''}</p>`;

  if (bestEffort) {
    // Plain, tentative "here's what we think we found" line instead of a
    // declarative warning box -- nothing here is confirmed on a platform
    // we don't actually support, so the framing shouldn't imply otherwise.
    if (data.video_url || !data.video_link) {
      renderSourceGuess('videoSourceGuess', 'We think the video is here: ', data.video_url, '[No video found]');
    } else {
      // A pointer to where the video probably lives, when nothing playable
      // was found -- two confidence tiers with distinct copy (the user's
      // own framing, 2026-08-14): a recognized video host gets a
      // confident line, a loose video-shaped guess gets a cautionary one.
      // Never fed to initVideo() -- a page URL in the player breaks the
      // native <video> path silently.
      let host = '';
      try { host = new URL(data.video_link).hostname.replace(/^www\./, ''); } catch (e) { /* leave blank */ }
      const suffix = data.video_link_recognized
        ? ` — we recognize ${host} as a regular video host, but can't embed it here yet.`
        : ` — but we don't recognize ${host} as a supported video host, so proceed with caution.`;
      const el = document.getElementById('videoLinkGuess');
      el.innerHTML = escapeHtml('We think the video is here: ')
        + `<a href="${escapeHtml(data.video_link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(data.video_link)}</a>`
        + escapeHtml(suffix);
      el.hidden = false;
    }
  } else {
    // #videoError (inside #videoSection, below the player) is where this
    // rendered when a video exists -- kept exactly as-is for that case. But
    // #videoSection gets hidden entirely when there's no video_url (initVideo()
    // below), which previously took this message down with it even though it
    // exists specifically to explain *why* there's no video -- #videoWarnings
    // (a sibling, always independently visible) is only for that no-video
    // case. #videoError itself stays reserved as before for genuine native-
    // <video>/HLS playback failures on top of that, a narrower case set later
    // by initVideo() where a video legitimately exists but failed to load.
    const videoWarnings = data.video_warnings || [];
    if (videoWarnings.length) {
      const target = document.getElementById(data.video_url ? 'videoError' : 'videoWarnings');
      renderWarnings(target, videoWarnings);
    }
  }

  const agendaItems = data.agenda_items || [];
  if (bestEffort) {
    // Always shown for a best-effort result, even with nothing found --
    // an honest "[No agenda found]" beats silently omitting the heading.
    document.getElementById('agendaSection').hidden = false;
    renderSourceGuess('agendaGuess', 'We think we found an agenda here: ', data.agenda_link, '[No agenda found]');
    if (agendaItems.length) renderAgenda(agendaItems);
  } else if (agendaItems.length) {
    document.getElementById('agendaSection').hidden = false;
    renderAgenda(agendaItems);
  }

  const transcriptWarnings = data.transcript_warnings || [];
  segments = data.segments || [];
  if (segments.length) {
    document.getElementById('transcriptSection').hidden = false;
    renderWarnings(document.getElementById('transcriptWarnings'), transcriptWarnings);
    setupTranscriptLanguagePicker(data.transcript_language, segments, data.alternate_transcripts || []);
    renderTranscript(segments);
    setupTranscriptSearch();
  } else if (transcriptWarnings.length) {
    document.getElementById('transcriptMissing').hidden = false;
    if (bestEffort) {
      // No live playhead to honestly show here -- deep-link reliability
      // isn't confirmed on an unsupported platform, and there may be no
      // video at all to track in the first place. Let the reader type
      // the moment they want instead of implying we're tracking one.
      document.getElementById('noTranscriptLive').hidden = true;
      document.getElementById('noTranscriptManual').hidden = false;
    } else {
      renderWarnings(document.getElementById('transcriptMissingWarnings'), transcriptWarnings);
    }
  }

  initVideo(data.video_url, data.video_format);
}

// Renders "<label><a>url</a>" or "<label>[fallback]" into #<id> -- the
// shared shape behind both the video and agenda "we think we found this"
// lines on a best-effort result page.
function renderSourceGuess(id, label, url, fallbackText) {
  const el = document.getElementById(id);
  el.innerHTML = escapeHtml(label) + (url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`
    : escapeHtml(fallbackText));
  el.hidden = false;
}

// The live-tracking "Copy link to this moment" (wireSharedControls, wired
// only when a real video adapter exists) has a manual-entry counterpart
// for best-effort results, wired unconditionally here since it must work
// even when no video was found at all (no adapter to read a time from).
function wireNoTranscriptManualLink() {
  const btn = document.getElementById('noTranscriptManualLinkBtn');
  const input = document.getElementById('noTranscriptManualInput');
  if (!btn || !input) return;
  const label = btn.querySelector('.cassette-label');
  const defaultText = label.textContent;
  btn.addEventListener('click', async () => {
    const t = parseTimeInput(input.value);
    if (t === null) {
      input.setCustomValidity('Enter a time like 1:23:45, 12:34, or seconds');
      input.reportValidity();
      return;
    }
    input.setCustomValidity('');
    updateUrlParams({ t, line: null });
    trackEvent('copy_link_to_time');
    try {
      await navigator.clipboard.writeText(window.location.href);
      label.textContent = 'Copied!';
      setTimeout(() => { label.textContent = defaultText; }, 1500);
    } catch (e) {
      // clipboard API unavailable; URL is already updated in the address bar
    }
  });
}

// Some warning messages (video, agenda, or transcript) mention requesting a
// transcript from the audio -- makes that phrase itself a real trigger for
// the same "Request Transcript from Audio" action, instead of leaving it as
// dead text next to a button elsewhere on the page the reader has to go
// find themselves.
const _TRANSCRIBE_PHRASE_RE = /request a transcript from the audio/i;

function renderWarnings(container, warnings) {
  container.innerHTML = warnings.map(linkifyWarning).map((html) => html.replace(
    _TRANSCRIBE_PHRASE_RE,
    (match) => `<button type="button" class="transcribe-inline-trigger">${match}</button>`
  )).join('<br>');
  container.hidden = false;
  container.querySelectorAll('.transcribe-inline-trigger').forEach((btn) => {
    btn.addEventListener('click', () => document.getElementById('transcribeToggle').click());
  });
}

init();
