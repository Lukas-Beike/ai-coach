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
`backend/runtime/` changed. The full suite runs when `backend/db/manager.py`,
`backend/db/bootstrap.py`, `backend/db/migrations.py`, the test harness
(`tests/run_tests.py`, `tests/changed_tests.py`, `tests/support.py`,
`tests/server_test_support.py`), or dependency and build files
(`requirements*`, `Dockerfile`, `pyproject.toml`) changed, when a source
cannot be parsed, or when the selection covers at least 80% of the test
modules; the run prints the reason. A changed file under `tests/fixtures/`
selects every test whose sources or imported modules name `fixtures` as a path
segment (loaders build fixture paths from parts); a fixture in a subdirectory
such as `tests/fixtures/chart-golden/` also needs that subdirectory named the
same way, unless one of those modules scans directories. Every change also selects
`test_line_endings` and `test_ai_docs_contract`, which check tracked files
across the repository. The slow tooling modules
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
.\tests\run_sqlcipher_tests.ps1 -Suite all -RecordDurationsDirectory $env:TEMP\durations
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
By default it runs CI's `container_tests` selection (`--suite container`), which
includes the SQLCipher migration, upgrade and restore modules. `-Suite all` runs
every module; duration recording and coverage require it. It finishes green: the
repository files tests read are mounted, `/tmp` allows the temporary scripts some
tests run, and the few Windows-, PowerShell- or Node-only tests skip with their
reason, which each shard's `result.json` lists under `skip_reasons` (#2553).

```powershell
./tests/run_sqlcipher_tests.ps1
./tests/run_sqlcipher_tests.ps1 -Suite all -Workers 2 -CacheState warm
./tests/run_sqlcipher_tests.ps1 -Workers 1 -ResultsDirectory $env:TEMP\coach-test-results
```

The serial default is preserved; `-Workers` accepts 1-4, with two as the first
benchmark candidate. Each run owns a unique directory below
`$env:TEMP/ai-coach-tests` (or the supplied parent), with `summary.json`, per-shard
selection/results and logs. Failed, missing, inconsistent or interrupted shards
cannot report complete success. Every class remains in one shard; all selected
IDs must form the complete selected suite exactly once. Compare complete one- and
two-worker runs on the same host, including the additional CPU/memory and summed
runner time, before increasing concurrency.

For modules that need the image's dependencies (`garminconnect`, SQLCipher),
`python scripts/run_sqlcipher_tests.py --module <test module>` (repeatable) runs
only those modules in the same container with the same mounts, including `docs/`
and `openspec/`; without `--suite` it selects from every module.

Coverage is optional. Prepare an offline wheel matching the locked dev pin and
the image's Python/Linux architecture separately; for the default amd64 image:

