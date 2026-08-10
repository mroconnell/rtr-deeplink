'use strict';

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const { makeWindow, setSegments, addSegmentEls, makeFakeVideo } = require('./helpers');

describe('getDeepLinkTime', () => {
  test('parses a real t param', () => {
    const window = makeWindow('http://localhost/m/x?t=630');
    assert.equal(window.getDeepLinkTime(), 630);
  });

  test('null when absent', () => {
    const window = makeWindow('http://localhost/m/x');
    assert.equal(window.getDeepLinkTime(), null);
  });
});

describe('buildYouTubePlayerVars', () => {
  test('folds a real t param in as start, rounded down', () => {
    const window = makeWindow('http://localhost/m/x?t=1168.7');
    const result = window.buildYouTubePlayerVars({ rel: 0, playsinline: 1 });
    assert.equal(result.start, 1168);
    // Real bug this guards against: a bare seekTo() call after onReady
    // silently landed at 0:00 instead of the requested moment (a known
    // YouTube IFrame API race) -- start avoids that by folding the
    // position into the initial player construction instead.
    assert.equal(result.rel, 0);
    assert.equal(result.playsinline, 1);
  });

  test('omits start entirely when there is no t param', () => {
    const window = makeWindow('http://localhost/m/x');
    const result = window.buildYouTubePlayerVars({ rel: 0, playsinline: 1 });
    assert.equal('start' in result, false);
  });

  test('does not mutate the base playerVars object passed in', () => {
    const window = makeWindow('http://localhost/m/x?t=42');
    const base = { rel: 0, playsinline: 1 };
    window.buildYouTubePlayerVars(base);
    assert.equal('start' in base, false);
  });
});

describe('getDeepLinkLine', () => {
  test('accepts a bare segment index and normalizes to seg-N', () => {
    const window = makeWindow('http://localhost/m/x?line=42');
    assert.equal(window.getDeepLinkLine(), 'seg-42');
  });

  test('accepts an already-prefixed seg-N form as-is', () => {
    const window = makeWindow('http://localhost/m/x?line=seg-42');
    assert.equal(window.getDeepLinkLine(), 'seg-42');
  });

  test('null for a garbage value', () => {
    const window = makeWindow('http://localhost/m/x?line=not-a-real-id');
    assert.equal(window.getDeepLinkLine(), null);
  });

  test('null when absent', () => {
    const window = makeWindow('http://localhost/m/x');
    assert.equal(window.getDeepLinkLine(), null);
  });
});

describe('getDeepLinkVersion', () => {
  test('reads the version param', () => {
    const window = makeWindow('http://localhost/m/x?version=7');
    assert.equal(window.getDeepLinkVersion(), '7');
  });

  test('null when absent', () => {
    const window = makeWindow('http://localhost/m/x');
    assert.equal(window.getDeepLinkVersion(), null);
  });
});

describe('updateUrlParams', () => {
  test('sets t and line into the URL', () => {
    const window = makeWindow('http://localhost/m/x');
    window.updateUrlParams({ t: 125.9, line: 'seg-3' });
    const params = new window.URLSearchParams(window.location.search);
    // Math.floor -- a deep link always seeks to a whole second, never a
    // fractional one, matching updateUrlParams's own String(Math.floor(t)).
    assert.equal(params.get('t'), '125');
    assert.equal(params.get('line'), 'seg-3');
  });

  test('automatically tags the current TranscriptVersion id when the page has one', () => {
    const window = makeWindow('http://localhost/m/x', { versionId: '9' });
    window.updateUrlParams({ t: 10 });
    const params = new window.URLSearchParams(window.location.search);
    assert.equal(params.get('version'), '9');
  });

  test('omits version entirely on a page with no version concept (the resolver page)', () => {
    const window = makeWindow('http://localhost/m/x');
    window.updateUrlParams({ t: 10 });
    const params = new window.URLSearchParams(window.location.search);
    assert.equal(params.has('version'), false);
  });
});

describe('findActiveSegment', () => {
  test('picks the last segment whose start is at-or-before currentTime', () => {
    const window = makeWindow('http://localhost/m/x');
    setSegments(window, [{ start: 0 }, { start: 60 }, { start: 130 }]);
    assert.equal(window.findActiveSegment(90), 'seg-1');
  });

  test('null before the first segment has started', () => {
    const window = makeWindow('http://localhost/m/x');
    setSegments(window, [{ start: 10 }, { start: 60 }]);
    assert.equal(window.findActiveSegment(5), null);
  });
});

