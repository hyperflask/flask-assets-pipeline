/**
 * A simple cache service worker to cache bundled assets. Useful for PWAs
 */

const CACHE_NAME = 'assets-v1';
const CACHE_URLS = [];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CACHE_URLS))
  );
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys
        .filter((key) => !key.includes(CACHE_NAME))
        .map((key) => caches.delete(key))
      );
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(caches.match(event.request).then((response) => {
    return response || fetch(event.request);
  }));
});
