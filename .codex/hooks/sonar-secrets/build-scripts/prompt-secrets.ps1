if (-not (Get-Command sonar -ErrorAction SilentlyContinue)) {
    # Fail open so prompts still reach the agent, but make the skipped scan visible.
    [Console]::Error.WriteLine("Warning: sonar executable not found; prompt secrets scan skipped.")
    exit 0
}
$stdinData = [Console]::In.ReadToEnd()
$stdinData | & sonar hook codex-prompt-submit
exit $LASTEXITCODE
