param(
    [string]$ImageTag = "ai-coach:local",
    # Directory that receives test_durations.json from a full run; see README.
    [string]$RecordDurationsDirectory = ""
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$testsDirectory = Join-Path $repositoryRoot "tests"
$docsDirectory = Join-Path $repositoryRoot "docs"
$publicDirectory = Join-Path $repositoryRoot "public"
$serverFile = Join-Path $repositoryRoot "server.py"
$e2eDirectory = Join-Path $repositoryRoot "e2e"
$playwrightConfig = Join-Path $repositoryRoot "playwright.config.cjs"
$githubDirectory = Join-Path $repositoryRoot ".github"
$toolsDirectory = Join-Path $repositoryRoot "tools"
$scriptsDirectory = Join-Path $repositoryRoot "scripts"
$pyprojectFile = Join-Path $repositoryRoot "pyproject.toml"
$dockerfile = Join-Path $repositoryRoot "Dockerfile"

Write-Host "Building isolated SQLCipher test image: $ImageTag"
& docker build --tag $ImageTag $repositoryRoot
if ($LASTEXITCODE -ne 0) {
    throw "Docker image build failed with exit code $LASTEXITCODE."
}

$recordArguments = @()
$runnerArguments = @()
if ($RecordDurationsDirectory) {
    $runnerArguments = @("--record-durations", "/durations/test_durations.json")
    $recordDirectory = (Resolve-Path -LiteralPath $RecordDurationsDirectory).Path
    $recordArguments = @("--volume", "${recordDirectory}:/durations")
}

Write-Host "Running the container unit-test suite with a read-only source mount."
# Mount only the test inputs. The application code comes from the freshly built
# image, so a developer's .env, data/, token store, database, and backups can
# never enter the test container.
& docker run --rm `
    --read-only `
    --network none `
    --security-opt no-new-privileges:true `
    --cap-drop=ALL `
    --pids-limit=256 `
    --memory=512m `
    --cpus=1 `
    --tmpfs /tmp `
    --tmpfs /data `
    --volume "${testsDirectory}:/review/tests:ro" `
    --volume "${dockerfile}:/review/Dockerfile:ro" `
    --volume "${repositoryRoot}/requirements.in:/review/requirements.in:ro" `
    --volume "${repositoryRoot}/requirements.txt:/review/requirements.txt:ro" `
    --volume "${repositoryRoot}/requirements-dev.in:/review/requirements-dev.in:ro" `
    --volume "${repositoryRoot}/requirements-dev.txt:/review/requirements-dev.txt:ro" `
    --volume "${pyprojectFile}:/review/pyproject.toml:ro" `
    --volume "${docsDirectory}:/review/docs:ro" `
    --volume "${publicDirectory}:/review/public:ro" `
    --volume "${serverFile}:/review/server.py:ro" `
    --volume "${playwrightConfig}:/review/playwright.config.cjs:ro" `
    --volume "${playwrightConfig}:/app/playwright.config.cjs:ro" `
    --volume "${e2eDirectory}:/app/e2e:ro" `
    --volume "${e2eDirectory}:/review/e2e:ro" `
    --volume "${githubDirectory}:/review/.github:ro" `
    --volume "${toolsDirectory}:/review/tools:ro" `
    --volume "${toolsDirectory}:/app/tools:ro" `
    --volume "${scriptsDirectory}:/review/scripts:ro" `
    --env "PYTHONPATH=/app:/review/tests" `
    --workdir /app `
    @recordArguments `
    $ImageTag `
    python /review/tests/run_tests.py @runnerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Container unit tests failed with exit code $LASTEXITCODE."
}

Write-Host "Container SQLCipher test suite passed."
