// domOXML Studio service worker.
//
// Vite already content-hashes the JS/CSS/WASM assets and the Python bundle
// is content-hashed by webapp/tools/build_bundle.py, so those URLs are
// immutable: cache-first forever. HTML and the bundle manifest are
// network-first so a new deployment is picked up on the next visit.
// Pyodide comes from a version-pinned CDN URL, so it is cache-first too:
// after the first visit, a repeat load downloads nothing at all.
// e889d499 is stamped with the bundle hash when the site is assembled.
const CACHE = "domoxml-studio-e889d499";
const CORE = ["./", "./index.html", "./py/bundle-manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(CORE)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isImmutable(url) {
  return (
    url.pathname.includes("/assets/") ||
    url.pathname.includes("/py/domoxml-bundle-") ||
    url.hostname === "cdn.jsdelivr.net"
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (isImmutable(url)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok || response.type === "opaque") {
              const copy = response.clone();
              caches.open(CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request)),
    );
  }
});
