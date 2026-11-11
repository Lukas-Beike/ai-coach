# Testing and quality assurance

The [Coach dialogue evaluation rubric](coach-dialogue-evaluation.md) and [executable tool coverage matrix](coach-tool-coverage.md) describe the current conversation and tool checks.

The current HTTP route inventory is in [docs/api-routes.md](api-routes.md).

## Native Python Unit Tests
Run standard unit tests with temporary in-memory fixtures (mocking external providers):
```powershell
python -m unittest discover -s tests -v
python -m compileall -q server.py backend tests
```

## Changed-Test Selection
Local runs can skip modules a change cannot affect. `--changed` compares the
merge base with `--base` (default `origin/develop`), including uncommitted and
untracked files, and runs only the test modules `tests/changed_tests.py` selects:
modules whose file changed, that transitively import a changed module, or whose
string literals name a changed path or module; a data file under `backend/`
selects the tests of the module that names it. Imports reached only through
`server.py` count only when `server.py`, `backend/http_api/`, or
`backend/runtime/` changed. Changes under
`backend/canonical/`, `backend/db/`, `tests/fixtures/`, the test harness, or
dependency and build files run the full suite. The slow tooling modules
`test_fixture_standard_data` and `test_ci_contracts` run under `--changed` only
when their own inputs change (the fixture runtime under `e2e/` and the test
fixtures, or the CI workflows, build, dependency and test-runner files), even if
an imported backend module changed; the run prints why it skipped them. CI
always runs everything:
```powershell
python tests/run_tests.py --changed
python tests/run_tests.py --changed --list
```

## Parallel Sharded CI Runner
CI splits the native suite into `PYTHON_TEST_SHARDS` shards (currently 4). Each
shard keeps every `TestCase` class whole, so class-level fixtures such as
`ServerTestCase.setUpClass` run once per class. Classes are assigned heaviest-first
to the least-loaded shard, so the assignment is deterministic and does not depend
on discovery order. A class weighs its recorded wall time from
`tests/test_durations.json`; a class without a recording weighs its test count
times the median recorded seconds per test. The quality job fails unless every
shard uploads exactly one coverage file. Run one shard locally, or list its test
IDs without running them:
```powershell
python tests/run_tests.py --shard 1 --total 4
python tests/run_tests.py --shard 1 --total 4 --list
```
Refresh the recording when shard times drift apart, with a full unsharded run in
the image. The Windows runner uses the same read-only mounts and writes the file
into the given directory, which then replaces `tests/test_durations.json`:
```powershell
New-Item -ItemType Directory -Force $env:TEMP\durations | Out-Null
.\tests\run_sqlcipher_tests.ps1 -RecordDurationsDirectory $env:TEMP\durations
Copy-Item $env:TEMP\durations\test_durations.json tests\test_durations.json
```

## Container-Sensitive Suite
`--suite container` runs only the modules that depend on the container runtime:
SQLCipher, the read-only non-root runtime, configuration, startup, security limits,
privacy, and authentication sessions. The CI `container_tests` job runs this subset
inside the built image. The default `--suite all` runs everything:
```powershell
python tests/run_tests.py --suite container --list
```

## Isolated SQLCipher Integration Tests

The PowerShell helper delegates to the standard-library supervisor. It builds
current application source once, then derives a disposable test image with Git
for synthetic repository tests; production `Dockerfile` stays unchanged. Tool
preparation may use the network, but tests run as the app user in read-only,
networkless containers with temporary data, one CPU and 512 MiB per worker.
Explicit read-only test inputs exclude the checkout root, `.git`, `.env` and live
data. Application server/backend/public files come from the current image.

```powershell
./tests/run_sqlcipher_tests.ps1
./tests/run_sqlcipher_tests.ps1 -Workers 2 -CacheState warm
./tests/run_sqlcipher_tests.ps1 -Workers 1 -ResultsDirectory $env:TEMP\coach-test-results
```

The serial default is preserved; `-Workers` accepts 1-4, with two as the first
benchmark candidate. Each run owns a unique directory below
`$env:TEMP/ai-coach-tests` (or the supplied parent), with `summary.json`, per-shard
selection/results and logs. Failed, missing, inconsistent or interrupted shards
cannot report complete success. Every class remains in one shard; all selected
IDs must form the complete discovery set exactly once. Compare complete one- and
two-worker runs on the same host, including the additional CPU/memory and summed
runner time, before increasing concurrency.

Coverage is optional. Prepare an offline wheel matching the locked dev pin and
the image's Python/Linux architecture separately; for the default amd64 image:

```powershell
$coverageVersion = (Select-String -Path requirements-dev.txt -Pattern '^coverage==([^ \\]+)').Matches.Groups[1].Value
python -m pip download --only-binary=:all: --no-deps --platform manylinux_2_17_x86_64 --python-version 314 --implementation cp --abi cp314 --dest $env:TEMP\coverage-wheels "coverage==$coverageVersion"
# Pass the downloaded .whl path explicitly:
./tests/run_sqlcipher_tests.ps1 -Workers 2 -CoverageWheel $env:TEMP\coverage-wheels\coverage-<version>-<wheel-tags>.whl
```

