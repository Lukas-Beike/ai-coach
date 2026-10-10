# AI guidance, CI and release modernization

Recorded snapshot: `d7efbf9d`, application version `1.12.26`, reviewed on
7 October 2026. The implementation in this worktree is the authority for
behavior; documents describe it and plans describe intended changes.

## Findings and adopted changes

| Priority | Evidence in the reviewed snapshot | Remediation |
| --- | --- | --- |
| P1 | `.github/workflows/codex-code-review.yml` and its composite action reconstructed review completion from comments/reactions and could report success when review was unavailable. The required check therefore did not consistently prove a completed review. | Remove the comment-driven workflow, parser, exemption paths and their obsolete tests. Use native automatic Codex reviews and inspect findings and reviewed commits. Remove the obsolete required contexts from both live rulesets. |
| P2 | Both live rulesets requested Copilot reviews in addition to Codex. | Remove `copilot_code_review` from rulesets `21816227` and `21853132`, as authorized. Preserve all other protections. |
| P2 | `.github/workflows/daily-release.yml` dispatched the custom review workflow for promotion PRs. | Remove those dispatches. Retain protected version/promotion PRs, explicit test dispatch, tested-tree agreement and release/image version checks. |
| P2 | `.github/dependabot.yml` omitted npm despite `package.json`/`package-lock.json`, and relied on an implicit target branch. | Cover pip, npm, Docker and GitHub Actions explicitly on `develop`, with Conventional Commit prefixes. Allow patch, minor and major squash auto-merge under required checks. Scope write permissions to the single auto-merge job; never execute PR source there. |
| P2 | `.github/workflows/pages.yml` used mutable action tags and its job permissions omitted `contents: read`, overriding the workflow default needed for private-repository checkout. | Resolve action tags through GitHub and pin commit SHAs; grant checkout read permission and disable persisted checkout credentials. |
| P2 | Container validation checkouts persisted credentials unnecessarily. | Disable credential persistence on every checkout in `publish-container.yml`; keep release checkouts that actually push under their explicitly scoped App token. |
| P2 | Root guidance denied the existence of frontend unit tests although executable Node regression tests were present. | Document the built-in Node runner and add it to the validation skill. |
| P2 | A global release skill duplicated repository-owned instructions. | Delete the explicitly authorized global copy; verify that the path no longer exists. |
| P3 | `caveman` and `ponytail` duplicated general communication/programming behavior, imposed output restrictions, and encouraged shortcuts inappropriate for a comprehensive audit. | Remove the repository copies. Keep task-specific skills with concrete project contracts. No claim about a particular model's capabilities is needed to justify these deletions. |
| P3 | Root instructions repeated Docker setup recipes and encoded a provider model name independently of configuration. | Link to the README runbook; express the model policy as preserving explicit selection and verifying provider/configuration code. |
| P3 | AI metadata and review documents entered the Docker build context despite being unnecessary for runtime. | Exclude `.agents/`, `.codex/` and `docs/`; keep explicit runtime copies and isolated CI mounts. |

## Review coverage and retained contracts

- Root and scoped instructions: root, backend, public, tests, e2e and `.github`.
  Retain SQLCipher, transactional migration/upgrade evidence, durable athlete
  data preservation, secret scanning, session/CSRF, explicit remote writes and
  domain ownership. Advanced coding models still need these project contracts.
- Skills: navigation, validation, Coach contracts, local security, PWA fixture,
  PR/CI diagnosis, releases, full application review, explicit PR execution and
  guarded orchestration. Keep domain-specific instructions and isolated worker
  adoption; repository-local skill names and links are checked mechanically.
  Tighten the navigator to sanitized fixtures instead of live athlete data.
- Codex configuration and hooks: retain the project Sonar integration and
  secret-scanning hook. No model-specific replacement or global synchronization.
- Workflows: conventions, AI documentation, container tests/publication,
  Dependabot auto-merge, automatic branch updates, daily releases and Pages.
  Keep App-authored synchronization events, aggregate test/browser checks,
  immutable source selection, hash-locked dependencies, signed image digests,
  protected promotion and required review-thread resolution. Make `ai-docs`
  required on both branches. Validate Dependabot's configured Conventional
  Commit prefixes instead of skipping its convention check.
