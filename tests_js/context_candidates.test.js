'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const {
  REVIEW_FIELDS,
  selectedCandidateIds,
  submitCandidateRecheck,
  candidateRecheckSummary,
  reviewErrorMessage,
  initCandidateReview,
  initCandidateQueue,
} = require('../archive/static/context_candidates.js');

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function reviewDom({ conflict = false, editorUrl = '/context/new?candidate=7&review=3' } = {}) {
  const conflictControl = conflict
    ? '<input type="checkbox" value="meeting_body" data-review-clear-conflict>'
    : '';
  const dom = new JSDOM(`
    <main data-context-candidate-page>
      <button data-recheck-one="7">Recheck</button>
      <span data-recheck-status></span>
      <a data-refresh-queue hidden>Refresh</a>
      <button data-review-edit>Edit</button>
      <a data-editor-handoff data-editor-url="${editorUrl}" href="${editorUrl}" aria-disabled="false">Open</a>
      <form data-candidate-review-form data-candidate-id="7" data-candidate-version="12" hidden>
        <div data-review-status hidden></div>
        ${conflictControl}
        <input name="jurisdiction" value="Indianapolis, IN">
        <input name="state" value="IN">
        <input name="gov_id" value="">
        <input name="meeting_date" value="2026-09-09">
        <input name="meeting_body" value="${conflict ? '' : 'Public Safety Committee'}">
        <input name="recording_url" value="https://example.com/recording">
        <input name="rtr_link" value="">
        <input name="t_seconds" value="1:05:26">
        <input name="title" value="Original title">
        <textarea name="summary">Original summary</textarea>
        <input name="source_label" value="Reporter">
        <select name="proposed_match"><option value=""></option><option value="related" selected>Related</option></select>
        <textarea name="notes"></textarea>
        <button type="submit" data-review-save disabled>Save</button>
        <button type="button" data-review-cancel>Cancel</button>
      </form>
    </main>
  `, { url: 'https://example.test/context/candidates/7' });
  return { dom, root: dom.window.document.querySelector('main') };
}

function input(window, control, value) {
  control.value = value;
  control.dispatchEvent(new window.Event('input', { bubbles: true }));
}

test('selectedCandidateIds returns only checked positive candidate ids', () => {
  const root = {
    querySelectorAll: () => [
      { dataset: { candidateId: '7' } },
      { dataset: { candidateId: '9' } },
    ],
  };
  assert.deepEqual(selectedCandidateIds(root), [7, 9]);
});

test('recheck sends only ids and never a browser-supplied Clerk id', async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ results: [] }) };
  };
  await submitCandidateRecheck([7, 9], fetchImpl);
  assert.equal(request.url, '/api/context/candidates/recheck');
  assert.deepEqual(JSON.parse(request.options.body), { ids: [7, 9] });
  assert.equal(request.options.method, 'POST');
});

test('recheck turns a proxy error into a safe operator message', async () => {
  const fetchImpl = async () => ({
    ok: false,
    json: async () => ({ error: 'not_editor', message: 'Access denied.' }),
  });
  await assert.rejects(submitCandidateRecheck([7], fetchImpl), /Access denied\./);
});

test('recheck summary does not call stale or missing candidates complete', () => {
  assert.equal(candidateRecheckSummary([
    { id: 7, outcome: 'checked' },
    { id: 8, outcome: 'stale' },
    { id: 9, outcome: 'not_found' },
  ]), '2 candidates need attention.');
  assert.equal(candidateRecheckSummary([{ id: 7, outcome: 'error' }]), '1 candidate needs attention.');
  assert.equal(candidateRecheckSummary([{ id: 7, outcome: 'checked' }]), 'Recheck complete.');
});

test('edit mode gates recheck and editor handoff; cancel restores both', () => {
  const { dom, root } = reviewDom();
  initCandidateReview(root, async () => { throw new Error('not called'); }, () => {});
  const form = root.querySelector('form');
  const save = root.querySelector('[data-review-save]');
  const recheck = root.querySelector('[data-recheck-one]');
  const handoff = root.querySelector('[data-editor-handoff]');
  root.querySelector('[data-review-edit]').click();
  assert.equal(form.hidden, false);
  assert.equal(save.disabled, false);
  assert.equal(recheck.disabled, true);
  assert.equal(handoff.hasAttribute('href'), false);
  assert.equal(
    handoff.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true, cancelable: true })),
    false
  );

  input(dom.window, form.elements.namedItem('title'), 'Changed title');
  assert.equal(save.disabled, false);
  root.querySelector('[data-review-cancel]').click();
  assert.equal(form.hidden, true);
  assert.equal(form.elements.namedItem('title').value, 'Original title');
  assert.equal(recheck.disabled, false);
  assert.equal(handoff.getAttribute('href'), '/context/new?candidate=7&review=3');
});

test('unchanged values can confirm a first review or acknowledge new research', async () => {
  for (const editorUrl of ['/context/new?candidate=7&review=3', '']) {
    const { dom, root } = reviewDom({ editorUrl });
    let payload;
    let reloads = 0;
    const fetchImpl = async (_url, options) => {
      payload = JSON.parse(options.body);
      return {
        ok: true,
        status: 200,
        json: async () => ({ outcome: 'saved', candidate: {} }),
      };
    };
    initCandidateReview(root, fetchImpl, () => { reloads += 1; });
    const form = root.querySelector('form');
    root.querySelector('[data-review-edit]').click();
    assert.equal(root.querySelector('[data-review-save]').disabled, false);
    form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
    await tick();
    assert.equal(payload.fields.title, 'Original title');
    assert.equal(payload.expected_version, 12);
    assert.equal(reloads, 1);
  }
});

