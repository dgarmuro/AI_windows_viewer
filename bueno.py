"""
window_replace.py
=================

Reemplazo fotorrealista de ventanas en fotos de fachada.

Arquitectura: ANALIZAR una vez por foto  ->  RENDERIZAR N veces (una por modelo de PNG).

    scene = analizar_fachada("fachada.jpg")          # caro, GPU, cacheable
    scene.guardar("fachada.scene")                   # JSON + PNGs auxiliares

    img = renderizar(scene, ProductAsset.cargar("modelos/corredera_roble.png"))
    cv2.imwrite("resultado.jpg", img)

El render es determinista, corre en CPU y tarda decimas de segundo, asi que el
cliente puede ir cambiando de modelo sin esperar.

Dependencias obligatorias:  opencv-python, numpy, scipy, pillow
Dependencias opcionales:
    ultralytics          -> SAM 3 (deteccion + segmentacion en una pasada)
    transformers + segment_anything -> fallback Grounding DINO + SAM
    simple-lama-inpainting -> placa limpia de calidad (MUY recomendado)
"""

from __future__ import annotations
import torch
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, Tuple, List

import cv2
import numpy as np
from scipy.optimize import minimize


# ===========================================================================
# 1. UTILIDADES GEOMETRICAS
# ===========================================================================

