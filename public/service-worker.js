const CACHE = "intervals-coach-v433";
const ASSETS = ["/", "/styles.css?v=316", "/format.js?v=1", "/api.js?v=224", "/navigation.js?v=233", "/appearance.js?v=218", "/state.js?v=223", "/views.js?v=227", "/plan-views.js?v=9", "/forms.js?v=217", "/components.js?v=217", "/coach.js?v=27", "/shared.js?v=12", "/auth.js?v=6", "/sync-status.js?v=10", "/notifications.js?v=4", "/nutrition.js?v=30", "/analysis.js?v=116", "/activity-details.js?v=13", "/performance-view.js?v=11", "/diagnostics.js?v=4", "/state-loader.js?v=8", "/sync-actions.js?v=5", "/wahoo-connection.js?v=3", "/settings.js?v=7", "/app.js?v=287", "/icon.svg?v=217", "/apple-touch-icon.png?v=1", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/format.js", "/activity-details.js", "/analysis.js", "/nutrition.js", "/api.js", "/navigation.js", "/appearance.js", "/state.js", "/views.js", "/plan-views.js", "/forms.js", "/components.js", "/coach.js", "/shared.js", "/auth.js", "/sync-status.js", "/notifications.js", "/performance-view.js", "/diagnostics.js", "/state-loader.js", "/sync-actions.js", "/wahoo-connection.js", "/settings.js", "/app.js", "/styles.css", "/icon.svg", "/apple-touch-icon.png"]);
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
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok) void caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.open(CACHE).then((cache) => cache.match(event.request))));
});
globalThis.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const existing = windows.find((client) => "focus" in client);
    return existing ? existing.focus() : clients.openWindow("/");
  }));
});
