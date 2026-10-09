(() => {
  const REQUEST_TIMEOUT_MS = 25_000;
  const REMOTE_ACTION_TIMEOUT_MS = 55_000;
  const TRANSCRIPTION_TIMEOUT_MS = 100_000;
  const NETWORK_ERROR_MESSAGE = "Keine Verbindung zum Coach-Server. Prüfe dein Netzwerk und versuche es erneut.";
  const UPSTREAM_MESSAGES = Object.freeze({
    upstream_auth: "Die Anmeldung beim externen Dienst ist fehlgeschlagen. Bitte die Verbindungseinstellungen prüfen.",
    upstream_rate_limited: "Der externe Dienst ist gerade ausgelastet. Bitte später erneut versuchen.",
    upstream_unavailable: "Der externe Dienst ist derzeit nicht erreichbar. Bitte später erneut versuchen.",
    upstream_rejected: "Der externe Dienst hat die Anfrage abgelehnt. Bitte die Anfrage prüfen und erneut versuchen.",
    upstream_not_found: "Die angeforderte Ressource wurde beim externen Dienst nicht gefunden.",
  });

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

  function messageForReason(reason, fallback = "Die Anfrage konnte nicht verarbeitet werden. Bitte später erneut versuchen.") {
    return UPSTREAM_MESSAGES[reason] || fallback;
  }

  function safeErrorMessage(response, payload, fallback) {
    if (UPSTREAM_MESSAGES[payload?.reason]) return UPSTREAM_MESSAGES[payload.reason];
    if (typeof payload?.reason === "string" && payload.reason.startsWith("upstream_")) return messageForReason(payload.reason);
    if (response.status === 401) return payload?.error || "Deine Sitzung ist abgelaufen. Bitte erneut anmelden.";
    if (response.status === 403) {
      if (payload?.error === "Ungültiges CSRF-Token.") return "Die Sicherheitsprüfung ist fehlgeschlagen. Bitte erneut versuchen.";
      return payload?.error || "Die Aktion ist nicht erlaubt.";
    }
    if (response.status === 404) {
      return payload?.error
        ? `${payload.error} Bitte prüfen, ob die Ressource noch verfügbar ist.`
        : "Die angeforderte Ressource wurde nicht gefunden. Bitte die Adresse prüfen.";
    }
    if (typeof payload?.error === "string") return payload.error;
    return fallback || `Anfrage fehlgeschlagen (${response.status})`;
  }

  function networkError() {
    const error = new Error(NETWORK_ERROR_MESSAGE);
    error.status = 0;
    error.reason = "network_error";
    error.retryAfter = null;
    return error;
  }

  // fetch() rejects with a raw TypeError when no response arrives. Replace it
  // with a user-facing message; aborts (timeouts, caller cancellation) pass through.
  async function fetchOrNetworkError(path, init) {
    try {
      return await fetch(path, init);
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      throw networkError();
    }
  }

  async function send(path, fetchOptions, onUnauthorized) {
    const method = String(fetchOptions.method || "GET").toUpperCase();
    const headers = new Headers(fetchOptions.headers || {});
    if (method !== "GET" && method !== "HEAD") headers.set("X-CSRF-Token", cookie("ic_csrf"));
    const response = await fetchOrNetworkError(path, { credentials: "same-origin", ...fetchOptions, method, headers });
    if (response.status === 401) onUnauthorized?.();
    if (response.status === 403 && method !== "GET" && method !== "HEAD") {
      const sentToken = headers.get("X-CSRF-Token");
      await fetch("/api/auth/status", { credentials: "same-origin", cache: "no-store" }).catch(() => null);
      const refreshedToken = cookie("ic_csrf");
      if (refreshedToken && refreshedToken !== sentToken) {
        headers.set("X-CSRF-Token", refreshedToken);
        const retry = await fetchOrNetworkError(path, { credentials: "same-origin", ...fetchOptions, method, headers });
        if (retry.status === 401) onUnauthorized?.();
        return retry;
      }
    }
    return response;
  }

  async function readResponse(response, onUnauthorized) {
    let payload;
    try { payload = await response.json(); } catch (_) {
      throw responseError(response, response.ok ? "Ungültige Serverantwort: JSON erwartet. Bitte den gespeicherten Stand prüfen." : safeErrorMessage(response, {}), "invalid_json");
    }
    if (!response.ok) {
      throw responseError(response, safeErrorMessage(response, payload), payload?.reason || "http_error", payload?.retry_after_seconds);
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
      const response = await send(path, {
        ...fetchOptions,
        signal: controller.signal,
        headers: { "Content-Type": "application/json", ...fetchOptions.headers },
      }, onUnauthorized);
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
      const response = await send(path, {
        method: "POST",
        body: blob,
        signal: controller.signal,
        headers: { "Content-Type": blob.type || "application/octet-stream" },
      }, onUnauthorized);
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

  async function download(path, options = {}, onUnauthorized) {
    const { timeoutMs = REQUEST_TIMEOUT_MS, timeoutMessage, fallback, ...fetchOptions } = options;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const callerSignal = fetchOptions.signal;
    const abortFromCaller = () => controller.abort();
    if (callerSignal?.aborted) controller.abort();
    else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
    try {
      const response = await send(path, { cache: "no-store", ...fetchOptions, signal: controller.signal }, onUnauthorized);
      if (!response.ok) {
        let payload = {};
        try { payload = await response.json(); } catch (_) { }
        throw responseError(response, safeErrorMessage(response, payload, fallback), payload?.reason || "http_error", payload?.retry_after_seconds);
      }
      return await response.blob();
    } catch (error) {
      if (error?.name === "AbortError" && !callerSignal?.aborted) throw new Error(timeoutMessage || `Der Server antwortet nicht innerhalb von ${Math.ceil(timeoutMs / 1000)} Sekunden.`);
      throw error;
    } finally {
      clearTimeout(timeout);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    }
  }

  async function stream(path, options = {}, onUnauthorized) {
    const response = await send(path, options, onUnauthorized);
    if (!response.ok) await readResponse(response, onUnauthorized);
    return response;
  }

  globalThis.AppApi = Object.freeze({ audio, download, messageForReason, request, responseError, stream });
})();
