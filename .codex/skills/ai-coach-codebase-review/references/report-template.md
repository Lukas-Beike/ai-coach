# Full-review report format

Write the report in the user's language. Keep code identifiers and commands exact.

## Severity

- **P0 Critical:** credible immediate credential compromise, arbitrary code execution, unrecoverable broad athlete-data loss, or unauthorized high-impact remote mutation.
- **P1 High:** serious security/privacy breach, durable corruption, authorization bypass, repeated remote mutation, or core coaching/sync flow failure under realistic conditions.
- **P2 Medium:** actionable correctness, reliability, accessibility, performance, or recovery defect with meaningful but bounded impact.
- **P3 Low:** real, localized robustness or maintainability problem with a concrete failure mode. Pure preferences and speculative hardening are not findings.

## Required structure

### Review scope

State commit, branch, dirty-tree status, whether this is a full repository review, instructions applied, excluded sensitive/runtime paths, and important environment limitations.

### Findings

Put findings first, ordered by P0 to P3 and then by impact. If there are none, say that no actionable findings were identified; do not imply proof of correctness.

Use this shape for each finding:

```text
[P1] Short imperative title — path/to/file.py:123

Evidence: What the code does and the end-to-end path that reaches it.
Trigger: Minimal realistic condition or reproduction.
Impact: Concrete effect and affected invariant/data/boundary.
Remediation: Smallest sound fix, including compatibility or migration concerns.
Regression test: Observable test that fails before and passes after.
Confidence: high | medium | low
```

Reference the narrowest useful line span in prose, but do not omit relevant callers in the explanation. Merge related symptoms under one root-cause finding.

### Cross-cutting observations

List non-finding design risks, systemic test gaps, or refactoring candidates separately. Make clear why they are not classified as confirmed defects.

### Coach-first verdict

State whether the Coach is demonstrably the reliable primary interface. Summarize:

- capability parity between UI/API operations and Coach tools;
- direct execution of explicit authorized requests versus protected special cases;
- message-lifecycle reliability and recovery;
- tool selection, durable effects, receipts, and truthful final wording;
- current-data and named-sync behavior across integrations.

Do not give a passing verdict while any core Coach capability, disappearing-message scenario, tool path, or unexplained 400 response remains untested or blocked.

### Validation

For each command or manual check, report passed, failed, or not run and why. Include syntax, unit, isolated container, browser, static-analysis, and dependency checks when applicable. Never say "all tests pass" if only a subset ran.

For local UI validation, record the runtime/container identity, viewport, browser, test-data mode, and flows exercised. Do not include passwords, cookies, provider payloads, screenshots with athlete data, or other secrets in the report.

### Coverage ledger

Include all 18 checklist domains:

| Domain | Main evidence inspected | Validation | Result | Remaining gap |
|---|---|---|---|---|
| Authentication and HTTP | `server.py`, request/response helpers, tests | unit/static | finding / clean / blocked | ... |

`clean` means reviewed without an actionable finding, not proven defect-free. `blocked` requires a specific reason.

Also include the detailed ledgers required by `coach-first-usage-audit.md`:

- Coach capability and tool parity;
- message lifecycle and race/interleaving coverage;
- frontend/backend API contracts and injected error classes;
- provider states, named syncs, partial failures, and recovery;
- complete user journeys by viewport and interaction mode.

Large ledgers may be attached as separate Markdown tables, but the report must summarize every blocked or failing row. Do not collapse several unexecuted scenarios into an unexplained "partial" label.

### Areas checked without actionable findings

Call out important trust boundaries and critical flows that were examined and found internally consistent. This is coverage evidence, not praise or a guarantee.

### Limitations and follow-up

Identify unavailable runtime evidence, skipped suites, platform constraints, external API assumptions, and low-confidence leads. Separate these from findings.

### Completion statement

State one of:

- `Complete for the recorded source snapshot; all checklist domains were reviewed or explicitly blocked.`
- `Incomplete; the following checklist domains still require review: ...`

Never claim exhaustive coverage of runtime behavior solely from static review.
