// Unsave buttons on /account/saved -- removes the row from the DOM on a
// successful response rather than reloading the page. The inline Clerk
// sign-in mount point (#clerk-sign-in, shown when signed out) is handled
// by shared_static/clerk_nav.js, not here.
function wireUnsaveButtons() {
  document.querySelectorAll('.unsave-meeting-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const res = await fetch('/api/account/unsave-meeting', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ slug: btn.dataset.slug }),
        });
        if (res.ok) {
          btn.closest('[data-saved-item-id]').remove();
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
      btn.disabled = true;
      try {
        const res = await fetch('/api/account/unsave-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ saved_item_id: Number(btn.dataset.savedItemId) }),
        });
        if (res.ok) {
          btn.closest('[data-saved-item-id]').remove();
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
