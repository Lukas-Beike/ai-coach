(() => {
  const REQUEST_TIMEOUT_MS = 25_000;
  const REMOTE_ACTION_TIMEOUT_MS = 55_000;
  const TRANSCRIPTION_TIMEOUT_MS = 100_000;

  function cookie(name) {
    return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
  }

  function responseError(response, message, reason, payloadRetryAfter = null) {
    const value = response.headers.get("Retry-After");
    let retryAfter = null;
    if (value != null) {
      const seconds = /^\d+$/.test(value) ? Number(value) : Math.ceil((Date.parse(value) - Date.now()) / 1000);
      if (Number.isFinite(seconds)) retryAfter = Math.max(0, seconds);
    }
    if (retryAfter == null && Number.isFinite(payloadRetryAfter)) retryAfter = Math.max(0, payloadRetryAfter);
    const retryMessage = retryAfter != null ? ` Bitte in ${retryAfter} Sekunden erneut versuchen.` : "";
    const error = new Error(`${message}${retryMessage}`);
    error.status = response.status;
    error.reason = reason;
    error.retryAfter = retryAfter;
    return error;
  }

  async function readResponse(response, onUnauthorized) {
    if (response.status === 401) onUnauthorized?.();
    let payload;
    try { payload = await response.json(); } catch (_) {
      throw responseError(response, response.ok ? "Ungültige Serverantwort: JSON erwartet. Bitte den gespeicherten Stand prüfen." : `Anfrage fehlgeschlagen (${response.status})`, "invalid_json");
    }
    if (!response.ok) {
      throw responseError(response, typeof payload?.error === "string" ? payload.error : `Anfrage fehlgeschlagen (${response.status})`, payload?.reason || "http_error", payload?.retry_after_seconds);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw responseError(response, "Ungültige Serverantwort: Objekt erwartet.", "invalid_shape");
    return payload;
  }

  async function request(path, options, onUnauthorized) {
    const { timeoutMs = path === "/api/coach/actions/execute" ? REMOTE_ACTION_TIMEOUT_MS : REQUEST_TIMEOUT_MS, ...fetchOptions } = options || {};
    const method = fetchOptions.method;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const callerSignal = fetchOptions.signal;
    const abortFromCaller = () => controller.abort();
    if (callerSignal?.aborted) controller.abort();
    else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
    try {
      const response = await fetch(path, {
        credentials: "same-origin",
        ...fetchOptions,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...(method && method !== "GET" && { "X-CSRF-Token": cookie("ic_csrf") }), ...fetchOptions.headers },
      });
      const payload = await readResponse(response, onUnauthorized);
      if (method && method !== "GET" && !Object.keys(payload).length) throw responseError(response, "Die Serverbestätigung fehlt. Bitte den gespeicherten Stand prüfen.", "empty_confirmation");
      return payload;
    } catch (error) {
      if (error?.name === "AbortError" && !callerSignal?.aborted) {
        throw new Error(`Der Server antwortet nicht innerhalb von ${Math.ceil(timeoutMs / 1000)} Sekunden.`);
      }
      throw error;
    } finally {
      clearTimeout(timeout);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    }
  }

  async function audio(path, blob, onUnauthorized) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), TRANSCRIPTION_TIMEOUT_MS);
    try {
      const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        body: blob,
        signal: controller.signal,
        headers: { "Content-Type": blob.type || "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") },
      });
      const payload = await readResponse(response, onUnauthorized);
      if (typeof payload.transcript !== "string") {
        throw responseError(response, "Die Transkriptionsbestätigung fehlt.", "invalid_transcription");
      }
      return payload;
    } catch (error) {
      if (error?.name === "AbortError") throw new Error(`Die Transkription antwortet nicht innerhalb von ${Math.ceil(TRANSCRIPTION_TIMEOUT_MS / 1000)} Sekunden.`);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  globalThis.AppApi = Object.freeze({ audio, request, responseError });
})();