- Documentation: align the README, routing and validation guidance with the
  executable workflow/tests. Historical architecture reviews and the feature
  plan remain dated evidence/proposals, not runtime specifications. Coach
  coverage/evaluation documents distinguish simulated execution tests from
  measured model quality; preserve that distinction.

## Native review activation and its limits

Official source fetched on 7 October 2026:
[OpenAI: Review GitHub pull requests with Codex](https://developers.openai.com/codex/integrations/github).
Enable automatic review for `Lukas-Beike/ai-coach` in Codex Settings and select
the trigger for subsequent pushes as well as new PRs. Verify a representative
PR and the reviewed commit after an update. No connected browser surface was
available in this session, so account-level activation is **unverified**.

Native reviews post GitHub reviews/comments. The documented integration does
not establish a mandatory successful status check for completed review. The
replacement therefore relies on required CI checks and resolution of posted
review threads; those protections do not themselves wait for a missing or late
native review. PR operators must inspect review completion before merging.
The new availability watchdog waits 180 seconds before one fallback mention,
then up to 180 seconds for the regular review or explicit usage response. It
does not assert review completion merely because Codex responds. Add its
`Codex review availability` required context only after the trusted workflow
is adopted on the corresponding protected branch, to avoid blocking every PR
with a check that cannot yet run.
Do not invent a native check context or turn provider absence into success.

The live ruleset edits are already effective. Repository workflow/documentation
changes are local until committed and merged. Existing protected branches may
still contain the old workflow until this change reaches them. No application
release, registry publication or Unraid deployment was initiated by this audit.

## Remaining plan and acceptance criteria

1. **Activate and verify native Codex reviews.** Confirm repository account
   settings and review-on-update behavior on a representative PR. Acceptance:
   native review evidence refers to the current commit and its findings are
   resolved. The watchdog waits three minutes, posts one fallback request, and
   requires either regular review activity or Codex's explicit usage-limit
   response. Missing access/review evidence remains explicit and failing.
2. **Adopt the validated worktree changes.** Review the patch, commit using
   Conventional Commits, then use the protected PR flow into `develop`.
   Acceptance: current required checks pass, feedback is resolved and GitHub
   reports the merge; auto-merge enabled alone is insufficient.
3. **Propagate through the ordinary release chain.** After adoption, use the
   daily version/promotion PR flow to carry the workflow removal to `main`.
   Acceptance: tested main tree, matching APP_VERSION/tag, signed release-tag
   and `latest` digest parity. Deployment requires separate runtime evidence.
4. **Verify dependency automation operationally.** Observe an actual npm update
   and a major-version update. Acceptance: manifest/lock agreement, all required
   test/browser/quality checks green, no bypass and squash merge into `develop`.
5. **Evaluate guidance by outcomes.** For Opus 5.5 and Sol 6.1, use the same
   synthetic change/review tasks with and without remaining guidance. Compare
   correctness, security/data preservation, review signal and unnecessary
   actions. Remove further rules only when evidence supports it. Model names
   and recency alone cannot establish obsolescence or a universal optimum.

## Validation evidence

- Focused CI/source-selection tests: 26 passed after modernization, including
  immutable action pins, non-persisted CI credentials and all dependency ecosystems.
- AI documentation contracts: 5 passed. All 7 release event/shell guard tests
  passed in the isolated Linux container with networking disabled; native
  Windows skips the 6 Bash-only cases.
- The watchdog regression suite is attached to the required `ai-docs` workflow
  and runs with the workflow implementation on every PR and protected-branch
  push.
- Node regressions: all 10 passed after `npm ci --ignore-scripts`.
- Docker build: `ai-coach:local` succeeded with Python 3.14 and SQLCipher.
- Full native Windows unit discovery was started but did not reach its final
  summary within the session runtime; observed output contained no failure.
  Treat the full-suite result as **unverified**, not as a pass. Final syntax,
  formatting and Linux shell validation are complete; no live provider or
  athlete account is used.
- Optional mypy on the two workflow test modules reports three pre-existing
  nullable import-spec/loader errors at `tests/test_ci_contracts.py:18` and
  `tests/test_ci_contracts.py:19`. These unchanged lines are outside this patch;
  the repository's incremental mypy gate targets backend modules.

This audit concerns AI guidance, automation, releases and documentation. It is
not a new full runtime/security audit of every product feature or a benchmark
certifying the named models.
