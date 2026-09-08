'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
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

async function createOrResumeReviewCheck(checkRuns) {
  const action = fs.readFileSync(
    path.join(__dirname, '../.github/actions/codex-review-gate/action.yml'),
    'utf8',
  );
  const start = action.indexOf('          const createOrResumeCheck =');
  const end = action.indexOf('          let checkRunId;', start);
  assert.ok(start >= 0 && end > start, 'the action must expose its current check-selection function');
  const calls = [];
  const github = {
    rest: {
      checks: {
        listForRef() {},
        async create(input) {
          calls.push({ operation: 'create', input });
          return { data: { id: 1001 } };
        },
      },
    },
    async paginate(method, input) {
      assert.equal(method, github.rest.checks.listForRef);
      assert.equal(input.ref, 'a'.repeat(40));
      return checkRuns;
    },
  };
  const updateCheck = async (...args) => calls.push({ operation: 'update', args });
  const buildFunction = new Function(
    'github', 'updateCheck', 'owner', 'repo', 'checkName',
    `${action.slice(start, end)}\nreturn createOrResumeCheck;`,
  );
  const createOrResume = buildFunction(
    github, updateCheck, 'example', 'release-test', 'Codex code review (main)',
  );
  return { id: await createOrResume('a'.repeat(40)), calls };
}

test('a manual review supersedes an exemption instead of resuming an older pending check', async () => {
  const { id, calls } = await createOrResumeReviewCheck([
    { id: 10, name: 'Codex code review (main)', status: 'in_progress' },
    { id: 20, name: 'Codex code review (main)', status: 'completed', conclusion: 'success' },
    { id: 30, name: 'unrelated test', status: 'in_progress' },
  ]);
  assert.equal(id, 1001);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operation, 'create');
  assert.equal(calls[0].input.name, 'Codex code review (main)');
  assert.equal(calls[0].input.head_sha, 'a'.repeat(40));
  assert.equal(calls[0].input.status, 'in_progress');
});

test('the newest unfinished matching review check can be resumed', async () => {
  const { id, calls } = await createOrResumeReviewCheck([
    { id: 10, name: 'Codex code review (main)', status: 'in_progress' },
    { id: 30, name: 'Codex code review (main)', status: 'in_progress' },
    { id: 20, name: 'Codex code review (main)', status: 'completed', conclusion: 'success' },
  ]);
  assert.equal(id, 30);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operation, 'update');
  assert.equal(calls[0].args[0], 30);
  assert.equal(calls[0].args[1], 'in_progress');
});

test('review recovery supersedes the newest failed exemption check', async () => {
  const { id, calls } = await createOrResumeReviewCheck([
    { id: 20, name: 'Codex code review (main)', status: 'completed', conclusion: 'failure' },
    { id: 10, name: 'Codex code review (main)', status: 'in_progress' },
  ]);
  assert.equal(id, 1001);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].operation, 'create');
  assert.equal(calls[0].input.status, 'in_progress');
});
