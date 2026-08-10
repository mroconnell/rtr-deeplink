// Trimmed port of app/static/player.js's video-adapter logic for the
// Archive's permanent pages. Not a straight copy: the resolver's
// player.js fetches JSON and builds the transcript DOM from scratch; here
// the transcript/agenda are already server-rendered into the page (that's
// the whole point -- real content on first byte, for crawlability), so this
// only wires interactivity onto DOM that already exists. t/line/version
// deep-link mechanics (getQueryParams, updateUrlParams, findActiveSegment,
// highlightSegment, applyDeepLink, segments, etc.) live in
// /shared-static/deep_link.js, loaded before this file (see
// meeting_page.html) -- the same file the resolver's player.js loads, so
// the two pages can no longer silently desync on this logic.

let activeVideoAdapter = null;

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
// this page has no video either). Mirrors app/static/player.js's
// identical helper.
function updateNoTranscriptTime(adapter) {
  const el = document.getElementById('noTranscriptTime');
  if (el) el.textContent = formatTime(adapter.currentTime);
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
  if (videoFormat === 'm3u8' && window.Hls && Hls.isSupported()) {
    const hls = new Hls();
    hls.loadSource(videoUrl);
    hls.attachMedia(video);
  } else {
    video.src = videoUrl; // mp4, or Safari's native HLS support
  }

  const adapter = createNativeAdapter(video);
  activeVideoAdapter = adapter;
  wireSharedControls(adapter);
  applyDeepLink(adapter);
}

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
  if (!videoId || !container) return;

  await loadYouTubeIframeApi();

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
      onReady: (event) => {
        const adapter = createYouTubeAdapter(event.target);
        activeVideoAdapter = adapter;
        wireSharedControls(adapter);
        applyDeepLink(adapter);
      },
    },
  });
}

function wireSharedControls(adapter) {
  const linkToCurrentLabel = document.getElementById('linkToCurrentLabel');
  adapter.addEventListener('timeupdate', () => {
    const segId = findActiveSegment(adapter.currentTime);
    if (segId) highlightSegment(segId, true, 'nearest');
    updateNoTranscriptTime(adapter);
    if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;
  });
  updateNoTranscriptTime(adapter);
  if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;

  const linkBtn = document.getElementById('linkToCurrentBtn');
  if (linkBtn) {
    const toast = document.getElementById('linkToCurrentToast');
    let toastTimer = null;
    linkBtn.addEventListener('click', async () => {
      const t = adapter.currentTime;
      const segId = findActiveSegment(t) || null;
      updateUrlParams({ t, line: segId });
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

  const noTranscriptLinkBtn = document.getElementById('noTranscriptLinkBtn');
  if (noTranscriptLinkBtn) {
    const label = noTranscriptLinkBtn.querySelector('.cassette-label');
    const defaultText = label.textContent;
    noTranscriptLinkBtn.addEventListener('click', async () => {
      const t = adapter.currentTime;
      const segId = findActiveSegment(t) || null;
      updateUrlParams({ t, line: segId });
      try {
        await navigator.clipboard.writeText(window.location.href);
        label.textContent = 'Copied!';
        setTimeout(() => { label.textContent = defaultText; }, 1500);
      } catch (e) {
        // clipboard API unavailable; URL is already updated in the address bar
      }
    });
  }
}

function wireSeekAndCopyClicks() {
  document.querySelectorAll('.segment-timestamp[data-start]').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const start = Number(a.dataset.start || '0');
      if (activeVideoAdapter) activeVideoAdapter.currentTime = start;
      const segId = a.closest('.transcript-segment')?.id;
      updateUrlParams({ t: start, line: segId && /^seg-\d+$/.test(segId) ? segId : null });
    });
  });

  document.querySelectorAll('.segment-link-btn[data-start]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const start = Number(btn.dataset.start || '0');
      updateUrlParams({ t: start, line: btn.dataset.line || null });
      try {
        await navigator.clipboard.writeText(window.location.href);
        btn.classList.add('copied');
        setTimeout(() => btn.classList.remove('copied'), 1200);
      } catch (e2) {
        // clipboard API unavailable; URL is already updated in the address bar
      }
    });
  });
}