The supervisor verifies the wheel hash against `requirements-dev.txt`, installs
it offline into temporary test storage, and combines exactly one independent
coverage file per successful shard. It retains the originals and the combined
`coverage/.coverage`; missing coverage blocks success. No dynamic per-test
coverage contexts are enabled. Duration recording remains a complete, unsharded
operation; `-RecordDurationsDirectory` cannot be combined with multiple workers,
and failed/partial/list runs never overwrite the authoritative recording.

## Playwright Browser E2E Tests

The shared runner lists the locked Playwright selection and gives every spec its
own disposable SQLCipher fixture. Prepare the locked native browser and build
current application source before running locally:

```powershell
npm ci --ignore-scripts
node node_modules/@playwright/test/cli.js install chromium
docker build -t "$(python scripts/run_browser_tests.py --print-image)" .
python scripts/run_browser_tests.py --project all --list
python scripts/run_browser_tests.py --project mobile-small --spec e2e/css-cascade.spec.js
python scripts/run_browser_tests.py --project all --jobs 1 --cache-state warm
```

The image tag is per checkout, so parallel worktrees keep their own builds.
`--list` starts no containers. A project/spec selection reports its focused scope;
unknown projects, missing specs, invalid shards and empty selections fail. Desktop
runs every functional contract, and the four smaller projects repeat only
`@responsive` scenarios. Use `--shard 1 --total 2` and `--shard 2 --total 2` for
complementary whole-file selections. Assignment uses the frozen
`e2e/browser_durations.json` weights, longest first to the least-loaded shard,
with a project's median (one second when unmeasured) for new files. Weights never
exclude tests. Replace weights only from comparable complete per-project records,
including environment/source identity; do not update them during a run.
The current weights are one warm native Windows observation per project, with
source/tool/image provenance in the file; they are not a Linux CI benchmark.

One process is the local default; `--jobs 2` is the bounded concurrency trial.
There is still one Playwright worker per spec. The two prewarm slots per process
have distinct containers, stable networks and loopback ports. Runs use separate
private authentication files and a unique result directory under
`test-results/browser-runs/` (override its parent with `--results-dir`).
`manifest.json` records selection, source, environment, phase times, child exits
and final status. Pending or interrupted records are unverified. Keep private
storage state and traces out of reports; the runner disables traces.
The runner warns when the application image's copy of `requirements.txt`,
`server.py`, `backend/` or `public/` differs from the working
tree; rebuild it before trusting results. A new `public/` file also needs an
entry in `STATIC_TARGETS` (`backend/http_api/static_assets.py`), which a unit
test enforces. A failed child prints a failing test's location and first error
line; its manifest entry lists all of them under `failures`. The run stops at the first failed child;
`--keep-going` runs every child and reports all failures (exit stays non-zero).

CI builds and shares the current application image once, then starts browser
jobs beside the native suite. Its prepared browser image is pinned by exact
version and digest in `scripts/browser_environment.json`; ordinary matrix jobs
pull that image and install no browser OS packages. The runner checks the locked
package and installed browser revisions before tests. The required `Browser
checks` aggregate rejects failed/missing shards and incomplete or duplicate
selection evidence. Summaries are scoped to the GitHub run attempt; rerun all
jobs to supply a complete matrix rather than rerunning only failed jobs.
Summaries are uploaded separately from failure reports; authentication remains
in private temporary storage.

Prepared browser execution uses Linux host networking. Windows keeps the native
browser path above. On a Linux host, pull the pinned image, then pass it explicitly:

```sh
browser_image="$(python -c "import json; print(json.load(open('scripts/browser_environment.json'))['image'])")"
docker pull "$browser_image"
python scripts/run_browser_tests.py --project desktop --browser-image "$browser_image"
```

When Playwright changes, resolve the matching upstream tag, inspect its digest
with `docker buildx imagetools inspect`, update the pin with the lockfile, and
verify observed browser revisions plus a disposable login/PWA run. A mismatch
fails explicitly. Measure complete cold and warm preparation costs; a warm cache
is not a cold-pull result. To roll back prepared execution locally, omit
`--browser-image` after preparing the locked native browser. CI rollback requires
restoring native browser/system preparation together with that invocation.
Keep the smaller matrix/serial path until measured concurrency gains justify
additional runner-minutes. The full isolated selection can take substantial time
on Docker Desktop; retain its manifest and wait for the terminal result.

Follow the [disposable browser validation notes](../.agents/skills/ai-coach-pwa-e2e/references/browser-validation.md)
for manual login, PWA/offline and UI checks. Never target a connected installation.
Direct `npm run test:e2e` remains available for an explicitly prepared fixture;
stateful specs require the shared runner's fresh per-file fixtures.

Configured viewports in `playwright.config.cjs`:
- `mobile-small`: 320x568 (Compact mobile)
- `mobile`: 390x844 (Standard mobile)
- `tablet`: 768x1024 (Tablet portrait)
- `tablet-landscape`: 844x390 (Mobile/tablet landscape)
- `desktop`: 1440x1000 (Desktop workstation)

