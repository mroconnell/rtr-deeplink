// /context/new -- the editor form (save/publish a Full Context entry) and
// the per-entry status actions (Publish/Hide/Move to drafts) in the entry
// list below it. See CLAUDE.md's WO-943 contract for the two endpoints
// this talks to; both are JSON-only (Content-Type: application/json,
// credentials: same-origin) -- the site's CSRF posture is a form with no
// action/method that only ever submits through here, same reasoning as
// saved_items.js's fetch calls, just with richer error handling since this
// form has real validation to report back.

function showFormAlert(message, linkText, linkHref) {
  const alertEl = document.getElementById('contextFormAlert');
  if (!alertEl) return;
  alertEl.replaceChildren();
  alertEl.appendChild(document.createTextNode(message));
  if (linkText && linkHref) {
    alertEl.appendChild(document.createTextNode(' '));
    const link = document.createElement('a');
    link.href = linkHref;
    link.textContent = linkText;
    alertEl.appendChild(link);
  }
  alertEl.hidden = false;
}

function hideFormAlert() {
  const alertEl = document.getElementById('contextFormAlert');
  if (!alertEl) return;
  alertEl.hidden = true;
  alertEl.replaceChildren();
}

// Turns one /api/context/save or /api/context/set-status response into the
// message (+ optional link) the WO-943 contract specifies for each status
// code. Shared by both callers below so the two forms of "something went
// wrong" (the main form, a per-entry action) read identically.
async function describeContextApiError(res) {
  if (res.status === 401) {
    return { message: 'Your session expired. Sign in again.', linkText: 'Sign in', linkHref: '/sign-in' };
  }
  if (res.status === 404) {
    return { message: "That didn't work -- reload the page and try again." };
  }
  if (res.status === 502) {
    return { message: 'The archive is unreachable right now. Try again in a moment.' };
  }
  if (res.status === 400 || res.status === 409) {
    let body = null;
    try {
      body = await res.json();
    } catch (err) {
      body = null;
    }
    const message = (body && body.message) || 'Something went wrong -- please try again.';
    if (res.status === 409 && body && typeof body.existing_id === 'number') {
      return { message, linkText: 'Open the existing entry', linkHref: `/context/new?id=${body.existing_id}` };
    }
    return { message };
  }
  return { message: 'Something went wrong -- please try again.' };
}

function wireCharCounter() {
  const textarea = document.querySelector('#contextEntryForm textarea[name="summary"]');
  const counter = document.getElementById('contextSummaryCount');
  if (!textarea || !counter) return;
  const max = textarea.maxLength > 0 ? textarea.maxLength : null;
  const update = () => {
    counter.textContent = max ? `${textarea.value.length} / ${max}` : String(textarea.value.length);
  };
  textarea.addEventListener('input', update);
  update();
}

function wireContextEntryForm() {
  const form = document.getElementById('contextEntryForm');
  if (!form) return;

  const buttons = Array.from(form.querySelectorAll('button[type="submit"]'));

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    hideFormAlert();

    // Which button submitted decides the status -- "Save draft" vs.
    // "Publish" are otherwise the same form. event.submitter is the
    // standard way to tell them apart without two separate <form>s.
    const status = (event.submitter && event.submitter.dataset.status) || 'draft';

    const idField = form.querySelector('input[name="id"]');
    const idValue = idField && idField.value ? Number(idField.value) : null;

    const payload = {
      social_url: form.querySelector('input[name="social_url"]').value,
      title: form.querySelector('input[name="title"]').value,
      summary: form.querySelector('textarea[name="summary"]').value,
      source_label: form.querySelector('input[name="source_label"]').value,
      rtr_link: form.querySelector('input[name="rtr_link"]').value,
      match_kind: form.querySelector('select[name="match_kind"]').value,
      status,
    };
    if (idValue) payload.id = idValue;

    buttons.forEach((btn) => { btn.disabled = true; });
    try {
      const res = await fetch('/api/context/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        // Simplest way to always land on a consistent, fully server-
        // rendered state -- the entry list below the form, the char
        // counter, the cleared/pre-filled form all come from one source
        // of truth (the route) rather than being patched up by hand here.
        window.location.href = '/context/new';
        return;
      }
      const { message, linkText, linkHref } = await describeContextApiError(res);
      showFormAlert(message, linkText, linkHref);
    } catch (err) {
      showFormAlert('Something went wrong -- please try again.');
    } finally {
      buttons.forEach((btn) => { btn.disabled = false; });
    }
  });
}

function wireEntryStatusButtons() {
  document.querySelectorAll('[data-set-status]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const entryId = Number(btn.dataset.entryId);
      const newStatus = btn.dataset.setStatus;
      const article = btn.closest('.context-entry');
      const msgEl = article ? article.querySelector('[data-entry-status-msg]') : null;
      if (msgEl) msgEl.textContent = '';

      const actionButtons = article ? Array.from(article.querySelectorAll('[data-set-status]')) : [btn];
      actionButtons.forEach((b) => { b.disabled = true; });

      try {
        const res = await fetch('/api/context/set-status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ id: entryId, status: newStatus }),
        });
        if (res.ok) {
          // Same reasoning as the form above: reload to the one place
          // that already knows how to render every status correctly,
          // rather than reproducing that logic here in JS.
          window.location.reload();
          return;
        }
        const { message, linkText, linkHref } = await describeContextApiError(res);
        if (msgEl) {
          msgEl.replaceChildren(document.createTextNode(message));
          if (linkText && linkHref) {
            msgEl.appendChild(document.createTextNode(' '));
            const link = document.createElement('a');
            link.href = linkHref;
            link.textContent = linkText;
            msgEl.appendChild(link);
          }
        }
      } catch (err) {
        if (msgEl) msgEl.textContent = 'Something went wrong -- please try again.';
      } finally {
        actionButtons.forEach((b) => { b.disabled = false; });
      }
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  wireCharCounter();
  wireContextEntryForm();
  wireEntryStatusButtons();
});
