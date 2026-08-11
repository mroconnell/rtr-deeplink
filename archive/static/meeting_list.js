// "Save this search" -- saves the current /meetings query as-is (see
// archive/templates/meeting_list.html's saveSearchBtn data-* attributes,
// set from the same server-rendered filter state the page itself used).
// No unsave here -- unsaving a search happens from /account/saved (see
// saved_items.js), where the saved-search list actually lives.
function wireSaveSearchButton() {
  const btn = document.getElementById('saveSearchBtn');
  const statusEl = document.getElementById('saveSearchStatus');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const searchParams = {};
    if (btn.dataset.q) searchParams.q = btn.dataset.q;
    if (btn.dataset.jurisdiction) searchParams.jurisdiction = btn.dataset.jurisdiction;
    if (btn.dataset.dateFrom) searchParams.date_from = btn.dataset.dateFrom;
    if (btn.dataset.dateTo) searchParams.date_to = btn.dataset.dateTo;
    if (btn.dataset.hasAgenda === 'true') searchParams.has_agenda = true;
    if (btn.dataset.hasTranscript === 'true') searchParams.has_transcript = true;
    if (btn.dataset.fuzzy === 'true') searchParams.fuzzy = true;

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
      btn.disabled = false;
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
