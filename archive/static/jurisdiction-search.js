// Lightweight, server-backed jurisdiction lookup for /coverage's "Find
// your government" box -- GET /api/jurisdictions?q=, debounced, never
// ships the full roster to the client (that's the receipts table's job,
// #coverageTable below, filtered/sorted entirely client-side by
// coverage.js since it's already rendered server-side in one pass). This
// box is the opposite shape on purpose: nothing about a match is in the
// DOM until it's actually typed.
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('jurisdictionSearch');
  const results = document.getElementById('jurisdictionSearchResults');
  if (!input || !results) return;

  const MIN_LENGTH = 2;
  const DEBOUNCE_MS = 200;
  let debounceTimer = null;
  let activeRequest = null;

  function hide() {
    results.hidden = true;
    results.innerHTML = '';
  }

  // A typed full state/province name (e.g. "California") comes back as
  // one `kind: "state"` entry (linking to /state/{slug}) followed by
  // that state's most-covered governments as ordinary `kind:
  // "jurisdiction"` entries -- see crud.search_jurisdictions(). Rendered
  // as a distinct state link plus a small subheading above the list it
  // introduces, rather than one flat list a reader can't tell apart.
  function render(matches) {
    results.innerHTML = '';
    if (!matches.length) {
      const empty = document.createElement('li');
      empty.className = 'coverage-search-empty';
      empty.textContent = 'No match yet -- try a shorter or different spelling.';
      results.appendChild(empty);
    } else {
      let afterState = false;
      matches.forEach((m) => {
        if (m.kind === 'state') {
          const li = document.createElement('li');
          li.className = 'coverage-search-result-state';
          const a = document.createElement('a');
          a.href = m.link;
          a.textContent = `${m.label} — browse the state page`;
          li.appendChild(a);
          results.appendChild(li);
          afterState = true;
          return;
        }
        if (afterState) {
          const heading = document.createElement('li');
          heading.className = 'coverage-search-subheading';
          heading.textContent = 'Most-covered governments:';
          results.appendChild(heading);
          afterState = false;
        }
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = m.link;
        a.textContent = m.label;
        li.appendChild(a);
        results.appendChild(li);
      });
    }
    results.hidden = false;
  }

  async function search(q) {
    const controller = new AbortController();
    activeRequest = controller;
    try {
      const response = await fetch(
        `/api/jurisdictions?q=${encodeURIComponent(q)}`,
        { signal: controller.signal }
      );
      if (!response.ok) {
        hide();
        return;
      }
      const data = await response.json();
      // A later keystroke's request may resolve after an earlier one --
      // only render if this is still the most recent request in flight.
      if (activeRequest === controller) {
        render(data.matches || []);
      }
    } catch (err) {
      if (err.name !== 'AbortError') hide();
    }
  }

  input.addEventListener('input', () => {
    const q = input.value.trim();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (activeRequest) activeRequest.abort();
    if (q.length < MIN_LENGTH) {
      hide();
      return;
    }
    debounceTimer = setTimeout(() => search(q), DEBOUNCE_MS);
  });

  document.addEventListener('click', (e) => {
    if (!results.contains(e.target) && e.target !== input) hide();
  });
});
