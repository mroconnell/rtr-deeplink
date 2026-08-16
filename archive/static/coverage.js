// Client-side sort for the "Every place we've covered" table on
// /coverage -- no backend/data change, every row is already
// server-rendered in one pass (`coverage.html`). Row numbers are frozen
// to the table's own display position (position: sticky; left: 0, see
// style.css), independent of which column is sorted -- they renumber
// 1..N to match the new order rather than staying tied to the original
// alphabetical rows.
document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('coverageTable');
  if (!table) return;
  const tbody = table.tBodies[0];
  const headers = table.querySelectorAll('th.sortable-col');

  function renumberRows() {
    Array.from(tbody.rows).forEach((row, i) => {
      const cell = row.querySelector('.row-number-col');
      if (cell) cell.textContent = i + 1;
    });
  }

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
    renumberRows();
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
});
