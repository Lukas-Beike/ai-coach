const CACHE = "intervals-coach-v521";
const ASSETS = ["/", "/styles.css?v=344", "/format.js?v=1", "/api.js?v=224", "/navigation.js?v=236", "/appearance.js?v=218", "/state.js?v=226", "/views.js?v=232", "/plan-views.js?v=18", "/forms.js?v=217", "/components.js?v=217", "/coach.js?v=38", "/shared.js?v=20", "/auth.js?v=13", "/sync-status.js?v=12", "/view-refresh.js?v=3", "/notifications.js?v=5", "/nutrition.js?v=46", "/analysis.js?v=137", "/activity-details.js?v=20", "/activity-analysis.js?v=5", "/performance-view.js?v=27", "/diagnostics.js?v=4", "/state-loader.js?v=20", "/sync-actions.js?v=5", "/wahoo-connection.js?v=4", "/provider-connections.js?v=4", "/settings.js?v=13", "/app.js?v=296", "/icon.svg?v=217", "/apple-touch-icon.png?v=1", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/format.js", "/activity-details.js", "/activity-analysis.js", "/analysis.js", "/nutrition.js", "/view-refresh.js", "/api.js", "/navigation.js", "/appearance.js", "/state.js", "/views.js", "/plan-views.js", "/forms.js", "/components.js", "/coach.js", "/shared.js", "/auth.js", "/sync-status.js", "/notifications.js", "/performance-view.js", "/diagnostics.js", "/state-loader.js", "/sync-actions.js", "/wahoo-connection.js", "/provider-connections.js", "/settings.js", "/app.js", "/styles.css", "/icon.svg", "/apple-touch-icon.png"]);
const NAVIGATION_TIMEOUT_MS = 2500;
// A new worker takes over at once; the open page reloads itself when nothing would be lost (notifications.js).
globalThis.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => globalThis.skipWaiting())));
globalThis.addEventListener("activate", (event) => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
  await globalThis.clients.claim();
})()));
globalThis.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  const isVersionedAsset = VERSIONED_ASSETS.has(url.pathname) && Boolean(url.searchParams.get("v"));
  if (isVersionedAsset) {
    event.respondWith(caches.open(CACHE).then((cache) => cache.match(event.request)).then((cached) => cached || fetch(event.request).then((response) => {
      if (response.ok) void caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
      return response;
    })));
    return;
  }
  const fetched = fetch(event.request).then((response) => {
    const copy = response.ok ? response.clone() : null;
    return { response, stored: copy && caches.open(CACHE).then((cache) => cache.put(event.request, copy)) };
  });
  // The cache update outlives a response that was already served from the cache.
  event.waitUntil(fetched.then(({ stored }) => stored).catch(() => {}));
  const network = fetched.then(({ response }) => response);
  const cached = () => caches.open(CACHE).then((cache) => cache.match(event.request));
  if (event.request.mode !== "navigate") {
    event.respondWith(network.catch(cached));
    return;
  }
  // A slow network must not hold the app start: after a short wait the cached
  // page starts the app while the network response still refreshes the cache.
  event.respondWith(new Promise((resolve, reject) => {
    let settled = false;
    const settle = (response) => { if (response && !settled) { settled = true; resolve(response); } };
    const timer = setTimeout(() => cached().then(settle).catch(() => {}), NAVIGATION_TIMEOUT_MS);
    network.then((response) => { clearTimeout(timer); settle(response); }).catch(async () => {
      clearTimeout(timer);
      const response = await cached().catch(() => null);
      if (response) settle(response);
      else if (!settled) reject(new TypeError("Offline"));
    });
  }));
});
globalThis.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const existing = windows.find((client) => "focus" in client);
    return existing ? existing.focus() : clients.openWindow("/");
  }));
});
