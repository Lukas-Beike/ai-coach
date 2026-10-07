'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/codex-review-watchdog.yml'), 'utf8');
const source = workflow.replace(/\r\n/g, '\n').split('          script: |\n')[1]
  .split('\n').map(line => line.slice(12)).join('\n');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const run = new AsyncFunction('github', 'context', 'process', 'Date', 'setTimeout', source);
const head = 'a'.repeat(40);
const bot = 'chatgpt-codex-connector[bot]';

async function scenario(options = {}) {
  let elapsed = 0;
  const epoch = Date.parse('2026-10-07T12:00:00Z');
  class Clock extends Date {
    constructor(value) { super(value === undefined ? epoch + elapsed : value); }
    static now() { return epoch + elapsed; }
  }
  const pull = {
    state: 'open', draft: false, updated_at: new Clock().toISOString(),
    user: { login: options.dependabot ? 'dependabot[bot]' : 'human' },
    head: { sha: head, repo: { full_name: 'owner/repo' } },
    base: { ref: 'develop', sha: 'b'.repeat(40) },
  };
  const comments = options.existing ? [{
    user: { login: 'github-actions[bot]' }, created_at: new Clock().toISOString(),
    body: `@codex review\n<!-- codex-watchdog:42:${head} -->`,
  }] : [];
  const writes = [];
  const results = [];
  let requested = Boolean(options.existing);
  const methods = {
    comments: () => {
      const native = [];
      if (options.active || (requested && options.limit)) native.push({
        user: { login: options.impostor ? 'other-bot' : bot },
        created_at: new Clock(options.old ? epoch - 1000 : epoch + elapsed).toISOString(),
        body: options.blocked ? '### Blocked: Required Secret Scanner Is Unavailable' :
          options.limit ? 'You have reached your Codex usage limits' :
          options.progress ? 'Codex review started' : options.unrelated ? 'Unrelated comment' :
            "Codex Review: Didn't find any major issues.",
      });
      return [...comments, ...native];
    },
    reviews: () => options.review ? [{
      user: { login: bot }, commit_id: options.wrongHead ? 'c'.repeat(40) : head,
      submitted_at: new Clock().toISOString(),
    }] : [],
    inline: () => [],
  };
  const github = {
    paginate: async method => method(),
    rest: {
      pulls: {
        get: async () => ({ data: {
          ...pull, head: { ...pull.head, sha: options.stale && elapsed >= 180000 ? 'd'.repeat(40) : head },
        } }),
        listReviews: methods.reviews,
        listReviewComments: methods.inline,
      },
      issues: {
        listComments: methods.comments,
        createComment: async payload => {
          writes.push({ ...payload, elapsed });
          requested = true;
          return { data: { created_at: new Clock().toISOString() } };
        },
      },
      checks: {
        create: async () => ({ data: { id: 1 } }),
        update: async payload => results.push(payload),
      },
    },
  };
  await run(github, { repo: { owner: 'owner', repo: 'repo' } }, {
    env: { PR_NUMBER: '42', EVENT_HEAD: head, EVENT_TIME: pull.updated_at },
  }, Clock, callback => { elapsed += 10000; callback(); });
  return { writes, results, elapsed };
}

test('native activity avoids fallback without claiming completed review', async () => {
  const result = await scenario({ active: true });
  assert.equal(result.writes.length, 0);
  assert.equal(result.results[0].conclusion, 'success');
  assert.match(result.results[0].output.summary, /not review completion/);
});

test('three minutes of silence trigger one fallback and an explicit usage exemption', async () => {
  const result = await scenario({ limit: true });
  assert.equal(result.writes.length, 1);
  assert.equal(result.writes[0].elapsed, 180000);
  assert.match(result.writes[0].body, /^@codex review\n/);
  assert.equal(result.results[0].conclusion, 'success');
  assert.match(result.results[0].output.title, /explicit usage limit/);
});

test('continued silence fails after bounded fallback wait', async () => {
  const result = await scenario();
  assert.equal(result.writes.length, 1);
  assert.equal(result.elapsed, 360000);
  assert.equal(result.results[0].conclusion, 'failure');
});

test('rerun never posts a second request for the same PR head', async () => {
  const result = await scenario({ existing: true });
  assert.equal(result.writes.length, 0);
  assert.equal(result.results[0].conclusion, 'failure');
});

test('watchdog resumes when Codex posts a late comment or review', () => {
  assert.match(workflow, /issue_comment:\n\s+types: \[created\]/);
  assert.match(workflow, /pull_request_review:\n\s+types: \[submitted\]/);
  assert.match(workflow, /github\.event\.comment\.user\.login == 'chatgpt-codex-connector\[bot\]'/);
  assert.match(workflow, /github\.event\.issue\.number \|\| inputs\.pull_request_number/);
  assert.match(workflow, /codex-watchdog-\$\{\{ github\.event\.pull_request\.number \|\| github\.event\.issue\.number \|\| inputs\.pull_request_number \}\}/);
  assert.doesNotMatch(workflow, /current\.base\.sha !== base/);
});

test('untrusted and old bot comments cannot prove activity', async () => {
  for (const options of [{ active: true, impostor: true }, { active: true, old: true }]) {
    const result = await scenario(options);
    assert.equal(result.results[0].conclusion, 'failure');
  }
});

test('integration-blocked comments fail and are not treated as usage exhaustion', async () => {
  const result = await scenario({ active: true, blocked: true });
  assert.equal(result.writes.length, 0);
  assert.equal(result.results[0].conclusion, 'failure');
  assert.match(result.results[0].output.title, /blocked/i);
});

test('only a review of the current head proves activity', async () => {
  assert.equal((await scenario({ review: true })).writes.length, 0);
  assert.equal((await scenario({ review: true, wrongHead: true })).results[0].conclusion, 'failure');
});

test('changed head cancels without issuing a stale fallback', async () => {
  const result = await scenario({ stale: true });
  assert.equal(result.writes.length, 0);
  assert.equal(result.results[0].conclusion, 'cancelled');
});

test('same-repository Dependabot retains the explicit exception', async () => {
  const result = await scenario({ dependabot: true });
  assert.equal(result.writes.length, 0);
  assert.equal(result.results[0].conclusion, 'success');
  assert.match(result.results[0].output.title, /Dependabot/);
});

test('privileged workflow never checks out or runs PR source', () => {
  assert.doesNotMatch(workflow, /actions\/checkout|require\(|eval\(/);
  assert.match(workflow, /permissions: \{\}/);
  assert.match(workflow, /pull-requests: write/);
  assert.match(workflow, /cancel-in-progress: true/);
});
