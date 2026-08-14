// Service worker minimo del Motor de Etiquetas: solo lo necesario para que
// el navegador ofrezca "Instalar app". Cachea la shell de la página para que
// abra rápido; las peticiones a la Zebra (fetch a /imprimir*) siempre van a red.
const CACHE_NAME = 'etiquetas-adpack-v1';
const ARCHIVOS_SHELL = [
  '/etiquetas.html',
  '/adpack-icon-web.png',
  '/termoformado-icon-web.png',
  '/logo-conversion.png',
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

  // Nunca cachear los trabajos de impresión ni llamadas a la Raspberry Pi.
  if (event.request.method !== 'GET' || url.pathname.indexOf('/imprimir') !== -1 || url.pathname === '/salud') {
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
