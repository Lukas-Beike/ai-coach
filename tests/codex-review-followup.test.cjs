'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/codex-code-review.yml'), 'utf8').replace(/\r\n/g, '\n');
const step = workflow.split('- name: Resolve affected pull requests\n')[1];
const script = step.split('          script: |\n')[1].split('\n');
const source = [];
for (const line of script) {
  if (line.trim() && !line.startsWith('            ')) break;
  source.push(line.slice(12));
}
const discover = new (Object.getPrototypeOf(async function () {}).constructor)(
  'github', 'context', 'core', 'process', source.join('\n'));
const bot = 'chatgpt-codex-connector[bot]';
const enforcementLines = workflow.split('- name: Enforce explicit Codex review policy\n')[1]
  .split('          script: |\n')[1].split('\n');
const enforce = new (Object.getPrototypeOf(async function () {}).constructor)(
  'github', 'context', 'core', 'process', enforcementLines.map(line => line.slice(12)).join('\n'));
const head = 'a'.repeat(40);
const pr = {
  number: 721, draft: false, state: 'open', title: 'refactor: test',
  user: { login: 'developer' }, base: { ref: 'develop' }, head: { sha: head, ref: 'feature' },
};
const p1Review = { id: 10, user: { login: bot }, submitted_at: '2026-09-23T15:19:04Z', body: '[P1] Fix fixture' };

test('policy enforcement cannot transfer a result to a changed head or base', async () => {
  for (const changedField of ['head', 'base', null]) {
    for (const changeOnRead of [1, 2]) {
      const writes = [];
      const failures = [];
      let reads = 0;
      const snapshot = { ...pr, base: { ...pr.base, sha: 'c'.repeat(40) } };
      const github = {
        rest: {
          pulls: { get: async () => {
            const data = structuredClone(snapshot);
            if (++reads >= changeOnRead && changedField) data[changedField].sha = 'd'.repeat(40);
            return { data };
          } },
          issues: { listComments: async () => [] },
          checks: { create: async value => writes.push(value) },
        },
        paginate: async method => method(),
      };
      await enforce(github, { repo: { owner: 'example', repo: 'coach' } },
        { setFailed: message => failures.push(message) }, { env: {
          PR_NUMBER: '721', EVALUATED_HEAD: head, EVALUATED_BASE: snapshot.base.sha,
          REVIEW_REQUIRED: 'false', CHECK_NAME: 'Codex code review',
        } });
      assert.equal(writes.length, changedField ? 0 : 1);
      assert.equal(failures.length, changedField ? 1 : 0);
      if (!changedField) assert.equal(writes[0].head_sha, head);
    }
  }
});

async function reviewRequired({ completedAt, reviewedHead = head, reaction = true, unresolved = false, sameDiff = true, differentContext = false, movedHunk = false, review = p1Review, eventName = 'push', native = false, author = bot } = {}) {
  const outputs = {};
  const github = {
    rest: {
      pulls: {
        list: async () => [pr],
        get: async () => ({ data: pr }),
        listReviews: async () => review ? [review] : [],
        listReviewComments: async () => [],
      },
      checks: { listForRef: async () => [] },
      issues: { listComments: async () => [{
        user: { login: author }, updated_at: '2026-09-23T15:32:00Z', created_at: completedAt,
        body: native
          ? `Codex Review: Didn't find any major issues. :rocket:\n\n**Reviewed commit:** \`${reviewedHead.slice(0, 10)}\``
          : `<!-- codex-pull-request-review-summary -->\n| 📝 **Code Review** | ✅ **Completed** <relative-time datetime="${completedAt}">now</relative-time> | \`${reviewedHead.slice(0, 7)}\` | Manual request |`,
      }] },
      reactions: { listForIssue: async () => reaction ? [{
        user: { login: bot }, content: '+1', created_at: '2026-09-23T15:32:01Z',
      }] : [] },
      repos: {
        getCommit: async () => ({ data: { sha: reviewedHead } }),
        compareCommits: async ({ head: comparedHead }) => ({
          data: {
            merge_base_commit: { sha: comparedHead === reviewedHead ? 'c'.repeat(40) : 'd'.repeat(40) },
            files: [{ filename: 'server.py' }],
          },
        }),
      },
    },
    paginate: async (method, args) => method(args),
    request: async (_route, { basehead }) => {
      const oldPatch = basehead.endsWith(reviewedHead);
      const contextLine = !oldPatch && differentContext ? 'different function' : 'context';
      return { data: `diff --git a/server.py b/server.py\nindex ${oldPatch ? 'abcdef0..1234567' : '4567890..7654321'} 100644\n--- a/server.py\n+++ b/server.py\n@@ -${!oldPatch && movedHunk ? 101 : 1},2 +${!oldPatch && movedHunk ? 101 : 1},2 @@\n ${contextLine}\n-old\n+${sameDiff || oldPatch ? 'new' : 'unreviewed'}\n` };
    },
    graphql: async () => ({ repository: { pullRequest: { reviewThreads: {
      nodes: unresolved ? [{ isResolved: false, comments: { nodes: [{ author: { login: bot }, pullRequestReview: { databaseId: 10 } }] } }] : [],
    } } } }),
  };
  await discover(github, {
    repo: { owner: 'example', repo: 'coach' }, eventName, ref: 'refs/heads/develop',
    payload: { inputs: { pull_request_number: '721' } },
  }, { setOutput: (name, value) => { outputs[name] = value; } }, { env: {} });
  return JSON.parse(outputs.pull_requests).include[0].reviewRequired;
}

