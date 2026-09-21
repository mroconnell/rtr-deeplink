// Click-to-load embeds for Full Context entries (/context, /context/new --
// _context_entry.html renders both). Privacy posture: no third party
// (YouTube, Instagram, TikTok) is contacted until the reader actually
// clicks "Show the post here" -- the server only ever renders a hidden
// button plus a few parser-derived data-* attributes (see
// _context_entry.html's own comment on why only those values reach the
// DOM). Everything below builds elements with createElement/setAttribute
// only, never innerHTML/string-concatenated HTML, since data-embed-url
// ultimately comes from an editor-typed social post URL.
//
// Same "plain top-level function declarations, no module system" shape as
// shared_static/deep_link.js -- see that file's own header comment. Kept
// pure/named for testing the same way: tests_js/ loads this file as a real
// <script> element so its declarations land in the window's script scope,
// same as a real page load.

const YOUTUBE_ID_RE = /^[A-Za-z0-9_-]{6,20}$/;
const TIKTOK_ID_RE = /^[0-9]+$/;

function isValidYouTubeId(id) {
  return typeof id === 'string' && YOUTUBE_ID_RE.test(id);
}

function isValidInstagramUrl(url) {
  return typeof url === 'string' && url.startsWith('https://www.instagram.com/');
}

function isValidTikTokId(id) {
  return typeof id === 'string' && TIKTOK_ID_RE.test(id);
}

function isValidTikTokUrl(url) {
  return typeof url === 'string' && url.startsWith('https://www.tiktok.com/');
}

// The fallback "open it elsewhere" link's target -- data-embed-url for
// instagram/tiktok, or (YouTube never sets data-embed-url, only
// data-embed-id) the plain watch URL built from the id.
function fallbackUrlFor(container) {
  const kind = container.dataset.embedKind;
  if (kind === 'youtube') {
    const id = container.dataset.embedId;
    return isValidYouTubeId(id) ? `https://www.youtube.com/watch?v=${id}` : null;
  }
  return container.dataset.embedUrl || null;
}

function buildYouTubeEmbed(id) {
  const wrap = document.createElement('div');
  wrap.className = 'context-embed-frame';
  const iframe = document.createElement('iframe');
  iframe.setAttribute('src', `https://www.youtube-nocookie.com/embed/${id}`);
  iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
  iframe.setAttribute('allowfullscreen', '');
  iframe.setAttribute('loading', 'lazy');
  iframe.setAttribute('title', 'YouTube video');
  iframe.setAttribute(
    'allow',
    'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share'
  );
  wrap.appendChild(iframe);
  return wrap;
}

// Instagram's embed.js only ever needs loading once per page -- a second
// click on a different Instagram entry (or a second entry on the same
// page) reuses the already-loaded window.instgrm and just asks it to
// (re)scan the page for new .instagram-media blockquotes.
let instagramScriptRequested = false;

function loadInstagramScript() {
  if (instagramScriptRequested) return;
  instagramScriptRequested = true;
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://www.instagram.com/embed.js';
  document.body.appendChild(script);
}

function buildInstagramEmbed(url) {
  const blockquote = document.createElement('blockquote');
  blockquote.className = 'instagram-media';
  blockquote.setAttribute('data-instgrm-permalink', url);
  blockquote.setAttribute('data-instgrm-version', '14');
  // Plain fallback link, present even before (or if) Instagram's script
  // ever processes this blockquote -- the same "must stand on its own"
  // posture as the rest of this markup.
  const link = document.createElement('a');
  link.href = url;
  link.textContent = 'View this post on Instagram';
  blockquote.appendChild(link);
  return blockquote;
}

function buildTikTokEmbed(id, url) {
  const blockquote = document.createElement('blockquote');
  blockquote.className = 'tiktok-embed';
  blockquote.setAttribute('cite', url);
  blockquote.setAttribute('data-video-id', id);
  // TikTok's embed.js fills this in; an empty <section> is the documented
  // placeholder shape its script looks for.
  blockquote.appendChild(document.createElement('section'));
  return blockquote;
}

// TikTok's embed.js only scans the page for new blockquotes at the moment
// it *loads* -- unlike Instagram's, calling some already-loaded global
// again does nothing for a blockquote added after the first load. So a
// fresh <script> is appended on every click, exactly as the WO-943 spec
// requires, even though this means re-fetching the same script file for a
// second TikTok entry on the same page.
function loadTikTokScript() {
  const script = document.createElement('script');
  script.async = true;
  script.src = 'https://www.tiktok.com/embed.js';
  document.body.appendChild(script);
}

function showEmbedFailure(container) {
  container.replaceChildren();
  const text = document.createElement('p');
  text.className = 'context-embed-fallback';
  text.textContent = "Couldn't load it here.";
  const url = fallbackUrlFor(container);
  if (url) {
    const link = document.createElement('a');
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener nofollow ugc';
    link.textContent = 'Open the original post';
    text.appendChild(document.createTextNode(' '));
    text.appendChild(link);
  }
  container.appendChild(text);
}

function loadEmbed(container) {
  const kind = container.dataset.embedKind;

  if (kind === 'youtube') {
    const id = container.dataset.embedId;
    if (!isValidYouTubeId(id)) {
      showEmbedFailure(container);
      return;
    }
    container.appendChild(buildYouTubeEmbed(id));
    // The iframe is built synchronously above, so there's nothing to
    // watch for here -- the 8s failure check below only matters for the
    // blockquote-based embeds, whose own script decides whether an
    // iframe ever shows up.
    return;
  }

  if (kind === 'instagram') {
    const url = container.dataset.embedUrl;
    if (!isValidInstagramUrl(url)) {
      showEmbedFailure(container);
      return;
    }
    container.appendChild(buildInstagramEmbed(url));
    if (window.instgrm && window.instgrm.Embeds) {
      window.instgrm.Embeds.process();
    } else {
      loadInstagramScript();
    }
  } else if (kind === 'tiktok') {
    const id = container.dataset.embedId;
    const url = container.dataset.embedUrl;
    if (!isValidTikTokId(id) || !isValidTikTokUrl(url)) {
      showEmbedFailure(container);
      return;
    }
    container.appendChild(buildTikTokEmbed(id, url));
    loadTikTokScript();
  } else {
    showEmbedFailure(container);
    return;
  }

  // ~8s grace period for the third-party script to load and turn the
  // blockquote into a real iframe. If nothing shows up (script blocked,
  // slow network, the post itself deleted), degrade to a plain link
  // rather than leaving an inert blockquote on the page.
  window.setTimeout(() => {
    if (!container.querySelector('iframe')) {
      showEmbedFailure(container);
    }
  }, 8000);
}

function wireContextEmbeds() {
  document.querySelectorAll('.context-embed-load').forEach((btn) => {
    btn.hidden = false;
    btn.addEventListener('click', () => {
      const container = btn.closest('.context-embed');
      btn.remove();
      if (container) loadEmbed(container);
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  wireContextEmbeds();
});
