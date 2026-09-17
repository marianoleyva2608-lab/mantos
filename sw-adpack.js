// Service worker minimo de la app principal AD-PACK (Mantenimiento
// Preventivo + accesos a Requisiciones, Refacciones, Ordenes, Reportes,
// Etiquetas, Trazabilidad y Control de Baños). Solo lo necesario para que
// el navegador ofrezca "Instalar app". Nunca cachea /api/ (datos en vivo).
const CACHE_NAME = 'adpack-v1';
const ARCHIVOS_SHELL = [
  '/',
  '/index.html',
  '/icon-etiquetas-192.png',
  '/icon-etiquetas-512.png',
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(ARCHIVOS_SHELL);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (nombres) {
      return Promise.all(
        nombres.filter(function (n) { return n !== CACHE_NAME; }).map(function (n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function (event) {
  var url = new URL(event.request.url);

  // Nunca cachear llamadas a la API ni trabajos de impresion/salud de la Zebra.
  if (
    event.request.method !== 'GET' ||
    url.pathname.indexOf('/api/') !== -1 ||
    url.pathname.indexOf('/imprimir') !== -1 ||
    url.pathname === '/salud'
  ) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(function (respuestaCache) {
      var redFetch = fetch(event.request).then(function (respuestaRed) {
        if (respuestaRed && respuestaRed.ok) {
          caches.open(CACHE_NAME).then(function (cache) { cache.put(event.request, respuestaRed.clone()); });
        }
        return respuestaRed;
      }).catch(function () { return respuestaCache; });
      return respuestaCache || redFetch;
    })
  );
});
