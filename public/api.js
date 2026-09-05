(() => {
  function cookie(name) {
    return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
  }

  function responseError(response, message, reason) {
    const value = response.headers.get("Retry-After");
    let retryAfter = null;
    if (value != null) {
      const seconds = /^\d+$/.test(value) ? Number(value) : Math.ceil((Date.parse(value) - Date.now()) / 1000);
      if (Number.isFinite(seconds)) retryAfter = Math.max(0, seconds);
    }
    const error = new Error(`${message}${retryAfter != null ? ` Bitte in ${retryAfter} Sekunden erneut versuchen.` : ""}`);
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
      throw responseError(response, typeof payload?.error === "string" ? payload.error : `Anfrage fehlgeschlagen (${response.status})`, payload?.reason || "http_error");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw responseError(response, "Ungültige Serverantwort: Objekt erwartet.", "invalid_shape");
    return payload;
  }

  async function request(path, options = {}, onUnauthorized) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": cookie("ic_csrf") } : {}), ...(options.headers || {}) },
    });
    const payload = await readResponse(response, onUnauthorized);
    if (options.method && options.method !== "GET" && !Object.keys(payload).length) throw responseError(response, "Die Serverbestätigung fehlt. Bitte den gespeicherten Stand prüfen.", "empty_confirmation");
    return payload;
  }

  async function audio(path, blob, onUnauthorized) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      body: blob,
      headers: { "Content-Type": blob.type || "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") },
    });
    const payload = await readResponse(response, onUnauthorized);
    if (typeof payload.transcript !== "string") throw responseError(response, "Die Transkriptionsbestätigung fehlt.", "invalid_transcription");
    return payload;
  }

  window.AppApi = Object.freeze({ audio, request, responseError });
})();
