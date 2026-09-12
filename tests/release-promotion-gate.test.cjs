'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

// Execute the actual trusted workflow scripts with mocked GitHub APIs. Provider
// blobs are only returned as data; this harness never contacts GitHub.
const workflow = fs.readFileSync(path.join(__dirname, '../.github/workflows/codex-code-review.yml'), 'utf8').replace(/\r\n/g, '\n');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
function scriptFor(stepName) {
  const step = workflow.split(`- name: ${stepName}\n`)[1];
  assert.ok(step, `Missing workflow step: ${stepName}`);
  const lines = step.split('          script: |\n')[1].split('\n');
  const script = [];
  for (const line of lines) {
    if (line.trim() && !line.startsWith('            ')) break;
    script.push(line.slice(12));
  }
  return new AsyncFunction('github', 'context', 'core', 'process', 'Buffer', script.join('\n'));
}
const discover = scriptFor('Resolve affected pull requests');
const exempt = scriptFor('Mark trusted Dependabot or release-bot PR as Codex-exempt');
const SHA = { head: 'a'.repeat(40), source: 'b'.repeat(40), main: 'c'.repeat(40), advanced: 'd'.repeat(40), tree: 'e'.repeat(40), blob: 'f'.repeat(40) };
const repo = { owner: 'example', repo: 'coach' };
const repository = { full_name: 'example/coach' };
const manualMarker = {
  id: 7, name: 'Codex manual review request', status: 'completed', conclusion: 'success',
  completed_at: '2026-09-08T12:00:00Z', output: { title: 'Manual Codex review requested' },
};
function fixture() {
  return {
    pr: {
      number: 437, state: 'open', draft: false,
      user: { login: 'ai-coach-release-bot[bot]', type: 'Bot' },
      title: 'chore(release): promote 1.9.4 to main',
      head: { sha: SHA.head, ref: 'chore/release-promotion-1.9.4', repo: repository },
      base: { sha: SHA.main, ref: 'main', repo: repository },
      updated_at: '2026-09-08T12:01:00Z',
    },
    commits: {
      [SHA.head]: { sha: SHA.head, tree: { sha: SHA.tree }, parents: [{ sha: SHA.source }, { sha: SHA.main }] },
      [SHA.source]: { sha: SHA.source, tree: { sha: SHA.tree }, parents: [{ sha: SHA.main }] },
    },
    developRefs: [SHA.source, SHA.source],
    comparisons: {
      [`${SHA.head}:${SHA.source}`]: { status: 'behind', merge_base_commit: { sha: SHA.source } },
      [`${SHA.head}:${SHA.advanced}`]: { status: 'diverged', merge_base_commit: { sha: SHA.main } },
      [`${SHA.source}:${SHA.source}`]: { status: 'identical', merge_base_commit: { sha: SHA.source } },
      [`${SHA.source}:${SHA.advanced}`]: { status: 'ahead', merge_base_commit: { sha: SHA.source } },
      [`${SHA.main}:${SHA.source}`]: { status: 'ahead', merge_base_commit: { sha: SHA.main } },
    },
    tree: { tree: [{ path: 'server.py', type: 'blob', mode: '100644', sha: SHA.blob }], truncated: false },
    server: 'APP_VERSION = "1.9.4"\nraise RuntimeError("This content must never execute")\n',
    checks: [], files: [], commitsList: [],
  };
}
async function run(script, data, context = {}) {
  const writes = [];
  const failures = [];
  const outputs = {};
  const calls = [];
  let prReads = 0;
  let refReads = 0;
  const github = {
    rest: {
      pulls: {
        get: async () => ({ data: structuredClone(prReads++ && data.latestPr ? data.latestPr : data.pr) }),
        list: async () => [structuredClone(data.pr)],
        listFiles: async () => data.files,
        listCommits: async () => data.commitsList,
      },
      git: {
        getCommit: async ({ commit_sha }) => {
          calls.push(['commit', commit_sha]);
          assert.ok(data.commits[commit_sha], 'Only fixture commits may be read');
          return { data: structuredClone(data.commits[commit_sha]) };
        },
        getRef: async ({ ref }) => {
          assert.equal(ref, 'heads/develop');
          return { data: { object: { sha: data.developRefs[Math.min(refReads++, data.developRefs.length - 1)] } } };
        },
        getTree: async ({ tree_sha }) => { calls.push(['tree', tree_sha]); return { data: structuredClone(data.tree) }; },
        getBlob: async ({ file_sha }) => {
          calls.push(['blob', file_sha]);
          return { data: { encoding: 'base64', content: Buffer.from(data.server).toString('base64') } };
        },
      },
      repos: {
        compareCommits: async ({ base, head }) => {
          calls.push(['compare', base, head]);
          const comparison = data.comparisons[`${base}:${head}`];
          assert.ok(comparison, 'Only fixture ancestry comparisons may be made');
          return { data: structuredClone(comparison) };
        },
      },
      checks: {
        listForRef: async () => structuredClone(data.checks),
        create: async (write) => { writes.push({ method: 'create', ...write }); return { data: { id: 99 } }; },
        update: async (write) => { writes.push({ method: 'update', ...write }); return { data: { id: write.check_run_id } }; },
      },
    },
    paginate: async (method, args) => method(args),
  };
  await script(github, { repo, ref: 'refs/heads/main', payload: {}, ...context }, {
    setFailed: (message) => failures.push(message), setOutput: (name, value) => { outputs[name] = value; },
  }, { env: { PR_NUMBER: '437', CHECK_NAME: 'Codex code review (main)' } }, Buffer);
  return { writes, failures, outputs, calls };
}
function assertSuccess(result) {
  assert.deepEqual(result.failures, []);
  assert.equal(result.writes.length, 1);
  assert.equal(result.writes[0].conclusion, 'success');
  assert.equal(result.writes[0].name, 'Codex code review (main)');
}
function assertFailure(result) {
  assert.equal(result.failures.length, 1);
  assert.equal(result.writes.length, 1);
  assert.equal(result.writes[0].conclusion, 'failure');
  assert.equal(result.writes[0].name, 'Codex code review (main)');
  assert.equal(result.writes[0].head_sha, SHA.head);
}
function matrix(result) {
  assert.deepEqual(result.failures, []);
  return JSON.parse(result.outputs.pull_requests).include[0];
}

