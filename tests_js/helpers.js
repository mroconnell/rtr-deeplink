'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const DEEP_LINK_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'shared_static', 'deep_link.js'),
  'utf8'
);

// Loads deep_link.js as a real <script> element (not vm.runInContext) so
// its top-level `let`/`function` declarations land in the window's actual
// global script scope -- the same distinction that mattered when this file
// was first manually verified (see BACKLOG_DONE.md): a real browser's
// separate classic <script> tags share top-level let/const bindings, which
// a plain eval() does not reproduce (eval creates its own nested scope).
// Every test gets a fresh window/module state this way, same as a real
// page load.
function makeWindow(url, { versionId = null } = {}) {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    url,
    runScripts: 'dangerously',
  });
  const { window } = dom;

  // jsdom doesn't implement layout, so scrollIntoView is unimplemented and
  // would otherwise spam "Error: Not implemented" to stderr on every
  // highlightSegment() call with scrollIntoView=true. A silent no-op is
  // enough -- these tests assert the .playing class and seek time, not
  // scroll behavior.
  window.Element.prototype.scrollIntoView = () => {};

  if (versionId !== null) {
    window.document.body.dataset.versionId = versionId;
  }

  const scriptEl = window.document.createElement('script');
  scriptEl.textContent = DEEP_LINK_SRC;
  window.document.head.appendChild(scriptEl);

  return window;
}

// `segments` is a top-level `let` in deep_link.js -- per spec, `let`/`const`
// (unlike function declarations) never become properties of `window`, only
// bare identifiers in the shared script scope. A second appended <script>
// with a bare (no `let`/`const`) assignment reaches that same scope, exactly
// how player.js/meeting_page.js set it for real after loading deep_link.js.
function setSegments(window, segments) {
  const scriptEl = window.document.createElement('script');
  scriptEl.textContent = `segments = ${JSON.stringify(segments)};`;
  window.document.head.appendChild(scriptEl);
}

// Real transcript-segment markup shape (matches player.js's renderAgenda()/
// the transcript renderer and meeting_page.html's transcript-segment divs):
// an element with a real id and a data-start seconds value.
function addSegmentEls(window, entries) {
  for (const { id, start } of entries) {
    const el = window.document.createElement('div');
    el.className = 'transcript-segment';
    el.id = id;
    el.dataset.start = String(start);
    window.document.body.appendChild(el);
  }
}

function makeFakeVideo(currentTime = 0) {
  return { currentTime };
}

module.exports = { makeWindow, setSegments, addSegmentEls, makeFakeVideo };
