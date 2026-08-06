// Deep-link mechanics ported from rtr-transcripts/app/static/transcript.js
// (query param parsing, hls.js setup, click-to-seek, auto-scroll highlighting),
// rewritten lean without the auth/archive/multi-tab-transcript machinery.

const sourceUrl = document.body.dataset.sourceUrl;
let autoScrollEnabled = true;
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

function formatTime(seconds) {
  seconds = Math.floor(seconds || 0);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
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

function renderTranscript(segs) {
  const container = document.getElementById('transcriptList');
  container.innerHTML = '';
  segs.forEach((seg, index) => {
    const segId = `seg-${index}`;
    const div = document.createElement('div');
    div.className = 'transcript-segment';
    div.id = segId;
    div.dataset.start = seg.start;
    div.innerHTML = `<a href="#${segId}" class="segment-timestamp" data-start="${seg.start}" data-seg-id="${segId}">[${formatTime(seg.start)}]</a> <span class="segment-text">${escapeHtml(seg.text)}</span>`;
    container.appendChild(div);
  });

  container.querySelectorAll('.segment-timestamp').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const start = Number(a.dataset.start || '0');
      const segId = a.dataset.segId;
      const video = document.getElementById('meetingVideo');
      if (video) video.currentTime = Math.max(0, start - 1);
      highlightSegment(segId, false);
      updateUrlParams({ t: start, line: segId });
    });
  });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

function initVideo(videoUrl, videoFormat) {
  const video = document.getElementById('meetingVideo');
  const section = document.getElementById('videoSection');
  const errorEl = document.getElementById('videoError');

  if (!videoUrl) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

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
    section.hidden = true;
  }

  video.addEventListener('timeupdate', () => {
    const segId = findActiveSegment(video.currentTime);
    if (segId) highlightSegment(segId, autoScrollEnabled);
  });

  const linkBtn = document.getElementById('linkToCurrentBtn');
  linkBtn.addEventListener('click', async () => {
    const t = video.currentTime;
    const segId = findActiveSegment(t) || null;
    updateUrlParams({ t, line: segId });
    try {
      await navigator.clipboard.writeText(window.location.href);
      linkBtn.textContent = 'Copied!';
      setTimeout(() => { linkBtn.textContent = 'Copy link to current time'; }, 1500);
    } catch (e) {
      // clipboard API unavailable; URL is already updated in the address bar
    }
  });

  const toggleBtn = document.getElementById('toggleAutoScrollBtn');
  const stateSpan = document.getElementById('autoScrollState');
  toggleBtn.addEventListener('click', () => {
    autoScrollEnabled = !autoScrollEnabled;
    stateSpan.textContent = autoScrollEnabled ? 'On' : 'Off';
  });

  applyDeepLink(video);
}

function applyDeepLink(video) {
  const line = getDeepLinkLine();
  const t = getDeepLinkTime();

  if (line) {
    const el = document.getElementById(line);
    if (el) {
      const start = Number(el.dataset.start || '0');
      video.currentTime = Math.max(0, start - (getOffsetSeconds()));
      highlightSegment(line, true);
      return;
    }
  }
  if (t !== null) {
    video.currentTime = t;
    const segId = findActiveSegment(t);
    if (segId) {
      highlightSegment(segId, true);
      updateUrlParams({ t, line: segId });
    }
  }
}

function getOffsetSeconds() {
  return 0; // reserved for future offset calibration, per rtr-transcripts PDR
}

async function init() {
  const statusEl = document.getElementById('statusMessage');
  const metaEl = document.getElementById('meta');

  if (!sourceUrl) {
    statusEl.textContent = 'No meeting URL provided.';
    return;
  }

  statusEl.textContent = 'Resolving meeting video and transcript...';

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

  if (data.error) {
    statusEl.textContent = data.message || 'This meeting could not be resolved.';
    return;
  }

  statusEl.textContent = '';
  document.getElementById('pageTitle').textContent = `${data.title || 'Meeting'} | rtr-deeplink`;
  metaEl.innerHTML = `<h1>${escapeHtml(data.title || 'Meeting')}</h1>` +
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
      ? transcriptWarnings.map(escapeHtml).join('<br>') : '';
    renderTranscript(segments);
  } else if (transcriptWarnings.length) {
    document.getElementById('transcriptMissing').hidden = false;
    document.getElementById('transcriptMissingWarnings').innerHTML = transcriptWarnings.map(escapeHtml).join('<br>');
  }

  initVideo(data.video_url, data.video_format);
}

init();
