---
name: orchestrated-plan-implementation
description: Always use for repository work, including implementation, documentation and skill changes, reviews, evaluations, and retrospectives. Coordinate isolated subagents with three user-selected model tiers and live provider discovery; the parent verifies results and alone adopts patches. Status answers and coordination do not require new workers.
license: MIT adaptations; see ../THIRD_PARTY.md.
---

# Provider-agnostic orchestration

The current parent owns scope, planning, coordination, personal review, and
integration. Workers perform bounded tasks; only the parent adopts patches.
Keep the current orchestrator model. Roles do not imply a provider or permission.

## Scope and workflow owners

This is the default workflow for every repository work session, including skill
authoring and the mandatory closing retro. Root AGENTS supplies standing
authorization for bounded delegation; no separate orchestration request is needed.
Reuse the session's model mapping rather than renegotiating it at each phase.
Status answers and coordination remain parent responsibilities without new workers.
Select implementation, review, or evaluation from the requested work.
Orchestration owns model selection, isolation, scheduling, and result handling.
Load only the applicable owner for task-specific rules:

## Choose execution mode before model questions

First decide whether workers are needed and whether this host can dispatch them
and collect required choices. Use **sequential parent-only mode** for read-only
reviews, genuinely trivial low-impact work, or when delegation/user interaction
is unavailable and the task can safely be completed without workers. This mode
still follows the applicable workflow, source identity, validation, and reporting
rules. Hosted and noninteractive reviewers must be able to complete read-only
reviews this way without prompts or child tasks. Do not ask for or claim worker
model tiers when no worker will be dispatched; report that the parent performed
the work sequentially and any resulting limitation. A missing tool or unanswered
choice is not itself permission to use this mode when workers are needed.

If the user explicitly requires delegated workers or an exact worker contract,
preserve that requirement and report the blocker when unsupported or unanswered;
do not substitute parent execution. Account/login/tool setup remains unauthorized
unless separately authorized. Never use sequential mode to bypass parent review
and adoption of an active worker candidate, a PR review gate, or authorization
for a remote action. Closing retrospectives may use the same sequential mode and
must not recursively spawn workers.

- [code-review](../code-review/SKILL.md): PR/branch-diff review criteria;
  [codebase review](../ai-coach-codebase-review/SKILL.md): full audits.
- [skill evaluation](../ai-coach-skill-evaluation/SKILL.md): repository-skill
  evaluation design, comparisons, and evidence.
- [validation](../ai-coach-validation/SKILL.md): affected application checks.
- [pr](../pr/SKILL.md), when invoked/authorized: mandatory PR review gate,
  round limits, waivers, and publication/merge lifecycle.

Review-only work returns findings without source edits. Evaluation-only work
permits its owner's scoped temporary artifacts, without adopting source changes
unless requested. Patch-adoption steps apply only to authorized source changes.
Every mode requires parent verification of results and inspected source identity.

## Select worker model tiers when dispatching workers

Inspect repository instructions, branch, worktree, and existing diff. Record the
objective, endpoint, acceptance criteria, exclusions, and starting tree identity.
Preserve user work and existing authorization.

Before any worker starts, inspect live delegation schemas and discover runnable
provider instances, model IDs, supported options, isolation, and limits. In T3
use `orchestrator_capabilities`; search omitted/requested models rather than
assuming the short catalog or native tool enum is exhaustive. Exclude disabled
or uninstalled providers and models unsuitable for the task.

Check official vendor release/model documentation by default when recommending
current models. Intersect documented releases with the runnable catalog. Catalog
presence establishes configured availability, not release recency, authentication
health, actual upstream identity, price, or quality. Date recommendations; if
release verification is unavailable, label recency unverified. Do not infer
newest/best/cheapest from names, list order, or custom aliases.

Only in delegated mode, ask the user once, in their language, for these complexity/risk tiers, giving
one recommended provider/model/effective-options tuple and useful alternatives
per tier, with a brief rationale:

| Tier | Suitable tasks |
| --- | --- |
| L1 simple | Bounded lookup, mechanical edits, clear local changes with an inexpensive acceptance check |
| L2 standard | Established feature work, multi-file fixes, focused tests, routine review |
| L3 complex/critical | Architecture, hard diagnosis, migrations, integrity/auth changes, independent critical review |

These are not design/implementation/test phases. File count alone does not
establish risk: a one-line authorization defect can be L3. Reuse an explicit
mapping for this run; ask only for missing choices. A single model selected for
all workers fills all tiers; per-task overrides win. Wait for required choices
before dispatch; recommendations, preselection, silence, and time are not answers.
Independent preparation may continue without another execution approval.

