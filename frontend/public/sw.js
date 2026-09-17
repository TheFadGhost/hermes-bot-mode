const CACHE = "hermes-bot-shell-v4";
const SHELL = ["/bot/", "/bot/index.html", "/bot/favicon.svg", "/bot/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith("hermes-bot-shell-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.pathname.includes("/bot/api/")) return;

  event.respondWith(
    fetch(request).then((response) => {
      if (response.ok && url.origin === self.location.origin && (url.pathname.startsWith("/bot/assets/") || url.pathname === "/bot/" || url.pathname === "/bot/index.html")) {
        const copy = response.clone();
        void caches.open(CACHE).then((cache) => cache.put(request, copy));
      }
      return response;
    }).catch(() => {
      if (request.mode === "navigate") return caches.match("/bot/");
      return caches.match(request).then((response) => response ?? Response.error());
    }),
  );
});
