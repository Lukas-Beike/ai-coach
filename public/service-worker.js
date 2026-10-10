const CACHE = "intervals-coach-v396";
const ASSETS = ["/", "/styles.css?v=297", "/format.js?v=1", "/api.js?v=224", "/navigation.js?v=231", "/appearance.js?v=218", "/state.js?v=220", "/views.js?v=223", "/plan-views.js?v=6", "/forms.js?v=217", "/components.js?v=217", "/coach.js?v=17", "/shared.js?v=7", "/auth.js?v=4", "/sync-status.js?v=4", "/notifications.js?v=1", "/nutrition.js?v=24", "/analysis.js?v=101", "/activity-details.js?v=12", "/performance-view.js?v=2", "/diagnostics.js?v=2", "/state-loader.js?v=2", "/sync-actions.js?v=2", "/settings.js?v=2", "/app.js?v=281", "/icon.svg?v=217", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/format.js", "/activity-details.js", "/analysis.js", "/nutrition.js", "/api.js", "/navigation.js", "/appearance.js", "/state.js", "/views.js", "/plan-views.js", "/forms.js", "/components.js", "/coach.js", "/shared.js", "/auth.js", "/sync-status.js", "/notifications.js", "/performance-view.js", "/diagnostics.js", "/state-loader.js", "/sync-actions.js", "/settings.js", "/app.js", "/styles.css", "/logo.png", "/icon.svg"]);
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
