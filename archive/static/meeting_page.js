// Trimmed port of app/static/player.js's video-adapter/seek/highlight logic
// for the Archive's permanent pages. Not a straight copy: the resolver's
// player.js fetches JSON and builds the transcript DOM from scratch; here
// the transcript/agenda are already server-rendered into the page (that's
// the whole point -- real content on first byte, for crawlability), so this
// only wires interactivity onto DOM that already exists. Deep-link params
// (`t`, `line`) and the segment-id scheme (`seg-N`) intentionally match the
// resolver's so a shared link behaves the same on either page.

let activeVideoAdapter = null;
let segments = [];

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
  if (scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
    playerVars: { rel: 0, playsinline: 1 },
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
  adapter.addEventListener('timeupdate', () => {
    const segId = findActiveSegment(adapter.currentTime);
    if (segId) highlightSegment(segId, true);
  });

  const linkBtn = document.getElementById('linkToCurrentBtn');
  if (linkBtn) {
    const label = linkBtn.querySelector('.cassette-label');
    const defaultText = label.textContent;
    linkBtn.addEventListener('click', async () => {
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

function applyDeepLink(adapter) {
  const line = getDeepLinkLine();
  const t = getDeepLinkTime();

  // `t` (exact seconds) always wins for the actual seek position -- `line`
  // only decides which row to highlight. Matches player.js's rule.
  if (t !== null) {
    adapter.currentTime = t;
    const segId = line || findActiveSegment(t);
    if (segId) highlightSegment(segId, true);
    return;
  }
  if (line) {
    const el = document.getElementById(line);
    if (el) {
      const start = Number(el.dataset.start || '0');
      adapter.currentTime = start;
      highlightSegment(line, true);
    }
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

document.addEventListener('DOMContentLoaded', () => {
  segments = Array.from(document.querySelectorAll('.transcript-section .transcript-segment[data-start]')).map(
    (el) => ({ start: Number(el.dataset.start || '0') })
  );

  wireSeekAndCopyClicks();

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
