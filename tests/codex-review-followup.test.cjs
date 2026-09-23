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
const head = 'a'.repeat(40);
const pr = {
  number: 721, draft: false, state: 'open', title: 'refactor: test',
  user: { login: 'developer' }, base: { ref: 'develop' }, head: { sha: head, ref: 'feature' },
};
const p1Review = { id: 10, user: { login: bot }, submitted_at: '2026-09-23T15:19:04Z', body: '[P1] Fix fixture' };

async function reviewRequired({ completedAt, reviewedHead = head, reaction = true, unresolved = false, sameDiff = true, differentContext = false, movedHunk = false } = {}) {
  const outputs = {};
  const github = {
    rest: {
      pulls: {
        list: async () => [pr],
        listReviews: async () => [p1Review],
        listReviewComments: async () => [],
      },
      checks: { listForRef: async () => [] },
      issues: { listComments: async () => [{
        user: { login: bot }, updated_at: '2026-09-23T15:32:00Z',
        body: `<!-- codex-pull-request-review-summary -->\n| 📝 **Code Review** | ✅ **Completed** <relative-time datetime="${completedAt}">now</relative-time> | \`${reviewedHead.slice(0, 7)}\` | Manual request |`,
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
    repo: { owner: 'example', repo: 'coach' }, eventName: 'push', ref: 'refs/heads/develop', payload: {},
  }, { setOutput: (name, value) => { outputs[name] = value; } }, { env: {} });
  return JSON.parse(outputs.pull_requests).include[0].reviewRequired;
}

test('a completed clean follow-up on the current head clears a previous P1', async () => {
  assert.equal(await reviewRequired({ completedAt: '2026-09-23T15:31:54Z' }), false);
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
