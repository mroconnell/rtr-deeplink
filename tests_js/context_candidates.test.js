'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const {
  selectedCandidateIds,
  submitCandidateRecheck,
} = require('../archive/static/context_candidates.js');

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
  await assert.rejects(
    submitCandidateRecheck([7], fetchImpl),
    /Access denied\./
  );
});