```powershell
$coverageVersion = (Select-String -Path requirements-dev.txt -Pattern '^coverage==([^ \\]+)').Matches.Groups[1].Value
python -m pip download --only-binary=:all: --no-deps --platform manylinux_2_17_x86_64 --python-version 314 --implementation cp --abi cp314 --dest $env:TEMP\coverage-wheels "coverage==$coverageVersion"
# Pass the downloaded .whl path explicitly:
./tests/run_sqlcipher_tests.ps1 -Suite all -Workers 2 -CoverageWheel $env:TEMP\coverage-wheels\coverage-<version>-<wheel-tags>.whl
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
own disposable SQLCipher fixture. `python scripts/prepare_worktree.py` prepares
the locked native browser and the image; after source changes, rebuild the
image before running locally:

```powershell
npm ci --ignore-scripts
node node_modules/@playwright/test/cli.js install chromium
docker build -t "$(python scripts/run_browser_tests.py --print-image)" .
python scripts/run_browser_tests.py --project all --list
python scripts/run_browser_tests.py --project mobile --spec e2e/css-cascade.spec.js
python scripts/run_browser_tests.py --project all --jobs 1 --cache-state warm
```

The image tag is per checkout, so parallel worktrees keep their own builds.
`--list` starts no containers. A project/spec selection reports its focused scope;
unknown projects, missing specs, invalid shards and empty selections fail. Desktop
runs every functional contract, and the two smaller projects repeat only
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
The runner stops before starting any fixture when the application image's copy
of `requirements.txt`, `server.py`, `backend/` or `public/` differs from the
working tree, and names the rebuild command; when it cannot compare them it warns
and runs (#2644). A new `public/` file is served from the
directory listing (`backend/http_api/static_assets.py`); add it to the
service-worker `ASSETS` list only if it is cached. A failed child prints a failing test's location and first error
line; its manifest entry lists all of them under `failures`. The run stops at the first failed child;
`--keep-going` runs every child and reports all failures (exit stays non-zero).

CI builds and shares the current application image once, then starts browser
jobs beside the native suite. Its prepared browser image is pinned by exact
version and digest in `scripts/browser_environment.json`; ordinary matrix jobs
pull that image and install no browser OS packages. The runner checks the locked
package and installed browser revisions before tests. The required `Browser
checks` aggregate rejects failed/missing shards and incomplete or duplicate
selection evidence. Summaries of every run attempt are kept and each shard's latest attempt
counts, so rerunning only the failed jobs is valid.
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
Add CI shards or local lanes only when measured critical-path gains justify the
additional runner-minutes (#2536 split mobile and tablet-landscape). The full isolated selection can take substantial time
on Docker Desktop; retain its manifest and wait for the terminal result.

Follow the [disposable browser validation notes](../.agents/skills/pacecraft-pwa-e2e/references/browser-validation.md)
for manual login, PWA/offline and UI checks. Never target a connected installation.
Direct `npm run test:e2e` remains available for an explicitly prepared fixture;
stateful specs require the shared runner's fresh per-file fixtures.

Configured viewports in `playwright.config.cjs`:
- `mobile`: 390x844 (Standard mobile)
- `tablet-landscape`: 844x390 (Phone landscape)
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
SQLCipher helper above. For browsers, retain the complete three-project selection
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

The provisional goals of the archived `accelerate-test-execution` change are a
GitHub validation median below six minutes and at least 30% less local wall time
for each complete Python and browser selection against its own newly captured
baseline. Report each goal as met, missed, or unverified. Timing goals do not
change correctness results, required checks, assertions, retries, or timeouts.

Results (#2149, one warm sample each on one Windows host, source `a821c26c`).
The baseline is the serial mode of the same runner. A pre-change baseline with a
comparable selection no longer exists, so this shows parallel against serial,
not the gain over the old runner:

| Measurement | Baseline | Comparison | Result |
| --- | --- | --- | --- |
| Browser, 3 projects, 187 specs, native Chromium, all passed | `--jobs 1`: 1425.8 s | `--jobs 2`: 909.4 s, summed child time +21% | -36.2%, met against serial |
| Python `-Suite all`, 9,358 tests | `-Workers 1`: 278.1 s | `-Workers 2`: 164.6 s, summed test time +6.8% | -40.8%, unverified |
| GitHub PR validation, five natural successful runs, creation to completion | median 18.9 min (#2149) | hosted runners (#2536): 17.1 min before, 9.0 min with two shards per browser project | lower, partly lighter queueing; six-minute goal missed |

GitHub split (#2536): five natural successful PR runs of `publish-container.yml`
on 2026-11-13 (43407572797, 43407637046, 43408243035, 43408548488,
43410126789), from workflow creation to completion, median 17.1 min (14.6 to
20.4). Queue time per job was 0.1 to 4.8 min; execution decided the critical
path. The last job before the aggregate was the single `mobile` browser job in
four runs and `tablet-landscape` in one: `mobile` ran 8.1 to 11.8 min and
`tablet-landscape` 8.6 to 10.7 min of tests, against 4.7 to 7.0 min per
`desktop` shard. The native chain (`test` aggregate, then incremental quality
checks) ended at 5.8 to 12.9 min, driven by up to 4 min of queue before the
aggregate. Browser jobs start 1.6 to 5.1 min after creation (source and image).
The 16 jobs of a run summed 41.2 to 45.3 runner-minutes of execution and 11.4
to 39.0 min of queue; each extra browser shard repeats about 0.7 min of setup.
The mobile and tablet-landscape projects therefore run as two shards each, like
desktop; the required check names stay unchanged. Six minutes stays out of
reach while the image, the queue and the native chain together take about that
long.

After the change, five natural successful PR runs on 2026-11-13 (43440109218,
43441233129, 43444249213, 43445764847, 43446210240) took 7.9 to 9.5 min, median
9.0 min. The six browser shards ran 4.2 to 7.0 min each; the last job before
the aggregate was a desktop shard in four runs and a mobile shard in one; the
largest queue of any job was 0.1 to 1.1 min and the 18 jobs queued 0.6 to 6.8 min
in sum (before: up to 4.8 min per job and 11.4 to 39.0 min in sum, under heavier
load, so part of the gain is lighter queueing); execution summed 40.7 to 45.4
runner-minutes, about the same as the 41.2 to 45.3 before. The
native chain ended at 2.8 to 6.0 min.

A third desktop shard was measured and removed again (#2616). The first five
natural successful PR runs with it on 2026-11-13 (43491144122, 43492630371,
43493529959, 43494276049, 43494889569) took 8.3 to 10.3 min, median 9.9 min,
against 9.0 min with two. The three desktop shards ran 3.6 to 6.1 min each, but
the last job before the aggregate became a mobile or tablet-landscape shard in
three runs (5.8 to 7.5 min); the 20 jobs summed 45.6 to 48.7 runner-minutes,
about 3 more, and the largest queue of any job was 0.7 to 2.1 min. Desktop
therefore stays at two shards. Six minutes stays missed while source, image and
one browser shard take about seven.

The Python goal stays unverified: both runs ended with the same 18 checkout/Git
environment failures that #2553 later removed, and an earlier same-host
sample on 26 October 2026 (7,289 tests, 728.71 s against 525.62 s) gave 27.87%.
Browser fixture readiness is hidden by prewarming:
6.9 s of readiness wait in 1425.8 s, median per spec 0.03 s, fixture start 0.32 s,
authentication 0.49 s, test 4.28 s. Setup cost: application image without layer
cache 9.8 s (warm 0.6 s), Chromium download 16.8 s (warm 0.4 s), `npm ci` 10.1 s
with an empty cache and 10.6 s warm (install-bound, not download-bound), prepared browser image pull 34.9 s (warm 0.3 s).
On Windows, `--browser-image` fails explicitly (Linux host networking); CI runs
the prepared image on every PR.

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
Version 8 is current. Version 6 added review scenarios on top of the v5 data: a rest day and a sick
day with illness text in the check-ins, a planned 30-minute Swim unit with
planned load next to a 20-minute swim at 11:00 and a fitting 30-minute swim at
18:00 on the same day (activity matching ambiguity), a
`[NO_INTENSITY]` camp day with a hard planned unit, a weekly `[SHORT_ONLY]`
series with a 90-minute ride. Upgrades from v5 add these records once; repeated
seeds and restarts keep the counts stable. Version 7 completes the synthetic
Garmin history (race predictions, thresholds, readiness, sleep and body battery),
adds manual nutrition products on gram and millilitre bases (one archived) and
reusable library templates for Ride, VirtualRide and Run. Version 8 adds one
distance-based run, "Tempolauf nach Distanz", on the first free day from day 4 on.
The default seed does not add a long
chat history; longer conversations are added on demand for specific scenarios.

`FIXTURE_OPENAI_MODE` controls the simulated OpenAI path. The default
`canned` keeps the canned Coach replies. `offline` makes each Coach
request fail as an unreachable OpenAI endpoint (`network_error`) without any
network call; the simulated failure does not reproduce the original transport
error details. Unknown values stop the fixture at startup. OpenAI stays
deliberately configured with a fake key (`OPENAI_API_KEY="e2e-fixture-openai-key"`)
in every mode, so Coach requests still take the normal Responses API path and no
real credential is needed.

Use a fresh fixture browser profile and check the mobile
project when reviewing this preview.

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
