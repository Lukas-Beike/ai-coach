const CACHE = "intervals-coach-v342";
const ASSETS = ["/", "/styles.css?v=270", "/api.js?v=221", "/navigation.js?v=230", "/appearance.js?v=218", "/state.js?v=218", "/views.js?v=218", "/forms.js?v=217", "/components.js?v=217", "/coach.js?v=6", "/app.js?v=270", "/nutrition.js?v=15", "/analysis.js?v=74", "/activity-details.js?v=8", "/icon.svg?v=217", "/manifest.webmanifest"];
const VERSIONED_ASSETS = new Set(["/activity-details.js", "/analysis.js", "/nutrition.js", "/api.js", "/navigation.js", "/appearance.js", "/state.js", "/views.js", "/forms.js", "/components.js", "/coach.js", "/app.js", "/styles.css", "/logo.png", "/icon.svg"]);
globalThis.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS))));
globalThis.addEventListener("activate", (event) => event.waitUntil((async () => {
  await globalThis.clients.claim();
})()));
globalThis.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  const isVersionedAsset = VERSIONED_ASSETS.has(url.pathname) && Boolean(url.searchParams.get("v"));
  if (isVersionedAsset) {
    event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
      if (response.ok) void caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
      return response;
    })));
    return;
  }
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok) void caches.open(CACHE).then((cache) => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request)));
});
globalThis.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
    const existing = windows.find((client) => "focus" in client);
    return existing ? existing.focus() : clients.openWindow("/");
  }));
});