Preserve selected effort, fast mode, and service tier exactly. Record and pass
supported option keys in tool arguments, not just prompts. In T3 options inherit
only for the same provider instance AND model; explicit entries override values,
while `{}` or `[]` clears inheritance. Verify returned provider/model/options
against the effective selection; stop mismatched runs and do not treat their
output as the requested model's work. Report unsupported settings without
silently reducing them. Escalation within the approved tier mapping needs an
update/ledger entry; changing outside it needs a new selection.

When workers are required or explicitly requested, missing capability/auth/quota
is not permission to substitute models or silently move that work to the parent;
preserve the worker contract and report the concrete blocker. A declared
sequential parent-only mode is permitted only under the conditions above, not as
a silent model or account substitution. Installing tools, changing
accounts/routing, or reading credentials remains unauthorized. Preserve
independent progress and explain the concrete limitation.

## Plan, brief, and isolate

Use the smallest executable plan. Obtain bounded design/critique only when
uncertainty warrants it. Assign each task an ID, role, tier/reason, allowed paths,
dependencies, interface contracts, acceptance checks, and required evidence.
Dispatch only after prerequisites are accepted. Serialize shared files or changing
producer/consumer contracts; separate files alone do not establish independence.
Use the owning validation/evaluation workflow rather than duplicate its rules.

Keep a resumable ledger and artifacts outside tracked source unless requested
as deliverables. Record its absolute location in handoffs. Retain objective,
source identity/dirty state, effective model mapping, owners/dependencies,
task handles/request keys/worktrees, states, attempts, candidate identities,
parent decisions, evidence, findings/responses, limitations, and next actions.
Distinguish running, waiting, result-ready, integrated, verified, and blocked.

Every worker gets a separate disposable source worktree and a self-contained
brief: objective/plan excerpt, mode/owning workflow, model/options, workspace and
base identity, allowed paths/interfaces, accepted dependencies, applicable
instructions including scan-before-read, acceptance checks, and handoff contract.
Do not assume it sees parent conversation. Never copy secrets, athlete data,
runtime state, or unrelated untracked files.

Implementation workers edit only their assigned tree/scope and run isolated
checks. Review workers inspect/run checks without source edits; evaluation
workers create only their brief's permitted artifacts. No nested agents, shared
integration/ref/config edits, commits, push, PRs, merges, deployments, external
messages, live providers/data, or destructive cleanup. Worktrees reduce
interference; they are not an OS sandbox or enforced access control.

Verify the actual starting tree, including setup-created changes. For dependent
work prepare an accepted local checkpoint under existing authorization, excluding
unrelated user changes. Otherwise use a supported isolated snapshot with a
recorded content identity; if neither is possible, report the baseline blocker.
Reviewers must receive the exact frozen candidate, including uncommitted changes,
through a permitted artifact mechanism, not just an older committed baseline.

Bound concurrency by host/user/fixture limits; default to at most three workers
when no tighter limit is known, reserving parent capacity. Record handles before
further dispatch. Prefer asynchronous completion notifications; yield after
dispatch on event-driven hosts. Otherwise use bounded waits/status checks.
Do not busy-poll, spawn watchers, or treat a wait timeout as cancellation.

## Runtime binding

Inspect the host's current schemas; do not invent flags or capabilities.

- **T3:** use `delegate_task` with `isolation: "worktree"`, explicit
  `target.providerInstanceId`, `target.model`, supported `target.options`, role,
  complete brief, and normally `mode: "async"`. This is required for isolated
  checkout binding, cross-provider work, native-unsupported models, requested
  options, and same-model nonempty inherited options. Its worktree starts from
  the parent's local commit, excludes uncommitted edits, and runs project setup.
- T3 task handles are `taskId` for `task_status`/`task_cancel`; `childThreadId`
  is backing storage. Use stable `clientRequestId` on retries of a lost response
  to avoid duplicates. For each new revision/review round call `delegate_task`
  again with a new key, original brief, current baseline/candidate, prior findings,
  responses, and unresolved objections. Do not continue review rounds through
  `t3_thread_send`. Use `workState`/`hasPendingChildRuns` to check remaining writers.
- Missing lazy T3 tools warrant one bounded direct capabilities attempt; use the
  host-documented `acp-mcp-call` fallback when advertised, without raw provider
  CLI/account setup. `t3_thread_launch`/`create_threads` are top-level conversations
  and require a separate-thread request; do not substitute them for child tasks.
- **Other hosts:** native delegation is suitable only if exact model/options,
  isolated source, and lifecycle requirements are supported. Prepare worker
  worktrees in the parent when no binding facility exists. With
  `collaboration.spawn_agent`, overrides require `fork_turns: "none"` and a
  complete brief. Use no invented enum values or inheritance modes.
- Keep runtime permissions inherited unless the user chooses a supported mode.
  Answer factual child questions from authorized context; pending permission
  approvals stay with their existing approval holder. Question tools cannot
  grant permission. Cancel through the adapter owning the task handle.

