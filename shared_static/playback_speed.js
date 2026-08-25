// Playback-speed control, shared by both player surfaces.
//
// Lives here rather than in app/static/player.js because
// archive/static/meeting_page.js is a trimmed port of that file's
// video-adapter logic (see its header) -- a speed control written twice
// is a speed control that silently diverges, and the Archive's permanent
// pages are the ones with real traffic. Both load this file from
// /shared-static/, same as deep_link.js.
//
// WHY AN OVERLAY, NOT A BUTTON IN THE PLAYER'S OWN CONTROL BAR: a native
// <video controls> bar is browser shadow DOM -- there is no supported way
// to add a control to it. Chrome hides playback speed behind an overflow
// menu, Safari behind a right-click, and the two iframe players behind
// their own vendor menus, which is exactly why nobody finds it. So this
// draws its own chip inside .video-wrapper (which is position:relative
// and overflow:hidden already -- see style.css), where it reads as part
// of the player rather than as another row of page furniture.
//
// ADAPTER CONTRACT (see createNativeAdapter and friends in both files):
//   adapter.speedRates   -> array of supported rates, or null when the
//                           player cannot change speed at all (Viebit).
//   adapter.playbackRate -> get/set, in the units of that array.
// An adapter that declares no speedRates gets no control rendered, which
// is why Viebit needs no special-casing here.

// Remembered across meetings on purpose: someone who watches council
// meetings at 2x wants 2x on the next one too, and re-picking per page is
// most of the friction this control exists to remove.
var PLAYBACK_RATE_STORAGE_KEY = 'rtr:playbackRate';

// The ladder offered when a player accepts arbitrary rates. 0.75 earns
// its place on a transcript product -- slowing down to catch a name or a
// mumbled motion is a real use of these pages, not just speeding up.
var PLAYBACK_RATE_LADDER = [0.75, 1, 1.25, 1.5, 2, 2.5, 3];

function formatPlaybackRate(rate) {
  // 1 -> "1x", 1.25 -> "1.25x". Trailing zeros look like a bug on a chip
  // this small.
  return String(Number(rate.toFixed(2))) + '×';
}

function readStoredPlaybackRate() {
  try {
    var raw = window.localStorage.getItem(PLAYBACK_RATE_STORAGE_KEY);
    if (!raw) return null;
    var parsed = parseFloat(raw);
    return isFinite(parsed) && parsed > 0 ? parsed : null;
  } catch (e) {
    // Private browsing / blocked storage. A speed control that throws on
    // load would take the whole player init down with it.
    return null;
  }
}

function storePlaybackRate(rate) {
  try {
    window.localStorage.setItem(PLAYBACK_RATE_STORAGE_KEY, String(rate));
  } catch (e) {
    /* not worth surfacing -- the rate still applies for this page view */
  }
}

// Picks the rate to open with: the remembered one when this player can
// actually do it, otherwise the closest rate it can (a reader who chose
// 3x on a Granicus page and then opens a YouTube-backed one gets 2x, the
// most of what they asked for that YouTube allows -- see the module
// comment in app/platforms/youtube.py's adapter for that hard cap).
function resolveInitialRate(rates, stored) {
  if (!stored) return 1;
  if (rates.indexOf(stored) !== -1) return stored;
  var best = 1;
  for (var i = 0; i < rates.length; i++) {
    if (rates[i] <= stored && rates[i] > best) best = rates[i];
  }
  return best;
}

function initPlaybackSpeed(adapter) {
  var rates = adapter && adapter.speedRates;
  if (!rates || !rates.length) return null;

  var wrapper = document.getElementById('videoWrapper');
  if (!wrapper) return null;
  // Both surfaces call wireSharedControls() once per page, but a
  // re-entrant call (or a future one) must not stack two chips.
  if (wrapper.querySelector('.speed-control')) return null;

  var control = document.createElement('div');
  control.className = 'speed-control';

  var chip = document.createElement('button');
  chip.type = 'button';
  chip.className = 'speed-chip';
  chip.setAttribute('aria-haspopup', 'true');
  chip.setAttribute('aria-expanded', 'false');
  chip.title = 'Playback speed';

  var menu = document.createElement('div');
  menu.className = 'speed-menu';
  menu.setAttribute('role', 'menu');
  menu.hidden = true;

  var currentRate = resolveInitialRate(rates, readStoredPlaybackRate());
  var items = [];

  function render() {
    chip.textContent = formatPlaybackRate(currentRate);
    // Only badge the chip when it differs from normal speed -- a
    // permanently-highlighted control stops carrying information.
    control.classList.toggle('is-active', currentRate !== 1);
    for (var i = 0; i < items.length; i++) {
      var on = items[i].rate === currentRate;
      items[i].el.setAttribute('aria-checked', on ? 'true' : 'false');
      items[i].el.classList.toggle('is-current', on);
    }
  }

  function applyRate(rate, { persist = true } = {}) {
    currentRate = rate;
    try {
      adapter.playbackRate = rate;
    } catch (e) {
      /* a player that rejects a rate it advertised: keep the UI honest
         by re-reading below rather than trusting the write */
    }
    if (persist) storePlaybackRate(rate);
    render();
  }

  function closeMenu() {
    menu.hidden = true;
    chip.setAttribute('aria-expanded', 'false');
  }

  function openMenu() {
    menu.hidden = false;
    chip.setAttribute('aria-expanded', 'true');
  }

  for (var i = 0; i < rates.length; i++) {
    (function (rate) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'speed-option';
      item.setAttribute('role', 'menuitemradio');
      item.textContent = formatPlaybackRate(rate);
      item.addEventListener('click', function () {
        applyRate(rate);
        closeMenu();
        chip.focus();
        window.trackEvent('video_speed_change', { rate: rate });
      });
      items.push({ rate: rate, el: item });
      menu.appendChild(item);
    })(rates[i]);
  }

  chip.addEventListener('click', function (evt) {
    evt.stopPropagation();
    if (menu.hidden) openMenu(); else closeMenu();
  });

  // Click-away and Escape, the two things a menu has to get right to not
  // feel broken. Bound on document, so the listener also catches clicks
  // landing on the video itself.
  document.addEventListener('click', function (evt) {
    if (!menu.hidden && !control.contains(evt.target)) closeMenu();
  });
  document.addEventListener('keydown', function (evt) {
    if (evt.key === 'Escape' && !menu.hidden) {
      closeMenu();
      chip.focus();
    }
  });

  control.appendChild(chip);
  control.appendChild(menu);
  wrapper.appendChild(control);

  // Apply the opening rate without re-persisting it: writing back on
  // every page load would turn a clamped rate (3x remembered, 2x
  // possible on this player) into the new remembered value, quietly
  // ratcheting the reader's preference down.
  applyRate(currentRate, { persist: false });

  return control;
}
