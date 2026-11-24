'use strict';

// Welcome bar for shared-moment arrivals (archive/static/welcome_bar.js).
// Clerk is faked: these tests pin our own logic (when the bar shows, which
// Clerk calls we make, what we save, which GA steps fire), not Clerk's.
// The fake's method names follow Clerk's documented custom email-code
// flow (signUp.create / prepareEmailAddressVerification /
// attemptEmailAddressVerification; signIn.create / prepareFirstFactor /
// attemptFirstFactor; Clerk.setActive). Synthetic: not yet exercised
// against the live Clerk instance.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const SRC = fs.readFileSync(path.join(__dirname, '..', 'archive', 'static', 'welcome_bar.js'), 'utf8');
const flush = () => new Promise((r) => setTimeout(r, 0));

const BAR = `
<section id="welcomeBar" hidden data-jurisdiction="Salisbury, NC" data-jurisdiction-display="Salisbury, NC">
  <span class="welcome-bar-time"></span>
  <form id="welcomeBarEmailForm"><input type="email" id="welcomeBarEmail"><button type="submit">Email me</button><button type="button" class="welcome-bar-dismiss">Not now</button></form>
  <form id="welcomeBarCodeForm" hidden><input id="welcomeBarCode"><button type="submit">Confirm</button></form>
  <p id="welcomeBarStatus"></p>
</section>`;

function makePage({ url = 'https://example.test/m/x?t=5025', referrer = 'https://chatgpt.com/', signedIn = false, existingAccount = false, done = false } = {}) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body>${BAR}</body></html>`, {
    url, referrer, runScripts: 'dangerously',
  });
  const { window } = dom;
  if (done) window.localStorage.setItem('rtrWelcomeBarDone', 'dismissed');
  const events = [];
  const calls = [];
  const fetches = [];
  window.trackEvent = (name, params) => events.push({ name, ...params });
  window.fetch = async (u, opts) => { fetches.push({ u, body: JSON.parse(opts.body) }); return { ok: true }; };
  window.RTRClerk = { isSignedIn: () => signedIn };
  const signUp = {
    create: async (p) => {
      calls.push(['signUp.create', p.emailAddress]);
      if (existingAccount) {
        const err = new Error('exists');
        err.errors = [{ code: 'form_identifier_exists' }];
        throw err;
      }
      return signUp;
    },
    prepareEmailAddressVerification: async (p) => { calls.push(['signUp.prepare', p.strategy]); },
    attemptEmailAddressVerification: async (p) => { calls.push(['signUp.attempt', p.code]); return { status: 'complete', createdSessionId: 'sess_up' }; },
  };
  const signIn = {
    supportedFirstFactors: [{ strategy: 'email_code', emailAddressId: 'idn_1' }],
    create: async (p) => { calls.push(['signIn.create', p.identifier]); return signIn; },
    prepareFirstFactor: async (p) => { calls.push(['signIn.prepare', p.strategy, p.emailAddressId]); },
    attemptFirstFactor: async (p) => { calls.push(['signIn.attempt', p.code]); return { status: 'complete', createdSessionId: 'sess_in' }; },
  };
  window.Clerk = {
    client: { signUp, signIn },
    setActive: async (p) => { calls.push(['setActive', p.session]); },
  };
  const s = window.document.createElement('script');
  s.textContent = SRC;
  window.document.head.appendChild(s);
  window.document.dispatchEvent(new window.CustomEvent('rtr-clerk-ready'));
  return { window, events, calls, fetches };
}

async function submitEmailThenCode(window) {
  const d = window.document;
  d.getElementById('welcomeBarEmail').value = 'reader@example.com';
  d.getElementById('welcomeBarEmailForm').dispatchEvent(new window.Event('submit', { cancelable: true }));
  await flush(); await flush(); await flush();
  d.getElementById('welcomeBarCode').value = '123456';
  d.getElementById('welcomeBarCodeForm').dispatchEvent(new window.Event('submit', { cancelable: true }));
  for (let i = 0; i < 6; i++) await flush();
}

describe('welcome_bar.js', () => {
  test('shows for a signed-out arrival on a t= link, with the time formatted', () => {
    const { window, events } = makePage();
    const bar = window.document.getElementById('welcomeBar');
    assert.equal(bar.hidden, false);
    assert.equal(bar.querySelector('.welcome-bar-time').textContent, '1:23:45');
    assert.deepEqual(events.map((e) => e.step), ['shown']);
  });

  test('stays hidden without t=, when signed in, when clicking around the site, or once done', () => {
    for (const opts of [
      { url: 'https://example.test/m/x' },
      { signedIn: true },
      { referrer: 'https://example.test/meetings' },
      { done: true },
    ]) {
      const { window, events } = makePage(opts);
      assert.equal(window.document.getElementById('welcomeBar').hidden, true, JSON.stringify(opts));
      assert.equal(events.length, 0);
    }
  });

  test('new email: sign-up code, session, then a saved search for the jurisdiction', async () => {
    const { window, events, calls, fetches } = makePage();
    await submitEmailThenCode(window);
    assert.deepEqual(calls, [
      ['signUp.create', 'reader@example.com'],
      ['signUp.prepare', 'email_code'],
      ['signUp.attempt', '123456'],
      ['setActive', 'sess_up'],
    ]);
    assert.deepEqual(fetches.map((f) => [f.u, f.body.search_params.jurisdiction]), [['/api/account/save-search', 'Salisbury, NC']]);
    assert.deepEqual(events.map((e) => e.step), ['shown', 'email_submitted', 'code_sent', 'verified', 'saved']);
    assert.equal(window.localStorage.getItem('rtrWelcomeBarDone'), 'verified');
    assert.match(window.document.getElementById('welcomeBarStatus').textContent, /all set/);
  });

  test('existing account: the same email gets a sign-in code instead', async () => {
    const { window, events, calls } = makePage({ existingAccount: true });
    await submitEmailThenCode(window);
    assert.deepEqual(calls, [
      ['signUp.create', 'reader@example.com'],
      ['signIn.create', 'reader@example.com'],
      ['signIn.prepare', 'email_code', 'idn_1'],
      ['signIn.attempt', '123456'],
      ['setActive', 'sess_in'],
    ]);
    assert.equal(events.find((e) => e.step === 'verified').path, 'sign_in');
  });

  test('"Not now" hides it for good and records a dismiss', () => {
    const { window, events } = makePage();
    window.document.querySelector('.welcome-bar-dismiss').click();
    assert.equal(window.document.getElementById('welcomeBar').hidden, true);
    assert.equal(window.localStorage.getItem('rtrWelcomeBarDone'), 'dismissed');
    assert.deepEqual(events.map((e) => e.step), ['shown', 'dismissed']);
  });
});
