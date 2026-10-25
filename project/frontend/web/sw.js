// Cache sencillo para que la app abra sin conexion. Sube VERSION al publicar cambios.
const VERSION = "vano-1";
const ARCHIVOS = ["./", "index.html", "app.css", "app.js", "motor.js", "catalogo.js", "ejemplos.js",
  "manifest.webmanifest", "iconos/icono-192.png", "iconos/icono-512.png",
  "img/ejemplo-casa-blanca.jpg", "img/ejemplo-casa-amarilla.jpg"];
self.addEventListener("install", e => e.waitUntil(caches.open(VERSION).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(res => {
    if (res.ok && new URL(e.request.url).origin === location.origin) { const copia = res.clone(); caches.open(VERSION).then(c => c.put(e.request, copia)); }
    return res;
  })));
});