function wireTranscribeForm() {
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
    toggle.hidden = false;
    checkStatusEl.textContent = '';
    checkStatusEl.className = 'transcribe-status';
    emailStep.hidden = true;
    statusEl.textContent = '';
    statusEl.className = 'transcribe-status';
    feasibilityOk = false;
  }

  // Friction is intentional (see BACKLOG.md's abuse-control notes): the
  // feasibility check always fires immediately on toggle, before any email
  // field appears, so a request that can't actually be transcribed never
  // gets that far.
  toggle.addEventListener('click', async () => {
    form.hidden = false;
    toggle.hidden = true;
    emailStep.hidden = true;
    checkStatusEl.textContent = 'Checking for a usable audio or video source…';
    checkStatusEl.className = 'transcribe-status';

    try {
      const res = await fetch('/api/transcription/check-feasibility', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: form.dataset.url || window.location.href }),
      });
      const data = await res.json();
      if (data.ok) {
        feasibilityOk = true;
        checkStatusEl.textContent = '';
        emailStep.hidden = false;
      } else {
        checkStatusEl.innerHTML = linkifyWarning(data.message || "We couldn't find a usable audio or video source for this meeting.");
        checkStatusEl.className = 'transcribe-status error';
      }
    } catch (err) {
      checkStatusEl.textContent = 'Something went wrong — please try again.';
      checkStatusEl.className = 'transcribe-status error';
    }
  });

  cancelBtn.addEventListener('click', resetForm);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!feasibilityOk) return;
    const email = document.getElementById('transcribeEmail').value;
    const submitBtn = form.querySelector('button[type="submit"]');

    submitBtn.disabled = true;
    statusEl.textContent = '';
    statusEl.className = 'transcribe-status';

    try {
      const res = await fetch('/api/transcription/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: form.dataset.url || window.location.href, email }),
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
      submitBtn.disabled = false;
    }
  });
}

function wireReportProblemForm() {
  const toggle = document.getElementById('reportProblemToggle');
  const form = document.getElementById('reportProblemForm');
  const cancelBtn = document.getElementById('reportProblemCancel');
  if (!toggle || !form) return;

  toggle.addEventListener('click', () => {
    form.hidden = false;
    toggle.hidden = true;
  });
  cancelBtn.addEventListener('click', () => {
    form.hidden = true;
    toggle.hidden = false;
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
          url: form.dataset.url || window.location.href,
          issue_type: issueType,
          details: document.getElementById('reportProblemDetails').value,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        statusEl.textContent = 'Thanks — we’ll take a look.';
        statusEl.className = 'report-problem-status success';
        form.reset();
        setTimeout(() => { form.hidden = true; toggle.hidden = false; }, 2000);
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

// Warnings (video_warnings, transcript_warnings) are rendered server-side
// via Jinja2's warnings_html filter (archive/utils/render_warnings.py,
// 2026-08-10), which already turns the standardized "request a transcript
// from the audio" phrase into a real <button class="transcribe-inline-
// trigger"> -- present in the initial DOM, not dynamically inserted, so
// this wires up clicks once at page load rather than per-insertion the
// way player.js's renderWarnings() does for its own JS-inserted version
// of the same markup. Called before the early `if (!wrapper) return`
// below on purpose -- the no-video case (no #videoWrapper at all) is
// exactly the case most likely to have this button in its warning text.
function wireTranscribeInlineTriggers() {
  document.querySelectorAll('.transcribe-inline-trigger').forEach((btn) => {
    btn.addEventListener('click', () => document.getElementById('transcribeToggle').click());
  });
}

document.addEventListener('DOMContentLoaded', () => {
  segments = Array.from(document.querySelectorAll('.transcript-section .transcript-segment[data-start]')).map(
    (el) => ({ start: Number(el.dataset.start || '0') })
  );

  wireSeekAndCopyClicks();
  wireReportProblemForm();
  wireTranscribeForm();
  wireTranscribeInlineTriggers();

  const wrapper = document.getElementById('videoWrapper');
  if (!wrapper) return;
  const videoUrl = wrapper.dataset.videoUrl;
  const videoFormat = wrapper.dataset.videoFormat;
  if (videoFormat === 'youtube') {
    initYouTubeVideo(videoUrl);
  } else if (videoUrl) {
    initNativeVideo(videoUrl, videoFormat);
  }
});
