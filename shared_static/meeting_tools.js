// Reader tools shared by both meeting pages: the resolver's /meeting page
// (app/static/player.js) and the Archive's /m/{slug} page
// (archive/static/meeting_page.js). Served from shared_static/, like
// deep_link.js, so the two pages cannot drift apart. Ryan, 2026-10-16:
//
//   1. A find bar over the agenda and transcript. Phones have no easy
//      Ctrl+F, so on a narrow screen the bar sticks to the top of the
//      screen while the reader scrolls (meeting_tools.css).
//   2. The agenda document viewer loads only when the reader asks for it.
//      Loading a vendor's agenda link in a frame on page load sometimes
//      made the browser download the file (a server that sends it as an
//      attachment, or a phone browser that cannot show a PDF in a frame).
//   3. Theater mode and a drag handle to resize the player (desktop).
//
// Each init function no-ops when its markup is missing, so either page
// can call all of them.

function safeStorageGet(key) {
  try { return window.localStorage.getItem(key); } catch (e) { return null; }
}

function safeStorageSet(key, value) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch (e) {
    // Private window or blocked storage: the setting just won't persist.
  }
}

// ---------------------------------------------------------------------
// 1. Find bar
// ---------------------------------------------------------------------

// Searches every .segment-text inside #transcriptColumn (agenda items and
// transcript lines). Works on the DOM rather than a data array so it
// covers both pages' markup, including the Archive's speaker labels
// (a <span> inside .segment-text): matches are wrapped text node by text
// node, and each element's original HTML is restored before the next
// search. A re-rendered transcript (the resolver's language picker) just
// produces new elements, so nothing needs resetting beyond clearing the
// input.
function initFindBar() {
  const bar = document.getElementById('transcriptSearch');
  const input = document.getElementById('transcriptSearchInput');
  const countEl = document.getElementById('transcriptSearchCount');
  const prevBtn = document.getElementById('transcriptSearchPrev');
  const nextBtn = document.getElementById('transcriptSearchNext');
  if (!bar || !input || bar.dataset.wired === 'true') return;
  bar.dataset.wired = 'true';

  const originals = new WeakMap();
  let touched = [];
  let matches = [];
  let current = -1;

  function restore() {
    touched.forEach((el) => {
      if (originals.has(el)) el.innerHTML = originals.get(el);
    });
    touched = [];
  }

  function updateCount() {
    if (!input.value.trim()) { countEl.textContent = ''; return; }
    countEl.textContent = matches.length ? `${current + 1}/${matches.length}` : '0 matches';
  }

  function goTo(idx) {
    if (!matches.length) return;
    if (current >= 0 && matches[current]) matches[current].classList.remove('current');
    current = ((idx % matches.length) + matches.length) % matches.length;
    const el = matches[current];
    el.classList.add('current');
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    updateCount();
  }

  function highlightIn(el, q) {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    let found = false;
    nodes.forEach((node) => {
      const text = node.nodeValue;
      const lower = text.toLowerCase();
      let pos = 0;
      let idx = lower.indexOf(q, pos);
      if (idx === -1) return;
      const frag = document.createDocumentFragment();
      while (idx !== -1) {
        if (idx > pos) frag.appendChild(document.createTextNode(text.slice(pos, idx)));
        const mark = document.createElement('mark');
        mark.className = 'search-match';
        mark.textContent = text.slice(idx, idx + q.length);
        frag.appendChild(mark);
        matches.push(mark);
        pos = idx + q.length;
        idx = lower.indexOf(q, pos);
      }
      if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
      node.parentNode.replaceChild(frag, node);
      found = true;
    });
    return found;
  }

  function run() {
    restore();
    matches = [];
    current = -1;
    const q = input.value.trim().toLowerCase();
    if (q) {
      document.querySelectorAll('#transcriptColumn .transcript-list .segment-text').forEach((el) => {
        if (!el.textContent.toLowerCase().includes(q)) return;
        if (!originals.has(el)) originals.set(el, el.innerHTML);
        if (highlightIn(el, q)) touched.push(el);
      });
    }
    updateCount();
    if (matches.length) goTo(0);
  }

  input.addEventListener('input', run);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      input.value = '';
      run();
      return;
    }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (matches.length) goTo(current + (e.shiftKey ? -1 : 1));
  });
  if (prevBtn) prevBtn.addEventListener('click', () => goTo(current - 1));
  if (nextBtn) nextBtn.addEventListener('click', () => goTo(current + 1));
}

// ---------------------------------------------------------------------
// 2. Agenda viewer, loaded on request only
// ---------------------------------------------------------------------

