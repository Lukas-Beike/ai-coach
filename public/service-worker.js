const CACHE = "intervals-coach-v467";
const ASSETS = ["/", "/styles.css?v=326", "/format.js?v=1", "/api.js?v=224", "/navigation.js?v=234", "/appearance.js?v=218", "/state.js?v=225", "/views.js?v=230", "/plan-views.js?v=14", "/forms.js?v=217", "/components.js?v=217", "/coach.js?v=33", "/shared.js?v=15", "/auth.js?v=11", "/sync-status.js?v=12", "/notifications.js?v=4", "/nutrition.js?v=31", "/analysis.js?v=120", "/activity-details.js?v=16", "/activity-analysis.js?v=3", "/performance-view.js?v=22", "/diagnostics.js?v=4", "/state-loader.js?v=15", "/sync-actions.js?v=5", "/wahoo-connection.js?v=4", "/provider-connections.js?v=1", "/settings.js?v=9", "/app.js?v=289", "/icon.svg?v=217", "/apple-touch-icon.png?v=1", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/format.js", "/activity-details.js", "/activity-analysis.js", "/analysis.js", "/nutrition.js", "/api.js", "/navigation.js", "/appearance.js", "/state.js", "/views.js", "/plan-views.js", "/forms.js", "/components.js", "/coach.js", "/shared.js", "/auth.js", "/sync-status.js", "/notifications.js", "/performance-view.js", "/diagnostics.js", "/state-loader.js", "/sync-actions.js", "/wahoo-connection.js", "/provider-connections.js", "/settings.js", "/app.js", "/styles.css", "/icon.svg", "/apple-touch-icon.png"]);
const NAVIGATION_TIMEOUT_MS = 2500;
globalThis.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS))));
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
