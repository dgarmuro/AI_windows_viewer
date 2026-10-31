from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import threading
import time
import uuid

import cv2
import numpy as np
from PIL import Image, ImageOps

# ---------------------------------------------------------------- rutas (variables de entorno)
AQUI = os.path.dirname(os.path.abspath(__file__))                       # project/backend
BACKEND_DIR = os.path.abspath(os.environ.get("BACKEND_DIR", AQUI))
WEB_DIR = os.path.abspath(os.environ.get("WEB_DIR", os.path.join(AQUI, "..", "frontend", "web")))
CATALOGO_DIR = os.path.abspath(os.environ.get("CATALOGO_DIR", os.path.join(BACKEND_DIR, "resources", "catalogo_imgs")))
SIDECAR_DIR = os.path.abspath(os.environ.get("SIDECAR_DIR", os.path.join(BACKEND_DIR, "resources", "catalogo_imgs_json")))
DATOS_DIR = os.path.abspath(os.environ.get("DATOS_DIR", os.path.join(AQUI, "datos")))
SESIONES_DIR = os.path.join(DATOS_DIR, "sesiones")
PRESUPUESTOS_DIR = os.path.join(DATOS_DIR, "presupuestos")
CACHE_DIR = os.path.join(DATOS_DIR, "cache")
# Plano interior automatico (dejar recercado/jamba reales y meter la ventana mas adentro).
# APAGADO: en tus fotos se equivoca y la ventana nueva sale estrecha dentro del hueco.
# Para probarlo: AUTO_INTERIOR=1 python main.py
AUTO_INTERIOR = os.environ.get("AUTO_INTERIOR", "0") == "1"
LIBERAR_DETECTOR = os.environ.get("LIBERAR_DETECTOR", "1") == "1"   # 8 GB: SAM y LaMa no a la vez
DIAS_SESION = float(os.environ.get("DIAS_SESION", "7"))
LADO_DETECCION = 1280
LADO_VISTA = 1600                   # imagenes que se mandan al movil
MAX_VENTANAS = 15

for d in (SESIONES_DIR, PRESUPUESTOS_DIR, CACHE_DIR):
    os.makedirs(d, exist_ok=True)

sys.path.insert(0, BACKEND_DIR)
from utils import (ajustar_cuadrilatero, tam_objetivo, ordenar_puntos, encoder_expandir,   # noqa: E402
                   placa_limpia, _color_anillo_pared, _color_cielo, _estimar_ruido,
                   medir_referencia, filtrar_oclusores, imread_u, imwrite_u)
from escena_class import Escena                                                       # noqa: E402
from product_class import ProductAsset                                                # noqa: E402
from auto_interior import detectar_interiores_fachada, contornos_parecidos            # noqa: E402
import replacer                                                                       # noqa: E402
try:                                                    # para el perfil a escala real con medidas
    from product_class import escalar_cortes                                          # noqa: E402
except ImportError:
    escalar_cortes = None

GPU = threading.Lock()              # una sola GPU: deteccion y render de uno en uno
_detector, _detector_error = None, None


def detector():
    """Carga DetectorVentanas una vez. Si falla (sin GPU o sin modelos) la app sigue:
    no detecta, pero el cliente puede marcar sus ventanas a mano."""
    global _detector, _detector_error
    if _detector is None and _detector_error is None:
        try:
            from detector_class import DetectorVentanas
            _detector = DetectorVentanas()
        except Exception as e:                                          # noqa: BLE001
            _detector_error = f"{type(e).__name__}: {e}"
            print(f"[servicio] detector no disponible: {_detector_error}")
    return _detector


