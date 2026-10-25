// Tech Bazaar service worker: it keeps the app shell (static assets, icons, manifest) and one /offline page so the app
// opens on a phone with no signal. It never stores market or agent data: nothing under /v1/, no JSON of any kind (those
// carry prices and quantities), no API or data routes, and no page with personal or live content. Navigations always go
// to the network; if that fails the buyer gets /offline, which has no numbers.

const CACHE = "tb-shell-v1";
const SHELL = ["/offline", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

/** "shell" for a request this worker may keep, else null. Pure, so it is tested (src/lib/pwa.test.ts). */
function cacheKind(href, method, origin) {
  if (method !== "GET") return null;
  let url;
  try {
    url = new URL(href);
  } catch {
    return null;
  }
  if (url.origin !== origin) return null;
  const path = url.pathname.toLowerCase();
  if (path.startsWith("/v1/") || path.startsWith("/api/") || path.startsWith("/_next/data/") || path.startsWith("/_next/image") || path.endsWith(".json")) return null;
  if (path === "/offline" || path === "/manifest.webmanifest" || path.startsWith("/_next/static/") || path.startsWith("/icons/")) return "shell";
  return null;
}

if (typeof self !== "undefined" && typeof self.addEventListener === "function") {
  self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
  });

  self.addEventListener("activate", (event) => {
    event.waitUntil(
      caches
        .keys()
        .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
        .then(() => self.clients.claim()),
    );
  });

  self.addEventListener("fetch", (event) => {
    const req = event.request;
    if (req.mode === "navigate") {
      event.respondWith(fetch(req).catch(() => caches.match("/offline")));
      return;
    }
    if (cacheKind(req.url, req.method, self.location.origin) !== "shell") return; // everything else goes straight to the network
    event.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy));
            }
            return res;
          }),
      ),
    );
  });
}

if (typeof module !== "undefined") module.exports = { cacheKind, CACHE };
