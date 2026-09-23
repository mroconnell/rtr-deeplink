'use strict';

// Private Context queue. Authentication comes from the existing session at
// the resolver; a Clerk id is deliberately never read or sent by this script.
const REVIEW_FIELDS = [
  'jurisdiction', 'state', 'gov_id', 'meeting_date', 'meeting_body',
  'recording_url', 'rtr_link', 't_seconds', 'title', 'summary',
  'source_label', 'proposed_match', 'notes',
];

function selectedCandidateIds(root) {
  return Array.from(root.querySelectorAll('[data-candidate-id]:checked'), (box) =>
    Number.parseInt(box.dataset.candidateId, 10)
  ).filter((id) => Number.isSafeInteger(id) && id > 0);
}

async function responseJson(response) {
  try { return await response.json(); } catch (_) { return {}; }
}

async function submitCandidateRecheck(ids, fetchImpl) {
  const response = await fetchImpl('/api/context/candidates/recheck', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  const body = await responseJson(response);
  if (!response.ok) throw new Error(body.message || 'The recheck could not be completed.');
  return body;
}

async function submitCandidateReview(payload, fetchImpl) {
  const response = await fetchImpl('/api/context/candidates/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await responseJson(response);
  if (!response.ok || body.outcome !== 'saved') {
    const error = new Error(body.message || 'The review could not be saved.');
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

function candidateRecheckSummary(results) {
  const unsuccessful = results.filter((item) => item.outcome !== 'checked').length;
  if (unsuccessful) {
    const noun = unsuccessful === 1 ? 'candidate needs' : 'candidates need';
    return `${unsuccessful} ${noun} attention.`;
  }
  return 'Recheck complete.';
}

function reviewFields(form) {
  const fields = {};
  REVIEW_FIELDS.forEach((name) => {
    const control = form.elements.namedItem(name);
    const value = control ? control.value.trim() : '';
    fields[name] = value === '' ? null : value;
  });
  return fields;
}

function reviewClearConflicts(form, fields) {
  return Array.from(
    form.querySelectorAll('[data-review-clear-conflict]:checked'),
    (checkbox) => checkbox.value
  ).filter((field) => REVIEW_FIELDS.includes(field) && fields[field] === null);
}

function reviewSnapshot(form) {
  const fields = reviewFields(form);
  return JSON.stringify({ fields, clear_conflicts: reviewClearConflicts(form, fields) });
}

function unresolvedConflictFields(form, fields) {
  return Array.from(form.querySelectorAll('[data-review-clear-conflict]'))
    .filter((checkbox) => fields[checkbox.value] === null && !checkbox.checked)
    .map((checkbox) => checkbox.value);
}

function reviewErrorMessage(error) {
  if (error.status === 409 || error.body?.outcome === 'stale') {
    return 'This candidate changed while you were editing. Reload the page before saving again.';
  }
  const errors = error.body?.errors;
  if (errors && typeof errors === 'object') {
    const messages = Object.entries(errors).map(([field, message]) =>
      `${field.replaceAll('_', ' ')}: ${Array.isArray(message) ? message.join(', ') : message}`
    );
    if (messages.length) return messages.join(' ');
  }
  return error.message || 'The review could not be saved.';
}

function setHandoffEnabled(link, enabled) {
  if (!link) return;
  const active = Boolean(enabled && link.dataset.editorUrl);
  link.setAttribute('aria-disabled', active ? 'false' : 'true');
  link.classList.toggle('candidate-disabled-link', !active);
  if (active) link.setAttribute('href', link.dataset.editorUrl);
  else link.removeAttribute('href');
}

function initCandidateReview(root, fetchImpl, reloadImpl) {
  const form = root.querySelector('[data-candidate-review-form]');
  if (!form) return null;
  const editButton = root.querySelector('[data-review-edit]');
  const saveButton = form.querySelector('[data-review-save]');
  const cancelButton = form.querySelector('[data-review-cancel]');
  const status = form.querySelector('[data-review-status]');
  const recheckButton = root.querySelector('[data-recheck-one]');
  const handoff = root.querySelector('[data-editor-handoff]');
  let initialSnapshot = reviewSnapshot(form);
  let editing = false;
  let saving = false;

  const showStatus = (message) => {
    status.textContent = message;
    status.hidden = !message;
  };
  const updateConflictControls = () => {
    form.querySelectorAll('[data-review-clear-conflict]').forEach((checkbox) => {
      const control = form.elements.namedItem(checkbox.value);
      if (checkbox.checked && control) control.value = '';
      if (control) control.disabled = saving || checkbox.checked;
    });
  };
  const updateGates = () => {
    const dirty = reviewSnapshot(form) !== initialSnapshot;
    saveButton.disabled = saving || !dirty;
    cancelButton.disabled = saving;
    editButton.disabled = saving || editing;
    if (recheckButton) recheckButton.disabled = saving || editing;
    form.querySelectorAll('input, textarea, select').forEach((control) => {
      control.disabled = saving;
    });
    updateConflictControls();
    setHandoffEnabled(handoff, !saving && !editing);
    return dirty;
  };

  editButton.addEventListener('click', () => {
    editing = true;
    form.hidden = false;
    showStatus('');
    updateGates();
    const first = form.querySelector('input:not([type="checkbox"]), textarea, select');
    if (first) first.focus();
  });
  form.addEventListener('input', updateGates);
  form.addEventListener('change', (event) => {
    if (event.target.matches('[data-review-clear-conflict]')) updateConflictControls();
    updateGates();
  });
  cancelButton.addEventListener('click', () => {
    form.reset();
    editing = false;
    saving = false;
    form.hidden = true;
    showStatus('');
    updateGates();
  });
  if (handoff) {
    handoff.addEventListener('click', (event) => {
      if (handoff.getAttribute('aria-disabled') === 'true') event.preventDefault();
    });
  }
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (reviewSnapshot(form) === initialSnapshot) {
      showStatus('No review changes to save.');
      return;
    }
    const fields = reviewFields(form);
    const unresolved = unresolvedConflictFields(form, fields);
    if (unresolved.length) {
      showStatus(`Resolve or mark unknown: ${unresolved.map((field) => field.replaceAll('_', ' ')).join(', ')}.`);
      return;
    }
    saving = true;
    showStatus('Saving review…');
    updateGates();
    try {
      await submitCandidateReview({
        id: Number.parseInt(form.dataset.candidateId, 10),
        expected_version: Number.parseInt(form.dataset.candidateVersion, 10),
        fields,
        clear_conflicts: reviewClearConflicts(form, fields),
      }, fetchImpl);
      initialSnapshot = reviewSnapshot(form);
      showStatus('Review saved. Refreshing…');
      reloadImpl();
    } catch (error) {
      saving = false;
      showStatus(reviewErrorMessage(error));
      updateGates();
    }
  });

  updateGates();
  return { updateGates };
}

function initCandidateQueue(root, fetchImpl, reloadImpl = () => window.location.reload()) {
  const status = root.querySelector('[data-recheck-status]');
  const refreshLink = root.querySelector('[data-refresh-queue]');
  const selectedButton = root.querySelector('[data-recheck-selected]');
  const oneButton = root.querySelector('[data-recheck-one]');
  const reviewEditButton = root.querySelector('[data-review-edit]');
  const reviewForm = root.querySelector('[data-candidate-review-form]');
  const setStatus = (message) => { if (status) status.textContent = message; };
  const run = async (ids, button) => {
    button.disabled = true;
    if (reviewEditButton) reviewEditButton.disabled = true;
    setStatus('Checking…');
    try {
      const body = await submitCandidateRecheck(ids, fetchImpl);
      setStatus(candidateRecheckSummary(body.results || []));
      if (refreshLink) refreshLink.hidden = false;
    } catch (error) {
      setStatus(error.message || 'The recheck could not be completed.');
    } finally {
      button.disabled = false;
      if (reviewEditButton) reviewEditButton.disabled = Boolean(reviewForm && !reviewForm.hidden);
    }
  };

  if (selectedButton) {
    root.addEventListener('change', () => { selectedButton.disabled = selectedCandidateIds(root).length === 0; });
    selectedButton.addEventListener('click', () => run(selectedCandidateIds(root), selectedButton));
  }
  if (oneButton) oneButton.addEventListener('click', () => run([Number.parseInt(oneButton.dataset.recheckOne, 10)], oneButton));
  initCandidateReview(root, fetchImpl, reloadImpl);
}

if (typeof module !== 'undefined') {
  module.exports = {
    REVIEW_FIELDS,
    selectedCandidateIds,
    submitCandidateRecheck,
    submitCandidateReview,
    candidateRecheckSummary,
    reviewFields,
    reviewClearConflicts,
    reviewErrorMessage,
    setHandoffEnabled,
    initCandidateReview,
    initCandidateQueue,
  };
}
if (typeof document !== 'undefined') {
  const root = document.querySelector('[data-context-candidate-page]');
  if (root) initCandidateQueue(root, window.fetch.bind(window));
}
