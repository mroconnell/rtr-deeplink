'use strict';

// WO-136: when a YouTube channel has disabled embedding outside YouTube,
// the resolver's ephemeral page (app/static/player.js) renders a "Watch
// on YouTube" link in place of the dead iframe -- both proactively
// (initVideo(), when the embed-disabled marker is already present in
// video_warnings from the resolve itself) and reactively
// (initYouTubeVideo()'s onError, when a channel disables embedding
// sometime after WO-135's own check last ran). Both call the same
// renderYouTubeEmbedFallback(), which is what this file pins: the two
// paths must render identically.

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const DEEP_LINK_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'shared_static', 'deep_link.js'),
  'utf8'
);
const PLAYER_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'player.js'),
  'utf8'
);
const MARKERS_SRC = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'platforms', 'youtube.py'),
  'utf8'
);

// Same real embed URL used by the live-verified sample in this WO's PR
// description (Peachtree Corners GA council meeting,
// youtube.com/embed/XtXhnDamWnc) -- a real 11-character video id, not an
// invented one.
const EMBED_URL = 'https://www.youtube.com/embed/XtXhnDamWnc';

// Read out of the Python source itself (WO-135's YOUTUBE_EMBED_DISABLED_
// MARKER, app/platforms/youtube.py), not retyped here, so this file can't
// silently drift from the real marker the way a hand-copied second
// definition could -- see that constant's own header comment on why a
// divergent copy (it's independently re-declared a third time, in
// archive/db/crud.py, per this repo's own convention) is a real, silent
// failure mode.
const PY_MARKER_MATCH = /YOUTUBE_EMBED_DISABLED_MARKER = \(\s*"([^"]+)"\s*\)/.exec(
  MARKERS_SRC
);
if (!PY_MARKER_MATCH) {
  throw new Error(
    'could not find YOUTUBE_EMBED_DISABLED_MARKER in app/platforms/youtube.py'
  );
}
const MARKER = PY_MARKER_MATCH[1];

