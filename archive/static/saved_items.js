// Unsave buttons on /account/saved -- removes the row from the DOM on a
// successful response rather than reloading the page. The inline Clerk
// sign-in mount point (#clerk-sign-in, shown when signed out) is handled
// by shared_static/clerk_nav.js, not here.
function wireUnsaveButtons() {
  document.querySelectorAll('.unsave-meeting-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const row = btn.closest('.saved-item-row');
      btn.disabled = true;
      try {
        const res = await fetch('/api/account/unsave-meeting', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug: btn.dataset.slug }),
        });
        if (res.ok) {
          row.remove();
        } else {
          btn.disabled = false;
        }
      } catch (err) {
        btn.disabled = false;
      }
    });
  });

  document.querySelectorAll('.unsave-search-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      // Read/remove via the row, not the button -- the button used to
      // carry its own data-saved-item-id too, which broke
      // closest('[data-saved-item-id]') (it matched the button itself,
      // not the row, since closest() includes the starting element).
      const row = btn.closest('.saved-item-row');
      btn.disabled = true;
      try {
        const res = await fetch('/api/account/unsave-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ saved_item_id: Number(row.dataset.savedItemId) }),
        });
        if (res.ok) {
          row.remove();
        } else {
          btn.disabled = false;
        }
      } catch (err) {
        btn.disabled = false;
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  wireUnsaveButtons();
});
