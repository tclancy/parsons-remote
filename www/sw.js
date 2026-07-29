var CACHE = "parsons-v2";
var ASSETS = ["/", "/style.css", "/app.js", "/manifest.json", "/icon.svg", "/devices.json"];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names
          .filter(function (n) {
            return n !== CACHE;
          })
          .map(function (n) {
            return caches.delete(n);
          })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;

  e.respondWith(
    fetch(e.request)
      .then(function (res) {
        var clone = res.clone();
        caches.open(CACHE).then(function (cache) {
          cache.put(e.request, clone);
        });
        return res;
      })
      .catch(function () {
        return caches.match(e.request);
      })
  );
});
