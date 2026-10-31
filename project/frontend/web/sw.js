// Cache de la app para que abra rapido y sin cobertura. La API y las fotos NO se cachean.
// Sube VERSION al publicar cambios.
const VERSION = "ventanas-5";
const ARCHIVOS = ["./", "index.html", "app.css", "app.js", "config.js", "ejemplos.json", "manifest.webmanifest",
  "iconos/icono-192.png", "iconos/icono-512.png", "img/ejemplo-casa-blanca.jpg", "img/ejemplo-casa-amarilla.jpg"];
self.addEventListener("install", e => e.waitUntil(caches.open(VERSION).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/sesiones/")) return;   // siempre al servidor
  // primero la red (asi se ven los cambios), y si no hay conexion, la cache
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) { const copia = res.clone(); caches.open(VERSION).then(c => c.put(e.request, copia)); }
    return res;
  }).catch(() => caches.match(e.request)));
});