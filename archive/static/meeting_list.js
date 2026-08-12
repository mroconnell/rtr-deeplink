// "Save this search" -- saves the current /meetings query as-is (see
// archive/templates/meeting_list.html's saveSearchBtn data-* attributes,
// set from the same server-rendered filter state the page itself used).
// No unsave here -- unsaving a search happens from /account/saved (see
// saved_items.js), where the saved-search list actually lives.
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
// so no separate "already saved" guard is needed here.
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

  const isStale = () =>
    (!!searchInput && searchInput.value !== applied.q) ||
    (!!jurisdictionInput && jurisdictionInput.value !== applied.jurisdiction) ||
    (!!dateFromInput && dateFromInput.value !== applied.dateFrom) ||
    (!!dateToInput && dateToInput.value !== applied.dateTo) ||
    (!!hasTranscriptInput && hasTranscriptInput.checked !== applied.hasTranscript) ||
    (!!hasAgendaInput && hasAgendaInput.checked !== applied.hasAgenda) ||
    (!!fuzzyInput && fuzzyInput.checked !== applied.fuzzy);

  const refreshStaleState = () => {
    const stale = isStale();
    btn.disabled = stale;
    btn.title = stale ? STALE_TITLE : '';
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
    const searchParams = {};
    if (applied.q) searchParams.q = applied.q;
    if (applied.jurisdiction) searchParams.jurisdiction = applied.jurisdiction;
    if (applied.dateFrom) searchParams.date_from = applied.dateFrom;
    if (applied.dateTo) searchParams.date_to = applied.dateTo;
    if (applied.hasAgenda) searchParams.has_agenda = true;
    if (applied.hasTranscript) searchParams.has_transcript = true;
    if (applied.fuzzy) searchParams.fuzzy = true;

    btn.disabled = true;
    if (statusEl) statusEl.textContent = '';
    try {
      const res = await fetch('/api/account/save-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_params: searchParams }),
      });
      if (res.ok) {
        if (statusEl) statusEl.textContent = 'Saved ✓';
      } else {
        if (statusEl) statusEl.textContent = 'Something went wrong — please try again.';
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
