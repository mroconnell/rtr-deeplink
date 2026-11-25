'use strict';

// Signed-out "Save" clicks open the free-account box instead of calling the
// save API (archive/static/signup_prompt.js, 2026-11-24), and the visit
// counter (shared_static/visit_counter.js) reports 30-day visit buckets.
// Markup mirrors meeting_page.html's two save controls.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const read = (...p) => fs.readFileSync(path.join(__dirname, '..', ...p), 'utf8');
const DEEP_LINK_SRC = read('shared_static', 'deep_link.js');
const MEETING_PAGE_SRC = read('archive', 'static', 'meeting_page.js');
const PROMPT_SRC = read('archive', 'static', 'signup_prompt.js');
const VISIT_SRC = read('shared_static', 'visit_counter.js');

const flush = () => new Promise((r) => setTimeout(r, 0));

function addScript(window, src) {
  const s = window.document.createElement('script');
  s.textContent = src;
  window.document.head.appendChild(s);
}

async function makePage({ signedIn, url = 'https://example.test/m/x', storage } = {}) {
  const flag = signedIn ? 'true' : 'false';
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <button id="saveMeetingBtn" class="save-meeting-control" data-slug="x" data-signed-in="${flag}" data-saved="false"><span class="cassette-label"></span></button>
      <button id="saveMeetingIconBtn" class="save-meeting-control" data-slug="x" data-signed-in="${flag}" data-saved="false"></button>
    </body></html>`,
    { url, runScripts: 'dangerously' }
  );
  const { window } = dom;
  if (storage) {
    for (const [k, v] of Object.entries(storage)) window.sessionStorage.setItem(k, v);
  }
  window.Element.prototype.scrollIntoView = () => {};
  const events = [];
  const fetches = [];
  window.trackEvent = (name, params) => events.push({ name, params: params || {} });
  window.fetch = async (u) => { fetches.push(u); return { ok: true }; };
  window.rtrMarkSignInReturn = () => window.sessionStorage.setItem('rtrSignInReturnUrl', window.location.href);
  window.RTRClerk = { isSignedIn: () => !!signedIn, getUserId: () => null };
  for (const src of [DEEP_LINK_SRC, PROMPT_SRC, MEETING_PAGE_SRC]) addScript(window, src);
  await flush();
  return { window, events, fetches };
}

describe('signup_prompt.js', () => {
  test('signed-out save click opens the box and calls no API', async () => {
    const { window, events, fetches } = await makePage({ signedIn: false });
    window.document.getElementById('saveMeetingBtn').click();
    await flush();
    const dialog = window.document.querySelector('dialog.signup-prompt');
    assert.ok(dialog, 'dialog rendered');
    assert.ok(dialog.hasAttribute('open'), 'dialog open');
    assert.match(dialog.textContent, /free account/);
    assert.equal(fetches.length, 0);
    assert.deepEqual(
      events.filter((e) => e.name === 'signup_prompt_shown').map((e) => e.params.feature),
      ['save_meeting']
    );
  });

  test('"Not now" closes the box and records a dismiss', async () => {
    const { window, events } = await makePage({ signedIn: false });
    window.document.getElementById('saveMeetingIconBtn').click();
    window.document.querySelector('.signup-prompt-dismiss').click();
    const dialog = window.document.querySelector('dialog.signup-prompt');
    assert.ok(!dialog.hasAttribute('open'));
    assert.deepEqual(
      events.filter((e) => e.name === 'signup_prompt_click').map((e) => e.params.action),
      ['dismiss']
    );
  });

  test('signed-in save click still calls the save API', async () => {
    const { window, fetches } = await makePage({ signedIn: true });
    window.document.getElementById('saveMeetingBtn').click();
    await flush(); await flush();
    assert.deepEqual(fetches, ['/api/account/save-meeting']);
    assert.equal(window.document.querySelector('dialog.signup-prompt'), null);
  });

  test('a pending save from before sign-up runs once on return, same URL only', async () => {
    const pending = JSON.stringify({
      buttonId: 'saveMeetingBtn', feature: 'save_meeting',
      url: 'https://example.test/m/x', at: Date.now(),
    });
    const { window, events, fetches } = await makePage({ signedIn: true, storage: { rtrPendingSave: pending } });
    window.document.dispatchEvent(new window.CustomEvent('rtr-clerk-ready'));
    await flush(); await flush();
    assert.deepEqual(fetches, ['/api/account/save-meeting']);
    assert.equal(window.sessionStorage.getItem('rtrPendingSave'), null);
    assert.equal(events.filter((e) => e.name === 'signup_prompt_completed').length, 1);

    const other = await makePage({ signedIn: true, url: 'https://example.test/m/y', storage: { rtrPendingSave: pending } });
    other.window.document.dispatchEvent(new other.window.CustomEvent('rtr-clerk-ready'));
    await flush(); await flush();
    assert.deepEqual(other.fetches, []);
  });
});

describe('visit_counter.js', () => {
  function makeWindow() {
    const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
      url: 'https://example.test/', runScripts: 'dangerously',
    });
    const events = [];
    dom.window.trackEvent = (name, params) => events.push({ name, params });
    addScript(dom.window, VISIT_SRC);
    return { window: dom.window, events };
  }

  test('counts a new visit only after 30 minutes without a page load', () => {
    const { window, events } = makeWindow();
    assert.equal(events.length, 1);
    assert.equal(events[0].params.visits_30d, '1');
    const c = window.RTRVisitCounter;
    const t0 = Date.now();
    assert.equal(c.run(t0 + 10 * 60 * 1000).isNewVisit, false);
    assert.equal(c.run(t0 + 50 * 60 * 1000).isNewVisit, true);
    assert.equal(window.RTRVisits.count30d, 2);
    assert.equal(events[events.length - 1].params.visits_30d, '2');
  });

  test('visits older than 30 days drop out, and the bucket caps at 5+', () => {
    const { window } = makeWindow();
    const c = window.RTRVisitCounter;
    const day = 24 * 60 * 60 * 1000;
    const t0 = Date.now();
    assert.equal(c.run(t0 + 31 * day).count, 1);
    assert.equal(c.bucket(7), '5+');
  });
});
