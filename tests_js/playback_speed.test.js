'use strict';

// shared_static/playback_speed.js -- the playback-speed chip shared by
// app/static/player.js and archive/static/meeting_page.js.
//
// The rate ceilings pinned here are real, measured against live players on
// 2026-08-24, not invented: a native <video> accepted every rate from 1.5
// to 16, while YouTube's own getAvailablePlaybackRates() returned
// [0.25,0.5,0.75,1,1.25,1.5,1.75,2] and setPlaybackRate() ignores anything
// off that list. That asymmetry is the whole reason the control is driven
// by a per-adapter `speedRates` array instead of one hardcoded ladder, so
// it is what these tests mostly cover.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const SPEED_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'shared_static', 'playback_speed.js'),
  'utf8'
);

// Loaded as a real <script> element rather than eval()'d, for the same
// reason helpers.js does it: separate classic <script> tags share one
// top-level scope, and eval() does not reproduce that.
function makeWindow() {
  const dom = new JSDOM(
    '<!DOCTYPE html><html><body><div id="videoWrapper"></div></body></html>',
    { url: 'https://redtaperecordings.com/m/example', runScripts: 'dangerously' }
  );
  const { window } = dom;
  // Always defined on the real pages by base.html (a no-op when analytics
  // is off), so the control is entitled to call it unguarded.
  window.trackEvent = () => {};
  const scriptEl = window.document.createElement('script');
  scriptEl.textContent = SPEED_SRC;
  window.document.head.appendChild(scriptEl);
  return window;
}

// A stand-in for the real adapters' speed half. `rates: null` is the
// Viebit shape (no cross-frame API, so speed genuinely cannot be set).
function fakeAdapter(rates) {
  return {
    speedRates: rates,
    _rate: 1,
    get playbackRate() { return this._rate; },
    set playbackRate(r) { this._rate = r; },
  };
}

const NATIVE_RATES = [0.75, 1, 1.25, 1.5, 2, 2.5, 3];
// The real intersection of the shared ladder with YouTube's own list.
const YOUTUBE_RATES = [0.75, 1, 1.25, 1.5, 2];

describe('playback speed control', () => {
  test('renders a chip and one option per supported rate', () => {
    const window = makeWindow();
    const adapter = fakeAdapter(NATIVE_RATES);
    window.initPlaybackSpeed(adapter);

    const options = [...window.document.querySelectorAll('.speed-option')];
    assert.deepEqual(options.map((o) => o.textContent), ['0.75×', '1×', '1.25×', '1.5×', '2×', '2.5×', '3×']);
    assert.equal(window.document.querySelector('.speed-chip').textContent, '1×');
  });

  test('the menu starts closed', () => {
    // Regression: .speed-menu carries an author `display: flex`, which beats
    // the UA stylesheet's [hidden] { display: none }. Without the explicit
    // .speed-menu[hidden] rule in playback_speed.css the menu renders open on
    // every page load -- caught in a browser, invisible to a code read.
    const window = makeWindow();
    window.initPlaybackSpeed(fakeAdapter(NATIVE_RATES));
    assert.equal(window.document.querySelector('.speed-menu').hidden, true);
    assert.equal(window.document.querySelector('.speed-chip').getAttribute('aria-expanded'), 'false');
  });

  test('choosing a rate applies it to the adapter and closes the menu', () => {
    const window = makeWindow();
    const adapter = fakeAdapter(NATIVE_RATES);
    window.initPlaybackSpeed(adapter);

    window.document.querySelector('.speed-chip').click();
    assert.equal(window.document.querySelector('.speed-menu').hidden, false);

    const threeX = [...window.document.querySelectorAll('.speed-option')].find((o) => o.textContent === '3×');
    threeX.click();

    assert.equal(adapter.playbackRate, 3);
    assert.equal(window.document.querySelector('.speed-chip').textContent, '3×');
    assert.equal(window.document.querySelector('.speed-menu').hidden, true);
    // Badged only while off normal speed, so the highlight keeps meaning something.
    assert.equal(window.document.querySelector('.speed-control').classList.contains('is-active'), true);
  });

  test('an adapter that declares no speed support renders no control at all', () => {
    // Viebit. A visible-but-dead chip would read as a bug, the same
    // reasoning that hides its share button rather than disabling it.
    const window = makeWindow();
    assert.equal(window.initPlaybackSpeed(fakeAdapter(null)), null);
    assert.equal(window.document.querySelector('.speed-control'), null);
  });

  test('a remembered rate is restored on the next meeting', () => {
    const window = makeWindow();
    window.localStorage.setItem('rtr:playbackRate', '2');
    const adapter = fakeAdapter(NATIVE_RATES);
    window.initPlaybackSpeed(adapter);

    assert.equal(adapter.playbackRate, 2);
    assert.equal(window.document.querySelector('.speed-chip').textContent, '2×');
  });

  test('a remembered rate the player cannot reach clamps down to its ceiling', () => {
    // 3x remembered from a Granicus page, then a YouTube-backed one opens:
    // 2x is the most of what was asked for that YouTube allows.
    const window = makeWindow();
    window.localStorage.setItem('rtr:playbackRate', '3');
    const adapter = fakeAdapter(YOUTUBE_RATES);
    window.initPlaybackSpeed(adapter);

    assert.equal(adapter.playbackRate, 2);
  });

  test('clamping does not overwrite the remembered rate', () => {
    // The ratchet guard: persisting the clamped value here would quietly
    // downgrade a 3x preference to 2x for every later meeting, just because
    // one YouTube page happened to be opened in between.
    const window = makeWindow();
    window.localStorage.setItem('rtr:playbackRate', '3');
    window.initPlaybackSpeed(fakeAdapter(YOUTUBE_RATES));

    assert.equal(window.localStorage.getItem('rtr:playbackRate'), '3');
  });

  test('an explicit choice is remembered', () => {
    const window = makeWindow();
    window.initPlaybackSpeed(fakeAdapter(NATIVE_RATES));
    [...window.document.querySelectorAll('.speed-option')].find((o) => o.textContent === '1.5×').click();

    assert.equal(window.localStorage.getItem('rtr:playbackRate'), '1.5');
  });

  test('unreadable storage does not take the player down with it', () => {
    // Private browsing / blocked storage throws on access; the speed
    // control failing there must not stop the rest of init.
    const window = makeWindow();
    Object.defineProperty(window, 'localStorage', {
      get() { throw new Error('SecurityError'); },
    });
    const adapter = fakeAdapter(NATIVE_RATES);
    assert.doesNotThrow(() => window.initPlaybackSpeed(adapter));
    assert.equal(adapter.playbackRate, 1);
  });

  test('calling twice does not stack two chips', () => {
    const window = makeWindow();
    const adapter = fakeAdapter(NATIVE_RATES);
    window.initPlaybackSpeed(adapter);
    window.initPlaybackSpeed(adapter);
    assert.equal(window.document.querySelectorAll('.speed-control').length, 1);
  });
});
