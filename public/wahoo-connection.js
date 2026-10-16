// Wahoo connection card: shows the safe server-side connection state and starts
// or ends the OAuth connection. Tokens never reach the browser.

const WAHOO_RETURN_OUTCOMES = Object.freeze({
  connected: ["Wahoo verbunden", false],
  error: ["Die Wahoo-Verbindung konnte nicht hergestellt werden. Bitte erneut versuchen.", true],
});

// The OAuth callback redirects to /?wahoo=connected|error. The parameter is named by
// the Wahoo provider id from the bootstrap JSON, which is not loaded yet when this
// script runs, so the address is read on the first render that knows the id. The
// outcome word is then dropped from the address bar so a reload does not repeat it.
let pendingWahooReturn = null;
let wahooReturnRead = false;

function takeWahooReturnOutcome() {
  if (wahooReturnRead || globalThis.location === undefined) return;
  const key = providerIds().wahoo;
  if (!key) return;
  wahooReturnRead = true;
  const params = new URLSearchParams(globalThis.location.search);
  const outcome = params.get(key);
  if (outcome === null) return;
  params.delete(key);
  const query = params.toString();
  // Land on the connections segment unless the address already names a route.
  const hash = globalThis.location.hash || "#more/connections";
  const search = query ? "?" + query : "";
  globalThis.history.replaceState(globalThis.history.state, "", globalThis.location.pathname + search + hash);
  pendingWahooReturn = Object.hasOwn(WAHOO_RETURN_OUTCOMES, outcome) ? outcome : null;
}

// True while the browser is being sent to Wahoo; keeps polling re-renders from
// re-enabling the button or resetting its label.
let wahooRedirecting = false;

// Plans reach Wahoo only through the explicit library export (README, Wahoo step 8).
const WAHOO_SCOPE_DETAIL = "Importiert Einheiten · schreibt nur bei ausdrücklichem Plan-Export";

function wahooProviderLabel(data) {
  return data?.provider_labels?.[data?.provider_ids?.wahoo] || "";
}

// Pure projection of the state JSON into what the card shows.
function wahooConnectionView(data) {
  const wahoo = data?.wahoo || {};
  const configured = Boolean(wahoo.configured);
  // Stored tokens stay disconnectable even after the WAHOO_* settings were removed.
  const connected = Boolean(wahoo.connected);
  const freshness = Array.isArray(data?.provider_freshness) ? data.provider_freshness : [];
  // A rejected refresh token is deleted server-side and surfaces as auth_required.
  const wahooId = data?.provider_ids?.wahoo;
  const reconnect = configured && !connected
    && freshness.some((entry) => Boolean(wahooId) && entry?.provider === wahooId && entry.error_code === "auth_required");
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
    detail: since ? `Verbunden seit ${since} · ${WAHOO_SCOPE_DETAIL}` : WAHOO_SCOPE_DETAIL,
    connectLabel: reconnect ? "Wahoo erneut verbinden" : "Wahoo verbinden",
    canConnect: configured && !connected,
    canDisconnect: connected,
    // Manual and full sync only make sense for a connected account.
    canSync: connected,
    showSetupHint: !configured,
  };
}

// Status line of the full resync; the same precedence as the Garmin and Intervals.icu lines.
function wahooFullResyncView(fullResync = {}, running = false) {
  const error = Boolean(fullResync?.last_error);
  if (running && fullResync?.status) return { text: fullResync.status, error };
  if (error) return { text: fullResync.last_error, error };
  if (fullResync?.last_resync_at) return { text: "Letzter vollständiger Resync: " + formatTime(fullResync.last_resync_at), error };
  return { text: "Lädt die letzten 90 Tage Wahoo-Einheiten neu; lokal gespeicherte Einheiten bleiben erhalten.", error };
}

function renderWahooSyncControls(data, view) {
  const actions = $("#wahooSyncActions");
  if (actions) actions.hidden = !view.canSync;
  const fullResync = data?.provider_resync?.[providerIds().wahoo] || {};
  const syncRunning = Boolean(state.localSync?.wahoo);
  const fullRunning = Boolean(fullResync.running || state.localSync?.wahooFull);
  const busy = syncRunning || fullRunning;
  const syncButton = $("#wahooSyncButton");
  if (syncButton) {
    syncButton.disabled = busy || !view.canSync;
    syncButton.textContent = syncRunning ? "Synchronisierung läuft…" : "Jetzt synchronisieren";
  }
  const fullButton = $("#wahooFullResyncButton");
  if (fullButton) {
    fullButton.disabled = busy || !view.canSync;
    fullButton.textContent = fullRunning ? "Vollständiger Resync läuft…" : "Vollständig neu synchronisieren";
  }
  const status = $("#wahooFullResyncStatus");
  if (status) {
    const line = wahooFullResyncView(fullResync, fullRunning);
    status.hidden = !view.canSync;
    status.classList.toggle("error", line.error);
    status.textContent = line.text;
  }
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
  renderWahooSyncControls(data, view);
  showWahooReturnOutcome();
  return view;
}

function showWahooReturnOutcome() {
  takeWahooReturnOutcome();
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

if (typeof module !== "undefined") module.exports = { wahooConnectionView, wahooFullResyncView, safeWahooAuthorizeUrl };
