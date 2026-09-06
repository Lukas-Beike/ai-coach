const CACHE = "intervals-coach-v188";
const ASSETS = ["/", "/styles.css?v=188", "/api.js?v=188", "/navigation.js?v=188", "/state.js?v=188", "/views.js?v=188", "/forms.js?v=188", "/components.js?v=188", "/app.js?v=188", "/icon.svg?v=188", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/api.js", "/navigation.js", "/state.js", "/views.js", "/forms.js", "/components.js", "/app.js", "/styles.css", "/logo.png", "/icon.svg"]);
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS))));
self.addEventListener("activate", (event) => event.waitUntil((async () => {
  await self.clients.claim();
})()));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  const isVersionedAsset = VERSIONED_ASSETS.has(url.pathname) && Boolean(url.searchParams.get("v"));
  if (isVersionedAsset) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      if (response.ok) caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
      return response;
    })));
    return;
  }
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok) caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request)));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const existing = windows.find((client) => "focus" in client);
    return existing ? existing.focus() : clients.openWindow("/");
  }));
});
