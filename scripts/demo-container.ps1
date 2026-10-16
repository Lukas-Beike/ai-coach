<#
Builds the current image and (re)creates a disposable demo container that
seeds itself with the standard synthetic fixture data on every start.
Only fake data is used; providers stay blocked. Password: e2e-fixture-password-1234

  .\scripts\demo-container.ps1                # data lives in the container
  .\scripts\demo-container.ps1 -Persist       # data survives recreation (named volume)
  .\scripts\demo-container.ps1 -SkipBuild -Port 8091
#>
param(
    [string]$Name = "ai-coach-demo",
    [int]$Port = 8091,
    [switch]$Persist,
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# Only disposable demo/fixture containers may be replaced. The production container
# (ai-coach) and every other name are refused before anything is built, stopped or removed.
if ($Name -eq "ai-coach" -or $Name -notmatch '^(ai-coach-)?(demo|fixture)') {
    throw "Refusing container name '$Name': use a demo or fixture name such as ai-coach-demo."
}

# $ErrorActionPreference does not stop on native exit codes in Windows PowerShell 5.1,
# so every native call is followed by an explicit $LASTEXITCODE check.
if (-not $SkipBuild) {
    docker build -q -t ai-coach:local . | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Image build failed (exit $LASTEXITCODE)." }
}
$existingContainer = docker ps -aq --filter "name=^$Name$"
if ($LASTEXITCODE -ne 0) { throw "Listing containers failed (exit $LASTEXITCODE)." }
if ($existingContainer) {
    docker stop $Name | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Stopping container '$Name' failed (exit $LASTEXITCODE)." }
    docker rm $Name | Out-Null   # never -v
    if ($LASTEXITCODE -ne 0) { throw "Removing container '$Name' failed (exit $LASTEXITCODE)." }
}
$dockerArguments = @("run", "-d", "--name", $Name, "-p", "127.0.0.1:${Port}:8090",
    "-e", "FIXTURE_AUTO_SEED=1", "-e", "AI_COACH_DISPOSABLE_FIXTURE=1", "-v", "${PWD}\e2e:/app/e2e:ro")
if ($Persist) { $dockerArguments += @("-v", "${Name}-data:/data") }
$dockerArguments += @("ai-coach:local", "python", "/app/e2e/fixture_runtime.py")
docker @dockerArguments | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Starting container '$Name' failed (exit $LASTEXITCODE)." }

# Bounded readiness wait: at most 60 probes. Failed probes and non-200 answers both sleep.
$healthy = $false
for ($i = 0; $i -lt 60 -and -not $healthy; $i++) {
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) {
            $healthy = $true
        } else {
            Start-Sleep -Seconds 2
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $healthy) { throw "Demo container did not become healthy on port $Port" }
Write-Host "Demo ready: http://127.0.0.1:$Port (password: e2e-fixture-password-1234)"