/* Service worker.
 *
 * The precache list and BUILD id below are rewritten at build time by the
 * pwa-precache plugin in vite.config.js, because Vite content-hashes the JS
 * and CSS filenames -- a hand-written list cannot name them, and the previous
 * one did not: offline, the app loaded its HTML and then failed to fetch its
 * only script and stylesheet, leaving an unstyled skeleton.
 *
 * The defaults here are what a dev server or an unprocessed copy gets. They
 * are deliberately a working subset rather than placeholders, so an sw.js that
 * misses the build step degrades instead of failing to install.
 */
const BUILD = '__BUILD_ID__';
const CACHE = `expenses-${BUILD}`;
const PRECACHE = [/*__PRECACHE__*/ '/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', event => {
  // Individually, so one 404 cannot fail the whole install the way addAll does.
  event.waitUntil(
    caches.open(CACHE).then(cache => Promise.all(
      PRECACHE.map(url => cache.add(url).catch(() => {}))
    ))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  // CACHE carries the build id, so a deploy drops the previous build's files
  // rather than leaving them to accumulate under hashed names.
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const { request } = event;
  // Expense API requests stay network-only: never cache data or key-bearing
  // URLs. Cross-origin is left to the browser entirely.
  if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;

  // Navigations prefer the network, so a deploy is picked up on the next
  // launch rather than whenever the cache happens to turn over.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone();
          caches.open(CACHE).then(cache => cache.put('/index.html', copy)).catch(() => {});
          return response;
        })
        .catch(() => caches.match('/index.html').then(cached => cached || caches.match('/')))
    );
    return;
  }

  // Everything else is cache-first and, on a miss, cached as it arrives. The
  // asset filenames are content-hashed, so a cached one can never be stale --
  // a change produces a new name. This is also what saves an install whose
  // precache did not run.
  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok && response.type === 'basic') {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {});
      }
      return response;
    }))
  );
});