test('an exact synthetic promotion gets a new success check without executing its content', async () => {
  const data = fixture();
  data.checks = [{ id: 5, name: 'Codex code review (main)', status: 'in_progress' }];
  const result = await run(exempt, data);
  assertSuccess(result);
  assert.equal(result.writes[0].method, 'create');
  assert.equal(result.writes[0].head_sha, SHA.head);
  assert.match(result.writes[0].output.summary, new RegExp(SHA.source));
  assert.ok(result.calls.some(([kind, sha]) => kind === 'tree' && sha === SHA.tree));
});

test('a direct develop commit is accepted when it includes main', async () => {
  const data = fixture();
  data.pr.head.sha = SHA.source;
  assertSuccess(await run(exempt, data));
});

test('develop may advance before or during validation while retaining the source snapshot', async () => {
  for (const refs of [[SHA.advanced, SHA.advanced], [SHA.source, SHA.advanced]]) {
    const data = fixture();
    data.developRefs = refs;
    assertSuccess(await run(exempt, data));
  }
});

const rejectionCases = {
  'untrusted author': (data) => { data.pr.user.login = 'someone'; },
  'non-bot author type': (data) => { data.pr.user.type = 'User'; },
  'fork repository': (data) => { data.pr.head.repo = { full_name: 'other/coach' }; },
  'wrong target': (data) => { data.pr.base.ref = 'develop'; },
  'wrong title': (data) => { data.pr.title = 'chore(release): promote 1.9.5 to main'; },
  'wrong branch version': (data) => { data.pr.head.ref = 'chore/release-promotion-1.9.5'; },
  'mutated promotion tree': (data) => { data.commits[SHA.head].tree.sha = '1'.repeat(40); },
  'stale main parent': (data) => { data.commits[SHA.head].parents[1].sha = '2'.repeat(40); },
  'additional merge parent': (data) => { data.commits[SHA.head].parents.push({ sha: SHA.advanced }); },
  'non-develop first parent': (data) => { data.comparisons[`${SHA.source}:${SHA.source}`] = { status: 'diverged', merge_base_commit: { sha: SHA.main } }; },
  'ancestry with mismatching merge base': (data) => { data.comparisons[`${SHA.source}:${SHA.source}`].merge_base_commit.sha = SHA.main; },
  'source removed from develop during validation': (data) => {
    data.developRefs = [SHA.source, SHA.advanced];
    data.comparisons[`${SHA.source}:${SHA.advanced}`] = { status: 'diverged', merge_base_commit: { sha: SHA.main } };
  },
  'APP_VERSION mismatch': (data) => { data.server = 'APP_VERSION = "1.9.3"\n'; },
  'missing APP_VERSION': (data) => { data.server = 'print("no version")\n'; },
  'duplicate APP_VERSION': (data) => { data.server += 'APP_VERSION = "1.9.4"\n'; },
  'server symlink': (data) => { data.tree.tree[0].mode = '120000'; },
  'truncated tree': (data) => { data.tree.truncated = true; },
  'explicit manual review': (data) => { data.checks = [manualMarker]; },
  'head changed during validation': (data) => { data.latestPr = structuredClone(data.pr); data.latestPr.head.sha = SHA.advanced; },
  'main changed during validation': (data) => { data.latestPr = structuredClone(data.pr); data.latestPr.base.sha = SHA.advanced; },
  'title changed during validation': (data) => { data.latestPr = structuredClone(data.pr); data.latestPr.title = 'other'; },
  'PR closed during validation': (data) => { data.latestPr = structuredClone(data.pr); data.latestPr.state = 'closed'; },
  'PR made draft during validation': (data) => { data.latestPr = structuredClone(data.pr); data.latestPr.draft = true; },
};
for (const [name, change] of Object.entries(rejectionCases)) {
  test(`promotion fails the required check for ${name}`, async () => {
    const data = fixture();
    data.checks = [{ id: 1, name: 'Codex code review (main)', status: 'completed', conclusion: 'success' }];
    change(data);
    assertFailure(await run(exempt, data));
  });
}

