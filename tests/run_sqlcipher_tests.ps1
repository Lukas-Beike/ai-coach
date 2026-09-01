param(
    [string]$ImageTag = "ai-coach:local"
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$testsDirectory = Join-Path $repositoryRoot "tests"
$publicDirectory = Join-Path $repositoryRoot "public"

Write-Host "Building isolated SQLCipher test image: $ImageTag"
& docker build --tag $ImageTag $repositoryRoot
if ($LASTEXITCODE -ne 0) {
    throw "Docker image build failed with exit code $LASTEXITCODE."
}

Write-Host "Running the container unit-test suite with a read-only source mount."
# Mount only the test inputs. The application code comes from the freshly built
# image, so a developer's .env, data/, token store, database, and backups can
# never enter the test container.
& docker run --rm `
    --read-only `
    --security-opt no-new-privileges:true `
    --cap-drop=ALL `
    --pids-limit=256 `
    --memory=512m `
    --cpus=1 `
    --tmpfs /tmp `
    --volume "${testsDirectory}:/review/tests:ro" `
    --volume "${publicDirectory}:/review/public:ro" `
    --env "PYTHONPATH=/app:/review/tests" `
    --workdir /app `
    $ImageTag `
    python /review/tests/run_tests.py
if ($LASTEXITCODE -ne 0) {
    throw "Container unit tests failed with exit code $LASTEXITCODE."
}

Write-Host "Container SQLCipher test suite passed."
