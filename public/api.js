(() => {
  function cookie(name) {
    return document.cookie.split("; ").find((part) => part.startsWith(`${name}=`))?.split("=").slice(1).join("=") || "";
  }

  async function request(path, options = {}, onUnauthorized) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.method && options.method !== "GET" ? { "X-CSRF-Token": cookie("ic_csrf") } : {}), ...(options.headers || {}) },
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      if (response.status === 401) onUnauthorized?.();
      throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
    }
    return payload;
  }

  async function audio(path, blob, onUnauthorized) {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      body: blob,
      headers: { "Content-Type": blob.type || "application/octet-stream", "X-CSRF-Token": cookie("ic_csrf") },
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      if (response.status === 401) onUnauthorized?.();
      throw new Error(payload.error || `Anfrage fehlgeschlagen (${response.status})`);
    }
    return payload;
  }

  window.AppApi = Object.freeze({ audio, request });
})();
