/**
 * Simple service worker for offline shell caching.
 *
 * Caches the app shell (HTML, CSS, JS) on install so the dashboard loads
 * instantly on repeat visits and works offline (with cached data).
 *
 * Strategy:
 *  - Network-first for navigation requests (HTML pages) — falls back to
 *    the cached shell when offline.
 *  - Cache-first for static assets (JS, CSS, fonts, images) — served from
 *    cache immediately, no network round-trip.
 *  - Stale-while-revalidate for API/data requests — returns stale data
 *    immediately and updates the cache in the background.
 */

const CACHE_NAME = "miraj-dashboard-v3";
const APP_SHELL = [
  "/",
  "/manifest.json",
];

// Assets that should be cached on install (app shell).
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)),
  );
  self.skipWaiting();
});

// Clean up old caches on activation.
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name)),
      ),
    ),
  );
  self.clients.claim();
});

// Fetch handler — different strategies based on request type.
self.addEventListener("fetch", (event) => {
  const { request } = event;

  // Skip non-GET requests ( mutations, auth, etc.).
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Skip cross-origin requests (external APIs, exchange data) — let the
  // browser handle them normally.
  if (url.origin !== self.location.origin) return;

  // Skip Next.js HMR and dev-specific paths.
  if (url.pathname.startsWith("/_next/webpack-hmr")) return;

  // API requests — stale-while-revalidate (return cached data immediately,
  // update cache in background).
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // Navigation requests (HTML pages) — network-first, fallback to cache.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request).then((cached) => cached || caches.match("/"))),
    );
    return;
  }

  // Static assets — cache-first (fast, no network needed).
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        // Only cache successful responses.
        if (!response || response.status !== 200) return response;
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      });
    }),
  );
});

/**
 * Stale-while-revalidate: return cached data immediately if available,
 * then fetch fresh data and update the cache.
 */
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request)
    .then((response) => {
      if (response && response.status === 200) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => cached);

  return cached || fetchPromise;
}