## Verify results and adopt patches

For read-only review/evaluation, require inspected input/source identity, actual
coverage, findings/outcomes with evidence, checks, artifacts, and limits. Parent
reconciles results under the owning workflow; no patch manifest is required
without source changes.

For source changes, confirm all writers have stopped and freeze the complete
candidate with base identity, artifact/manifest, and content hash such as SHA-256.
Include untracked additions, deletions, renames, modes, and binary assets;
tracked `git diff` alone is insufficient. Scan before reading; later edits
invalidate review. Keep reports/patches free of secrets and athlete content.

The parent personally inspects every changed file/asset and relevant surrounding
flow, verifies behavior/contracts and meaningful checks, and records accept,
revise, or reject with identity/evidence/reasons. For complex/critical changes
obtain independent L3 critique under the relevant review criteria; supply the
candidate/contracts without the author's self-assessment. Resolve findings by
evidence, not model rank or votes. A partial acceptance needs its own frozen
artifact/review. Worker reports, extra reviewers, and green tests do not replace
parent inspection.

Before adoption verify the integration tree's expected identity and patch
applicability (`git apply --check` for Git patches). Only the parent applies
accepted artifacts. No blind cherry-picks, whole-tree replacement, automatic
conflict resolution, or reset of user work. On drift/conflict delegate regeneration
against the new baseline and review afresh; the parent does not write repairs
to bypass adoption. Inspect the result and run affected integration checks.

Patch acceptance never replaces the mandatory PR gate. Use the PR owner's final
branch range, evidence, waiver rules, and round limit. Record PR rounds separately
from worker attempts; invocations performed as part of that gate count under its
rules, including delegated execution. Worker budgets cannot reset/extend it.

## Recover and complete

User updates steer the existing objective unless clearly replacing/cancelling
it. Invalidate affected tasks/candidates and continue independent work. On stop,
cancel the named/all requested tasks and confirm writers stopped before cleanup.
Retain artifacts. After compaction/resume reconcile ledger, handles, source,
model choices, and unresolved findings; do not duplicate active work.

Diagnose before retrying. Default to one targeted repair after the first failed
result; after a second, re-scope or escalate within approved tiers. At most three
attempts per task, without renaming to reset counts; user bounds and stricter
owner-workflow limits take precedence. Preserve accepted work, report concrete
blockers, and never weaken checks or silently change models/options.

For implementation review the combined final diff and run required validation
on the final integrated tree. For reviews/evaluations verify coverage and evidence
under their owner. Report behavior/results, effective models/options, accepted
work, checks, limits, and pending/blocked criteria. Do not equate worker completion
with verified feature completion. Distinguish local changes, commits, PR, merge,
publication, and deployment with evidence. Continue already-authorized external
work under its workflow; no new permissions or blanket approval are implied.
Use T3 PR linking/watch facilities when available and applicable. Remove only
confirmed disposable resources after writers stop and artifacts are retained.
Before the final session completion or blocked handoff, run
[retro](../ai-coach-retro/SKILL.md) under the same model mapping, then report its
concise conclusions. Waiting for active tasks or model choices is not a session
ending; do not launch recursive retrospectives of the retro itself.

## Source assessment

Reviewed 2026-10-22; pinned revisions and MIT notices are in
[THIRD_PARTY.md](../THIRD_PARTY.md). This is a design assessment, not a benchmark.

- **Oliviero Pinotti/orchestrator:** retain asynchronous dispatch, durable ledger,
  and complete briefs. Replace fixed Claude/model defaults, unconditional
  delegation, nested orchestrators, shared writes, and summary-only acceptance
  with live choices, bounded parent scheduling, isolation, and patch review.
- **Alireza Rezvani/Orchestration Protocol:** retain objective-first phases,
  role/method/task separation, and explicit handoffs without a new framework.
  Personas are not independent review, and skills can conflict; add instruction
  precedence, concrete lifecycle/isolation, and verified completion.
- **eddiearc/dev-orchestrator:** design critique, proportional workflow depth,
  validation, and visible deviations are useful concepts. Reject fixed
  Gemini/Codex/Claude roles, assumed logins, auto-approval CLI examples, deferred
  testing, blanket human approvals, and missing artifact gates. At revision
  `300e9ade5161e27916159f178112c4cfc9300c33` no license was found; its text,
  diagrams, and templates are not copied or redistributed.

When maintaining this skill, use the skill-evaluation workflow with positive and
non-trigger cases plus boundaries: partial/preselected model choices, unsupported
options, lost async responses, dirty baselines, omitted new files, candidate drift,
read-only tasks, PR round limits, cancellation, and resumed runs. Static checks
and manual walkthroughs are not independent model-behavior benchmarks.
