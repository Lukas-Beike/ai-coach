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

# Only the app's own runtime is used: .env values are loaded into this process,
# so a Python from another project must never receive them.
$pythonExecutable = Join-Path $appDirectory ".runtime\python\python.exe"
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "The app's Python runtime was not found at $pythonExecutable. Install it there and start again."
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
