"""Servidor: sirve la app (../frontend/web) y la API que llama al backend.

    cd backend && python main.py        -> http://localhost:8000
    PUERTO=8080 python main.py          -> otro puerto
"""
import os
from typing import List, Optional
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import servicio as S

app = FastAPI(title="Visualizador de ventanas")
# CORS: para la app instalada (Capacitor/TWA) o servida desde otro dominio
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGENES", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])
S.limpiar_sesiones()


# ------------------------------------------------------------------ catalogo
@app.get("/api/catalogo")
def catalogo():
    return S.listar_catalogo()


@app.get("/catalogo/{nombre}")
def imagen_catalogo(nombre: str):
    ruta = os.path.join(S.CATALOGO_DIR, os.path.basename(nombre))
    if not os.path.isfile(ruta):
        raise HTTPException(404)
    return FileResponse(ruta, headers={"Cache-Control": "public, max-age=86400"})


# ------------------------------------------------------------------ foto -> ventanas
@app.post("/api/sesion")
async def nueva_sesion(foto: UploadFile = File(...)):
    datos = await foto.read()
    try:
        sid = S.crear_sesion(datos)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return await run_in_threadpool(S.detectar, sid)


class Ejemplo(BaseModel):
    id: str


@app.post("/api/sesion/ejemplo")
async def sesion_ejemplo(p: Ejemplo):
    ej = next((e for e in S._leer_json(os.path.join(S.WEB_DIR, "ejemplos.json")) if e["id"] == p.id), None)
    if ej is None:
        raise HTTPException(404, "No existe ese ejemplo")
    with open(os.path.join(S.WEB_DIR, ej["imagen"]), "rb") as f:
        sid = S.crear_sesion(f.read())
    return await run_in_threadpool(S.detectar, sid)


# ------------------------------------------------------------------ render
class Ventana(BaseModel):
    id: str
    quad: List[List[float]]
    interior: Optional[List[List[float]]] = None
    origen: str = "auto"
    ancho_mm: Optional[float] = None
    alto_mm: Optional[float] = None


class PeticionRender(BaseModel):
    sesion: str
    variante: str
    ventanas: List[Ventana]


@app.post("/api/render")
async def render(p: PeticionRender):
    try:
        return await run_in_threadpool(S.renderizar, p.sesion, p.variante, [v.model_dump() for v in p.ventanas])
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/sesiones/{sid}/{nombre}")
def fichero_sesion(sid: str, nombre: str):
    if not nombre.endswith(".jpg"):
        raise HTTPException(404)
    ruta = os.path.join(S.SESIONES_DIR, os.path.basename(sid), os.path.basename(nombre))
    if not os.path.isfile(ruta):
        raise HTTPException(404)
    return FileResponse(ruta)


# ------------------------------------------------------------------ presupuesto
@app.post("/api/presupuesto")
def presupuesto(datos: dict):
    if not (datos.get("contacto") or {}).get("telefono"):
        raise HTTPException(400, "Falta el teléfono")
    return {"id": S.guardar_presupuesto(datos)}


@app.exception_handler(Exception)
async def error_general(_, exc):
    print(f"[error] {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


# ------------------------------------------------------------------ la app
app.mount("/", StaticFiles(directory=S.WEB_DIR, html=True), name="web")

if __name__ == "__main__":
    
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PUERTO", "8000")))