test('detail recheck reloads on a completed response but not a network failure', async () => {
  {
    const { root } = reviewDom();
    let reloads = 0;
    const fetchImpl = async () => ({
      ok: true,
      status: 200,
      json: async () => ({ results: [{ id: 7, outcome: 'checked' }] }),
    });
    initCandidateQueue(root, fetchImpl, () => { reloads += 1; });
    root.querySelector('[data-recheck-one]').click();
    await tick();
    assert.equal(reloads, 1);
    assert.equal(root.querySelector('[data-recheck-status]').textContent, 'Recheck complete.');
  }

  {
    const { root } = reviewDom();
    let reloads = 0;
    const fetchImpl = async () => { throw new Error('Network unavailable.'); };
    initCandidateQueue(root, fetchImpl, () => { reloads += 1; });
    root.querySelector('[data-recheck-one]').click();
    await tick();
    assert.equal(reloads, 0);
    assert.equal(root.querySelector('[data-recheck-status]').textContent, 'Network unavailable.');
  }
});

test('save posts a complete snapshot, disables controls in flight, then reloads', async () => {
  const { dom, root } = reviewDom();
  let finishRequest;
  let request;
  let reloads = 0;
  const fetchImpl = (url, options) => {
    request = { url, options };
    return new Promise((resolve) => { finishRequest = resolve; });
  };
  initCandidateReview(root, fetchImpl, () => { reloads += 1; });
  const form = root.querySelector('form');
  root.querySelector('[data-review-edit]').click();
  input(dom.window, form.elements.namedItem('notes'), 'Reviewed against the full recording.');
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(form.elements.namedItem('title').disabled, true);
  assert.equal(root.querySelector('[data-review-save]').disabled, true);
  assert.equal(root.querySelector('[data-review-cancel]').disabled, true);
  assert.equal(root.querySelector('[data-recheck-one]').disabled, true);

  const payload = JSON.parse(request.options.body);
  assert.equal(request.url, '/api/context/candidates/save');
  assert.equal(payload.id, 7);
  assert.equal(payload.expected_version, 12);
  assert.deepEqual(Object.keys(payload.fields), REVIEW_FIELDS);
  assert.equal(payload.fields.notes, 'Reviewed against the full recording.');
  assert.equal(payload.fields.gov_id, null);
  assert.equal(payload.fields.t_seconds, '1:05:26');
  assert.deepEqual(payload.clear_conflicts, []);
  assert.equal('clerk_user_id' in payload, false);

  finishRequest({ ok: true, status: 200, json: async () => ({ outcome: 'saved', candidate: {} }) });
  await tick();
  assert.equal(reloads, 1);
  assert.match(root.querySelector('[data-review-status]').textContent, /Review saved/);
});

test('stale save keeps edits and shows a reload message', async () => {
  const { dom, root } = reviewDom();
  const fetchImpl = async () => ({
    ok: false,
    status: 409,
    json: async () => ({ outcome: 'stale', message: 'old version' }),
  });
  initCandidateReview(root, fetchImpl, () => { throw new Error('must not reload'); });
  const form = root.querySelector('form');
  root.querySelector('[data-review-edit]').click();
  input(dom.window, form.elements.namedItem('title'), 'Keep my edit');
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick();
  assert.equal(form.hidden, false);
  assert.equal(form.elements.namedItem('title').value, 'Keep my edit');
  assert.equal(form.elements.namedItem('title').disabled, false);
  assert.match(root.querySelector('[data-review-status]').textContent, /Reload the page/);
  assert.equal(root.querySelector('[data-editor-handoff]').hasAttribute('href'), false);
});

test('a blank conflicting fact requires an explicit unknown choice', async () => {
  const { dom, root } = reviewDom({ conflict: true });
  let calls = 0;
  let payload;
  const fetchImpl = async (_url, options) => {
    calls += 1;
    payload = JSON.parse(options.body);
    return { ok: true, status: 200, json: async () => ({ outcome: 'saved', candidate: {} }) };
  };
  initCandidateReview(root, fetchImpl, () => {});
  const form = root.querySelector('form');
  root.querySelector('[data-review-edit]').click();
  input(dom.window, form.elements.namedItem('notes'), 'The source conflict remains unresolved.');
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(calls, 0);
  assert.match(root.querySelector('[data-review-status]').textContent, /meeting body/);

  const clear = root.querySelector('[data-review-clear-conflict]');
  clear.checked = true;
  clear.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  await tick();
  assert.equal(calls, 1);
  assert.deepEqual(payload.clear_conflicts, ['meeting_body']);
  assert.equal(payload.fields.meeting_body, null);
});

test('server field errors are shown with readable field names', () => {
  const error = new Error('invalid');
  error.status = 422;
  error.body = { errors: { meeting_date: 'Use YYYY-MM-DD.', t_seconds: ['Use seconds.', 'Maximum 86400.'] } };
  assert.equal(
    reviewErrorMessage(error),
    'meeting date: Use YYYY-MM-DD. t seconds: Use seconds., Maximum 86400.'
  );
});