# ============================================================== CATALOGO
def _leer_json(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[catalogo] {ruta}: {e}")
        return {}


def _sidecar(stem):
    for d in (SIDECAR_DIR, CATALOGO_DIR):               # carpeta de sidecars; si no, junto al PNG
        p = os.path.join(d, stem + ".json")
        if os.path.exists(p):
            return p
    return None


def _color(meta, stem):
    c = meta.get("color")
    if isinstance(c, dict):
        return {"nombre": c.get("nombre", stem), "codigo": c.get("codigo", ""), "hex": c.get("hex", "#C9CCC8")}
    return {"nombre": c or stem.replace("_", " "), "codigo": "", "hex": "#C9CCC8"}


# campos sueltos del sidecar que tambien se ensenan en la ficha si no hay "ficha"
CAMPOS_FICHA = {"vidrio_tipo": "Vidrio", "vidrio": "Vidrio", "perfil": "Sistema", "uw": "Transmitancia Uw",
                "acustico": "Aislamiento acústico", "garantia": "Garantía", "precio": "Precio"}


def _ficha(meta):
    f = dict(meta.get("ficha") or meta.get("especificaciones") or {})
    for k, etq in CAMPOS_FICHA.items():
        if k in meta and etq not in f and isinstance(meta[k], (str, int, float)) and not (k == "precio" and meta.get("precio_m2")):
            f[etq] = meta[k]
    return f


def listar_catalogo():
    """Un modelo por cada valor de "modelo" en los sidecars; cada PNG es un color (variante).
    Sin "modelo", cada PNG es un modelo con un solo color."""
    modelos = {}
    if not os.path.isdir(CATALOGO_DIR):
        print(f"[catalogo] no existe {CATALOGO_DIR}")
        return []
    for f in sorted(os.listdir(CATALOGO_DIR)):
        if not f.lower().endswith(".png"):
            continue
        stem = os.path.splitext(f)[0]
        sc = _sidecar(stem)
        meta = _leer_json(sc) if sc else {}
        mid = str(meta.get("modelo") or stem)
        m = modelos.setdefault(mid, {
            "id": mid,
            "nombre": meta.get("nombre", stem.replace("_", " ").capitalize()),
            "material": meta.get("material", ""),
            "apertura": meta.get("apertura", ""),
            "lema": meta.get("lema", meta.get("descripcion", "")),
            "precio_m2": meta.get("precio_m2"),
            "destacado": bool(meta.get("destacado", False)),
            "ficha": _ficha(meta),
            "variantes": [],
        })
        m["destacado"] = m["destacado"] or bool(meta.get("destacado", False))
        m["variantes"].append({
            "id": stem, **_color(meta, stem),
            "imagen": f"/catalogo/{f}",
            "medidas": bool(meta.get("ancho_mm")),        # admite perfil a escala real
            "preparado": "esquinas_exteriores" in meta,
        })
    return list(modelos.values())


_assets = {}


def cargar_asset(stem):
    """ProductAsset con su sidecar aunque este en otra carpeta (catalogo_imgs_json)."""
    png = os.path.join(CATALOGO_DIR, os.path.basename(stem) + ".png")
    if not os.path.exists(png):
        raise FileNotFoundError(f"producto {stem}")
    sc = _sidecar(stem)
    clave = (stem, os.path.getmtime(png), os.path.getmtime(sc) if sc else 0)
    if clave in _assets:
        return _assets[clave]
    if sc is None or os.path.dirname(sc) == os.path.dirname(png):
        asset = ProductAsset.cargar(png)
    else:
        # ProductAsset.cargar busca el .json junto al .png: se copian juntos a la cache
        d = os.path.join(CACHE_DIR, "assets")
        os.makedirs(d, exist_ok=True)
        for src in (png, sc):
            dst = os.path.join(d, os.path.basename(src))
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
        asset = ProductAsset.cargar(os.path.join(d, os.path.basename(png)))
    _assets.clear()
    _assets[clave] = asset
    return asset


class AssetConMedidas:
    """Con las medidas reales del hueco, el perfil sale con su grosor REAL.
    k = (px de salida por mm) / (px del PNG por mm de catalogo)."""

    def __init__(self, base, ancho_mm=None, alto_mm=None):
        self.base, self.meta = base, base.meta
        self.ancho_mm, self.alto_mm = ancho_mm, alto_mm

    def escalar(self, out_w, out_h):
        b = self.base
        cw, ch = b.meta.get("ancho_mm"), b.meta.get("alto_mm")
        h, w = b.alpha.shape
        ks = []
        if cw and self.ancho_mm:
            ks.append((out_w / float(self.ancho_mm)) / (w / float(cw)))
        if ch and self.alto_mm:
            ks.append((out_h / float(self.alto_mm)) / (h / float(ch)))
        if not ks or not b.nine_slice or escalar_cortes is None:
            return b.escalar(out_w, out_h)
        k = float(np.mean(ks))
        x0, y0, x1, y1 = b.rect_interior
        fx = [(0, x0), (x1, w)] + b.meta.get("fijos_x_rect", [])
        fy = [(0, y0), (y1, h)] + b.meta.get("fijos_y_rect", [])
        return escalar_cortes(b.rgb, b.alpha, fx, fy, out_w, out_h, k_min=k, k_max=k)


# ============================================================== SESIONES
def _dir(sid):
    d = os.path.join(SESIONES_DIR, os.path.basename(sid))
    if not os.path.isdir(d):
        raise FileNotFoundError(f"sesion {sid} (caducada o inexistente)")
    return d


def _vista(img, ruta):
    h, w = img.shape[:2]
    f = min(1.0, LADO_VISTA / max(h, w))
    imwrite_u(ruta, cv2.resize(img, (round(w * f), round(h * f)), interpolation=cv2.INTER_AREA) if f < 1 else img)


def limpiar_sesiones():
    limite = time.time() - DIAS_SESION * 86400
    for s in os.listdir(SESIONES_DIR):
        d = os.path.join(SESIONES_DIR, s)
        guardar = s.startswith("portada") or os.path.exists(os.path.join(d, "presupuesto"))
        if os.path.isdir(d) and not guardar and os.path.getmtime(d) < limite:
            shutil.rmtree(d, ignore_errors=True)


def crear_sesion(datos: bytes, sid=None) -> str:
    sid = sid or uuid.uuid4().hex[:12]
    d = os.path.join(SESIONES_DIR, sid)
    os.makedirs(os.path.join(d, "mascaras"), exist_ok=True)
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(datos))).convert("RGB")   # las de movil vienen giradas
    except Exception as e:                                              # noqa: BLE001
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError(f"No se puede leer la imagen ({e}). Si es HEIC, instala pillow-heif.") from e
    foto = np.array(im)[:, :, ::-1].copy()
    imwrite_u(os.path.join(d, "foto.jpg"), foto)
    _vista(foto, os.path.join(d, "vista.jpg"))
    return sid


