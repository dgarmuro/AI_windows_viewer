# Frontend (app web instalable) + servidor

```
project/
  backend/
    main.py               FastAPI: sirve frontend/web y la API
    servicio.py           puente con replacer, utils, auto_interior, luz...
    preparar_assets.py    6 clics por PNG -> resources/catalogo_imgs_json/<nombre>.json
    resources/
      catalogo_imgs/        PNG del catálogo  (uno por color)
      catalogo_imgs_json/   sidecar de cada PNG (mismo nombre)
    datos/                se crea solo: sesiones, presupuestos, caché
  frontend/web/           la app
```

## Arrancar

```bash
cd project/backend
pip install fastapi uvicorn python-multipart pillow     # una vez
python main.py
```
- Ordenador: http://localhost:8000
- Móvil (misma wifi): `http://IP-DEL-ORDENADOR:8000`  (IP con `hostname -I`)
- Para instalarla como app hace falta https: `cloudflared tunnel --url http://localhost:8000`

## Añadir un producto

1. Copia el PNG a `backend/resources/catalogo_imgs/`.
2. `python preparar_assets.py resources/catalogo_imgs/mi_ventana.png` (6 clics).
3. Completa el JSON que se crea en `catalogo_imgs_json/` con los datos de la app (todos opcionales):

```json
{
  "modelo": "aura-70-duo",
  "nombre": "Aura 70 Duo",
  "material": "PVC",
  "apertura": "Oscilobatiente, 2 hojas",
  "lema": "La ventana de dos hojas para casi cualquier fachada.",
  "color": {"nombre": "Blanco", "codigo": "RAL 9016", "hex": "#F1F0EB"},
  "precio_m2": 295,
  "destacado": true,
  "ficha": {"Transmitancia Uw": "1,2 W/m²K", "Aislamiento acústico": "36 dB", "Garantía": "10 años"},
  "ancho_mm": 1200, "alto_mm": 1400
}
```
PNG con el mismo `modelo` salen como colores de un mismo producto. Recarga la app: no hace falta reiniciar.

## Variables de entorno (opcionales)

`PUERTO` (8000) · `WEB_DIR` (../frontend/web) · `CATALOGO_DIR` · `SIDECAR_DIR` · `DATOS_DIR` ·
`LIBERAR_DETECTOR` (1: libera SAM tras detectar) · `DIAS_SESION` (7) · `CORS_ORIGENES` (*)

Si la app se empaqueta (Capacitor/TWA) o va en otro dominio: `web/config.js` → `window.API_BASE = "https://..."`.