## Measuring validation performance

Record performance against a frozen source revision and the same complete test
selection on the same host. Keep focused results separate. Save the revision,
working-tree changes, Python/Node/Docker versions, image identities, CPU/memory
limits, process count, and whether caches were cold, warm, or unknown alongside
start/end timestamps and the process exit code. Store these records outside
athlete storage; never include authentication state, credentials, or traces in
published evidence. An unfinished record is unverified, never a pass.

For Python, measure image build and test execution separately using the full
SQLCipher helper above. For browsers, retain the complete five-project selection
and fresh fixture per spec; measure image transfer/preparation, fixture readiness,
authentication, and execution separately. Do not compare a focused run against a
complete baseline or enable per-test dynamic coverage contexts for routine timing.

For GitHub, measure elapsed time from workflow creation until the required test,
browser, and quality gates finish, excluding review and publication. Report queue
time where available and sum job durations as runner-minutes separately from
wall time. Compare at least five naturally occurring successful runs with
comparable selections and environments before claiming an improved median;
report failed and cold-cache runs separately. Do not dispatch extra workflows
just to populate a benchmark.

The provisional goals of the archived `accelerate-test-execution` change (open measurements: #2149) are a GitHub validation
median below six minutes and at least 30% less local wall time for each complete
Python and browser selection against its own newly captured baseline. Report
each goal as met, missed, or unverified. Timing goals do not change correctness
results, required checks, assertions, retries, or timeouts.

A same-host complete SQLCipher comparison on 26 October 2026 ran all 7,289
tests exactly once with one and two workers (14 platform skips in each). Warm
whole-run time was 728.71 seconds versus 525.62 seconds, a 27.87% reduction in
one sample. This compares worker counts on the new runner, not a successful
pre-change baseline; browser and hosted improvement goals remain unverified.

## Standard synthetic preview data

Specialized staging/collision tests use `seed_fixture_planning_calendar(today)`
in a fresh temporary database. It shares the complete seed's planning/calendar
generation and omits unrelated history. `seed_preview_demo()` remains the
complete demo seed used by creation, upgrade, repeated-seed, and restart tests;
startup invokes it only when `FIXTURE_AUTO_SEED=1`.

The disposable fixture runtime exposes `GET /api/fixture/demo` for a reusable,
mobile-safe preview. It seeds profile, check-ins, nutrition, competitions,
library workouts, activity details, recovery, body history, Garmin daily
calories, dated Garmin FTP, calendar marker examples,
and active, archived, component, zero-target, no-target, and over-target gear.
All values are synthetic and providers remain blocked; no credentials or live
athlete data are read. The seed is idempotent and carries a version marker so
an older demo seed is upgraded in place when the disposable database is reused.
Version 6 adds review scenarios on top of the v5 data: a rest day and a sick
day with illness text in the check-ins, a planned 30-minute Swim unit with
planned load next to a 20-minute swim at 11:00 and a fitting 30-minute swim at
18:00 on the same day (activity matching ambiguity), a
`[NO_INTENSITY]` camp day with a hard planned unit, a weekly `[SHORT_ONLY]`
series with a 90-minute ride. Upgrades from v5 add these records once; repeated
seeds and restarts keep the counts stable. The default seed does not add a long
chat history; longer conversations are added on demand for specific scenarios.

`FIXTURE_OPENAI_MODE` controls the simulated OpenAI path. The default
`canned` keeps the canned Coach replies. `offline` makes each Coach
request fail as an unreachable OpenAI endpoint (`network_error`) without any
network call; the simulated failure does not reproduce the original transport
error details. Unknown values stop the fixture at startup. OpenAI stays
deliberately configured with a fake key (`OPENAI_API_KEY="e2e-fixture-openai-key"`)
in every mode, so Coach requests still take the normal Responses API path and no
real credential is needed.

Use a fresh fixture browser profile and check the mobile-small and mobile
projects when reviewing this preview.

`scripts/demo-container.ps1` builds the image and starts a disposable demo
container that seeds this data itself on every start (`FIXTURE_AUTO_SEED=1`).
Restarts keep the seeded data unchanged, including with `-Persist`; the
explicit `GET /api/fixture/features` and `GET /api/fixture/activity` test seeds
add their synthetic activities to the existing snapshot instead of replacing
it. Run it with
`powershell -ExecutionPolicy Bypass -File scripts/demo-container.ps1`; add
`-Persist` to keep the data in a named volume and `-Port`/`-Name` to adjust the
container. `-Name` must start with `demo` or `fixture` (optionally after an
`pacecraft-` or `ai-coach-` prefix); the production container `pacecraft` (formerly `ai-coach`) and every other name are
refused before anything is built, stopped or removed. The fixture refuses to
start unless `AI_COACH_DISPOSABLE_FIXTURE=1` is set; only the demo script and the
CI fixture container set it. The login password is the fixture password
`e2e-fixture-password-1234`. Never point it at a real `/data` directory.
