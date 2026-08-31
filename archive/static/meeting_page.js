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

// Kept in sync with app/static/player.js's identical constant (this
// file's own header comment) -- used by wireTranscribeForm()'s loading
// state below.
const CASSETTE_REEL_SVG = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="7" fill="#fff" stroke="#bbb" stroke-width="2"/><circle cx="9" cy="9" r="2.2" fill="#bbb"/></svg>';

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

// The speed control lives in /shared-static/playback_speed.js, loaded as a
// separate <script>. These two helpers keep it strictly optional: if that
// file fails to load, the page loses its speed chip and nothing else.
// wireSharedControls() also drives transcript highlighting and deep links
// -- the core of the product -- so it must not throw over a nice-to-have.
function speedLadder() {
  return typeof PLAYBACK_RATE_LADDER !== 'undefined' ? PLAYBACK_RATE_LADDER : [];
}

function wirePlaybackSpeed(adapter) {
  if (typeof initPlaybackSpeed === 'function') initPlaybackSpeed(adapter);
}

function createNativeAdapter(videoEl) {
  return {
    get currentTime() { return videoEl.currentTime; },
    set currentTime(t) { videoEl.currentTime = t; },
    play: () => videoEl.play(),
    pause: () => videoEl.pause(),
    addEventListener: (evt, handler) => videoEl.addEventListener(evt, handler),
    // Speed contract -- see app/static/player.js's createNativeAdapter and
    // shared_static/playback_speed.js for the reasoning. No vendor cap on
    // this path, so the full shared ladder applies.
    speedRates: speedLadder(),
    get playbackRate() { return videoEl.playbackRate; },
    set playbackRate(rate) {
      videoEl.playbackRate = rate;
      if ('preservesPitch' in videoEl) videoEl.preservesPitch = true;
    },
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

  // Rates come from the player itself -- YouTube caps at 2x and ignores
  // any value off its own list. See app/static/player.js's version.
  const availableRates = typeof ytPlayer.getAvailablePlaybackRates === 'function'
    ? ytPlayer.getAvailablePlaybackRates()
    : [1];
  const speedRates = speedLadder().filter((r) => availableRates.indexOf(r) !== -1);

  return {
    get currentTime() { return ytPlayer.getCurrentTime(); },
    set currentTime(t) { ytPlayer.seekTo(t, true); },
    play: () => ytPlayer.playVideo(),
    pause: () => ytPlayer.pauseVideo(),
    addEventListener: (evt, handler) => { if (listeners[evt]) listeners[evt].push(handler); },
    speedRates: speedRates.length > 1 ? speedRates : null,
    get playbackRate() { return ytPlayer.getPlaybackRate(); },
    set playbackRate(rate) { ytPlayer.setPlaybackRate(rate); },
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

// liveTracking=false (Viebit only, see createViebitAdapter -- no
// cross-frame API of any kind exists, so adapter.currentTime can't
// reflect real playback position once playback has moved past whatever
// time it was last explicitly set to) skips every affordance that would
// read adapter.currentTime to construct or display a link, rather than
// silently showing/copying a stale position. Explicit seeks (a
// transcript-line click) still work fully either way. Mirrors
// app/static/player.js's identical option.
// GA event names + params here deliberately mirror app/static/player.js's
// (the resolver's ephemeral /meeting page) exactly, so one GA report covers
// both surfaces. Added to the Archive 2026-08-17: until then the permanent
// /m/* pages -- 1,200+ of them, where sitemap/search/shared-link traffic
// actually lands -- emitted zero custom events, so a week of real visitors
// showed only page_view/scroll and "does anyone use the deep links" was
// unanswerable in principle (BACKLOG.md's audit "user validation" lead;
// GA for 2026-08-17 with Ryan filtered out: page_view, session_start,
// first_visit, scroll, user_engagement, nothing else). No extra params:
// GA attaches page_location to every event, which already separates
// /m/* from the resolver's /meeting?..., and the WO-9 low-cardinality
// rule says don't add what isn't needed. save_meeting is the one event
// the resolver doesn't have (saving needs a permanent page).
//
// Coverage note: `video_play` comes from the adapter's 'play' event, which
// the native <video> and YouTube adapters both emit; the Viebit iframe
// adapter can't (no cross-frame API -- see createViebitAdapter), so NYC
// Council pages report seeks/copies but never plays. applyDeepLink() does
// not auto-play, so a play event is a real press, not a warm-up.
function wireSharedControls(adapter, { liveTracking = true } = {}) {
  // Above the !liveTracking early return below on purpose: speed support
  // is the adapter's own declared capability, a different question from
  // whether its position can be read live. They coincide today (Viebit
  // lacks both), but wiring speed off liveTracking would couple them.
  wirePlaybackSpeed(adapter);

  const linkToCurrentLabel = document.getElementById('linkToCurrentLabel');
  const linkBtn = document.getElementById('linkToCurrentBtn');
  const noTranscriptLinkBtn = document.getElementById('noTranscriptLinkBtn');

  adapter.addEventListener('play', () => trackEvent('video_play'));

  if (!liveTracking) {
    if (linkBtn) linkBtn.hidden = true;
    if (noTranscriptLinkBtn) noTranscriptLinkBtn.hidden = true;
    return;
  }

  adapter.addEventListener('timeupdate', () => {
    const segId = findActiveSegment(adapter.currentTime);
    if (segId) highlightSegment(segId, autoScrollEnabled, 'nearest');
    updateNoTranscriptTime(adapter);
    if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;
  });
  updateNoTranscriptTime(adapter);
  if (linkToCurrentLabel) linkToCurrentLabel.textContent = `Share video at ${formatTime(adapter.currentTime)}`;

  if (linkBtn) {
    const toast = document.getElementById('linkToCurrentToast');
    let toastTimer = null;
    linkBtn.addEventListener('click', async () => {
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
}

// Vimeo (Chicago ELMS delegates here too) -- iframe + Vimeo's own Player
// SDK, not native <video>/hls.js. Mirrors app/static/player.js's
// identical adapter/initializer -- see that file's comments and
// vimeo.py's module docstring for the full "why", including why this one
// is wired with liveTracking ON (a real, confirmed cross-frame
// play/pause/seek/timeupdate API) unlike the Viebit adapter below.
let _vimeoSdkLoadPromise = null;

function loadVimeoPlayerSdk() {
  if (window.Vimeo && window.Vimeo.Player) return Promise.resolve();
  if (_vimeoSdkLoadPromise) return _vimeoSdkLoadPromise;
  _vimeoSdkLoadPromise = new Promise((resolve, reject) => {
    const tag = document.createElement('script');
    tag.src = 'https://player.vimeo.com/api/player.js';
    tag.onload = () => resolve();
    tag.onerror = () => reject(new Error('Vimeo Player SDK failed to load'));
    document.head.appendChild(tag);
  });
  return _vimeoSdkLoadPromise;
}

function isVimeoEmbedUrl(embedUrl) {
  return /^https:\/\/player\.vimeo\.com\/video\/\d+(?:\?|$)/.test(embedUrl || '');
}

function buildVimeoEmbedUrl(embedUrl) {
  const deepLinkTime = getDeepLinkTime();
  if (deepLinkTime === null) return embedUrl;
  return `${embedUrl}#t=${Math.max(0, Math.floor(deepLinkTime))}s`;
}

function createVimeoAdapter(player) {
  const listeners = { play: [], pause: [], timeupdate: [] };
  const fire = (name) => listeners[name].forEach((fn) => fn());
  let lastKnownTime = 0;
  // Cached because the SDK's getters are promise-based; the speed chip
  // reads playbackRate synchronously.
  let lastKnownRate = 1;

  const track = (data) => {
    if (data && typeof data.seconds === 'number') lastKnownTime = data.seconds;
  };
  player.on('play', () => fire('play'));
  player.on('pause', () => fire('pause'));
  player.on('ended', () => fire('pause'));
  player.on('timeupdate', (data) => { track(data); fire('timeupdate'); });
  player.on('seeked', (data) => { track(data); fire('timeupdate'); });

  return {
    get currentTime() { return lastKnownTime; },
    set currentTime(t) {
      lastKnownTime = Math.max(0, t);
      player.setCurrentTime(lastKnownTime).catch(() => {});
    },
    play: () => player.play().catch(() => {}),
    pause: () => player.pause().catch(() => {}),
    addEventListener: (evt, handler) => { if (listeners[evt]) listeners[evt].push(handler); },
    // Vimeo's SDK documents 0.5-2 and exposes no capability query, so the
    // ladder is capped rather than asked for. See player.js's version.
    speedRates: speedLadder().filter((r) => r <= 2),
    get playbackRate() { return lastKnownRate; },
    set playbackRate(rate) {
      lastKnownRate = rate;
      player.setPlaybackRate(rate).catch(() => {});
    },
  };
}

async function initVimeoVideo(embedUrl) {
  const container = document.getElementById('vimeoPlayerContainer');
  if (!isVimeoEmbedUrl(embedUrl) || !container) return;

  try {
    await loadVimeoPlayerSdk();
  } catch (e) {
    return;
  }

  const iframe = document.createElement('iframe');
  iframe.src = buildVimeoEmbedUrl(embedUrl);
  iframe.setAttribute('allow', 'autoplay; fullscreen; picture-in-picture');
  iframe.setAttribute('allowfullscreen', '');
  iframe.setAttribute('title', 'Meeting video');
  container.replaceChildren(iframe);

  let player;
  try {
    player = new Vimeo.Player(iframe);
    await player.ready();
  } catch (e) {
    return;
  }

  const adapter = createVimeoAdapter(player);
  activeVideoAdapter = adapter;
  wireSharedControls(adapter);
  applyDeepLink(adapter);
}

// Viebit (NYC Council, via Legistar delegation) -- iframe-embedded, not
// native <video>/hls.js. Mirrors app/static/player.js's identical
// adapter/initializer -- see that file's comments and viebit.py's module
// docstring for the full "why": no cross-frame API exists on Viebit's
// embed page at all, so the only control available is the `?t={seconds}`
// query param it reads once on load.
function createViebitAdapter(iframeEl, baseEmbedUrl) {
  let lastSetTime = 0;
  return {
    get currentTime() { return lastSetTime; },
    set currentTime(t) {
      lastSetTime = Math.max(0, Math.floor(t));
      const url = new URL(baseEmbedUrl);
      url.searchParams.set('t', String(lastSetTime));
      iframeEl.src = url.toString();
    },
    play: () => {},
    pause: () => {},
    addEventListener: () => {},
    // No cross-frame API, so speed can't be set either -- null makes
    // initPlaybackSpeed skip the chip rather than render a dead one.
    speedRates: null,
  };
}

function initViebitVideo(embedUrl) {
  const iframe = document.getElementById('viebitFrame');
  if (!iframe) return;

  iframe.src = embedUrl;

  const adapter = createViebitAdapter(iframe, embedUrl);
  activeVideoAdapter = adapter;
  wireSharedControls(adapter, { liveTracking: false });
  applyDeepLink(adapter);
}

function wireAutoScrollToggle() {
  const toggleBtn = document.getElementById('toggleAutoScrollBtn');
  const stateSpan = document.getElementById('autoScrollState');
  if (!toggleBtn || !stateSpan) return;
  toggleBtn.addEventListener('click', () => {
    autoScrollEnabled = !autoScrollEnabled;
    stateSpan.textContent = autoScrollEnabled ? 'On' : 'Off';
  });
}

function wireSeekAndCopyClicks() {
  document.querySelectorAll('.segment-timestamp[data-start]').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const start = Number(a.dataset.start || '0');
      if (activeVideoAdapter) activeVideoAdapter.currentTime = start;
      const segId = a.closest('.transcript-segment')?.id;
      updateUrlParams({ t: start, line: segId && /^seg-\d+$/.test(segId) ? segId : null });
      trackEvent('transcript_seek');
    });
  });

  document.querySelectorAll('.segment-link-btn[data-start]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const start = Number(btn.dataset.start || '0');
      updateUrlParams({ t: start, line: btn.dataset.line || null });
      trackEvent('copy_link_to_time');
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
      if (res.status === 429) {
        // Real bug fixed 2026-08-12: slowapi's rate-limit response has no
        // `ok`/`message` keys (its body is `{"error": "Rate limit
        // exceeded: ..."}`), so this used to fall through to the generic
        // "couldn't find a usable audio or video source" message below --
        // reading exactly like a real resolution failure with no hint the
        // actual cause was "you've already requested several transcripts
        // this hour." Checked before `data.ok` specifically so a real
        // rate limit is never mistaken for that. Same duplicated fix as
        // app/static/player.js's copy of this function.
        checkStatusEl.textContent = "You've hit the transcript request limit for now — please try again in about an hour.";
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

// "Refresh this page" -- WO-15 (BACKLOG.md, 2026-08-16): re-submitting
// this URL through the homepage never triggered a refresh on its own
// (only a token-gated admin endpoint or the passive 30-day recheck cycle
// did), the confirmed root cause behind several separately-filed "why
// does this page look wrong" bugs. Calls the resolver's own
// /api/refresh-archived-page (same-origin via app/main.py's /m/{slug}
// proxy, same pattern wireReportProblemForm()/wireTranscribeForm() above
// already rely on) and reloads on success so the visitor sees the result
// immediately rather than having to guess whether anything changed.
function wireRefreshPageButton() {
  const btn = document.getElementById('refreshPageBtn');
  const statusEl = document.getElementById('refreshPageStatus');
  if (!btn || !statusEl) return;

  btn.addEventListener('click', async () => {
    const url = btn.dataset.url;
    if (!url) return;

    btn.disabled = true;
    statusEl.textContent = 'Checking the source for updates…';
    statusEl.className = 'refresh-page-status';

    try {
      const res = await fetch('/api/refresh-archived-page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (res.ok) {
        statusEl.textContent = data.pushed
          ? 'Updated — reloading…'
          : 'No changes found at the source.';
        statusEl.className = 'refresh-page-status success';
        if (data.pushed) {
          setTimeout(() => window.location.reload(), 1200);
          return;
        }
      } else {
        statusEl.textContent = data.message || 'Something went wrong — please try again.';
        statusEl.className = 'refresh-page-status error';
      }
    } catch (err) {
      statusEl.textContent = 'Something went wrong — please try again.';
      statusEl.className = 'refresh-page-status error';
    } finally {
      btn.disabled = false;
    }
  });
}

// Save this meeting -- two controls that toggle the same saved/unsaved
// state together: the text button below the video (#saveMeetingBtn) and
// the bookmark icon next to the title (#saveMeetingIconBtn), both tagged
// with the shared .save-meeting-control class. No reveal-form needed
// (unlike wireReportProblemForm/wireTranscribeForm above, this needs no
// extra input from the visitor). Server-rendered with the correct
// initial saved/unsaved state (see archive/main.py's meeting_page()
// route, is_meeting_saved()) so there's no flash of the wrong state on
// load; this only handles the click.
function wireSaveMeetingButton() {
  const controls = Array.from(document.querySelectorAll('.save-meeting-control'));
  if (!controls.length) return;

  function applyState(saved) {
    controls.forEach((el) => {
      el.dataset.saved = saved ? 'true' : 'false';
      const label = el.querySelector('.cassette-label');
      if (label) label.textContent = saved ? 'Saved ✓ (click to unsave)' : 'Save this meeting';
      if (el.id === 'saveMeetingIconBtn') {
        el.title = saved ? 'Click to unsave this meeting' : 'Click to save this meeting on your account profile';
      }
    });
  }

  controls.forEach((btn) => {
    btn.addEventListener('click', async () => {
      const saved = btn.dataset.saved === 'true';
      const endpoint = saved ? '/api/account/unsave-meeting' : '/api/account/save-meeting';
      controls.forEach((el) => { el.disabled = true; });
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug: btn.dataset.slug }),
        });
        if (res.ok) {
          applyState(!saved);
          // Fired only on a confirmed server-side flip, so the count means
          // real saves, not clicks. `action` is a two-value enum (WO-9
          // low-cardinality rule); no slug -- page_location already has it.
          trackEvent('save_meeting', { action: saved ? 'unsave' : 'save' });
        }
        // A 401 (session expired mid-visit) or any other failure leaves the
        // controls exactly as they were -- no misleading state flip on failure.
      } catch (err) {
        // Network error -- same "leave state alone" reasoning as above.
      } finally {
        controls.forEach((el) => { el.disabled = false; });
      }
    });
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
  // :not(#sourceDisclaimerPointer) -- that one link reuses this class for
  // its link-styled look only, not this auto-click behavior; it's wired
  // separately below by wireSourceDisclaimerPointer(), deliberately
  // *not* auto-clicking the real button (see that function's comment).
  document.querySelectorAll('.transcribe-inline-trigger:not(#sourceDisclaimerPointer)').forEach((btn) => {
    btn.addEventListener('click', () => document.getElementById('transcribeToggle').click());
  });
}

// The source-transcript disclaimer's "button to the left" link (user
// request 2026-08-11, meeting_page.html) -- unlike the warnings-text
// .transcribe-inline-trigger buttons above, this deliberately does NOT
// auto-click #transcribeToggle (that would silently fire the feasibility
// check's real network request just from reading the disclaimer,
// working against wireTranscribeForm()'s own deliberate friction). Just
// draws the eye to the real button: a brief pop/glow via the
// .pointed-to animation (style.css), the same "depressed vs. popped-up"
// tape-deck cue floated for the search/save-search buttons in
// BACKLOG.md. Removes-then-re-adds the class (with a forced reflow in
// between) so a second click re-triggers the animation even if it's
// still settling from the first.
//
// User feedback 2026-08-11: the plain #transcribeToggle anchor's native
// jump-scrolled every click, even when the button was already fully on
// screen -- jarring on a typical desktop viewport where the two-column
// layout usually keeps it in view already. preventDefault() replaces
// that with a real visibility check: only scrolls when the button isn't
// already fully within the viewport, the glow alone otherwise.
function wireSourceDisclaimerPointer() {
  const link = document.getElementById('sourceDisclaimerPointer');
  const toggle = document.getElementById('transcribeToggle');
  if (!link || !toggle) return;
  link.addEventListener('click', (e) => {
    e.preventDefault();
    const rect = toggle.getBoundingClientRect();
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const fullyVisible = rect.top >= 0 && rect.bottom <= viewportHeight;
    if (!fullyVisible) {
      toggle.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    toggle.classList.remove('pointed-to');
    void toggle.offsetWidth;
    toggle.classList.add('pointed-to');
  });
}

function wireVersionAnalytics() {
  // Both events are load-time observations, not interactions -- the
  // change event itself fires inline in the picker's own onchange
  // (meeting_page.html), since navigation must never depend on this
  // file having loaded. A page with only one version never renders
  // #versionSelect at all, so this naturally covers that population too.
  const select = document.getElementById('versionSelect');
  if (!select) return;
  const labels = Array.from(select.options).map((o) => o.textContent);
  const labelAmbiguous = new Set(labels).size < labels.length;
  trackEvent('transcript_version_available', {
    count: Number(select.dataset.versionCount || '0'),
    active_source: select.dataset.activeSource || '',
    label_ambiguous: labelAmbiguous,
  });
  trackEvent('transcript_version_viewed', {
    is_default: select.dataset.isDefault === 'true',
  });
}

document.addEventListener('DOMContentLoaded', () => {
  segments = Array.from(document.querySelectorAll('.transcript-section .transcript-segment[data-start]')).map(
    (el) => ({ start: Number(el.dataset.start || '0') })
  );

  wireSeekAndCopyClicks();
  wireAutoScrollToggle();
  wireReportProblemForm();
  wireTranscribeForm();
  wireTranscribeInlineTriggers();
  wireSourceDisclaimerPointer();
  wireSaveMeetingButton();
  wireVersionAnalytics();
  wireRefreshPageButton();

  const wrapper = document.getElementById('videoWrapper');
  if (!wrapper) return;
  const videoUrl = wrapper.dataset.videoUrl;
  const videoFormat = wrapper.dataset.videoFormat;
  if (videoFormat === 'youtube') {
    initYouTubeVideo(videoUrl);
  } else if (videoFormat === 'vimeo') {
    initVimeoVideo(videoUrl);
  } else if (videoFormat === 'viebit') {
    initViebitVideo(videoUrl);
  } else if (videoUrl) {
    initNativeVideo(videoUrl, videoFormat);
  }
});