def ordenar_puntos(pts: np.ndarray) -> np.ndarray:
    """Devuelve [arriba-izq, arriba-der, abajo-der, abajo-izq]."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1) # x + y de cada punto
    d = (pts[:, 1] - pts[:, 0]) # y - x de cad punto

    # La arriba-derecha tiene x grande e y pequeña, así que y−x es el mínimo (muy negativo).
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _energia_bordes(quad: np.ndarray, grad: np.ndarray, n: int = 40) -> float:
    """Media de |gradiente| muestreada a lo largo de los 4 lados del cuadrilatero.

    Premia que las aristas caigan sobre bordes reales de la imagen (el marco),
    no sobre el interior difuso de la mascara.

    Mide cuánto "apoyan" los cuatro lados del cuadrilátero sobre bordes reales de la foto.
    
    La máscara de SAM es una mancha. Sus bordes son aproximados: puede comerse el marco, 
    incluir el alféizar, o quedarse corta en una esquina. Si solo optimizas IoU 
    contra esa mancha, el cuadrilátero se ajusta a los errores de la mancha.
    
    El píxel de pared y el píxel de marco tienen colores muy distintos, y ese salto está exactamente donde termina la ventana, con precisión de un píxel.


    Esta función mide si los cuatro lados del cuadrilátero propuesto caen encima de esos saltos. Da un número alto si sí, bajo si no. El optimizador lo usa para afinar lo que el IoU deja a medias.

    """
    h, w = grad.shape # grad es una imagen del mismo tamaño que la foto, pero en vez de color guarda cuánto cambia el brillo en ese punto. Negro donde la imagen es lisa, blanco donde hay un borde.
    total, cuenta = 0.0, 0

    '''quad = np.array([[300, 200],    # fila 0 → TL, arriba-izquierda
                 [620, 215],    # fila 1 → TR, arriba-derecha
                 [615, 680],    # fila 2 → BR, abajo-derecha
                 [295, 660]])   # fila 3 → BL, abajo-izquierda'''
    
    for i in range(4): # Recorre los 4 lados
        p0, p1 = quad[i], quad[(i + 1) % 4]
        t = np.linspace(0.05, 0.95, n)[:, None] # genera 40 números repartidos por igual entre 0.05 y 0.95.Son las posiciones relativas a lo largo del lado
        pts = p0[None, :] * (1 - t) + p1[None, :] * t # añade dim nueva de tam 1: p1[None, :]. Ejemplo: p0= [300 200]; p0[None, :]  →  [[300 200]] 
        xs = np.clip(pts[:, 0].astype(int), 0, w - 1) # np.clip(valor, minimo, maximo) si el valor es menor que el mínimo, devuelve el mínimo; si es mayor que el máximo, devuelve el máximo; si está dentro, lo devuelve tal cual.
        ys = np.clip(pts[:, 1].astype(int), 0, h - 1)
        total += grad[ys, xs].sum()
        cuenta += n
    return total / max(cuenta, 1)


def ajustar_cuadrilatero(mask: np.ndarray,
                         gray: Optional[np.ndarray] = None,
                         peso_bordes: float = 0.30) -> np.ndarray:
    """Ajusta un cuadrilatero en perspectiva al hueco.

    En vez de approxPolyDP (que falla en cuanto la mascara incluye alfeizar,
    reja o persiana), optimizamos las 8 coordenadas de las esquinas maximizando
    IoU con la mascara y, opcionalmente, la energia de borde sobre las aristas.

    Convierte la mancha irregular de SAM en un cuadrilátero de cuatro esquinas que respeta la perspectiva.
    """
    m = (mask > 127).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("Mascara vacia")
    largest = max(contours, key=cv2.contourArea)

    init = ordenar_puntos(cv2.boxPoints(cv2.minAreaRect(largest)))

    grad = None
    if gray is not None:
        g = cv2.GaussianBlur(gray, (0, 0), 1.2)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        grad = cv2.magnitude(gx, gy)
        grad /= (np.percentile(grad, 99) + 1e-6)
        grad = np.clip(grad, 0, 1)

    area_ref = float(m.sum())
    lienzo = np.empty_like(m)

    def coste(p):
        # Planteo el problema como una optimización. Las incógnitas son las 8 coordenadas (4 esquinas × 2). La función de coste mide lo mal que va una propuesta
        q = p.reshape(4, 2).astype(np.float32)
        lienzo.fill(0)
        cv2.fillConvexPoly(lienzo, q.astype(np.int32), 1) # pinta el cuadrilátero propuesto relleno de unos en un lienzo negro.
        inter = float(np.count_nonzero(lienzo & m)) # píxeles que están en ambos (la intersección)
        union = float(np.count_nonzero(lienzo | m)) # píxeles en alguno de los dos (la unión).
        c = 1.0 - inter / max(union, 1.0)
        if grad is not None:
            c -= peso_bordes * _energia_bordes(q, grad)
        # penaliza degeneraciones
        if float(lienzo.sum()) < 0.3 * area_ref:
            c += 1.0
        return c

    res = minimize(coste, init.ravel(), method="Powell", options={"maxiter": 2000, "xtol": 0.5, "ftol": 1e-4}) # prueba valores y se queda con los que bajan el coste. Powell no necesita derivadas, que aquí no existen porque el coste es un conteo de píxeles. Empieza en minAreaRect y va empujando esquinas hasta que encaja.
    quad = ordenar_puntos(res.x.reshape(4, 2))

    # si la optimizacion empeoro las cosas, nos quedamos con la inicial
    return quad if coste(quad.ravel()) <= coste(init.ravel()) else init


def tam_objetivo(quad: np.ndarray) -> Tuple[int, int]:
    """Tamano en pixeles que ocupa el cuadrilatero (media de lados opuestos)."""
    tl, tr, br, bl = quad
    w = 0.5 * (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) # es la distancia euclídea entre dos puntos
    h = 0.5 * (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr))
    return max(int(round(w)), 8), max(int(round(h)), 8)


def encoger_quad(quad: np.ndarray, frac_x: float, frac_y: float) -> np.ndarray:
    """Mete el cuadrilatero hacia dentro (retranqueo de la ventana en el hueco)."""
    tl, tr, br, bl = quad
    def lerp(a, b, t): return a * (1 - t) + b * t # lerp(tl, tr, 0.018) avanza un 1.8% del lado superior desde la esquina izquierda hacia la derecha.
    t_l, t_r = lerp(tl, tr, frac_x), lerp(tr, tl, frac_x)
    b_l, b_r = lerp(bl, br, frac_x), lerp(br, bl, frac_x)
    return np.array([lerp(t_l, b_l, frac_y), lerp(t_r, b_r, frac_y),
                     lerp(b_r, t_r, frac_y), lerp(b_l, t_l, frac_y)],
                    dtype=np.float32)


def lado_visible(quad: np.ndarray) -> str:
    """Desde que lado miramos, segun que arista vertical se ve mas corta.

    Si la arista izquierda es mas corta, la camara esta a la derecha y por tanto
    la jamba que se ve es la izquierda.
    """
    tl, tr, br, bl = quad
    izq = np.linalg.norm(bl - tl)
    der = np.linalg.norm(br - tr)
    if abs(izq - der) < 0.03 * max(izq, der):
        return "ninguno"
    return "izquierda" if izq < der else "derecha"


# ===========================================================================
# 2. ASSET DE PRODUCTO (PNG + sidecar JSON)
# ===========================================================================

@dataclass # No requiere init, declaras campos y python escribe el constructor
class ProductAsset:
    """Un modelo de ventana del catalogo.

    El sidecar JSON (mismo nombre, extension .json) es opcional pero MUY
    recomendable: se mide una vez por producto y elimina toda una clase de
    errores. Formato:

        {
          "esquinas_exteriores": [[x,y],[x,y],[x,y],[x,y]],  # TL,TR,BR,BL del marco
          "rect_interior": [x0, y0, x1, y1],                 # zona que puede estirar
          "nine_slice": true,
          "ancho_mm": 1200, "alto_mm": 1400
        }

    Sin sidecar se asume que el PNG esta a escuadra y se usa el bbox del alfa.
    """
    rgb: np.ndarray            # float32 0..1, HxWx3 (NO premultiplicado)
    alpha: np.ndarray          # float32 0..1, HxW
    rect_interior: Tuple[int, int, int, int]
    nine_slice: bool = True
    nombre: str = ""
    meta: dict = field(default_factory=dict)

    @staticmethod
    def cargar(png_path: str) -> "ProductAsset":
        img = cv2.imread(png_path, cv2.IMREAD_UNCHANGED) # sin ese flag OpenCV descarta el cuarto canal silenciosamente y pierdes la transparencia.
        if img is None:
            raise FileNotFoundError(png_path)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            bgr, a = img[:, :, :3], img[:, :, 3]
        else:
            bgr, a = img, np.full(img.shape[:2], 255, np.uint8)

        meta = {}
        sidecar = os.path.splitext(png_path)[0] + ".json"
        if os.path.exists(sidecar):
            with open(sidecar, "r", encoding="utf-8") as f:
                meta = json.load(f)

        rgb = bgr.astype(np.float32) / 255.0
        alpha = a.astype(np.float32) / 255.0

        # --- rectificar: llevamos las esquinas del marco a un rectangulo exacto
        if "esquinas_exteriores" in meta:
            src = ordenar_puntos(np.array(meta["esquinas_exteriores"], np.float32))
        else:
            ys, xs = np.where(alpha > 0.04)
            if len(xs) == 0:
                raise ValueError(f"{png_path}: alfa completamente vacio")
            x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
            src = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32)

        W, H = tam_objetivo(src)
        dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
        M = cv2.getPerspectiveTransform(src, dst) # homografía que lleva el marco a un rectángulo perfecto

        pre = rgb * alpha[..., None]                       # premultiplicar
        pre = cv2.warpPerspective(pre, M, (W, H), flags=cv2.INTER_CUBIC)
        alpha = cv2.warpPerspective(alpha, M, (W, H), flags=cv2.INTER_CUBIC)
        alpha = np.clip(alpha, 0, 1)
        rgb = pre / np.maximum(alpha[..., None], 1e-4)     # des-premultiplicar
        rgb = np.clip(rgb, 0, 1)

        if "rect_interior" in meta:
            ri = tuple(int(v) for v in meta["rect_interior"])
        else:
            mx, my = int(W * 0.14), int(H * 0.14)          # marco ~14% por defecto
            ri = (mx, my, W - mx, H - my)

        return ProductAsset(rgb=rgb, alpha=alpha, rect_interior=ri,
                            nine_slice=bool(meta.get("nine_slice", True)),
                            nombre=os.path.basename(png_path), meta=meta)

    # -------------------------------------------------------------------
    def escalar(self, out_w: int, out_h: int) -> Tuple[np.ndarray, np.ndarray]:
        """Lleva el asset a (out_w, out_h).

        Con nine_slice, el grosor de la perfileria se mantiene (solo estira el
        vidrio), que es como se comporta una ventana a medida real.
        """
        '''if not self.nine_slice:
            interp = cv2.INTER_AREA if out_w < self.rgb.shape[1] else cv2.INTER_CUBIC
            pre = cv2.resize(self.rgb * self.alpha[..., None], (out_w, out_h), interpolation=interp)
            a = cv2.resize(self.alpha, (out_w, out_h), interpolation=interp)
            return pre, np.clip(a, 0, 1)'''

        h0, w0 = self.alpha.shape
        x0, y0, x1, y1 = self.rect_interior

        if not self.nine_slice:
            interp = cv2.INTER_AREA if out_w < w0 else cv2.INTER_CUBIC
            pre = cv2.resize(self.rgb * self.alpha[..., None], (out_w, out_h), interpolation=interp)
            a = cv2.resize(self.alpha, (out_w, out_h), interpolation=interp)
            sx, sy = out_w / w0, out_h / h0
            rect = (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))
            return pre, np.clip(a, 0, 1), rect


        pre_full = self.rgb * self.alpha[..., None]
        capas = [pre_full, self.alpha[..., None]]
        salidas = []

        #h, w = self.alpha.shape
        #x0, y0, x1, y1 = self.rect_interior
        h, w = h0, w0 # new
        L, R, T, B = x0, w - x1, y0, h - y1

        # el marco se escala con el factor global mas suave para no deformarse
        k = min(out_w / w, out_h / h)
        k = float(np.clip(k, 0.35, 2.5))
        oL, oR = max(1, int(L * k)), max(1, int(R * k))
        oT, oB = max(1, int(T * k)), max(1, int(B * k))
        # si el marco no cabe, lo comprimimos proporcionalmente
        if oL + oR >= out_w - 2:
            f = (out_w - 3) / (oL + oR); oL, oR = max(1, int(oL * f)), max(1, int(oR * f))
        if oT + oB >= out_h - 2:
            f = (out_h - 3) / (oT + oB); oT, oB = max(1, int(oT * f)), max(1, int(oB * f))
        mid_w, mid_h = out_w - oL - oR, out_h - oT - oB

        cols_in = [(0, x0), (x0, x1), (x1, w)]
        rows_in = [(0, y0), (y0, y1), (y1, h)]
        cols_out = [(0, oL), (oL, oL + mid_w), (oL + mid_w, out_w)]
        rows_out = [(0, oT), (oT, oT + mid_h), (oT + mid_h, out_h)]

        for capa in capas:
            out = np.zeros((out_h, out_w, capa.shape[2]), np.float32)
            for (ra, rb), (oa, ob) in zip(rows_in, rows_out):
                for (ca, cb), (oc, od) in zip(cols_in, cols_out):
                    trozo = capa[ra:rb, ca:cb]
                    if trozo.size == 0 or (ob - oa) <= 0 or (od - oc) <= 0:
                        continue
                    interp = cv2.INTER_AREA if (od - oc) < (cb - ca) else cv2.INTER_CUBIC
                    r = cv2.resize(trozo, (od - oc, ob - oa), interpolation=interp)
                    out[oa:ob, oc:od] = r.reshape(ob - oa, od - oc, capa.shape[2])
            salidas.append(out)

        rect = (oL, oT, oL + mid_w, oT + mid_h)   # donde ha caido el vidrio
        return salidas[0], np.clip(salidas[1][:, :, 0], 0, 1), rect
        #return salidas[0], np.clip(salidas[1][:, :, 0], 0, 1)


# ===========================================================================
# 3. DETECCION Y SEGMENTACION
# ===========================================================================

class DetectorVentanas:
    """Envuelve SAM 3 (preferido) con fallback a Grounding DINO + SAM 1.

    IMPORTANTE: instanciar UNA vez al arrancar el servicio. Cargar los pesos en
    cada peticion era el mayor coste oculto del script original.
    """

    '''def __init__(self, backend: str = "auto", sam_checkpoint: str = "sam_vit_l_0b3195.pth"):
        self.backend = backend
        self.sam_checkpoint = sam_checkpoint
        self._sam3 = None
        self._dino = None
        self._sam1 = None
        if backend in ("auto", "sam3"):
            try:
                from ultralytics import SAM
                self._sam3 = SAM("sam3.pt")
                self.backend = "sam3"
            except Exception as e:
                if backend == "sam3":
                    raise
                print(f"[detector] SAM 3 no disponible ({e}); usando DINO+SAM")
                self.backend = "dino_sam"
        else:
            self.backend = backend

    # -------------------------------------------------------------------
    
    def liberar(self):
        """Suelta los pesos de la VRAM. Llamar cuando ya se ha detectado."""
        import gc
        self._dino = None
        self._sam1 = None
        self._sam3 = None
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    

    def _detectar_sam3(self, image_bgr, prompt):
        res = self._sam3(image_bgr[:, :, ::-1], prompt=prompt, verbose=False)[0]
        if res.masks is None or len(res.masks) == 0:
            raise RuntimeError("No se detecto ninguna ventana")
        h, w = image_bgr.shape[:2]
        out = []
        for m in res.masks.data.cpu().numpy():
            m = (m > 0.5).astype(np.uint8) * 255
            if m.shape != (h, w):
                m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
            out.append(m)
        return out'''

    def __init__(self, backend: str = "auto",
                 sam_checkpoint: str = "sam_vit_l_0b3195.pth",
                 sam3_id: str = "facebook/sam3",
                 media_precision: bool = True):
        self.sam_checkpoint = sam_checkpoint
        self._sam3 = None
        self._dino = None
        self._sam1 = None

        if backend in ("auto", "sam3"):
            try:
                from transformers import Sam3Model, Sam3Processor
                dev = "cuda" if torch.cuda.is_available() else "cpu"
                modelo = Sam3Model.from_pretrained(sam3_id)
                if dev == "cuda" and media_precision:
                    modelo = modelo.to(dev, torch.bfloat16)   # ~1.7 GB en vez de ~3.5
                else:
                    modelo = modelo.to(dev)
                modelo.eval()
                proc = Sam3Processor.from_pretrained(sam3_id)
                self._sam3 = (proc, modelo, dev)
                self.backend = "sam3"
                print(f"[detector] SAM 3 cargado en {dev}")
            except Exception as e:
                if backend == "sam3":
                    raise
                print(f"[detector] SAM 3 no disponible ({e}); usando DINO+SAM")
                self.backend = "dino_sam"
        else:
            self.backend = backend

    def liberar(self):
        """Suelta los pesos de la VRAM. Llamar cuando ya no haga falta detectar."""
        import gc
        self._dino = None
        self._sam1 = None
        self._sam3 = None
        self.backend = "liberado"        # evita que se recargue sin querer
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    def _detectar_sam3(self, image_bgr, prompt):
        from PIL import Image
        proc, modelo, dev = self._sam3

        # transformers espera PIL en RGB
        pil = Image.fromarray(image_bgr[:, :, ::-1])
        inputs = proc(images=pil, text=prompt, return_tensors="pt").to(dev)

        with torch.no_grad():
            outputs = modelo(**inputs)

        res = proc.post_process_instance_segmentation(
            outputs,
            threshold=0.5,           # confianza minima de la deteccion
            mask_threshold=0.5,      # umbral para binarizar la mascara
            target_sizes=inputs.get("original_sizes").tolist(),
        )[0]

        masks = res["masks"]
        if len(masks) == 0:
            raise RuntimeError(f"SAM 3 no detecto '{prompt}'")

        masks = masks.cpu().numpy()
        h, w = image_bgr.shape[:2]
        out = []
        for m in masks:
            m = (m > 0.5).astype(np.uint8) * 255
            if m.shape != (h, w):
                m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
            out.append(m)
        return out

    def __call__(self, image_bgr: np.ndarray, prompt: str = "window") -> List[np.ndarray]:
        """Devuelve una lista de mascaras uint8 (0/255), una por ventana."""
        if self.backend == "sam3":
            return self._detectar_sam3(image_bgr, prompt)
        return self._detectar_dino_sam(image_bgr)

    def _cargar_dino_sam(self):
        if self._dino is None:
            import torch
            from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            mid = "IDEA-Research/grounding-dino-base"
            self._dino = (AutoProcessor.from_pretrained(mid),
                          AutoModelForZeroShotObjectDetection.from_pretrained(mid).to(dev), dev)
        if self._sam1 is None:
            from segment_anything import sam_model_registry, SamPredictor
            dev = self._dino[2]
            sam = sam_model_registry["vit_l"](checkpoint=self.sam_checkpoint).to(dev)
            self._sam1 = SamPredictor(sam)

    def _detectar_dino_sam(self, image_bgr):
        import torch
        from PIL import Image
        self._cargar_dino_sam()
        processor, model, dev = self._dino
        pil = Image.fromarray(image_bgr[:, :, ::-1])
        inputs = processor(images=pil, text="window.", return_tensors="pt").to(dev)
        with torch.no_grad():
            outputs = model(**inputs)
        r = processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=0.30, text_threshold=0.25,
            target_sizes=[pil.size[::-1]])[0]
        boxes = r["boxes"].cpu().numpy()
        if len(boxes) == 0:
            raise RuntimeError("Grounding DINO no detecto ventana")

        self._sam1.set_image(image_bgr[:, :, ::-1])
        masks = []
        for b in boxes:                       # TODAS las ventanas, no solo argmax
            m, _, _ = self._sam1.predict(box=b.astype(int),
                                         multimask_output=False)  # con caja, False
            masks.append(m[0].astype(np.uint8) * 255)
        return masks


# ===========================================================================
# 4. PLACA LIMPIA (borrar la ventana vieja)
# ===========================================================================

_LAMA = None # . LaMa está entrenado específicamente para rellenar huecos continuando estructuras y texturas. No necesita prompt, es determinista (misma entrada, misma salida siempre) y tarda menos de un segundo. Difusión aquí inventa cosas, cambia entre ejecuciones y tarda segundos o minutos.


def placa_limpia(image_bgr, mask, dilatar=14, lado_lama=896,
                 margen=0.40, device=None):
    """Borra la ventana vieja y reconstruye pared.

    Trabaja sobre un RECORTE alrededor del hueco, no sobre la foto entera:
    menos memoria y mejor calidad, porque LaMa rinde cerca de su resolucion
    de entrenamiento (~512 px) y se degrada con imagenes muy grandes.
    """
    global _LAMA
    H, W = image_bgr.shape[:2]
    k = np.ones((dilatar * 2 + 1, dilatar * 2 + 1), np.uint8)
    m = cv2.dilate((mask > 127).astype(np.uint8) * 255, k)

    ys, xs = np.where(m > 0)
    if len(xs) == 0:
        return image_bgr.copy()

    # --- recorte con margen: LaMa necesita ver pared alrededor para copiarla
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    mx, my = int((x1 - x0 + 1) * margen), int((y1 - y0 + 1) * margen)
    cx0, cy0 = max(0, x0 - mx), max(0, y0 - my)
    cx1, cy1 = min(W, x1 + mx + 1), min(H, y1 + my + 1)

    crop = image_bgr[cy0:cy1, cx0:cx1]
    crop_m = m[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    # --- bajar a la escala de trabajo de LaMa
    esc = min(1.0, lado_lama / max(ch, cw))
    if esc < 1.0:
        sw, sh = int(cw * esc), int(ch * esc)
        peq = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA)
        peq_m = cv2.resize(crop_m, (sw, sh), interpolation=cv2.INTER_NEAREST)
    else:
        peq, peq_m = crop, crop_m

    try:
        if _LAMA is None:
            from simple_lama_inpainting import SimpleLama
            _LAMA = SimpleLama(device=device) if device else SimpleLama()
        from PIL import Image
        out = _LAMA(Image.fromarray(peq[:, :, ::-1]), Image.fromarray(peq_m))

        # LaMa rellena hasta multiplo de 8 y NO deshace ese relleno:
        # hay que recortar a las dimensiones que le dimos.
        ph, pw = peq.shape[:2]
        rel_peq = np.array(out)[:ph, :pw, ::-1]

        rel = cv2.resize(rel_peq, (cw, ch), interpolation=cv2.INTER_CUBIC) \
            if esc < 1.0 else rel_peq
    except Exception as e:
        print(f"[placa] LaMa fallo ({type(e).__name__}: {e}); usando cv2.inpaint")
        rel = cv2.inpaint(crop, crop_m, 7, cv2.INPAINT_TELEA)

    # --- pegar SOLO dentro de la mascara: el resto de la foto no se toca
    a = cv2.GaussianBlur(crop_m.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
    salida = image_bgr.copy()
    salida[cy0:cy1, cx0:cx1] = (crop.astype(np.float32) * (1 - a) +
                                rel.astype(np.float32) * a).astype(np.uint8)
    return salida

# ===========================================================================
# 5. ESCENA (resultado del analisis, cacheable)
# ===========================================================================

@dataclass
class Escena:
    ruta_foto: str
    quad: np.ndarray                    # 4x2 en coordenadas de la foto original
    placa: np.ndarray                   # BGR uint8, resolucion completa
    mask_hueco: np.ndarray              # uint8 0/255
    mask_oclusores: Optional[np.ndarray]  # lo que va POR DELANTE de la ventana
    color_pared_bgr: Tuple[float, float, float]
    color_cielo_bgr: Tuple[float, float, float]
    sigma_ruido: float
    iou_ajuste: float
    quad_ref: Optional[np.ndarray] = None
    ref_foto: Optional[dict] = None

    def guardar(self, carpeta: str):
        os.makedirs(carpeta, exist_ok=True)
        cv2.imwrite(os.path.join(carpeta, "placa.png"), self.placa)
        cv2.imwrite(os.path.join(carpeta, "hueco.png"), self.mask_hueco)
        if self.mask_oclusores is not None:
            cv2.imwrite(os.path.join(carpeta, "oclusores.png"), self.mask_oclusores)
        '''meta = {k: v for k, v in asdict(self).items()
                if k not in ("placa", "mask_hueco", "mask_oclusores")}
        meta["quad"] = self.quad.tolist()'''

        meta = {k: v for k, v in asdict(self).items()
                if k not in ("placa", "mask_hueco", "mask_oclusores", "quad_ref")}
        meta["quad"] = self.quad.tolist()
        meta["quad_ref"] = self.quad_ref.tolist() if self.quad_ref is not None else None

        with open(os.path.join(carpeta, "escena.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @staticmethod
    def cargar(carpeta: str) -> "Escena":
        with open(os.path.join(carpeta, "escena.json"), encoding="utf-8") as f:
            meta = json.load(f)
        occ_p = os.path.join(carpeta, "oclusores.png")
        return Escena(ruta_foto=meta["ruta_foto"],
                      quad=np.array(meta["quad"], np.float32),
                      placa=cv2.imread(os.path.join(carpeta, "placa.png")),
                      mask_hueco=cv2.imread(os.path.join(carpeta, "hueco.png"), 0),
                      mask_oclusores=cv2.imread(occ_p, 0) if os.path.exists(occ_p) else None,
                      color_pared_bgr=tuple(meta["color_pared_bgr"]),
                      color_cielo_bgr=tuple(meta["color_cielo_bgr"]),
                      sigma_ruido=meta["sigma_ruido"],
                      iou_ajuste=meta["iou_ajuste"],
                      quad_ref=(np.array(meta["quad_ref"], np.float32) if meta.get("quad_ref") else None),
                      ref_foto=meta.get("ref_foto"))


def _color_anillo_pared(img, quad, grosor=0.10):
    """Color medio de la pared en un anillo ALREDEDOR del hueco.

    Medir dentro del hueco (como hacia ajustar_brillo del script original) toma
    el cristal oscuro de la ventana vieja y oscurece sistematicamente el render.
    """
    fuera = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(fuera, encoder_expandir(quad, 1 + grosor).astype(np.int32), 255)
    dentro = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(dentro, encoder_expandir(quad, 1 + grosor * 0.15).astype(np.int32), 255)
    anillo = cv2.subtract(fuera, dentro)
    px = img[anillo > 0]
    return tuple(np.median(px, axis=0).astype(float)) if len(px) else (128., 128., 128.)


def encoder_expandir(quad: np.ndarray, factor: float) -> np.ndarray:
    c = quad.mean(axis=0)
    return (c + (quad - c) * factor).astype(np.float32)


def _estimar_ruido(img, quad):
    """Sigma del ruido en la pared, para poder igualarlo en el parche pegado."""
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, encoder_expandir(quad, 1.6).astype(np.int32), 255)
    cv2.fillConvexPoly(m, encoder_expandir(quad, 1.05).astype(np.int32), 0)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    alta = g - cv2.GaussianBlur(g, (0, 0), 1.5)
    px = alta[m > 0]
    return float(np.std(px)) if len(px) > 50 else 1.5


def _color_cielo(img):
    banda = img[: max(8, img.shape[0] // 10)]
    return tuple(np.percentile(banda.reshape(-1, 3), 75, axis=0).astype(float))


# ===========================================================================
# 6. ANALISIS
# ===========================================================================

def analizar_fachada(ruta_foto: str,
                     detector: Optional[DetectorVentanas] = None,
                     indice_ventana: int = 0,
                     quad_manual: Optional[np.ndarray] = None,
                     lado_deteccion: int = 1280,
                     detectar_oclusores: bool = True) -> Escena:
    """Analisis completo de una foto. Caro, se hace una vez y se cachea.

    quad_manual permite saltarse la deteccion por completo: es el camino que
    usara el editor de esquinas del comercial cuando la deteccion falle.
    """
    foto = cv2.imread(ruta_foto)
    if foto is None:
        raise FileNotFoundError(ruta_foto)
    H, W = foto.shape[:2]

    escala = min(1.0, lado_deteccion / max(H, W))
    peq = cv2.resize(foto, (int(W * escala), int(H * escala)),
                     interpolation=cv2.INTER_AREA) if escala < 1 else foto
    quad_ref = None
    if quad_manual is not None:
        quad = ordenar_puntos(np.asarray(quad_manual, np.float32))
        mask_full = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask_full, quad.astype(np.int32), 255)
        iou = 1.0
    else:
        detector = detector or DetectorVentanas()
        masks = detector(peq)
        masks.sort(key=lambda m: -int((m > 127).sum()))
        mask = masks[min(indice_ventana, len(masks) - 1)]

        gray = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
        quad_peq = ajustar_cuadrilatero(mask, gray)

        # metrica de calidad: si el quad no cuadra con la mascara, hay que revisar
        test = np.zeros_like(mask)
        cv2.fillConvexPoly(test, quad_peq.astype(np.int32), 255)
        b1, b2 = test > 127, mask > 127
        iou = float(np.count_nonzero(b1 & b2)) / max(np.count_nonzero(b1 | b2), 1)

        for m_alt in masks[1:]:
            try:
                quad_ref = ajustar_cuadrilatero(m_alt, gray) / escala
                break
            except Exception:
                continue
        # >>> clave: las esquinas vuelven a RESOLUCION COMPLETA
        quad = quad_peq / escala
        mask_full = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)

    print(f"[analisis] quad IoU={iou:.3f}  hueco={tam_objetivo(quad)} px")
    if iou < 0.85:
        print("[analisis] AVISO: ajuste dudoso, conviene corregir esquinas a mano")

    
    oclusores = None
    if detectar_oclusores and detector is not None and detector.backend == "sam3":
        try:
            zona = np.zeros((H, W), np.uint8)
            cv2.fillConvexPoly(zona, encoder_expandir(quad, 1.25).astype(np.int32), 255)
            acc = np.zeros((H, W), np.uint8)
            for p in ("railing", "plant", "awning", "pipe", "cable"):
                for m in detector(peq, prompt=p):
                    acc |= cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
            oclusores = cv2.bitwise_and(acc, zona)
            if oclusores.sum() == 0:
                oclusores = None
        except Exception as e:
            print(f"[analisis] oclusores omitidos: {e}")

    if detector is not None:
        detector.liberar()
    print("[analisis] generando placa limpia...")
    placa = placa_limpia(foto, mask_full)

    return Escena(ruta_foto=ruta_foto, quad=quad, placa=placa, mask_hueco=mask_full,
                  mask_oclusores=oclusores,
                  color_pared_bgr=_color_anillo_pared(foto, quad),
                  color_cielo_bgr=_color_cielo(foto),
                  sigma_ruido=_estimar_ruido(foto, quad),
                  iou_ajuste=iou,
                quad_ref=quad_ref,
                  ref_foto=(medir_referencia(foto, quad_ref)
                            if quad_ref is not None else None))


# ===========================================================================
# 7. RENDER
# ===========================================================================

def _campo_iluminacion(placa, quad, sigma_rel=0.25):
    """Campo de luz de baja frecuencia normalizado, tomado de la pared.

    Multiplicarlo transfiere la variacion espacial de luz de la fachada
    (sombra del alero, degradado) SIN tocar el color base del producto.
    """
    w, h = tam_objetivo(quad)
    sigma = max(3.0, sigma_rel * max(w, h))
    lab = cv2.cvtColor(placa, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = cv2.GaussianBlur(lab[:, :, 0], (0, 0), sigma)
    return L / max(float(np.median(L)), 1e-3)


def _reflejo_cristal(pre, alpha, color_cielo, intensidad=0.22):
    """Degradado de cielo sobre el vidrio.

    Un PNG de estudio tiene el cristal plano; en exterior el cristal SIEMPRE
    refleja el cielo. Sin esto el montaje canta aunque todo lo demas este bien.
    """
    h, w = alpha.shape
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    cielo = np.array(color_cielo, np.float32) / 255.0
    grad = cielo[None, None, :] * (1.0 - t) ** 1.6
    # solo donde hay producto, y mas fuerte en zonas lisas (el vidrio)
    lisura = 1.0 - np.clip(cv2.Laplacian(
        cv2.cvtColor(np.clip(pre, 0, 1), cv2.COLOR_BGR2GRAY), cv2.CV_32F, ksize=3) * 6, 0, 1)
    peso = (intensidad * lisura * alpha)[..., None]
    return np.clip(pre * (1 - peso * 0.4) + grad * peso, 0, 1)


def _dibujar_jamba(img, quad_hueco, quad_ventana, color_pared, lado):
    """Pinta la jamba visible del retranqueo, para que la ventana no parezca plana."""
    if lado == "ninguno":
        return img
    ho, hi = quad_hueco, quad_ventana
    idx = (0, 3, 3, 0) if lado == "izquierda" else (1, 2, 2, 1)
    poly = np.array([ho[idx[0]], hi[idx[3]], hi[idx[2]], ho[idx[1]]], np.float32)
    capa = img.copy()
    col = tuple(float(c * 0.72) for c in color_pared)      # jamba en sombra
    cv2.fillConvexPoly(capa, poly.astype(np.int32), col)
    m = np.zeros(img.shape[:2], np.float32)
    cv2.fillConvexPoly(m, poly.astype(np.int32), 1.0)
    m = cv2.GaussianBlur(m, (0, 0), 1.2)[..., None]
    return (img.astype(np.float32) * (1 - m) + capa.astype(np.float32) * m).astype(np.uint8)


def _oclusion_contacto(img, quad, fuerza=0.35, ancho_rel=0.035):
    """Oscurecimiento suave en el perimetro interior del hueco (contact shadow)."""
    h, w = img.shape[:2]
    m = np.zeros((h, w), np.float32)
    cv2.fillConvexPoly(m, quad.astype(np.int32), 1.0)
    interior = np.zeros((h, w), np.float32)
    cv2.fillConvexPoly(interior, encoder_expandir(quad, 1 - ancho_rel * 2).astype(np.int32), 1.0)
    banda = np.clip(m - interior, 0, 1)
    tw, th = tam_objetivo(quad)
    banda = cv2.GaussianBlur(banda, (0, 0), max(1.5, 0.02 * max(tw, th)))
    f = (1.0 - fuerza * banda)[..., None]
    return np.clip(img.astype(np.float32) * f, 0, 255).astype(np.uint8)


def renderizar(escena: Escena,
               asset: ProductAsset,
               retranqueo: float = 0.018, #0.018,
               reflejo: float = 0.22,
               grano: bool = True,
               supersample: float = 1.6) -> np.ndarray:
    """Compone el asset en la escena. Determinista, CPU, decimas de segundo."""
    placa = escena.placa
    H, W = placa.shape[:2]
    quad_hueco = escena.quad
    quad_win = encoger_quad(quad_hueco, retranqueo, retranqueo * 0.6)

    ''' # 1) escalar el asset (nine-slice) a un tamano ligeramente superior al final:
    #    warpPerspective aliasea muchisimo la perfileria fina si no sobremuestreas
    tw, th = tam_objetivo(quad_win)
    pre, a = asset.escalar(int(tw * supersample), int(th * supersample))

    # 2) reflejo de cielo en el vidrio (antes del warp, en espacio rectificado)
    if reflejo > 0:
        rgb = pre / np.maximum(a[..., None], 1e-4)
        rgb = _reflejo_cristal(rgb, a, escena.color_cielo_bgr, reflejo)
        pre = rgb * a[..., None]'''

    # 1) escalar el asset (nine-slice) a un tamano ligeramente superior al final
    tw, th = tam_objetivo(quad_win)
    pre, a, rect_vidrio = asset.escalar(int(tw * supersample), int(th * supersample))

    rgb = pre / np.maximum(a[..., None], 1e-4)

    # 2a) ARMONIZAR contra una ventana real de la misma foto: exposicion,
    #     temperatura de color y oscuridad del cristal, todo de una vez
    if escena.ref_foto is not None:
        rgb = _armonizar_por_referencia(rgb, a, rect_vidrio, escena.ref_foto)

    # 2b) reflejo de cielo, ya en el espacio de luz de la escena
    if reflejo > 0:
        rgb = _reflejo_cristal(rgb, a, escena.color_cielo_bgr, reflejo)

    pre = rgb * a[..., None]


    # 3) homografia. Alfa PREMULTIPLICADO -> sin halos oscuros en los perfiles
    hs, ws = a.shape
    src = np.array([[0, 0], [ws - 1, 0], [ws - 1, hs - 1], [0, hs - 1]], np.float32)
    M = cv2.getPerspectiveTransform(src, quad_win)
    pre_w = cv2.warpPerspective(pre, M, (W, H), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a_w = cv2.warpPerspective(a, M, (W, H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a_w = np.clip(a_w, 0, 1)

    # 4) transferir la luz de la fachada sin alterar el color del producto
    campo = _campo_iluminacion(placa, quad_hueco)[..., None]
    pre_w = np.clip(pre_w * campo, 0, 1)

    # 5) jamba del retranqueo
    fondo = _dibujar_jamba(placa, quad_hueco, quad_win,
                           escena.color_pared_bgr, lado_visible(quad_hueco))

    # 6) composicion sobre premultiplicado
    out = fondo.astype(np.float32) / 255.0 * (1 - a_w[..., None]) + pre_w
    out = np.clip(out * 255.0, 0, 255).astype(np.uint8)

    # 7) sombra de contacto en el perimetro del hueco
    out = _oclusion_contacto(out, quad_hueco)

    # 8) igualar grano: sin esto el parche se lee como "demasiado limpio"
    if grano and escena.sigma_ruido > 0.2:
        rng = np.random.default_rng(0)                  # semilla fija = determinista
        ruido = rng.normal(0, escena.sigma_ruido, (H, W, 1)).astype(np.float32)
        m = (a_w > 0.02)[..., None]
        out = np.clip(out.astype(np.float32) + ruido * m, 0, 255).astype(np.uint8)

    # 9) devolver los oclusores al frente (reja, planta, bajante)
    if escena.mask_oclusores is not None:
        mo = cv2.GaussianBlur(escena.mask_oclusores.astype(np.float32) / 255.0, (0, 0), 0.8)[..., None]
        orig = cv2.imread(escena.ruta_foto)
        if orig is not None and orig.shape == out.shape:
            out = (out.astype(np.float32) * (1 - mo) + orig.astype(np.float32) * mo).astype(np.uint8)

    return out


# ===========================================================================
# 8. DEBUG
# ===========================================================================

def debug_escena(escena: Escena, salida="debug_escena.jpg"):
    foto = cv2.imread(escena.ruta_foto)
    vis = foto.copy()
    ov = vis.copy()
    ov[escena.mask_hueco > 127] = (0, 200, 0)
    vis = cv2.addWeighted(ov, 0.30, vis, 0.70, 0)
    cv2.polylines(vis, [escena.quad.astype(np.int32)], True, (0, 0, 255), 3)
    for i, p in enumerate(escena.quad.astype(int)):
        cv2.circle(vis, tuple(p), 9, (255, 0, 0), -1)
        cv2.putText(vis, "TL TR BR BL".split()[i], tuple(p + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
    cv2.imwrite(salida, vis)
    return vis

def medir_referencia(foto_bgr, quad_ref, frac_marco=0.20):
    """Brillo y color reales de una ventana YA EXISTENTE en la misma foto.

    Es el mejor patron posible: misma luz, mismo muro, misma camara, mismo
    balance de blancos. Mejor que cualquier constante que estimemos a ojo.
    """
    h, w = foto_bgr.shape[:2]
    fuera = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(fuera, quad_ref.astype(np.int32), 255)
    dentro = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(dentro, encoder_expandir(quad_ref, 1 - 2*frac_marco).astype(np.int32), 255)
    marco = cv2.subtract(fuera, dentro)

    pm = foto_bgr[marco > 0].astype(np.float32) / 255.0
    pv = foto_bgr[dentro > 0].astype(np.float32) / 255.0
    if len(pm) < 30 or len(pv) < 30:
        return None
    #return {"marco": np.median(pm, 0), "vidrio": np.median(pv, 0)}
    return {"marco": np.median(pm, 0).tolist(),"vidrio": np.median(pv, 0).tolist()}

def _armonizar_por_referencia(rgb, alpha, rect_vidrio, ref,
                              fuerza=0.85, gain_max=3.0):
    """Lleva marco y vidrio del producto al brillo medido en una ventana real.

    Corrige exposicion, temperatura de color y oscuridad del cristal de una
    sola vez, porque la ganancia se calcula por canal BGR.
    """
    h, w = alpha.shape
    x0, y0, x1, y1 = [int(v) for v in rect_vidrio]

    m_vidrio = np.zeros((h, w), np.float32)
    cv2.rectangle(m_vidrio, (x0, y0), (x1, y1), 1.0, -1)
    m_vidrio = cv2.GaussianBlur(m_vidrio, (0, 0), max(1.0, 0.008 * max(w, h)))
    opaco = (alpha > 0.5).astype(np.float32)
    m_vidrio *= opaco
    m_marco = np.clip(1.0 - m_vidrio, 0, 1) * opaco

    out = rgb.astype(np.float32).copy()
    for mascara, clave in ((m_marco, "marco"), (m_vidrio, "vidrio")):
        sel = mascara > 0.5
        if sel.sum() < 30:
            continue
        actual = np.median(rgb[sel], 0)
        objetivo = np.array(ref[clave], np.float32)
        gain = np.clip(objetivo / np.maximum(actual, 1e-3), 1.0 / gain_max, gain_max)
        gain = 1.0 + (gain - 1.0) * fuerza
        out = out * (1 - mascara[..., None]) + out * gain[None, None, :] * mascara[..., None]

    return np.clip(out, 0, 1)

# ===========================================================================
if __name__ == "__main__":
    detector = DetectorVentanas()                       # una sola vez

    escena = analizar_fachada("./fachada_real4.jpg", detector=detector)
    debug_escena(escena)
    escena.guardar("./cache/fachada_real4")

    # a partir de aqui, cada modelo del catalogo es casi instantaneo
    

    '''for png in ["./replace2.png"]:
        if not os.path.exists(png):
            continue
        asset = ProductAsset.cargar(png)
        img = renderizar(escena, asset)
        nombre = os.path.splitext(os.path.basename(png))[0]
        cv2.imwrite(f"resultado_{nombre}.jpg", img)
        print("->", f"resultado_{nombre}.jpg")'''

    for png in ["./replace3.png"]:
        if not os.path.exists(png):
            print(f"[main] no existe {png}")
            continue

        sidecar = os.path.splitext(png)[0] + ".json"
        if not os.path.exists(sidecar):
            print(f"[main] AVISO: falta {sidecar}. Sin el, la perspectiva "
                  f"propia del PNG no se corrige. Ejecuta:\n"
                  f"        python3 preparar_asset.py {png}")

        asset = ProductAsset.cargar(png)
        img = renderizar(escena, asset)
        nombre = os.path.splitext(os.path.basename(png))[0]
        cv2.imwrite(f"resultado_{nombre}.jpg", img)
        print("->", f"resultado_{nombre}.jpg")