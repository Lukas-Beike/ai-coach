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

if (-not $SkipBuild) { docker build -q -t ai-coach:local . | Out-Null }
if (docker ps -aq --filter "name=^$Name$") {
    docker stop $Name | Out-Null
    docker rm $Name | Out-Null   # never -v
}
$dockerArguments = @("run", "-d", "--name", $Name, "-p", "127.0.0.1:${Port}:8090",
    "-e", "FIXTURE_AUTO_SEED=1", "-v", "${PWD}\e2e:/app/e2e:ro")
if ($Persist) { $dockerArguments += @("-v", "${Name}-data:/data") }
$dockerArguments += @("ai-coach:local", "python", "/app/e2e/fixture_runtime.py")
docker @dockerArguments | Out-Null

for ($i = 0; $i -lt 60; $i++) {
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break }
    } catch { Start-Sleep -Seconds 2 }
}
Write-Host "Demo ready: http://127.0.0.1:$Port (password: e2e-fixture-password-1234)"