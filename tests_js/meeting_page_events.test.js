'use strict';

// GA instrumentation on the Archive's permanent /m/* pages
// (archive/static/meeting_page.js), added 2026-08-17 -- until then those
// pages emitted no custom events at all, so a week of real visitors showed
// only page_view/scroll (see BACKLOG_DONE.md). Event names deliberately
// mirror app/static/player.js's so one GA report spans both surfaces; this
// pins that the four interactions fire exactly those names, once each, and
// that save_meeting fires only on a confirmed server response.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const DEEP_LINK_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'shared_static', 'deep_link.js'),
  'utf8'
);
const MEETING_PAGE_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'archive', 'static', 'meeting_page.js'),
  'utf8'
);

// Same real markup shapes meeting_page.html renders (a transcript segment
// with its timestamp anchor + copy button, the two "Share video at" buttons,
// the two save controls). Loaded the same way tests_js/helpers.js loads
// deep_link.js -- as real <script> elements so top-level declarations share
// the page's script scope.
async function makePage({ fetchOk = true } = {}) {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <button id="linkToCurrentBtn"><span id="linkToCurrentLabel"></span></button>
      <span id="linkToCurrentToast"></span>
      <button id="noTranscriptLinkBtn"><span class="cassette-label">Copy link</span></button>
      <div class="transcript-section">
        <div class="transcript-segment" id="seg-0" data-start="12">
          <a href="#seg-0" class="segment-timestamp" data-start="12">[0:12]</a>
          <button class="segment-link-btn" data-start="12" data-line="seg-0"></button>
        </div>
      </div>
      <button id="saveMeetingBtn" class="save-meeting-control" data-slug="x" data-saved="false"><span class="cassette-label"></span></button>
      <button id="saveMeetingIconBtn" class="save-meeting-control" data-slug="x" data-saved="false"></button>
    </body></html>`,
    { url: 'https://example.test/m/x', runScripts: 'dangerously' }
  );
  const { window } = dom;
  window.Element.prototype.scrollIntoView = () => {};
  const events = [];
  window.trackEvent = (name, params) => events.push({ name, params });
  window.fetch = async () => ({ ok: fetchOk });
  for (const src of [DEEP_LINK_SRC, MEETING_PAGE_SRC]) {
    const s = window.document.createElement('script');
    s.textContent = src;
    window.document.head.appendChild(s);
  }
  // Let meeting_page.js's own DOMContentLoaded boot run (jsdom fires it on
  // the next tick): it wires the seek/copy clicks and the save controls
  // itself. Wiring those manually as well would double-register listeners
  // -- exactly what a first draft of this test did, and it showed up as a
  // duplicated save_meeting event. wireSharedControls() is the exception:
  // boot only calls it when a #videoWrapper exists, so tests call it.
  await new Promise((r) => setTimeout(r, 0));
  return { window, events };
}

function fakeAdapter() {
  const listeners = {};
  return {
    currentTime: 30,
    addEventListener: (evt, fn) => { (listeners[evt] = listeners[evt] || []).push(fn); },
    fire: (evt) => (listeners[evt] || []).forEach((fn) => fn()),
  };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe('meeting_page.js GA events', () => {
  test('video_play fires once per adapter play event, on the shared controls', async () => {
    const { window, events } = await makePage();
    const adapter = fakeAdapter();
    window.wireSharedControls(adapter);
    adapter.fire('play');
    assert.deepEqual(events.filter((e) => e.name === 'video_play').length, 1);
    // ...and even when live tracking is off (Viebit-style adapters wire
    // the play listener before the early return, so a real play would still
    // count -- Viebit's adapter just never emits one).
    const { window: w2, events: ev2 } = await makePage();
    const a2 = fakeAdapter();
    w2.wireSharedControls(a2, { liveTracking: false });
    a2.fire('play');
    assert.equal(ev2.filter((e) => e.name === 'video_play').length, 1);
  });

  test('copy_link_to_time fires for both share buttons and the per-line copy button', async () => {
    const { window, events } = await makePage();
    window.wireSharedControls(fakeAdapter());
    window.document.getElementById('linkToCurrentBtn').click();
    window.document.getElementById('noTranscriptLinkBtn').click();
    window.document.querySelector('.segment-link-btn').click();
    await flush();
    assert.equal(events.filter((e) => e.name === 'copy_link_to_time').length, 3);
  });

  test('transcript_seek fires on a timestamp click, not on a copy click', async () => {
    const { window, events } = await makePage();
    window.document.querySelector('.segment-timestamp').click();
    await flush();
    assert.equal(events.filter((e) => e.name === 'transcript_seek').length, 1);
    assert.equal(events.filter((e) => e.name === 'copy_link_to_time').length, 0);
  });

  test('save_meeting fires with a two-value action only after a confirmed server flip', async () => {
    const { window, events } = await makePage({ fetchOk: true });
    window.document.getElementById('saveMeetingBtn').click();
    await flush(); await flush();
    // Compare extracted values, not objects: params are created inside the
    // jsdom window (a different realm), so strict deepEqual's prototype
    // check would fail on structurally identical objects.
    assert.deepEqual(
      events.filter((e) => e.name === 'save_meeting').map((e) => [e.name, e.params.action]),
      [['save_meeting', 'save']]
    );
    // Second click flips back -> 'unsave'.
    window.document.getElementById('saveMeetingBtn').click();
    await flush(); await flush();
    assert.deepEqual(events.filter((e) => e.name === 'save_meeting').map((e) => e.params.action), ['save', 'unsave']);

    // A failed request (401/network) leaves state alone AND fires nothing.
    const { window: w2, events: ev2 } = await makePage({ fetchOk: false });
    w2.document.getElementById('saveMeetingBtn').click();
    await flush(); await flush();
    assert.equal(ev2.filter((e) => e.name === 'save_meeting').length, 0);
  });

  test('event names are exactly the resolver page\'s, so one GA report spans both surfaces', () => {
    const playerSrc = fs.readFileSync(path.join(__dirname, '..', 'app', 'static', 'player.js'), 'utf8');
    for (const name of ['video_play', 'transcript_seek', 'copy_link_to_time']) {
      assert.ok(playerSrc.includes(`trackEvent('${name}'`), `${name} missing from player.js`);
      assert.ok(MEETING_PAGE_SRC.includes(`trackEvent('${name}'`), `${name} missing from meeting_page.js`);
    }
  });
});

// Transcript version-picker analytics (BACKLOG.md, 2026-08-22 entry --
// "the picker has zero trackEvent calls, so there is no evidence about
// whether it is ever seen or used"). #versionSelect only renders when
// page.versions|length > 1 (meeting_page.html), so its absence is the
// real single-version case, not a bug -- covered below too.
async function makeVersionPickerPage({ optionsHtml, dataset } = {}) {
  const opts = optionsHtml || [
    '<option value="1" data-source="scraped" selected>English (sourced)</option>',
    '<option value="2" data-source="whisper">English (auto-generated)</option>',
  ].join('');
  const attrs = Object.assign(
    { activeSource: 'scraped', versionCount: '2', isDefault: 'true' },
    dataset
  );
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <form method="get" class="version-picker">
        <select id="versionSelect" name="version"
                data-active-source="${attrs.activeSource}"
                data-version-count="${attrs.versionCount}"
                data-is-default="${attrs.isDefault}">
          ${opts}
        </select>
      </form>
    </body></html>`,
    { url: 'https://example.test/m/x', runScripts: 'dangerously' }
  );
  const { window } = dom;
  const events = [];
  window.trackEvent = (name, params) => events.push({ name, params });
  const s = window.document.createElement('script');
  s.textContent = MEETING_PAGE_SRC;
  window.document.head.appendChild(s);
  await flush();
  return { window, events };
}

describe('meeting_page.js transcript version-picker analytics', () => {
  test('transcript_version_available and transcript_version_viewed fire once on load', async () => {
    // Compare extracted values, not whole objects: params are created
    // inside the jsdom window (a different realm), so deepEqual's
    // prototype check fails on structurally identical objects -- same
    // gotcha the save_meeting test above already documents.
    const { events } = await makeVersionPickerPage();
    const available = events.filter((e) => e.name === 'transcript_version_available');
    assert.equal(available.length, 1);
    assert.deepEqual(
      [available[0].params.count, available[0].params.active_source, available[0].params.label_ambiguous],
      [2, 'scraped', false]
    );
    const viewed = events.filter((e) => e.name === 'transcript_version_viewed');
    assert.equal(viewed.length, 1);
    assert.equal(viewed[0].params.is_default, true);
  });

  test('label_ambiguous is true when two options render identical text', async () => {
    const dupeOptions = [
      '<option value="1" data-source="scraped" selected>English (sourced)</option>',
      '<option value="2" data-source="deduped">English (sourced)</option>',
    ].join('');
    const { events } = await makeVersionPickerPage({ optionsHtml: dupeOptions });
    const available = events.find((e) => e.name === 'transcript_version_available');
    assert.equal(available.params.label_ambiguous, true);
  });

  test('is_default reflects a non-default selection', async () => {
    const { events } = await makeVersionPickerPage({ dataset: { isDefault: 'false' } });
    const viewed = events.find((e) => e.name === 'transcript_version_viewed');
    assert.equal(viewed.params.is_default, false);
  });

  test('no #versionSelect (single-version page) fires nothing, not an error', async () => {
    const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
      url: 'https://example.test/m/x',
      runScripts: 'dangerously',
    });
    const { window } = dom;
    const events = [];
    window.trackEvent = (name, params) => events.push({ name, params });
    const s = window.document.createElement('script');
    s.textContent = MEETING_PAGE_SRC;
    window.document.head.appendChild(s);
    await flush();
    assert.equal(events.length, 0);
  });

  test('transcript_version_change is wired inline in the template, not this file', () => {
    // Per BACKLOG.md's own decision: navigation must never depend on this
    // file loading, so the change event fires inline in meeting_page.html's
    // onchange, immediately before the existing this.form.submit(). Pin
    // that the inline call exists in the template rather than assuming
    // meeting_page.js emits it.
    const templateSrc = fs.readFileSync(
      path.join(__dirname, '..', 'archive', 'templates', 'meeting_page.html'),
      'utf8'
    );
    assert.ok(templateSrc.includes("trackEvent('transcript_version_change'"));
    assert.ok(!MEETING_PAGE_SRC.includes("trackEvent('transcript_version_change'"));
  });
});
