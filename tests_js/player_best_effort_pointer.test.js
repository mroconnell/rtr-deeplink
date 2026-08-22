'use strict';

// The best-effort meeting page's "We think the video is here" line
// (app/static/player.js's renderBestEffortVideoPointer). WO-43, 2026-08-22.
//
// Before this fix, a best-effort result that HAD a real playable video still
// printed "We think the video is here: <video_url>" directly above the
// working player -- and that URL is always a machine artifact (an embed
// shell or a raw CDN media file), never a page a human would open. The fix
// drops the line for that case only; the two branches that carry real
// information (the tier-5 pointer, and the honest "[No video found]") are
// untouched, which is what most of this file pins.
//
// Every payload below is a REAL, live-captured /api/resolve response
// (confirmed 2026-08-22 against the live pages named in each case), trimmed
// to the fields this code path reads. Nothing here is invented.

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

// The real #videoSourceGuess / #videoLinkGuess pair from
// app/templates/meeting.html, in their real order: both sit in
// #videoColumn ABOVE #videoSection, which is exactly why a redundant line
// here pushes the working player down the page. #statusMessage and #meta
// are the two nodes player.js's init() touches before its own early
// return.
async function makePage() {
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>
      <div id="meta" class="meta"></div>
      <div id="statusMessage" class="status"></div>
      <div id="videoColumn" class="video-column">
        <div id="videoWarnings" class="warnings" hidden></div>
        <p id="videoSourceGuess" class="source-guess" hidden></p>
        <p id="videoLinkGuess" class="source-guess" hidden></p>
        <div id="videoSection" class="video-section" hidden></div>
      </div>
    </body></html>`,
    { url: 'https://example.test/meeting', runScripts: 'dangerously' }
  );
  const { window } = dom;
  window.trackEvent = () => {};
  // No data-source-url on <body>, so player.js's own bottom-of-file init()
  // call takes its "No meeting URL provided." early return instead of
  // firing a real /api/resolve fetch. Everything this file tests is a
  // top-level function declaration, which is defined either way.
  for (const src of [DEEP_LINK_SRC, PLAYER_SRC]) {
    const s = window.document.createElement('script');
    s.textContent = src;
    window.document.head.appendChild(s);
  }
  await new Promise((r) => setTimeout(r, 0));
  return window;
}

function readLines(window) {
  const g = window.document.getElementById('videoSourceGuess');
  const l = window.document.getElementById('videoLinkGuess');
  return {
    sourceGuessHidden: g.hidden,
    sourceGuessText: g.textContent,
    linkGuessHidden: l.hidden,
    linkGuessText: l.textContent,
    linkGuessHref: l.querySelector('a') ? l.querySelector('a').getAttribute('href') : null,
  };
}

describe('best-effort video pointer line', () => {
  // --- The three real shapes a playable best-effort video_url takes. All
  // three must now render NOTHING. Each is a distinct generic_fallback.py
  // video tier, which is the point: fixing only the Vimeo one would have
  // left the other two printing the same ugly line.

  test('tier 3 delegation to Vimeo (Sebastopol CA) drops the line', async () => {
    // Real: https://www.cityofsebastopol.gov/events/city-council-meeting-january-6-2026/
    // The reported symptom -- a bare player.vimeo.com embed URL, with the
    // real privacy hash riding along in the query string.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: 'https://player.vimeo.com/video/1152708575?h=db9859a2aa',
      video_format: 'vimeo',
      video_link: null,
      video_link_recognized: false,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, true);
    assert.equal(lines.sourceGuessText, '');
    assert.equal(lines.linkGuessHidden, true);
  });

  test('tier 1/2 YouTube embed (Tarrant County TX) drops the line', async () => {
    // Real: agendamgmtprod.tarrantcountytx.gov/Meetings/GetHTMLAgenda?...
    // YouTubeAssetFinder's video_url is youtube.com/embed/{id} -- an embed
    // shell, not the watch page, so this case was never "prettier" than
    // the Vimeo one it just looked less obviously wrong.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: 'https://www.youtube.com/embed/Awrb74sMXyM',
      video_format: 'youtube',
      video_link: null,
      video_link_recognized: false,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, true);
    assert.equal(lines.linkGuessHidden, true);
  });

  test('tier 4 raw media scan (Orange County FL) drops the line', async () => {
    // Real: https://netapps.ocfl.net/Mod/meetings/1/2069 -- a direct CDN
    // .mp4 found by media_scan. There is no human-facing variant of this
    // URL at all, which is the clearest argument against option (a).
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: 'https://otv.ocfl.net/otv/BCC2026/BCC071626/BCC071626AA.mp4',
      video_format: 'mp4',
      video_link: null,
      video_link_recognized: false,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, true);
    assert.equal(lines.linkGuessHidden, true);
  });

  // --- The two branches WO-43 must leave exactly as they were.

  test('tier 5 pointer (Birmingham MI) still renders, unchanged', async () => {
    // Real: https://www.bhamgov.org/about_birmingham/city_government/watch_a_city_meeting.php
    // -- nothing playable, a curated-host Vimeo showcase link instead.
    // This is the case where the line genuinely carries information the
    // page has nowhere else, and where the URL IS a page a human can open.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: null,
      video_format: null,
      video_link: 'https://vimeo.com/showcase/11598114/embed',
      video_link_recognized: true,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, true);
    assert.equal(lines.linkGuessHidden, false);
    assert.equal(
      lines.linkGuessText,
      'We think the video is here: https://vimeo.com/showcase/11598114/embed'
        + " — we recognize vimeo.com as a regular video host, but can't embed it here yet."
    );
    assert.equal(lines.linkGuessHref, 'https://vimeo.com/showcase/11598114/embed');
  });

  test('an unrecognized pointer host still gets the cautionary copy', async () => {
    // Synthetic, and deliberately so: no real page currently in hand
    // resolves to the LOOSE pointer tier (recognized=false) -- Birmingham
    // MI above covers the curated tier, and the loose tier's own real
    // motivating shape (Wayne County MI's "Video" anchor) is caught two
    // tiers earlier now that its href is a YouTube link. The payload
    // reuses the exact real field shape asserted above; only the host
    // differs, matching tests/test_generic_fallback.py's own
    // example-cdn.com placeholder for this same branch.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: null,
      video_format: null,
      video_link: 'https://player.example-vendor.com/embed/456',
      video_link_recognized: false,
    });
    const lines = readLines(window);
    assert.equal(lines.linkGuessHidden, false);
    assert.match(
      lines.linkGuessText,
      /but we don't recognize player\.example-vendor\.com as a supported video host/
    );
  });

  test('nothing found at all (Palm Beach County FL) still says so', async () => {
    // Real: discover.pbc.gov/countycommissioners/Pages/bcc-meeting-videos.aspx?videoid=...
    // -- a JS-rendered SharePoint shell the non-headless resolve honestly
    // finds nothing on. An empty page with no line at all would be worse
    // than this one, so it stays.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: null,
      video_format: null,
      video_link: null,
      video_link_recognized: false,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, false);
    assert.equal(lines.sourceGuessText, 'We think the video is here: [No video found]');
    assert.equal(lines.linkGuessHidden, true);
  });

  test('a playable video wins even if a pointer somehow rode along', async () => {
    // Defensive: every real producer sets at most one of these (see
    // media_scan.scan_page_for_video_evidence's own docstring, and
    // generic_fallback.py only computing video_link `if not video_url`),
    // so this combination has never been observed live. Pinned anyway
    // because the old condition (`data.video_url || !data.video_link`)
    // resolved it the other way round by accident rather than on purpose.
    const window = await makePage();
    window.renderBestEffortVideoPointer({
      best_effort: true,
      video_url: 'https://otv.ocfl.net/otv/BCC2026/BCC071626/BCC071626AA.mp4',
      video_format: 'mp4',
      video_link: 'https://vimeo.com/showcase/11598114/embed',
      video_link_recognized: true,
    });
    const lines = readLines(window);
    assert.equal(lines.sourceGuessHidden, true);
    assert.equal(lines.linkGuessHidden, true);
  });
});