describe('highlightSegment', () => {
  test('adds .playing to the target element and removes it from any previous one', () => {
    const window = makeWindow('http://localhost/m/x');
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    window.highlightSegment('seg-0', false);
    assert.ok(window.document.getElementById('seg-0').classList.contains('playing'));

    window.highlightSegment('seg-1', false);
    assert.ok(!window.document.getElementById('seg-0').classList.contains('playing'));
    assert.ok(window.document.getElementById('seg-1').classList.contains('playing'));
  });

  test('a missing element id is a no-op, not a crash', () => {
    const window = makeWindow('http://localhost/m/x');
    assert.doesNotThrow(() => window.highlightSegment('seg-404', false));
  });
});

// The 9 cases originally verified manually via a one-off Node vm.runInContext
// script (see BACKLOG_DONE.md's deep-link versioning entry) -- now a real,
// permanent regression suite instead of a one-time check.
describe('applyDeepLink: t always wins the actual seek', () => {
  test('t seeks regardless of a present, trustworthy line', () => {
    const window = makeWindow('http://localhost/m/x?t=90&line=seg-0');
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    setSegments(window, [{ start: 0 }, { start: 60 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 90);
  });

  test('t highlights the trustworthy line, not the time-proximity match', () => {
    const window = makeWindow('http://localhost/m/x?t=90&line=seg-0', { versionId: '5' });
    window.document.body.dataset.versionId = '5';
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    setSegments(window, [{ start: 0 }, { start: 60 }]);
    window.applyDeepLink(makeFakeVideo());
    assert.ok(window.document.getElementById('seg-0').classList.contains('playing'));
    assert.ok(!window.document.getElementById('seg-1').classList.contains('playing'));
  });
});

describe('applyDeepLink: version match/mismatch decides whether line is trusted', () => {
  test('matching version: line is trusted and highlighted even without t', () => {
    const window = makeWindow('http://localhost/m/x?line=seg-1&version=5', { versionId: '5' });
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    setSegments(window, [{ start: 0 }, { start: 60 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 60);
    assert.ok(window.document.getElementById('seg-1').classList.contains('playing'));
  });

  test('mismatched version + t present: falls back to time-proximity, not the stale line', () => {
    const window = makeWindow('http://localhost/m/x?t=65&line=seg-1&version=4', { versionId: '5' });
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 200 }]);
    setSegments(window, [{ start: 0 }, { start: 200 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 65);
    // seg-1 genuinely starts at 200 -- if the stale line had won, seg-1
    // would be highlighted instead of the time-proximity match (seg-0).
    assert.ok(window.document.getElementById('seg-0').classList.contains('playing'));
    assert.ok(!window.document.getElementById('seg-1').classList.contains('playing'));
  });

  test('mismatched version, no t at all: nothing reliable to seek to, video untouched', () => {
    const window = makeWindow('http://localhost/m/x?line=seg-1&version=4', { versionId: '5' });
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 200 }]);
    setSegments(window, [{ start: 0 }, { start: 200 }]);
    const video = makeFakeVideo(0);
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 0);
    assert.ok(!window.document.getElementById('seg-0').classList.contains('playing'));
    assert.ok(!window.document.getElementById('seg-1').classList.contains('playing'));
  });

  test('no version on either side (old pre-versioning link): line is trusted', () => {
    const window = makeWindow('http://localhost/m/x?line=seg-1');
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    setSegments(window, [{ start: 0 }, { start: 60 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 60);
    assert.ok(window.document.getElementById('seg-1').classList.contains('playing'));
  });

  test('the resolver page (no version concept at all): line is trusted even with a URL version param', () => {
    // The resolver's meeting.html never sets data-version-id, so
    // currentVersion is always null there regardless of what a shared/
    // copied URL's own version param says.
    const window = makeWindow('http://localhost/m/x?line=seg-1&version=99');
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 60 }]);
    setSegments(window, [{ start: 0 }, { start: 60 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 60);
  });
});

describe('applyDeepLink: line only, no t', () => {
  test('seeks to the trustworthy line\'s own start time', () => {
    const window = makeWindow('http://localhost/m/x?line=seg-1', { versionId: '5' });
    window.document.body.dataset.versionId = '5';
    addSegmentEls(window, [{ id: 'seg-0', start: 0 }, { id: 'seg-1', start: 42 }]);
    const video = makeFakeVideo();
    window.applyDeepLink(video);
    assert.equal(video.currentTime, 42);
  });
});
