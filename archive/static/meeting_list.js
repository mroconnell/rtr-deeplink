// "Save this search" -- saves the current /meetings query as-is (see
// archive/templates/meeting_list.html's saveSearchBtn data-* attributes,
// set from the same server-rendered filter state the page itself used).
//
// Real bug fixed 2026-08-11: the button used to always read those
// server-rendered data-* values, which only reflect the *last-applied*
// search -- so typing a new query/filter without hitting Search first
// silently saved the stale one instead, with no indication anything was
// wrong (see BACKLOG.md's original report). Fix: track the live values of
// the search box and every filter field against that same applied
// baseline, and disable Save the moment they diverge -- you can't save
// something you haven't actually searched for yet. `save_search()`
// (archive/db/crud.py) already dedupes identical repeat saves server-side,
// so a fresh click on an identical already-saved search just returns that
// row's own id again rather than erroring or duplicating.
//
// Save/Unsave toggle added 2026-08-13, per the user's own brainstormed
// design (BACKLOG.md): flips to "Unsave search" immediately after a
// successful save, reverts to "Save this search" the moment the box/
// filters change again (handled by refreshStaleState() below, since an
// edited-but-not-yet-searched query no longer represents whatever's
// saved). In-session only -- doesn't check the server for a pre-existing
// matching saved search on page load, matching the user's own stated
// scope ("immediately after a successful save"), not a fuller "is this
// exact search already saved" feature. Unsaving here reuses the exact
// same /api/account/unsave-search endpoint saved_items.js already calls
// from /account/saved.
//
// Visual cue on both actions reuses .pointed-to (style.css) -- the same
// "pop up and glow" tape-deck cue built for #transcribeToggle
// (wireSourceDisclaimerPointer() below), per the user's own explicit
// request to keep that exact aesthetic consistent across the site rather
// than invent a new one.
function wireSaveSearchButton() {
  const btn = document.getElementById('saveSearchBtn');
  const statusEl = document.getElementById('saveSearchStatus');
  if (!btn) return;

  const searchInput = document.querySelector('.meeting-search-form input[name="q"]');
  const jurisdictionInput = document.querySelector('.meeting-filters-form input[name="jurisdiction"]');
  const dateFromInput = document.querySelector('.meeting-filters-form input[name="date_from"]');
  const dateToInput = document.querySelector('.meeting-filters-form input[name="date_to"]');
  const hasTranscriptInput = document.querySelector('.meeting-filters-form input[name="has_transcript"]');
  const hasAgendaInput = document.querySelector('.meeting-filters-form input[name="has_agenda"]');
  const fuzzyInput = document.querySelector('.meeting-filters-form input[name="fuzzy"]');

  const applied = {
    q: btn.dataset.q || '',
    jurisdiction: btn.dataset.jurisdiction || '',
    dateFrom: btn.dataset.dateFrom || '',
    dateTo: btn.dataset.dateTo || '',
    hasAgenda: btn.dataset.hasAgenda === 'true',
    hasTranscript: btn.dataset.hasTranscript === 'true',
    fuzzy: btn.dataset.fuzzy === 'true',
  };

  const STALE_TITLE = 'Hit Search to apply your changes first';
  let savedItemId = null;

  const isStale = () =>
    (!!searchInput && searchInput.value !== applied.q) ||
    (!!jurisdictionInput && jurisdictionInput.value !== applied.jurisdiction) ||
    (!!dateFromInput && dateFromInput.value !== applied.dateFrom) ||
    (!!dateToInput && dateToInput.value !== applied.dateTo) ||
    (!!hasTranscriptInput && hasTranscriptInput.checked !== applied.hasTranscript) ||
    (!!hasAgendaInput && hasAgendaInput.checked !== applied.hasAgenda) ||
    (!!fuzzyInput && fuzzyInput.checked !== applied.fuzzy);

  const applySavedState = (saved) => {
    btn.dataset.saved = saved ? 'true' : 'false';
    const label = btn.querySelector('.cassette-label');
    if (label) label.textContent = saved ? 'Unsave search' : 'Save this search';
    if (!saved) savedItemId = null;
  };

  // Restarts the CSS animation on demand -- simply re-adding the class
  // is a no-op if it's already present (from a previous save/unsave in
  // the same session), since the animation already ran to completion.
  const popGlow = () => {
    btn.classList.remove('pointed-to');
    void btn.offsetWidth; // force reflow so the removal actually registers
    btn.classList.add('pointed-to');
  };

  const refreshStaleState = () => {
    const stale = isStale();
    btn.title = stale ? STALE_TITLE : '';
    if (stale) {
      // The in-progress edit no longer matches whatever's actually
      // saved -- stop claiming "Unsave search" for a search that isn't
      // this one anymore. Real correctness fix, not just cosmetic: a
      // stale "Unsave search" label would otherwise unsave the *old*
      // search using an id that no longer corresponds to what's on
      // screen.
      applySavedState(false);
      // A lingering "Saved ✓"/"Removed" from before this edit would
      // otherwise sit next to a now-reverted, disabled button, reading
      // as if that message still applies to the in-progress edit.
      if (statusEl) statusEl.textContent = '';
    }
    btn.disabled = stale;
  };

  [searchInput, jurisdictionInput, dateFromInput, dateToInput].forEach((el) => {
    if (el) el.addEventListener('input', refreshStaleState);
  });
  [hasTranscriptInput, hasAgendaInput, fuzzyInput].forEach((el) => {
    if (el) el.addEventListener('change', refreshStaleState);
  });
  refreshStaleState();

  btn.addEventListener('click', async () => {
    if (isStale()) return;
    const saved = btn.dataset.saved === 'true';

    btn.disabled = true;
    if (statusEl) statusEl.textContent = '';
    try {
      if (saved) {
        const res = await fetch('/api/account/unsave-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ saved_item_id: savedItemId }),
        });
        if (res.ok) {
          applySavedState(false);
          if (statusEl) statusEl.textContent = 'Removed';
          popGlow();
        } else {
          if (statusEl) statusEl.textContent = 'Something went wrong — please try again.';
        }
      } else {
        const searchParams = {};
        if (applied.q) searchParams.q = applied.q;
        if (applied.jurisdiction) searchParams.jurisdiction = applied.jurisdiction;
        if (applied.dateFrom) searchParams.date_from = applied.dateFrom;
        if (applied.dateTo) searchParams.date_to = applied.dateTo;
        if (applied.hasAgenda) searchParams.has_agenda = true;
        if (applied.hasTranscript) searchParams.has_transcript = true;
        if (applied.fuzzy) searchParams.fuzzy = true;

        const res = await fetch('/api/account/save-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ search_params: searchParams }),
        });
        if (res.ok) {
          const data = await res.json();
          savedItemId = (data && typeof data.id === 'number') ? data.id : null;
          applySavedState(true);
          if (statusEl) statusEl.textContent = 'Saved ✓';
          popGlow();
        } else {
          if (statusEl) statusEl.textContent = 'Something went wrong — please try again.';
        }
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = 'Something went wrong — please try again.';
    } finally {
      btn.disabled = isStale();
    }
  });
}

// Search tips icon: hover/keyboard-focus already reveal the panel via CSS
// alone (see .search-hint:hover/:focus-within in style.css) -- this only
// adds click-to-toggle, since touch devices have no hover state at all.
function wireSearchHelpIcon() {
  const icon = document.getElementById('searchHelpIcon');
  const panel = document.getElementById('searchHelpPanel');
  if (!icon || !panel) return;

  const close = () => {
    panel.classList.remove('is-open');
    icon.setAttribute('aria-expanded', 'false');
  };

  icon.addEventListener('click', (e) => {
    e.stopPropagation();
    const willOpen = !panel.classList.contains('is-open');
    panel.classList.toggle('is-open', willOpen);
    icon.setAttribute('aria-expanded', String(willOpen));
  });

  document.addEventListener('click', (e) => {
    if (!panel.contains(e.target) && e.target !== icon) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
}

document.addEventListener('DOMContentLoaded', () => {
  wireSaveSearchButton();
  wireSearchHelpIcon();
});