test('a direct develop snapshot cannot omit current main', async () => {
  const data = fixture();
  data.pr.head.sha = SHA.source;
  data.comparisons[`${SHA.main}:${SHA.source}`] = { status: 'diverged', merge_base_commit: { sha: SHA.advanced } };
  const result = await run(exempt, data);
  assert.equal(result.writes[0].conclusion, 'failure');
  assert.equal(result.writes[0].head_sha, SHA.source);
});

test('the existing exact version-only exemption is preserved', async () => {
  const data = fixture();
  data.pr.base.ref = 'develop';
  data.pr.head.ref = 'chore/release-version-1.9.4';
  data.pr.title = 'chore(release): set application version to 1.9.4';
  data.files = [{ filename: 'server.py', status: 'modified', additions: 1, deletions: 1, changes: 2,
    patch: '-APP_VERSION = "1.9.3"\n+APP_VERSION = "1.9.4"' }];
  data.checks = [
    { id: 1, name: 'Codex code review (main)', status: 'in_progress' },
    { id: 2, name: 'Codex code review (main)', status: 'completed', conclusion: 'failure' },
  ];
  const result = await run(exempt, data);
  assertSuccess(result);
  assert.equal(result.writes[0].method, 'create');
});

test('the existing Dependabot dependency-only exemption is preserved', async () => {
  const data = fixture();
  data.pr.user.login = 'dependabot[bot]';
  data.pr.base.ref = 'develop';
  data.pr.head.ref = 'dependabot/pip/example';
  data.files = [{ filename: 'requirements.txt' }];
  data.commitsList = [{ author: { login: 'dependabot[bot]' }, commit: {
    author: { email: '49699333+dependabot[bot]@users.noreply.github.com' },
    message: 'Signed-off-by: dependabot[bot] <support@github.com>',
  } }];
  assertSuccess(await run(exempt, data));
});

test('promotion discovery routes main PR events into validation', async () => {
  const data = fixture();
  assert.equal(matrix(await run(discover, data, {
    eventName: 'pull_request_target', payload: { action: 'opened', pull_request: data.pr },
  })).skipCodexReview, true);
});

test('a manual request persists through synchronize, reopen and title edit events', async () => {
  for (const action of ['synchronize', 'reopened', 'edited']) {
    const data = fixture();
    data.checks = [manualMarker];
    const result = matrix(await run(discover, data, { eventName: 'pull_request_target', payload: {
      action, changes: { title: { from: 'old title' } }, pull_request: data.pr,
    } }));
    assert.equal(result.skipCodexReview, false);
    assert.equal(result.reviewRequestedAt, action === 'synchronize' ? manualMarker.completed_at : data.pr.updated_at);
  }
});

