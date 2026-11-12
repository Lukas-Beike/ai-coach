const CACHE = "pacecraft-__ASSET_HASH__";
const ASSETS = [
  "/",
  "/styles.css",
  "/format.js",
  "/api.js",
  "/navigation.js",
  "/appearance.js",
  "/state.js",
  "/views.js",
  "/plan-views.js",
  "/components.js",
  "/connection-status.js",
  "/status-strip.js",
  "/coach.js",
  "/shared.js",
  "/auth.js",
  "/sync-status.js",
  "/view-refresh.js",
  "/notifications.js",
  "/nutrition.js",
  "/analysis.js",
  "/activity-details.js",
  "/activity-analysis.js",
  "/performance-view.js",
  "/diagnostics.js",
  "/state-loader.js",
  "/sync-actions.js",
  "/wahoo-connection.js",
  "/provider-connections.js",
  "/provider-checks.js",
  "/settings.js",
  "/app.js",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/icon-maskable-512.png",
  "/apple-touch-icon.png",
  "/manifest.webmanifest"
];
const CACHED_PATHS = new Set(ASSETS.map((asset) => asset.split("?")[0]));
// The server stamps a version query onto every versioned entry of ASSETS.
const VERSIONED_ASSETS = new Set(ASSETS.filter((asset) => asset.includes("?")).map((asset) => asset.split("?")[0]));
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
  const isNavigation = event.request.mode === "navigate";
  // Every navigation is the one app shell and is kept under "/" only, so unknown
  // paths and OAuth return URLs add no copies. Other files are kept only when precached.
  const cacheKey = isNavigation ? "/" : event.request;
  const storable = isNavigation || CACHED_PATHS.has(url.pathname);
  const fetched = fetch(event.request).then((response) => {
    const copy = storable && response.ok ? response.clone() : null;
    return { response, stored: copy && caches.open(CACHE).then((cache) => cache.put(cacheKey, copy)) };
  });
  // The cache update outlives a response that was already served from the cache.
  event.waitUntil(fetched.then(({ stored }) => stored).catch(() => {}));
  const network = fetched.then(({ response }) => response);
  const cached = () => caches.open(CACHE).then((cache) => cache.match(cacheKey));
  if (!isNavigation) {
    event.respondWith(network.catch(cached));
    return;
  }
  // A slow network must not hold the app start: after a short wait the cached
  // page starts the app while the network response still refreshes the cache.
  // A server error (a proxy's 502 page during a restart) counts as no network.
  event.respondWith(new Promise((resolve, reject) => {
    let settled = false;
    const settle = (response) => { if (response && !settled) { settled = true; resolve(response); } };
    const timer = setTimeout(() => cached().then(settle).catch(() => {}), NAVIGATION_TIMEOUT_MS);
    network.then(async (response) => {
      clearTimeout(timer);
      if (response.status < 500) return settle(response);
      settle(await cached().catch(() => null) || response);
    }).catch(async () => {
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
