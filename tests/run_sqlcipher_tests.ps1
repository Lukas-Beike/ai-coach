param(
    [string]$ImageTag = "ai-coach:local",
    [string]$RecordDurationsDirectory = "",
    [ValidateRange(1, 4)][int]$Workers = 1,
    [string]$ResultsDirectory = "",
    [string]$CoverageWheel = "",
    [ValidateSet("cold", "warm", "unknown")][string]$CacheState = "unknown"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$supervisor = Join-Path $repositoryRoot "scripts/run_sqlcipher_tests.py"
$runnerArguments = @($supervisor, "--image", $ImageTag, "--workers", "$Workers", "--cache-state", $CacheState)
if ($RecordDurationsDirectory) {
    $runnerArguments += @("--record-durations-directory", (Resolve-Path -LiteralPath $RecordDurationsDirectory).Path)
}
if ($ResultsDirectory) {
    $runnerArguments += @("--results-dir", $ResultsDirectory)
}
if ($CoverageWheel) {
    $runnerArguments += @("--coverage-wheel", (Resolve-Path -LiteralPath $CoverageWheel).Path)
}
# The stdlib supervisor owns hidden Windows children and networkless containers.
& python @runnerArguments
if ($LASTEXITCODE -ne 0) {
    throw "Container unit tests failed with exit code $LASTEXITCODE."
}