def _respuesta(sid, datos):
    return {"sesion": sid, "foto": f"/sesiones/{sid}/vista.jpg", **datos}


def detectar(sid):
    d = _dir(sid)
    foto = imread_u(os.path.join(d, "foto.jpg"))
    H, W = foto.shape[:2]
    ventanas, aviso = [], None
    with GPU:
        det = detector()
        if det is None:
            aviso = "La detección automática no está disponible: añade tus ventanas a mano."
        else:
            escala = min(1.0, LADO_DETECCION / max(H, W))
            peq = cv2.resize(foto, (round(W * escala), round(H * escala)), interpolation=cv2.INTER_AREA) if escala < 1 else foto
            try:
                masks = list(det(peq))
            except RuntimeError as e:
                print(f"[deteccion] {e}")
                masks = []
            masks = [m for m in masks if (m > 127).sum() > 0.0005 * m.size]
            masks.sort(key=lambda m: -int((m > 127).sum()))
            masks = masks[:MAX_VENTANAS]
            gray = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
            factor = np.array([W / peq.shape[1], H / peq.shape[0]], np.float32)
            buenas, quads = [], []
            for m in masks:
                try:
                    quads.append(ajustar_cuadrilatero(m, gray) * factor)
                    buenas.append(m)
                except Exception:                                       # noqa: BLE001
                    continue
            for i, (m, q) in enumerate(zip(buenas, quads)):
                interior = None
                try:                                    # plano de la ventana vieja: voto con las parecidas
                    otras = contornos_parecidos(buenas, i, factor) if AUTO_INTERIOR else []
                    if otras:
                        qi = detectar_interiores_fachada(foto, [q] + otras)[0][0]
                        frac = cv2.contourArea(qi) / max(cv2.contourArea(q), 1.0)
                        if 0.35 <= frac <= 0.97:
                            interior = qi
                except Exception as e:                                  # noqa: BLE001
                    print(f"[deteccion] interior de la ventana {i}: {e}")
                vid = f"v{i}"
                imwrite_u(os.path.join(d, "mascaras", vid + ".png"), m)
                ventanas.append({"id": vid, "quad": np.round(q, 1).tolist(), "origen": "auto",
                                 "interior": None if interior is None else np.round(interior, 1).tolist()})
            if getattr(det, "backend", "") == "sam3":   # oclusores de toda la foto; se recortan por ventana
                acc = np.zeros((H, W), np.uint8)
                for p in ("railing", "plant", "awning", "pipe", "cable"):
                    try:
                        for m in det(peq, prompt=p):
                            acc |= cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
                    except RuntimeError:
                        pass
                if acc.any():
                    imwrite_u(os.path.join(d, "oclusores.png"), acc)
            if LIBERAR_DETECTOR and hasattr(det, "liberar"):
                det.liberar()
            if not ventanas:
                aviso = "No hemos encontrado ventanas en la foto: añádelas a mano."
    datos = {"ancho": W, "alto": H, "ventanas": ventanas, "aviso": aviso}
    with open(os.path.join(d, "datos.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f)
    return _respuesta(sid, datos)


def _poligono(q, H, W):
    m = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(m, np.round(np.asarray(q, np.float32)).astype(np.int32), 255)
    return m


def _caja(q):
    q = np.asarray(q, np.float32)
    (x0, y0), (x1, y1) = q.min(0), q.max(0)
    return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, 1), max(y1 - y0, 1)


def _referencia(foto, q_obj, candidatas):
    """Ventana que NO se cambia, la mas parecida en luz: misma planta, cerca y de tamano similar."""
    if not candidatas:
        return None
    cx, cy, w, h = _caja(q_obj)

    def nota(q):
        x, y, w2, h2 = _caja(q)
        return abs(x - cx) / w + 2.0 * abs(y - cy) / h + abs(np.log((w2 * h2) / (w * h)))
    for q in sorted(candidatas, key=nota):
        try:
            return medir_referencia(foto, np.asarray(q, np.float32))
        except Exception:                                               # noqa: BLE001
            continue
    return None


def renderizar(sid, variante, seleccion):
    """seleccion: [{"id", "quad", "interior" | None, "origen", "ancho_mm", "alto_mm"}]"""
    d = _dir(sid)
    if not seleccion:
        raise ValueError("No hay ventanas elegidas")
    foto = imread_u(os.path.join(d, "foto.jpg"))
    H, W = foto.shape[:2]
    asset_base = cargar_asset(variante)
    occ_p = os.path.join(d, "oclusores.png")
    acc = imread_u(occ_p, 0) if os.path.exists(occ_p) else None

    ventanas = []
    for v in seleccion:
        q_ext = ordenar_puntos(np.asarray(v["quad"], np.float32))
        q_int = ordenar_puntos(np.asarray(v["interior"], np.float32)) if (AUTO_INTERIOR and v.get("interior")) else None
        ventanas.append((v, q_ext, q_int))

    # ---- placa comun: todas las ventanas elegidas borradas (cacheada por seleccion)
    firma = [[v["id"], np.round(qe).tolist(), None if qi is None else np.round(qi).tolist()] for v, qe, qi in ventanas]
    clave = hashlib.md5(json.dumps(firma).encode()).hexdigest()[:12]
    mascaras = []
    for v, q_ext, q_int in ventanas:
        mp = os.path.join(d, "mascaras", f"{v['id']}.png")
        if q_int is not None:
            mascaras.append((_poligono(q_int, H, W), 2))                # conserva recercado y jamba reales
        elif v.get("origen") == "auto" and os.path.exists(mp):
            mascaras.append((cv2.resize(imread_u(mp, 0), (W, H), interpolation=cv2.INTER_NEAREST), 14))
        else:
            mascaras.append((_poligono(q_ext, H, W), 6))

    datos_p = os.path.join(d, "datos.json")
    detectadas = _leer_json(datos_p).get("ventanas", []) if os.path.exists(datos_p) else []
    elegidas = {v["id"] for v in seleccion}
    resto = [v["quad"] for v in detectadas if v["id"] not in elegidas]

    avisos = []
    with GPU:
        placa_p = os.path.join(d, f"placa_{clave}.png")
        if os.path.exists(placa_p):
            placa = imread_u(placa_p)
        else:
            placa = foto.copy()
            for m, dil in mascaras:
                placa = placa_limpia(placa, m, dilatar=dil)
            imwrite_u(placa_p, placa)

        salida = placa                          # cada ventana se pinta sobre el resultado de la anterior
        for (v, q_ext, q_int), (m, _) in zip(ventanas, mascaras):
            q_ven = q_int if q_int is not None else q_ext
            oclus = None
            if acc is not None:
                zona = _poligono(encoder_expandir(q_ext, 1.25), H, W)
                oclus = filtrar_oclusores(cv2.bitwise_and(acc, zona), q_ext)
            esc = Escena(ruta_foto=os.path.join(d, "foto.jpg"), quad=q_ven, placa=salida, mask_hueco=m,
                         mask_oclusores=oclus, color_pared_bgr=_color_anillo_pared(foto, q_ext),
                         color_cielo_bgr=_color_cielo(foto), sigma_ruido=_estimar_ruido(foto, q_ext),
                         iou_ajuste=1.0, quad_ref=None, ref_foto=_referencia(foto, q_ext, resto),
                         quad_pared=q_ext if q_int is not None else None)
            a_mm, h_mm = v.get("ancho_mm"), v.get("alto_mm")
            if a_mm and h_mm:
                tw, th = tam_objetivo(q_ven)
                if abs(np.log((a_mm / h_mm) / (tw / max(th, 1)))) > 0.25:
                    avisos.append(f"Las medidas de una ventana ({a_mm:.0f} × {h_mm:.0f} mm) no cuadran con su forma en la foto.")
            salida = replacer.renderizar(esc, AssetConMedidas(asset_base, a_mm, h_mm), foto_orig=foto)

    nombre = f"res_{os.path.basename(variante)}_{clave}"
    imwrite_u(os.path.join(d, nombre + ".jpg"), salida)
    _vista(salida, os.path.join(d, nombre + "_vista.jpg"))
    return {"resultado": f"/sesiones/{sid}/{nombre}_vista.jpg",
            "descarga": f"/sesiones/{sid}/{nombre}.jpg",
            "original": f"/sesiones/{sid}/vista.jpg",
            "original_full": f"/sesiones/{sid}/foto.jpg",
            "avisos": sorted(set(avisos))}


# ============================================================== PORTADA (antes / despues de inicio)
def portada():
    """Ejemplo de la pantalla de inicio, renderizado UNA vez con el modelo destacado y cacheado."""
    catalogo = listar_catalogo()
    ejemplos = _leer_json(os.path.join(WEB_DIR, "ejemplos.json")) or []
    if not catalogo or not ejemplos:
        return None
    modelo = next((m for m in catalogo if m["destacado"]), catalogo[0])
    var = modelo["variantes"][0]
    ej = ejemplos[0]
    ruta = os.path.join(WEB_DIR, ej["imagen"])
    sid = "portada_" + hashlib.md5(f"{ej['id']}|{var['id']}|{os.path.getmtime(ruta)}".encode()).hexdigest()[:10]
    cache = os.path.join(SESIONES_DIR, sid, "portada.json")
    if os.path.exists(cache):
        return _leer_json(cache)
    with open(ruta, "rb") as f:
        crear_sesion(f.read(), sid)
    sel = [{"id": f"p{i}", "quad": q, "origen": "manual"} for i, q in enumerate(ej["ventanas"][:4])]
    res = renderizar(sid, var["id"], sel)
    out = {"antes": res["original"], "despues": res["resultado"], "ancho": ej["ancho"], "alto": ej["alto"],
           "ventanas": ej["ventanas"][:4], "modelo": modelo["id"], "nombre": modelo["nombre"], "color": var["nombre"]}
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return out


# ============================================================== PRESUPUESTOS
def guardar_presupuesto(datos: dict) -> str:
    pid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    datos = {**datos, "id": pid, "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
    sid = datos.get("sesion")
    if sid:                                             # la sesion de un presupuesto no se borra
        try:
            datos["carpeta_sesion"] = _dir(sid)
            open(os.path.join(_dir(sid), "presupuesto"), "w").close()
        except FileNotFoundError:
            pass
    with open(os.path.join(PRESUPUESTOS_DIR, pid + ".json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print(f"[presupuesto] {pid}: {datos.get('contacto', {}).get('nombre')} · {datos.get('modelo')}")
    return pid