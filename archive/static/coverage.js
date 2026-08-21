// Client-side sort (and, for one table, filter) for /coverage -- no
// backend/data change, every row is already server-rendered in one pass
// (coverage.html). Row numbers are frozen to each table's own display
// position (position: sticky; left: 0, see style.css), independent of
// which column is sorted or which rows a filter is hiding -- they
// renumber 1..N across only the currently-*visible* rows, so a filtered
// view never shows numbering with gaps in it.
//
// Originally built for just the "Every place we've covered" table
// (#coverageTable), then generalized 2026-08-17 when the fuller
// "Full jurisdiction detail table" (#fullCoverageTable, see BACKLOG.md's
// "Coverage page" entry) needed the same sort behavior on more columns
// plus real filtering -- renumberVisibleRows()/initSortableTable() below
// are shared by both tables; the filtering block further down only
// attaches to #fullCoverageTable.
document.addEventListener('DOMContentLoaded', () => {
  function renumberVisibleRows(tbody) {
    let n = 0;
    Array.from(tbody.rows).forEach((row) => {
      if (row.style.display === 'none') return;
      n += 1;
      const cell = row.querySelector('.row-number-col');
      if (cell) cell.textContent = n;
    });
    return n;
  }

  function initSortableTable(table) {
    const tbody = table.tBodies[0];
    const headers = table.querySelectorAll('th.sortable-col');

    function sortBy(key, ascending) {
      const rows = Array.from(tbody.rows);
      rows.sort((a, b) => {
        const va = (a.dataset[key] || '').toLowerCase();
        const vb = (b.dataset[key] || '').toLowerCase();
        if (va < vb) return ascending ? -1 : 1;
        if (va > vb) return ascending ? 1 : -1;
        return 0;
      });
      rows.forEach((row) => tbody.appendChild(row));
      renumberVisibleRows(tbody);
    }

    function activateHeader(th) {
      const key = th.dataset.sortKey;
      const ascending = th.getAttribute('aria-sort') !== 'ascending';
      headers.forEach((h) => h.removeAttribute('aria-sort'));
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      sortBy(key, ascending);
    }

    headers.forEach((th) => {
      th.addEventListener('click', () => activateHeader(th));
      th.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activateHeader(th);
        }
      });
    });
  }

  document.querySelectorAll('table.sortable-table').forEach(initSortableTable);

  // Client-side filtering for the "Full jurisdiction detail table" only --
  // confirmed live 2026-08-17 that /coverage's jurisdiction roster is
  // ~870 rows total, small enough to render every row server-side and
  // filter/sort entirely in the browser (same reasoning the sort code
  // above already relies on), so this deliberately doesn't add
  // server-side pagination or a second request -- every control below
  // just shows/hides rows already in the DOM, matching the sort code's
  // own client-side-only style rather than inventing a second mechanism.
  const fullTable = document.getElementById('fullCoverageTable');
  if (fullTable) {
    const tbody = fullTable.tBodies[0];
    const rows = Array.from(tbody.rows);
    const countEl = document.getElementById('fullCoverageCount');
    const searchEl = document.getElementById('fullCoverageSearch');
    const outcomeEl = document.getElementById('fullCoverageOutcomeFilter');
    const detailEl = document.getElementById('fullCoverageDetailFilter');
    const videoPlatformEl = document.getElementById(
      'fullCoverageVideoPlatformFilter'
    );
    const videoOnlyEl = document.getElementById('fullCoverageVideoOnly');
    const agendaOnlyEl = document.getElementById('fullCoverageAgendaOnly');
    const instantOnlyEl = document.getElementById('fullCoverageInstantOnly');
    const audioOnlyEl = document.getElementById('fullCoverageAudioOnly');

    function applyFilters() {
      const search = (searchEl.value || '').trim().toLowerCase();
      const outcome = outcomeEl.value;
      const detail = detailEl.value;
      const videoPlatform = videoPlatformEl.value;
      rows.forEach((row) => {
        const d = row.dataset;
        const matches =
          (!search || d.jurisdiction.toLowerCase().includes(search)) &&
          (!outcome || d.outcome === outcome) &&
          (!detail || d.detail === detail) &&
          (!videoPlatform || d.videoPlatform === videoPlatform) &&
          (!videoOnlyEl.checked || d.video === '1') &&
          (!agendaOnlyEl.checked || d.agenda === '1') &&
          (!instantOnlyEl.checked || d.instant === '1') &&
          (!audioOnlyEl.checked || d.audio === '1');
        row.style.display = matches ? '' : 'none';
      });
      const shown = renumberVisibleRows(tbody);
      if (countEl) {
        countEl.textContent = `Showing ${shown} of ${rows.length} jurisdictions`;
      }
    }

    [searchEl, outcomeEl, detailEl, videoPlatformEl].forEach((el) => {
      el.addEventListener('input', applyFilters);
      el.addEventListener('change', applyFilters);
    });
    [videoOnlyEl, agendaOnlyEl, instantOnlyEl, audioOnlyEl].forEach((el) => {
      el.addEventListener('change', applyFilters);
    });

    applyFilters();
  }
});
