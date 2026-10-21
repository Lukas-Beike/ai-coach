param()
$ErrorActionPreference = 'Stop'
$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
    exit 0
}
$worker = Join-Path $repoRoot 'scripts/graphify_local.py'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) {
    Write-Host 'Graphify unavailable: local worker missing; run the documented setup/update commands.'
    exit 0
}
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host 'Graphify unavailable: Python is missing; install Python manually to enable local updates.'
    exit 0
}
& $python.Source $worker update --session-start
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Graphify update did not complete; check the local status before using graph results.'
}
exit 0