test('manual re-evaluation clears a resolved P2 after fixes without another review', async () => {
  assert.equal(await reviewRequired({ eventName: 'workflow_dispatch',
    review: { ...p1Review, body: '[P2] Fix fixture' }, sameDiff: false }), false);
});

test('manual re-evaluation keeps unresolved findings and P1 blocked', async () => {
  assert.equal(await reviewRequired({ eventName: 'workflow_dispatch',
    review: { ...p1Review, body: '[P2] Fix fixture' }, unresolved: true }), true);
  assert.equal(await reviewRequired({ eventName: 'workflow_dispatch', reaction: false }), true);
  assert.equal(await reviewRequired({ review: { ...p1Review,
    body: '![P1 Badge](https://img.shields.io/badge/P1-orange)' }, reaction: false }), true);
});

test('manual re-evaluation cannot replace the initial review', async () => {
  assert.equal(await reviewRequired({ eventName: 'workflow_dispatch', review: null, reaction: false }), true);
});

test('a summary-only clean initial review cannot approve a changed diff', async () => {
  assert.equal(await reviewRequired({ review: null, completedAt: '2026-09-23T15:31:54Z',
    reviewedHead: 'b'.repeat(40), sameDiff: false }), true);
  assert.equal(await reviewRequired({ review: null, completedAt: '2026-09-23T15:31:54Z',
    unresolved: true }), true);
});

test('manual re-evaluation preserves a changes-requested blocker', async () => {
  assert.equal(await reviewRequired({ eventName: 'workflow_dispatch',
    review: { ...p1Review, body: '', state: 'CHANGES_REQUESTED' }, reaction: false }), true);
});

test('a completed clean follow-up on the current head clears a previous P1', async () => {
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:31:54Z' }), false);
});

test('a native clean comment completes initial review without a reaction', async () => {
  assert.equal(await reviewRequired({
    completedAt: '2026-09-23T15:31:54Z', native: true, review: null, reaction: false,
  }), false);
});

test('native clean follow-up retains timestamp, diff, author and finding safeguards', async () => {
  const native = { native: true, completedAt: '2026-09-23T15:31:54Z', reaction: false };
  assert.equal(await reviewRequired(native), false);
  for (const changed of [
    { completedAt: '2026-09-23T15:18:00Z' }, { author: 'athlete' },
    { unresolved: true }, { reviewedHead: 'b'.repeat(40), sameDiff: false },
    { completedAt: undefined },
  ]) assert.equal(await reviewRequired({ ...native, ...changed }), true);
  assert.equal(await reviewRequired({ ...native, review: null,
    reviewedHead: 'b'.repeat(40), sameDiff: false }), true);
});

test('an old or missing clean reaction cannot clear a P1', async () => {
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:18:00Z' }), true);
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:31:54Z', reaction: false }), true);
});

test('a clean follow-up remains valid after develop advances and the PR is rebased', async () => {
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:31:54Z', reviewedHead: 'b'.repeat(40) }), false);
});

test('a new unreviewed change after the clean follow-up remains blocked', async () => {
  assert.equal(await reviewRequired({
    completedAt: '2026-09-23T15:31:54Z', reviewedHead: 'b'.repeat(40), sameDiff: false,
  }), true);
});

test('the same replacement at a different code location remains blocked', async () => {
  assert.equal(await reviewRequired({
    completedAt: '2026-09-23T15:31:54Z', reviewedHead: 'b'.repeat(40), differentContext: true,
  }), true);
});

test('identical context cannot hide a relocated hunk', async () => {
  assert.equal(await reviewRequired({
    completedAt: '2026-09-23T15:31:54Z', reviewedHead: 'b'.repeat(40), movedHunk: true,
  }), true);
});

test('a clean follow-up still requires all Codex threads to be resolved', async () => {
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:31:54Z', unresolved: true }), true);
});

test('a Codex usage limit comment skips the review requirement', async () => {
  const outputs = {};
  const usageLimitBot = 'chatgpt-codex-connector[bot]';
  const github = {
    rest: {
      pulls: {
        list: async () => [pr],
        listReviews: async () => [],
        listReviewComments: async () => [],
      },
      checks: { listForRef: async () => [] },
      issues: { listComments: async () => [{
        user: { login: usageLimitBot }, created_at: '2026-09-25T13:16:06Z',
        body: 'You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).',
      }] },
      reactions: { listForIssue: async () => [] },
      repos: { getCommit: async () => ({ data: { sha: head } }), compareCommits: async () => ({ data: { files: [] } }) },
    },
    paginate: async (method, args) => method(args),
    request: async () => ({ data: '' }),
    graphql: async () => ({ repository: { pullRequest: { reviewThreads: { nodes: [] } } } }),
  };
  await discover(github, {
    repo: { owner: 'example', repo: 'coach' }, eventName: 'push', ref: 'refs/heads/develop', payload: {},
  }, { setOutput: (name, value) => { outputs[name] = value; } }, { env: {} });
  assert.equal(JSON.parse(outputs.pull_requests).include[0].reviewRequired, false);
});
