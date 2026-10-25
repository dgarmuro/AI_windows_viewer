# Vano · app del cliente

App para que el cliente final pruebe ventanas del catálogo sobre la foto de su fachada.
Funciona **sin servidor**: todo se calcula en el propio móvil (catálogo, detección de ejemplo,
composición en perspectiva con luz de la pared, presupuesto orientativo y proyectos guardados).

```
web/
  index.html            página única
  app.css               estilos (modo claro y oscuro)
  app.js                pantallas y navegación
  motor.js              dibujo vectorial de ventanas + composición sobre la foto
  catalogo.js           modelos, colores, perfiles y precios   ← edita aquí tu catálogo
  ejemplos.js           fotos de ejemplo con sus ventanas marcadas
  manifest.webmanifest  datos para instalarla como app
  sw.js                 caché para abrir sin conexión
  iconos/  img/
```

## Probar en el ordenador

```bash
cd web
python3 -m http.server 8000
```
Abre http://localhost:8000. Usa las herramientas de desarrollador en modo móvil (Ctrl+Shift+M en Chrome)
para verla con tamaño de teléfono. En el ordenador, «Hacer una foto» y «Galería» abren el selector de archivos.

## Probar en el móvil

**Misma wifi (lo más rápido).** Con el servidor anterior en marcha, busca la IP del ordenador
(`ipconfig` en Windows, `ip addr` o `ifconfig` en Linux/Mac) y abre en el móvil `http://192.168.X.X:8000`.
Todo funciona, salvo instalarla como app y el modo sin conexión: eso exige HTTPS.

**Con HTTPS (para instalarla).** Cualquiera de estas opciones vale:
- `npx localtunnel --port 8000` o `cloudflared tunnel --url http://localhost:8000` dan una URL https temporal.
- Sube la carpeta `web/` a Netlify Drop (arrastrar y soltar), GitHub Pages o Vercel.

Después, en **Android (Chrome)**: menú ⋮ → *Instalar app*. En **iPhone (Safari)**: Compartir → *Añadir a pantalla de inicio*.
Se abre a pantalla completa, con su icono, como una app más.

## Qué hace

1. **Inicio**: comparador antes/después, cómo funciona y modelos destacados.
2. **Ventanas (catálogo)**: búsqueda, filtros por material y guardadas (♥).
3. **Ficha**: vista a escala que cambia de color al momento, cifras (Uw, dB, garantía), especificaciones y precio.
4. **Tu fachada** (1/3): cámara, galería o dos fotos de ejemplo.
5. **Elige ventanas** (2/3): toca las ventanas para elegirlas o descartarlas, ajusta sus 4 esquinas,
   añade otras y, si quieres, mete las medidas reales (ancho × alto en mm, para una o para todas).
   Con medidas el perfil sale a escala real y el precio se afina.
6. **Resultado** (3/3): comparador deslizante, cambio de modelo y color en vivo, precio orientativo,
   guardar el proyecto, descargar la imagen y pedir presupuesto.
7. **Pedir presupuesto** → confirmación. **Proyectos**: lo guardado y lo pedido, en el propio dispositivo.

Sin backend, en las fotos del cliente no hay detección automática: aparece un marco en el centro para
colocarlo sobre la ventana. Las fotos de ejemplo traen las ventanas ya detectadas.

## Conectar el backend más adelante

En `app.js` están marcados con `[BACKEND]` los tres puntos a sustituir:

| Punto | Ahora | Con backend |
|---|---|---|
| `usarArchivo()` | marco centrado | `POST /api/analizar` con la foto → lista de quads |
| `componer()` en Resultado | `Motor.componer` (vectorial, en el móvil) | `POST /api/render` con foto, quads, medidas y producto → imagen |
| envío en Presupuesto | se guarda en `localStorage` | `POST /api/presupuesto` |

Los datos ya tienen la forma que espera el pipeline: cada ventana es `{quad: [[x,y]×4], ancho_mm, alto_mm}`
en píxeles de la foto (lado mayor 1600 px). El catálogo puede pasar a venir de `/api/catalogo` con los PNG reales.

## Publicar en Play Store / App Store

La app ya es una PWA instalable. Para las tiendas:
- **Android**: empaquétala como TWA con [Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap) o PWABuilder
  apuntando a la URL https donde la publiques.
- **Android + iOS**: [Capacitor](https://capacitorjs.com) — `npm i @capacitor/core @capacitor/cli`,
  `npx cap init Vano es.vano.app --web-dir web`, `npx cap add android`, `npx cap add ios`.
  La carpeta `web/` se usa tal cual. iOS requiere un Mac con Xcode.

Al cambiar archivos, sube `VERSION` en `sw.js` para que los móviles descarguen la versión nueva.
