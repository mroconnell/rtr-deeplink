'use strict';

// Private Context queue. Authentication comes from the existing session at
// the resolver; a Clerk id is deliberately never read or sent by this script.
function selectedCandidateIds(root) {
  return Array.from(root.querySelectorAll('[data-candidate-id]:checked'), (box) =>
    Number.parseInt(box.dataset.candidateId, 10)
  ).filter((id) => Number.isSafeInteger(id) && id > 0);
}

async function submitCandidateRecheck(ids, fetchImpl) {
  const response = await fetchImpl('/api/context/candidates/recheck', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  let body = {};
  try { body = await response.json(); } catch (_) { /* plain proxy error */ }
  if (!response.ok) throw new Error(body.message || 'The recheck could not be completed.');
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

function initCandidateQueue(root, fetchImpl) {
  const status = root.querySelector('[data-recheck-status]');
  const refreshLink = root.querySelector('[data-refresh-queue]');
  const selectedButton = root.querySelector('[data-recheck-selected]');
  const oneButton = root.querySelector('[data-recheck-one]');
  const setStatus = (message) => { if (status) status.textContent = message; };
  const run = async (ids, button) => {
    button.disabled = true;
    setStatus('Checking…');
    try {
      const body = await submitCandidateRecheck(ids, fetchImpl);
      setStatus(candidateRecheckSummary(body.results || []));
      if (refreshLink) refreshLink.hidden = false;
    } catch (error) {
      setStatus(error.message || 'The recheck could not be completed.');
    } finally {
      button.disabled = false;
    }
  };

  if (selectedButton) {
    root.addEventListener('change', () => { selectedButton.disabled = selectedCandidateIds(root).length === 0; });
    selectedButton.addEventListener('click', () => run(selectedCandidateIds(root), selectedButton));
  }
  if (oneButton) oneButton.addEventListener('click', () => run([Number.parseInt(oneButton.dataset.recheckOne, 10)], oneButton));
}

if (typeof module !== 'undefined') module.exports = { selectedCandidateIds, submitCandidateRecheck, candidateRecheckSummary, initCandidateQueue };
if (typeof document !== 'undefined') {
  const root = document.querySelector('[data-context-candidate-page]');
  if (root) initCandidateQueue(root, window.fetch.bind(window));
}
