'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {
  commitMatchesHead,
  isAtOrAfterTimestamp,
  isCodexUsageLimitComment,
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

test('accepts the native clean Codex review comment format', () => {
  const result = parseCodeReviewSummary(
    "Codex Review: Didn't find any major issues. :rocket:\n\n**Reviewed commit:** `9494ff2`",
    '2026-10-03T16:31:39Z',
  );

  assert.deepEqual(result, {
    commit: '9494ff2',
    status: 'completed',
    completedAt: Date.parse('2026-10-03T16:31:39Z'),
    clean: true,
  });
});

test('accepts observed native clean suffixes without accepting contradictory text', () => {
  for (const suffix of ['Hooray!', 'Swish!', 'Keep it up!', 'Already looking forward to the next diff.', 'Bravo.', ':+1:']) {
    const body = `Codex Review: Didn't find any major issues. ${suffix}\n\n**Reviewed commit:** \`9494ff2\``;
    assert.equal(parseCodeReviewSummary(body, '2026-10-04T13:55:13Z').clean, true);
    assert.equal(parseCodeReviewSummary(body + '\n[P1] Fix this', '2026-10-04T13:55:13Z'), undefined);
  }
});

test('rejects ambiguous native clean evidence', () => {
  const body = "Codex Review: Didn't find any major issues. :rocket:\n\n**Reviewed commit:** `9494ff2`";
  const at = '2026-10-03T16:31:39Z';
  for (const candidate of [
    body.replace('9494ff2', 'no-sha'),
    body + '\n**Reviewed commit:** `abcdef0`',
    body + '\n[P1] Unresolved finding',
    body.replace('Codex Review:', '> Codex Review:'),
    body.replace(':rocket:', 'But there are problems.'),
  ]) assert.equal(parseCodeReviewSummary(candidate, at), undefined);
  assert.equal(parseCodeReviewSummary(body), undefined);
});

async function runNativeReviewGate({ wrongCommit = false, unresolved = false,
  author = 'chatgpt-codex-connector', review, stale = false, changedRevision } = {}) {
  const action = fs.readFileSync(
    path.join(__dirname, '../.github/actions/codex-review-gate/action.yml'), 'utf8',
  ).replace(/\r\n/g, '\n');
  const script = action.split('        script: |\n')[1]
    .split('\n').map(line => line.slice(10)).join('\n');
  const head = 'a'.repeat(40);
  const base = 'c'.repeat(40);
  const checks = [];
  const failures = [];
  let reads = 0;
  let ticks = 0;
  const github = {
    rest: {
      pulls: {
        get: async () => {
          const data = { state: 'open', head: { sha: head }, base: { sha: base } };
          if (++reads >= 3 && changedRevision) data[changedRevision].sha = 'd'.repeat(40);
          return { data };
        },
        listReviews: async () => review ? [review] : [],
        listReviewComments: async () => [],
      },
      issues: { listComments: async () => [{
        id: 1, user: { login: author },
        created_at: stale ? '2026-10-03T16:00:00Z' : '2026-10-03T16:31:39Z',
        updated_at: '2026-10-03T16:31:39Z',
        body: `Codex Review: Didn't find any major issues. :rocket:\n\n**Reviewed commit:** \`${head.slice(0, 10)}\``,
      }] },
      reactions: { listForIssue: async () => [] },
      repos: { getCommit: async () => ({ data: { sha: wrongCommit ? 'b'.repeat(40) : head } }) },
      checks: {
        listForRef: async () => [],
        create: async () => ({ data: { id: 100 } }),
        update: async value => checks.push(value),
      },
    },
    paginate: async (method, args) => method(args),
    graphql: async () => ({ repository: { pullRequest: { reviewThreads: {
      nodes: unresolved ? [{ isResolved: false, comments: { nodes: [{
        author: { login: 'chatgpt-codex-connector' }, pullRequestReview: { databaseId: 10 },
      }] } }] : [], pageInfo: { hasNextPage: false },
    } } } }),
  };
  const FakeDate = class extends Date {
    static now() { return ticks++ < 2 ? 0 : 2000; }
  };
  const execute = new (Object.getPrototypeOf(async function () {}).constructor)(
    'github', 'context', 'core', 'process', 'require', 'Date', 'setTimeout', script,
  );
  await execute(github, { repo: { owner: 'example', repo: 'coach' }, eventName: 'workflow_dispatch' },
    { info() {}, debug() {}, warning() {}, setFailed: message => failures.push(message) },
    { env: { ACTION_PATH: path.join(__dirname, '../.github/actions/codex-review-gate'),
      PR_NUMBER: '928', CHECK_NAME: 'Codex code review', CODEX_BOT_LOGINS: 'chatgpt-codex-connector',
      TIMEOUT_SECONDS: '1', POLL_SECONDS: '1', REVIEW_REQUESTED_AT: '2026-10-03T16:29:13Z',
    } }, require, FakeDate, callback => callback());
  return { checks, failures };
}

test('native clean review completes the actual gate without a reaction', async () => {
  const { checks, failures } = await runNativeReviewGate();
  assert.equal(checks.at(-1).conclusion, 'success');
  assert.deepEqual(failures, []);
});

test('actual gate rejects wrong, stale, untrusted and unresolved native evidence', async () => {
  for (const options of [
    { wrongCommit: true }, { stale: true }, { author: 'athlete' }, { unresolved: true },
    { changedRevision: 'head' }, { changedRevision: 'base' },
    { review: { user: { login: 'chatgpt-codex-connector' }, state: 'PENDING' } },
    { review: { id: 10, user: { login: 'chatgpt-codex-connector' },
      submitted_at: '2026-10-03T16:31:00Z', state: 'CHANGES_REQUESTED', body: '[P1] Fix this' } },
  ]) {
    const { checks, failures } = await runNativeReviewGate(options);
    assert.equal(checks.at(-1).conclusion, 'failure', JSON.stringify(options));
    assert.equal(failures.length, 1);
  }
});

test('rejects missing and ambiguous commit references', () => {
  assert.equal(parseCodeReviewSummary('no review table'), undefined);
  assert.equal(parseCodeReviewSummary('| **Code Review** | **Completed** | no sha | automatic |'), undefined);
  assert.equal(commitMatchesHead('abcdef0123456789abcdef0123456789abcdef01', 'abcdef0123456789abcdef0123456789abcdef01'), true);
  assert.equal(commitMatchesHead('abcdef0', 'not-a-full-sha'), false);
});

test('detects subscription usage limit comments', () => {
  const quotaComment = 'You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).\nTo continue using code reviews, you can upgrade your account or add credits to your account and enable them for code reviews in your [settings](https://chatgpt.com/codex/cloud/settings/code-review).';
  assert.equal(isCodexUsageLimitComment(quotaComment), true);
  assert.equal(isCodexUsageLimitComment('You have reached your Codex usage limits'), true);
  assert.equal(isCodexUsageLimitComment('Some other comment'), false);
  assert.equal(isCodexUsageLimitComment(''), false);
  assert.equal(isCodexUsageLimitComment(undefined), false);
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
