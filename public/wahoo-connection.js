// Wahoo connection card: shows the safe server-side connection state and starts
// or ends the OAuth connection. Tokens never reach the browser.

const WAHOO_RETURN_OUTCOMES = Object.freeze({
  connected: ["Wahoo verbunden", false],
  error: ["Die Wahoo-Verbindung konnte nicht hergestellt werden. Bitte erneut versuchen.", true],
});

// The OAuth callback redirects to /?wahoo=connected|error. Remember the outcome
// word once and drop it from the address bar so a reload does not repeat it.
let pendingWahooReturn = (() => {
  if (globalThis.location === undefined) return null;
  const params = new URLSearchParams(globalThis.location.search);
  const outcome = params.get("wahoo");
  if (outcome === null) return null;
  params.delete("wahoo");
  const query = params.toString();
  // Land on the connections segment unless the address already names a route.
  const hash = globalThis.location.hash || "#more/connections";
  const search = query ? "?" + query : "";
  globalThis.history.replaceState(globalThis.history.state, "", globalThis.location.pathname + search + hash);
  return Object.hasOwn(WAHOO_RETURN_OUTCOMES, outcome) ? outcome : null;
})();

// True while the browser is being sent to Wahoo; keeps polling re-renders from
// re-enabling the button or resetting its label.
let wahooRedirecting = false;

function wahooProviderLabel(data) {
  return data?.provider_labels?.wahoo || "Wahoo";
}

// Pure projection of the state JSON into what the card shows.
function wahooConnectionView(data) {
  const wahoo = data?.wahoo || {};
  const configured = Boolean(wahoo.configured);
  // Stored tokens stay disconnectable even after the WAHOO_* settings were removed.
  const connected = Boolean(wahoo.connected);
  const freshness = Array.isArray(data?.provider_freshness) ? data.provider_freshness : [];
  // A rejected refresh token is deleted server-side and surfaces as auth_required.
  const reconnect = configured && !connected
    && freshness.some((entry) => entry?.provider === "wahoo" && entry.error_code === "auth_required");
  let status = "Nicht verbunden";
  if (connected) status = "Verbunden";
  else if (!configured) status = "Nicht konfiguriert";
  else if (reconnect) status = "Erneute Verbindung erforderlich";
  const since = connected && wahoo.connected_at ? globalThis.AppFormat?.dateTime(wahoo.connected_at) : null;
  return {
    configured,
    connected,
    reconnect,
    status,
    ok: connected,
    detail: since ? `Verbunden seit ${since}` : "",
    connectLabel: reconnect ? "Wahoo erneut verbinden" : "Wahoo verbinden",
    canConnect: configured && !connected,
    canDisconnect: connected,
    showSetupHint: !configured,
  };
}

function renderWahooConnection(data) {
  const view = wahooConnectionView(data);
  const title = $("#wahooConnectionTitle");
  if (title) title.textContent = wahooProviderLabel(data);
  settingsStatus("#wahooConnectionStatus", view.ok, view.status);
  const detail = $("#wahooConnectionDetail");
  if (detail) detail.textContent = view.detail;
  const connect = $("#wahooConnectButton");
  if (connect) {
    connect.hidden = !view.canConnect;
    connect.disabled = wahooRedirecting;
    connect.textContent = wahooRedirecting ? "Weiterleitung zu Wahoo…" : view.connectLabel;
  }
  const disconnect = $("#wahooDisconnectButton");
  if (disconnect) disconnect.hidden = !view.canDisconnect;
  const actions = $("#wahooConnectionActions");
  if (actions) actions.hidden = !view.canConnect && !view.canDisconnect;
  const hint = $("#wahooSetupHint");
  if (hint) hint.hidden = !view.showSetupHint;
  showWahooReturnOutcome();
  return view;
}

function showWahooReturnOutcome() {
  if (!pendingWahooReturn) return;
  const [message, isError] = WAHOO_RETURN_OUTCOMES[pendingWahooReturn];
  pendingWahooReturn = null;
  toast(message, isError);
  const section = document.querySelector('details[data-more-segment-panel="connections"]');
  if (section) section.open = true;
}

function safeWahooAuthorizeUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : null;
  } catch { return null; }
}

async function connectWahoo() {
  const button = $("#wahooConnectButton");
  if (!button) return;
  wahooRedirecting = true;
  renderWahooConnection(state.data || {});
  try {
    const result = await api("/api/wahoo/connect", { method: "POST", body: "{}" });
    const target = safeWahooAuthorizeUrl(result?.authorize_url);
    if (!target) throw new Error("Die Wahoo-Anmeldeadresse fehlt oder ist ungültig.");
    globalThis.location.assign(target);
  } catch (error) {
    wahooRedirecting = false;
    toast(error.message, true);
    renderWahooConnection(state.data || {});
  }
}

// Returning from Wahoo with the back button restores the page from the bfcache.
globalThis.addEventListener?.("pageshow", (event) => {
  if (!event.persisted || !wahooRedirecting) return;
  wahooRedirecting = false;
  if (state?.data) renderWahooConnection(state.data);
});

async function disconnectWahoo() {
  const button = $("#wahooDisconnectButton");
  if (!button) return;
  const label = wahooProviderLabel(state.data);
  if (!await requestConfirmation(`${label} trennen? Der Zugriff wird bei ${label} widerrufen und die lokalen Zugangsdaten werden gelöscht. Bereits geladene Einheiten bleiben erhalten.`, { title: `${label} trennen?` })) return;
  button.disabled = true;
  try {
    await api("/api/wahoo/disconnect", { method: "POST", body: "{}" });
    toast(`${label} getrennt`);
    invalidateContextPreview();
    await load();
    button.disabled = false;
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}

if (typeof module !== "undefined") module.exports = { wahooConnectionView, safeWahooAuthorizeUrl };
