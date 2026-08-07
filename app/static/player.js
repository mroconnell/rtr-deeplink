// Deep-link mechanics ported from rtr-transcripts/app/static/transcript.js
// (query param parsing, hls.js setup, click-to-seek, auto-scroll highlighting),
// rewritten lean without the auth/archive/multi-tab-transcript machinery.

const sourceUrl = document.body.dataset.sourceUrl;
let autoScrollEnabled = true;
let segments = [];

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

function updateUrlParams({ t = null, line = null }) {
  const params = getQueryParams();
  if (t !== null) params.set('t', String(Math.floor(t)));
  if (line !== null) params.set('line', line);
  const newUrl = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState({}, '', newUrl);
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

const LINK_ICON_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M6.5 9.5a.75.75 0 0 0 1 .06l.06-.06 3-3a.75.75 0 0 0-1-1.12l-.06.06-3 3a.75.75 0 0 0 0 1.06z"/><path fill="currentColor" d="M5.72 11.03a2.5 2.5 0 0 1 0-3.54l1.5-1.5a.75.75 0 0 1 1.06 1.06l-1.5 1.5a1 1 0 0 0 1.42 1.42l1.5-1.5a.75.75 0 1 1 1.06 1.06l-1.5 1.5a2.5 2.5 0 0 1-3.54 0z"/><path fill="currentColor" d="M9.72 4.97a2.5 2.5 0 0 1 3.54 3.54l-1.5 1.5a.75.75 0 1 1-1.06-1.06l1.5-1.5a1 1 0 0 0-1.42-1.42l-1.5 1.5A.75.75 0 1 1 8.22 6.5l1.5-1.5z"/></svg>';

const CASSETTE_REEL_SVG = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7" fill="#fff" stroke="#bbb" stroke-width="2"/><circle cx="9" cy="9" r="2.2" fill="#bbb"/></svg>';

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

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

// Warning messages are plain server-generated text, but some (e.g. a
// Granicus agenda fallback link) include a bare URL meant to be
// clickable -- escape first for safety, then linkify on the escaped
// text so this never introduces raw HTML from warning content itself.
function linkifyWarning(text) {
  return escapeHtml(text).replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );
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
    playerVars: { rel: 0, playsinline: 1 },
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

// Controls shared by both the native <video> and YouTube adapters --
// "Copy link to current time", auto-scroll toggle, the "Go to time" box,
// and highlighting the active transcript line as playback advances. Each
// initializer builds its own adapter (native wraps <video> directly;
// YouTube polls getCurrentTime() since there's no native timeupdate
// event) and calls this once, so this logic only needs to be written once.
function wireSharedControls(adapter) {
  // Gently suggests the current transcript line is deep-linkable (its
  // link icon shows without a hover) when paused -- suppressed during
  // playback so it doesn't flicker from line to line as the highlighted
  // segment advances.
  adapter.addEventListener('play', () => document.body.classList.remove('video-at-rest'));
  adapter.addEventListener('pause', () => document.body.classList.add('video-at-rest'));

  adapter.addEventListener('timeupdate', () => {
    const segId = findActiveSegment(adapter.currentTime);
    if (segId) highlightSegment(segId, autoScrollEnabled);
    updateNoTranscriptTime(adapter);
  });

  // Two buttons do the exact same "copy a link to right now" action --
  // the toolbar one (always present) and a second, more prominent one
  // filling the space where the transcript would otherwise be, for
  // meetings with nothing to click through. Same handler for both.
  [document.getElementById('linkToCurrentBtn'), document.getElementById('noTranscriptLinkBtn')]
    .filter(Boolean)
    .forEach((btn) => {
      const label = btn.querySelector('.cassette-label');
      const defaultText = label.textContent;
      btn.addEventListener('click', async () => {
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
    });

  // Reflects the initial position immediately (deep-linked or not),
  // rather than waiting for the first timeupdate -- matters most for
  // YouTube, where timeupdate is only polled while actually playing, so
  // a paused/autoplay-blocked load would otherwise show a stale "0:00".
  updateNoTranscriptTime(adapter);

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

function applyDeepLink(video) {
  const line = getDeepLinkLine();
  const t = getDeepLinkTime();

  // `t` (exact seconds) always wins for the actual seek position -- `line`
  // is only used to decide which row to highlight. Previously `line`, when
  // present, seeked to that segment's *start* and silently discarded a more
  // precise `t` in the same URL. That was barely noticeable for Granicus's
  // short (~2-10s) caption lines, but very wrong for CivicClerk's
  // multi-minute chapter markers: "copy link to current time" partway
  // through a chapter would jump back to the chapter's start on reload.
  if (t !== null) {
    video.currentTime = t;
    const segId = line || findActiveSegment(t);
    if (segId) highlightSegment(segId, true);
    return;
  }
  if (line) {
    const el = document.getElementById(line);
    if (el) {
      const start = Number(el.dataset.start || '0');
      video.currentTime = Math.max(0, start - (getOffsetSeconds()));
      highlightSegment(line, true);
    }
  }
}

function getOffsetSeconds() {
  return 0; // reserved for future offset calibration, per rtr-transcripts PDR
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

  if (data.error === 'calendar_page') {
    renderCalendarPage(data);
    return;
  }

  if (data.error) {
    statusEl.textContent = data.message || 'This meeting could not be resolved.';
    return;
  }

  statusEl.textContent = '';
  document.getElementById('pageTitle').textContent = `${data.title || 'Meeting'} | Red Tape Recordings`;
  metaEl.innerHTML = `<h1>${escapeHtml(data.title || 'Meeting')}</h1>` +
    `<p class="source-link"><a href="${escapeHtml(data.source_url)}" target="_blank" rel="noopener noreferrer">View original source &#8599;</a></p>` +
    `<p>${escapeHtml(data.jurisdiction || '')}${data.date ? ' &middot; ' + escapeHtml(data.date) : ''}</p>`;

  const videoWarnings = data.video_warnings || [];
  if (videoWarnings.length) {
    document.getElementById('videoError').textContent = videoWarnings.map((w) => w).join(' ');
    document.getElementById('videoError').hidden = false;
  }

  const transcriptWarnings = data.transcript_warnings || [];
  segments = data.segments || [];
  if (segments.length) {
    document.getElementById('transcriptSection').hidden = false;
    document.getElementById('transcriptWarnings').innerHTML = transcriptWarnings.length
      ? transcriptWarnings.map(linkifyWarning).join('<br>') : '';
    renderTranscript(segments);
    setupTranscriptSearch();
  } else if (transcriptWarnings.length) {
    document.getElementById('transcriptMissing').hidden = false;
    document.getElementById('transcriptMissingWarnings').innerHTML = transcriptWarnings.map(linkifyWarning).join('<br>');
  }

  initVideo(data.video_url, data.video_format);
}

init();
