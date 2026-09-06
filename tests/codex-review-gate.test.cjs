'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  commitMatchesHead,
  isAtOrAfterTimestamp,
  parseCodeReviewSummary,
} = require('../.github/actions/codex-review-gate/summary.cjs');

test('reads the code-review row instead of stale security metadata', () => {
  const body = `<!-- codex-pull-request-review-summary -->
<!-- codex-security-review:v1 {"headSha":"c43b6385314894c676cbce054c5a90dd3b4d8e49","status":"completed"} -->
| Review | Status | Commit | Review trigger |
| --- | --- | --- | --- |
| **Code Review** | **Completed** <relative-time datetime="2026-09-06T04:18:25.905897Z">now</relative-time> | \`9494ff2\` | New commits |
| **Security Review** | **Completed** <relative-time datetime="2026-09-05T20:12:29.510493Z">earlier</relative-time> | \`c43b638\` | PR opened |`;

  const result = parseCodeReviewSummary(body);

  assert.deepEqual(result, {
    commit: '9494ff2',
    status: 'completed',
    completedAt: Date.parse('2026-09-06T04:18:25.905897Z'),
  });
  assert.equal(commitMatchesHead(result.commit, '9494ff28f295d8fd164e4e415e7f4d9da92d7b62'), false);
  assert.equal(commitMatchesHead(result.commit, 'c43b6385314894c676cbce054c5a90dd3b4d8e49'), false);
});

test('keeps an unfinished code review pending', () => {
  const result = parseCodeReviewSummary(
    '| **Code Review** | **In progress** | `abcdef0` | New commits |',
  );

  assert.equal(result.status, 'pending');
  assert.equal(Number.isNaN(result.completedAt), true);
});

test('rejects missing and ambiguous commit references', () => {
  assert.equal(parseCodeReviewSummary('no review table'), undefined);
  assert.equal(parseCodeReviewSummary('| **Code Review** | **Completed** | no sha | automatic |'), undefined);
  assert.equal(commitMatchesHead('abcdef0123456789abcdef0123456789abcdef01', 'abcdef0123456789abcdef0123456789abcdef01'), true);
  assert.equal(commitMatchesHead('abcdef0', 'not-a-full-sha'), false);
});

test('compares reaction timestamps at GitHub second precision', () => {
  assert.equal(
    isAtOrAfterTimestamp('2026-09-06T04:18:25Z', '2026-09-06T04:18:25.905897Z'),
    true,
  );
  assert.equal(
    isAtOrAfterTimestamp('2026-09-06T04:18:24Z', '2026-09-06T04:18:25.905897Z'),
    false,
  );
});
