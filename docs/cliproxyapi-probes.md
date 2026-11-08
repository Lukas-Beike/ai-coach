# Optional local CLIProxyAPI probes

Agents may use the existing [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)
connection for small manual checks when real model replies, Responses streaming,
or tool-call behavior would help a task. Keep mocked tests and the canned fixture
as the default for repeatable regression and browser checks. These probes are
separate from the fixture; `FIXTURE_OPENAI_MODE` has no live-proxy mode.

The local connection verified on 2026-10-13 was
`http://127.0.0.1:8317/v1`, with `gpt-6-luna` available. The user confirmed
Codex/ChatGPT OAuth routing with paid API-key upstreams and fallbacks disabled.
That setup uses subscription quota rather than OpenAI API credits; it is not
unlimited or offline inference. This authorization permits useful bounded
synthetic probes without asking again while this confirmed setup is unchanged.
Query `/v1/models` for current availability; that endpoint alone does not prove
OAuth-only billing. If there is evidence of changed routing or paid fallbacks,
or routing is unknown for a different connection, stop live probes. If the proxy
is unavailable, or authentication is required without already supplied local
client access, report the limit and continue with mocks. Never read proxy
credential/config files, OAuth tokens, or the application's `.env` to obtain
access. Do not enable paid fallbacks, change provider settings, install another
proxy, or purchase quota as part of a probe.

From the Windows host, this minimal probe uses the verified connection's existing
client access (it accepted requests without a client key). Run only after the
routing check above; choose a model actually listed by `/v1/models`:

```powershell
$proxyBase = 'http://127.0.0.1:8317/v1'
try {
    $proxyModels = Invoke-RestMethod -Uri "$proxyBase/models" -TimeoutSec 10
    if ('gpt-6-luna' -notin $proxyModels.data.id) { throw 'Proxy test model unavailable' }
    $proxyPayload = @{
        model = 'gpt-6-luna'
        instructions = 'Reply exactly PROXY_OK. Synthetic connectivity check.'
        input = 'Connectivity test.'
        reasoning = @{ effort = 'low' }
        max_output_tokens = 256
        store = $false
    } | ConvertTo-Json -Depth 5 -Compress
    $proxyResult = Invoke-RestMethod -Method Post -Uri "$proxyBase/responses" `
        -ContentType 'application/json' -Body $proxyPayload -TimeoutSec 60
    $proxyText = ($proxyResult.output | Where-Object type -eq 'message').content |
        Where-Object type -eq 'output_text' | ForEach-Object text
    [pscustomobject]@{
        Completed = $proxyResult.status -eq 'completed'
        ExpectedReply = (($proxyText -join '').Trim() -eq 'PROXY_OK')
    }
} catch {
    $proxyHttpStatus = if ($_.Exception.Response) {
        [int]$_.Exception.Response.StatusCode
    } else { $null }
    [pscustomobject]@{ Completed = $false; HttpStatus = $proxyHttpStatus }
    throw 'Local proxy probe failed; continue with mocked tests.'
}
```

Send only invented prompts and tool results, never athlete records, attachments,
database contents, credentials, or real provider snapshots. Synthetic tools must
not dispatch app actions or remote writes. Keep any custom probe scripts and
outputs outside tracked source; report only bounded status/shape metadata, model,
and pass/fail. Do not expose raw proxy errors or logs. Stop after the necessary
check rather than running bulk evaluations against subscription quota.

The verified app provider clients accepted JSON Responses, streaming function
calls, and a synthetic tool-result round trip. Full Coach compatibility failed:
`POST /v1/conversations` returned 404, and background Responses creation returned
400. Coach entry still provisions a conversation before inference, including
when its ordinary request later omits the remote conversation field. Recheck
affected capabilities after proxy/app changes; these results do not establish
official API parity. Do not bypass conversation, persistence, approval, or
background-job contracts to make a smoke test pass.

Use host-side provider probes for now. Inside Docker, `127.0.0.1` refers to the
container, and the app rejects plain HTTP to `host.docker.internal`; preserve
the HTTPS/loopback URL guard. This runbook does not reconfigure a connected app
or replace fixture/browser verification.
