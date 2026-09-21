'use strict';

// Regression coverage for the pure validation/URL helpers in
// archive/static/context_embeds.js -- the ones WO-943's own spec calls
// out to keep small and named specifically so they're unit-testable. The
// DOM-building side (createElement calls, the 8s failure timer, the
// third-party script injection) is exercised in-browser instead (see the
// WO-943 report), same division of labor tests_js/deep_link.test.js and
// meeting_page_events.test.js already use for their own DOM-heavy files.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const CONTEXT_EMBEDS_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'archive', 'static', 'context_embeds.js'),
  'utf8'
);

// Loaded as a real <script> element, same reasoning as tests_js/helpers.js's
// makeWindow() -- top-level `function`/`let` declarations land in the
// window's actual script scope, not a nested eval() scope.
function makeWindow() {
  const dom = new JSDOM('<!DOCTYPE html><html><head></head><body></body></html>', {
    url: 'http://localhost/context',
    runScripts: 'dangerously',
  });
  const { window } = dom;
  const scriptEl = window.document.createElement('script');
  scriptEl.textContent = CONTEXT_EMBEDS_SRC;
  window.document.head.appendChild(scriptEl);
  return window;
}

describe('isValidYouTubeId', () => {
  test('accepts a real-shaped 11-character id', () => {
    const window = makeWindow();
    assert.equal(window.isValidYouTubeId('dQw4w9WgXcQ'), true);
  });

  test('rejects something too short to be a real id', () => {
    const window = makeWindow();
    assert.equal(window.isValidYouTubeId('abc'), false);
  });

  test('rejects a value carrying markup/script characters', () => {
    const window = makeWindow();
    assert.equal(window.isValidYouTubeId('<script>x'), false);
  });
});

describe('isValidInstagramUrl', () => {
  test('accepts a real instagram.com permalink', () => {
    const window = makeWindow();
    assert.equal(window.isValidInstagramUrl('https://www.instagram.com/p/abc123/'), true);
  });

  test('rejects a lookalike host', () => {
    const window = makeWindow();
    assert.equal(window.isValidInstagramUrl('https://www.instagram.com.evil.example/p/abc123/'), false);
  });

  test('rejects plain http', () => {
    const window = makeWindow();
    assert.equal(window.isValidInstagramUrl('http://www.instagram.com/p/abc123/'), false);
  });
});

describe('isValidTikTokId / isValidTikTokUrl', () => {
  test('accepts a real numeric video id', () => {
    const window = makeWindow();
    assert.equal(window.isValidTikTokId('7123456789012345678'), true);
  });

  test('rejects a non-numeric id', () => {
    const window = makeWindow();
    assert.equal(window.isValidTikTokId('abc123'), false);
  });

  test('accepts a real tiktok.com URL', () => {
    const window = makeWindow();
    assert.equal(window.isValidTikTokUrl('https://www.tiktok.com/@someone/video/7123456789012345678'), true);
  });

  test('rejects a lookalike host', () => {
    const window = makeWindow();
    assert.equal(window.isValidTikTokUrl('https://tiktok.com.evil.example/@someone/video/1'), false);
  });
});

describe('fallbackUrlFor', () => {
  test('YouTube: builds the plain watch URL from a valid id', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    container.dataset.embedKind = 'youtube';
    container.dataset.embedId = 'dQw4w9WgXcQ';
    assert.equal(window.fallbackUrlFor(container), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');
  });

  test('YouTube: null when the id is invalid (never builds a broken link)', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    container.dataset.embedKind = 'youtube';
    container.dataset.embedId = '<bad>';
    assert.equal(window.fallbackUrlFor(container), null);
  });

  test('Instagram/TikTok: reads data-embed-url as-is', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    container.dataset.embedKind = 'instagram';
    container.dataset.embedUrl = 'https://www.instagram.com/p/abc123/';
    assert.equal(window.fallbackUrlFor(container), 'https://www.instagram.com/p/abc123/');
  });

  test('null when there is no data-embed-url at all', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    container.dataset.embedKind = 'tiktok';
    assert.equal(window.fallbackUrlFor(container), null);
  });
});

describe('isAutoloadEmbed', () => {
  test('true when data-embed-autoload is present (boolean attribute)', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    container.setAttribute('data-embed-autoload', '');
    assert.equal(window.isAutoloadEmbed(container), true);
  });

  test('false when data-embed-autoload is absent -- the click-to-load default', () => {
    const window = makeWindow();
    const container = window.document.createElement('div');
    assert.equal(window.isAutoloadEmbed(container), false);
  });

  test('false for a null/undefined container', () => {
    const window = makeWindow();
    assert.equal(window.isAutoloadEmbed(null), false);
    assert.equal(window.isAutoloadEmbed(undefined), false);
  });
});