// The server renders a button with data-src instead of an <iframe src>.
// Nothing from the agenda's host is requested until the reader clicks.
function initAgendaViewer() {
  document.querySelectorAll('.agenda-frame-toggle[data-src]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const holder = btn.closest('.agenda-viewer');
      if (!holder) return;
      let frame = holder.querySelector('iframe.agenda-inline-frame');
      if (frame) {
        frame.remove();
        btn.textContent = btn.dataset.showLabel || 'Show the agenda here';
        btn.setAttribute('aria-expanded', 'false');
        return;
      }
      frame = document.createElement('iframe');
      frame.className = 'agenda-inline-frame';
      frame.title = 'Meeting agenda document';
      frame.setAttribute('referrerpolicy', 'no-referrer');
      frame.src = btn.dataset.src;
      holder.appendChild(frame);
      btn.dataset.showLabel = btn.textContent;
      btn.textContent = 'Hide the agenda';
      btn.setAttribute('aria-expanded', 'true');
    });
  });
}

// ---------------------------------------------------------------------
// 3. Theater mode and player size (desktop only)
// ---------------------------------------------------------------------

const PLAYER_WIDTH_KEY = 'rtr.playerWidth';
const THEATER_KEY = 'rtr.theaterMode';
const PLAYER_MIN_WIDTH = 220;
// Leave the transcript at least this much room beside the player.
const TRANSCRIPT_MIN_WIDTH = 360;

function isDesktopLayout() {
  return window.matchMedia('(min-width: 900px)').matches;
}

function clampPlayerWidth(px) {
  const page = document.querySelector('.meeting-page');
  const pageWidth = page ? page.parentElement.clientWidth : window.innerWidth;
  // 1.5rem padding each side plus the 1.75rem column gap, in px.
  const chrome = 24 * 2 + 28;
  const max = Math.max(PLAYER_MIN_WIDTH, pageWidth - chrome - TRANSCRIPT_MIN_WIDTH);
  return Math.round(Math.min(Math.max(px, PLAYER_MIN_WIDTH), max));
}

function applyPlayerWidth(px) {
  const root = document.querySelector('.meeting-page');
  if (!root) return;
  if (px === null) root.style.removeProperty('--video-col-width');
  else root.style.setProperty('--video-col-width', `${clampPlayerWidth(px)}px`);
}

function initPlayerLayout() {
  const page = document.querySelector('.meeting-page');
  const column = document.getElementById('videoColumn');
  const theaterBtn = document.getElementById('theaterModeBtn');
  if (!page || !column) return;

  const saved = Number(safeStorageGet(PLAYER_WIDTH_KEY));
  if (saved) applyPlayerWidth(saved);

  function setTheater(on) {
    document.body.classList.toggle('theater-mode', on);
    if (theaterBtn) {
      theaterBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
      theaterBtn.textContent = on ? 'Exit theater mode' : 'Theater mode';
    }
    safeStorageSet(THEATER_KEY, on ? '1' : null);
  }

  if (theaterBtn) {
    theaterBtn.addEventListener('click', () => setTheater(!document.body.classList.contains('theater-mode')));
    if (safeStorageGet(THEATER_KEY) === '1') setTheater(true);
  }

  // Drag handle on the player column's right edge.
  const handle = document.createElement('div');
  handle.className = 'player-resize-handle';
  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-orientation', 'vertical');
  handle.setAttribute('aria-label', 'Drag to resize the video. Double-click to reset.');
  handle.title = 'Drag to resize the video. Double-click to reset.';
  handle.tabIndex = 0;
  column.appendChild(handle);

  let startX = 0;
  let startWidth = 0;
  let dragging = false;

  function onMove(e) {
    if (!dragging) return;
    applyPlayerWidth(startWidth + (e.clientX - startX));
  }

  function onUp() {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('player-resizing');
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    safeStorageSet(PLAYER_WIDTH_KEY, String(column.getBoundingClientRect().width | 0));
  }

  handle.addEventListener('pointerdown', (e) => {
    if (!isDesktopLayout() || document.body.classList.contains('theater-mode')) return;
    e.preventDefault();
    dragging = true;
    startX = e.clientX;
    startWidth = column.getBoundingClientRect().width;
    // Iframe players (YouTube, Vimeo, Viebit) swallow pointer events, so
    // the drag would stall the moment the cursor crosses one. The CSS for
    // this class turns pointer events off on them during a drag.
    document.body.classList.add('player-resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  });

  handle.addEventListener('dblclick', () => {
    applyPlayerWidth(null);
    safeStorageSet(PLAYER_WIDTH_KEY, null);
  });

  handle.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const width = column.getBoundingClientRect().width + (e.key === 'ArrowRight' ? 40 : -40);
    applyPlayerWidth(width);
    safeStorageSet(PLAYER_WIDTH_KEY, String(clampPlayerWidth(width)));
  });

  // Keep a saved width valid when the window shrinks.
  window.addEventListener('resize', () => {
    const w = Number(safeStorageGet(PLAYER_WIDTH_KEY));
    if (w) applyPlayerWidth(w);
  });
}

function initMeetingTools() {
  initFindBar();
  initAgendaViewer();
  initPlayerLayout();
}
