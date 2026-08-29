$ErrorActionPreference = "Stop"

$appDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $appDirectory

Get-Content -LiteralPath (Join-Path $appDirectory ".env") | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        $settingName = $Matches[1]
        $settingValue = $Matches[2].Trim()
        if (
            $settingValue.Length -ge 2 -and
            (($settingValue.StartsWith('"') -and $settingValue.EndsWith('"')) -or
             ($settingValue.StartsWith("'") -and $settingValue.EndsWith("'")))
        ) {
            $settingValue = $settingValue.Substring(1, $settingValue.Length - 2)
        }
        [Environment]::SetEnvironmentVariable($settingName, $settingValue, "Process")
    }
}

$pythonCandidates = @(
    (Join-Path $appDirectory ".runtime\python\python.exe"),
    (Join-Path $appDirectory "..\..\Game\.runtime\python\python.exe")
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExecutable) {
    throw "No usable Python runtime was found."
}

$dataDirectory = Join-Path $appDirectory "data"
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$logPath = Join-Path $dataDirectory "server.log"

# Keep the native invocation tolerant of stderr so an unexpected Python
# traceback is captured in the launcher log instead of stopping PowerShell's
# wrapper before it can report the exit code.
$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonExecutable (Join-Path $appDirectory "server.py") *>> $logPath
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($pythonExitCode -ne 0) {
    throw "Intervals Coach stopped with exit code $pythonExitCode. See $logPath."
}