// The real elements this code touches, matching app/templates/meeting.html:
// #meetingVideo / #bigPlayButton / #youtubePlayerContainer inside
// #videoSection, #videoWrapper's own container, plus #videoError which
// initYouTubeVideo's other (unrelated) failure branches still use.
async function makePage(url) {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <div id="meta" class="meta"></div>
      <div id="statusMessage" class="status"></div>
      <div id="videoColumn" class="video-column">
        <div id="videoSection" class="video-section" hidden>
          <div id="videoWrapper" class="video-wrapper">
            <video id="meetingVideo" controls playsinline preload="auto"></video>
            <div id="youtubePlayerContainer" class="youtube-player-container" hidden></div>
            <button id="bigPlayButton" class="big-play-button" hidden></button>
          </div>
          <div id="videoError" class="error" hidden></div>
        </div>
      </div>
    </body></html>`,
    { url, runScripts: 'dangerously' }
  );
  const { window } = dom;
  window.trackEvent = () => {};
  for (const src of [DEEP_LINK_SRC, PLAYER_SRC]) {
    const s = window.document.createElement('script');
    s.textContent = src;
    window.document.head.appendChild(s);
  }
  // player.js's EMBEDDING_DISABLED_VIDEO_WARNING is a top-level `const` --
  // per spec that never becomes a `window` property (same note
  // tests_js/helpers.js makes about deep_link.js's `segments`), so a
  // later appended <script> (which shares the same top-level lexical
  // scope real sequential classic <script> tags always share) is the only
  // way to read it back out for the sync-check test below.
  const bridge = window.document.createElement('script');
  bridge.textContent = 'window.__embeddingDisabledMarker__ = EMBEDDING_DISABLED_VIDEO_WARNING;';
  window.document.head.appendChild(bridge);
  await new Promise((r) => setTimeout(r, 0));
  return window;
}

describe('EMBEDDING_DISABLED_VIDEO_WARNING stays in sync with its Python source', () => {
  test('player.js\'s constant is byte-for-byte the same string app/platforms/youtube.py defines', async () => {
    const window = await makePage('https://example.test/meeting');
    assert.equal(window.__embeddingDisabledMarker__, MARKER);
  });
});

describe('renderYouTubeEmbedFallback', () => {
  test('shows the note and a working watch link, honoring a deep-linked t=', async () => {
    const window = await makePage('https://example.test/meeting?t=754');
    window.renderYouTubeEmbedFallback(EMBED_URL);

    const container = window.document.getElementById('youtubePlayerContainer');
    assert.equal(container.hidden, false);
    assert.match(container.textContent, /disabled embedding outside YouTube/);

    const link = container.querySelector('a.watch-on-youtube-link');
    assert.ok(link, 'expected a "Watch on YouTube" link');
    assert.equal(link.getAttribute('href'), 'https://www.youtube.com/watch?v=XtXhnDamWnc&t=754s');
    assert.equal(link.getAttribute('target'), '_blank');
    assert.equal(link.getAttribute('rel'), 'noopener noreferrer');

    // The dead native <video>/big-play-button never show through underneath.
    assert.equal(window.document.getElementById('meetingVideo').hidden, true);
    assert.equal(window.document.getElementById('bigPlayButton').hidden, true);
  });

  test('omits &t= entirely with no deep-link time', async () => {
    const window = await makePage('https://example.test/meeting');
    window.renderYouTubeEmbedFallback(EMBED_URL);
    const link = window.document.querySelector('a.watch-on-youtube-link');
    assert.equal(link.getAttribute('href'), 'https://www.youtube.com/watch?v=XtXhnDamWnc');
  });

  test('still shows the note with no link when no video id is extractable', async () => {
    const window = await makePage('https://example.test/meeting');
    window.renderYouTubeEmbedFallback('https://www.youtube.com/embed/');
    const container = window.document.getElementById('youtubePlayerContainer');
    assert.match(container.textContent, /disabled embedding outside YouTube/);
    assert.equal(container.querySelector('a.watch-on-youtube-link'), null);
  });

  // Real bug, caught only by a live browser check per CLAUDE.md's own
  // rule (not by the resolve JSON, and not by the tests above, since they
  // never replaced #youtubePlayerContainer with YT.Player's real output
  // first): live-verified 2026-09-09 against an actual embedding-disabled
  // video (youtube.com/watch?v=XtXhnDamWnc) that by the time onError
  // fires, YT.Player has already swapped the original
  // <div id="youtubePlayerContainer"> for an <iframe> of the same id --
  // and writing fallback content into an <iframe> element only produces
  // invisible "browser doesn't support iframes" fallback nodes, so
  // YouTube's own in-frame "Video unavailable... disabled by the video
  // owner" placard kept rendering on top, unchanged, even though
  // querying the DOM found the note/link "present".
  test('swaps a live iframe (YT.Player\'s real post-onReady shape) for a real element instead of writing into it', async () => {
    const window = await makePage('https://example.test/meeting');
    const original = window.document.getElementById('youtubePlayerContainer');
    const iframe = window.document.createElement('iframe');
    iframe.id = 'youtubePlayerContainer';
    iframe.className = original.className;
    original.replaceWith(iframe);
    assert.equal(window.document.getElementById('youtubePlayerContainer').tagName, 'IFRAME');

    window.renderYouTubeEmbedFallback(EMBED_URL);

    const replaced = window.document.getElementById('youtubePlayerContainer');
    assert.equal(replaced.tagName, 'DIV');
    assert.equal(replaced.className, 'youtube-player-container');
    assert.match(replaced.textContent, /disabled embedding outside YouTube/);
    const link = replaced.querySelector('a.watch-on-youtube-link');
    assert.ok(link, 'expected a real, visible "Watch on YouTube" link, not fallback content inside a dead iframe');
  });

  // Real bug found alongside the one above: handleResolveResponse()
  // decides noTranscriptLive vs. noTranscriptManual from data.video_warnings
  // *before* initVideo() ever runs, using only the proactive marker --
  // which a reactive onError (no marker present yet) has no way to have
  // anticipated. Left uncorrected, a real onError would leave a frozen
  // "0:00" and a "Copy link to this moment" button with no click handler
  // at all (both only ever wired from a real adapter's onReady).
  test('flips a frozen live no-transcript block to the manual-entry variant', async () => {
    const window = await makePage('https://example.test/meeting');
    const html = `
      <div id="transcriptMissing" class="transcript-section">
        <div id="noTranscriptLive" class="no-transcript-timestamp"></div>
        <div id="noTranscriptManual" class="no-transcript-timestamp" hidden></div>
      </div>`;
    window.document.body.insertAdjacentHTML('beforeend', html);
    assert.equal(window.document.getElementById('noTranscriptLive').hidden, false);
    assert.equal(window.document.getElementById('noTranscriptManual').hidden, true);

    window.renderYouTubeEmbedFallback(EMBED_URL);

    assert.equal(window.document.getElementById('noTranscriptLive').hidden, true);
    assert.equal(window.document.getElementById('noTranscriptManual').hidden, false);
  });
});

describe('initVideo proactive marker check', () => {
  test('a marker already in video_warnings skips the iframe and renders the fallback directly', async () => {
    const window = await makePage('https://example.test/meeting?t=90');
    window.initVideo(EMBED_URL, 'youtube', [MARKER]);

    const container = window.document.getElementById('youtubePlayerContainer');
    assert.equal(window.document.getElementById('videoSection').hidden, false);
    assert.match(container.textContent, /disabled embedding outside YouTube/);
    const link = container.querySelector('a.watch-on-youtube-link');
    assert.equal(link.getAttribute('href'), 'https://www.youtube.com/watch?v=XtXhnDamWnc&t=90s');
  });

  test('an ordinary YouTube page (no marker) is left for initYouTubeVideo, not the fallback', async () => {
    const window = await makePage('https://example.test/meeting');
    // loadYouTubeIframeApi() would otherwise try to inject a real
    // <script src="https://www.youtube.com/iframe_api">; stub window.YT
    // so initYouTubeVideo() resolves immediately without a real network
    // call, same shape as this file's own loadYouTubeIframeApi() early
    // return when window.YT.Player already exists.
    window.YT = { Player: function () {}, PlayerState: { PLAYING: 1 } };
    window.initVideo(EMBED_URL, 'youtube', []);
    const container = window.document.getElementById('youtubePlayerContainer');
    assert.equal(container.hidden, false);
    // No fallback markup was ever written -- initYouTubeVideo() only
    // shows the container for YT.Player to fill, it doesn't touch
    // innerHTML itself.
    assert.equal(container.querySelector('a.watch-on-youtube-link'), null);
    assert.equal(container.querySelector('p.youtube-embed-disabled-note'), null);
  });
});