test('a main push keeps explicit manual review mandatory', async () => {
  const data = fixture();
  data.checks = [manualMarker];
  assert.equal(matrix(await run(discover, data, { eventName: 'push' })).skipCodexReview, false);
});

test('protected develop dispatch can re-evaluate an exact main promotion', async () => {
  const result = await run(discover, fixture(), { eventName: 'workflow_dispatch', ref: 'refs/heads/develop',
    payload: { inputs: { pull_request_number: '437' } } });
  const entry = matrix(result);
  assert.equal(entry.pullRequestNumber, 437);
  assert.equal(entry.baseRef, 'main');
  assert.equal(entry.skipCodexReview, true);
});

test('dispatch preserves an explicit manual review and its timestamp', async () => {
  const data = fixture();
  data.checks = [manualMarker];
  const entry = matrix(await run(discover, data, { eventName: 'workflow_dispatch', ref: 'refs/heads/develop',
    payload: { inputs: { pull_request_number: '437' } } }));
  assert.equal(entry.skipCodexReview, false);
  assert.equal(entry.reviewRequestedAt, manualMarker.completed_at);
});

test('dispatch cannot run from a feature branch or main', async () => {
  for (const ref of ['refs/heads/feature/example', 'refs/heads/main']) {
    const result = await run(discover, fixture(), { eventName: 'workflow_dispatch', ref,
      payload: { inputs: { pull_request_number: '437' } } });
    assert.equal(result.failures.length, 1);
    assert.deepEqual(result.outputs, {});
    assert.deepEqual(result.writes, []);
  }
});

test('dispatch refuses an ordinary main PR and malformed PR numbers', async () => {
  const data = fixture();
  data.pr.user.login = 'someone';
  for (const number of ['437', '0', '-1', 'not-a-number', '1.5']) {
    const result = await run(discover, data, { eventName: 'workflow_dispatch', ref: 'refs/heads/develop',
      payload: { inputs: { pull_request_number: number } } });
    assert.equal(result.failures.length, 1);
    assert.deepEqual(result.outputs, {});
    assert.deepEqual(result.writes, []);
  }
});

<<<<<<< HEAD
test('manual events use the current protected action without checking out pull-request code', () => {
  function actionEnabled(stepName, baseRef, eventName, exempt = false) {
    const step = workflow.split(`- name: ${stepName}\n`)[1].split('\n      - name:', 1)[0];
    const condition = step.match(/^        if: (.+)$/m)[1];
    return new Function('matrix', 'github', `return (${condition});`)(
      { baseRef, skipCodexReview: exempt }, {
        event_name: eventName,
        repository: 'Lukas-Beike/ai-coach',
        event: eventName === 'pull_request_target'
          ? { pull_request: { head: { repo: { full_name: 'Lukas-Beike/ai-coach' } } } }
          : undefined,
      },
    );
  }
  for (const event of ['workflow_dispatch', 'issue_comment', 'pull_request_target', 'push']) {
    const fromDevelop = ['workflow_dispatch', 'issue_comment'].includes(event);
    const pushEvent = event === 'push';
    assert.equal(actionEnabled('Run trusted develop Codex gate', 'main', event), !pushEvent && fromDevelop);
    assert.equal(actionEnabled('Run trusted main Codex gate', 'main', event), !pushEvent && !fromDevelop);
    assert.equal(actionEnabled('Run trusted develop Codex gate', 'develop', event), !pushEvent);
    assert.equal(actionEnabled('Run trusted main Codex gate', 'develop', event), false);
    assert.equal(actionEnabled('Run trusted develop Codex gate', 'main', event, true), false);
    assert.equal(actionEnabled('Run trusted main Codex gate', 'main', event, true), false);
  }
=======
test('privileged review gate uses a pinned protected action without checkout', () => {
  assert.doesNotMatch(workflow, /actions\/checkout/);
  assert.match(
    workflow,
    /uses: Lukas-Beike\/ai-coach\/\.github\/actions\/codex-review-gate@[0-9a-f]{40}/,
  );
>>>>>>> 32cd82d (refactor: reduce Sonar complexity hotspots)
});

