from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Tuple
import cv2
import numpy as np
from utils import ordenar_puntos, tam_objetivo, imread_u


def rect_a_rectificado(rect, M, W, H):
    x0, y0, x1, y1 = [float(v) for v in rect]
    esq = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], np.float32).reshape(-1, 1, 2)
    t = cv2.perspectiveTransform(esq, M).reshape(4, 2)
    rx0, rx1 = max(t[0, 0], t[3, 0]), min(t[1, 0], t[2, 0])   # rectangulo inscrito
    ry0, ry1 = max(t[0, 1], t[1, 1]), min(t[2, 1], t[3, 1])
    ri = (int(np.ceil(rx0)), int(np.ceil(ry0)), int(np.floor(rx1)), int(np.floor(ry1)))
    if not (0 < ri[0] < ri[2] < W and 0 < ri[1] < ri[3] < H):
        raise ValueError(f"rect_interior {rect} queda fuera del marco rectificado: {ri} en {W}x{H}")
    return ri

def _tramos(n_in, fijos, n_out, k):
    """Parte [0, n_in) en tramos fijos (escalan con k) y elasticos (absorben el resto)."""
    fijos = sorted((int(a), int(b)) for a, b in fijos)
    cortes, pos = [], 0
    for a, b in fijos:
        if a > pos: cortes.append((pos, a, False))
        cortes.append((a, b, True)); pos = b
    if pos < n_in: cortes.append((pos, n_in, False))
    fijo_out = [max(1, round((b - a) * k)) for a, b, f in cortes if f]
    elast_in = sum(b - a for a, b, f in cortes if not f)
    resto = n_out - sum(fijo_out)
    if resto < len([c for c in cortes if not c[2]]) or elast_in == 0:   # no cabe: escalar todo igual
        return [(a, b, round(a * n_out / n_in), round(b * n_out / n_in), f) for a, b, f in cortes]
    out, o, acum_e, i_f = [], 0, 0, 0
    for a, b, f in cortes:
        if f:
            l = fijo_out[i_f]; i_f += 1
        else:
            acum_e += b - a
            l = round(acum_e / elast_in * resto) - (o - sum(fijo_out[:i_f]))
        out.append((a, b, o, o + l, f)); o += l
    return out
 
def escalar_cortes(rgb, alpha, fijos_x, fijos_y, out_w, out_h, k_min=0.35, k_max=2.5):
    h, w = alpha.shape
    k = float(np.clip(min(out_w / w, out_h / h), k_min, k_max))
    tx, ty = _tramos(w, fijos_x, out_w, k), _tramos(h, fijos_y, out_h, k)
    pre_in = rgb * alpha[..., None]
    pre = np.zeros((out_h, out_w, 3), np.float32); a = np.zeros((out_h, out_w), np.float32)
    m_vidrio = np.zeros((out_h, out_w), np.float32)
    for ya, yb, oya, oyb, fy in ty:
        for xa, xb, oxa, oxb, fx in tx:
            if oyb <= oya or oxb <= oxa: continue
            sz = (oxb - oxa, oyb - oya)
            interp = cv2.INTER_AREA if sz[0] * sz[1] < (xb - xa) * (yb - ya) else cv2.INTER_LINEAR
            pre[oya:oyb, oxa:oxb] = cv2.resize(pre_in[ya:yb, xa:xb], sz, interpolation=interp).reshape(sz[1], sz[0], 3)
            a[oya:oyb, oxa:oxb] = cv2.resize(alpha[ya:yb, xa:xb], sz, interpolation=interp).reshape(sz[1], sz[0])
            if not fx and not fy:
                m_vidrio[oya:oyb, oxa:oxb] = 1.0          # tramo elastico en x e y = vidrio
    a = np.clip(a, 0, 1)
    pre = np.clip(pre, 0, a[..., None])                    # sin sobreoscilaciones
    return pre, a, m_vidrio

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
        #img = cv2.imread(png_path, cv2.IMREAD_UNCHANGED) # sin ese flag OpenCV descarta el cuarto canal silenciosamente y pierdes la transparencia.
        img = imread_u(png_path, cv2.IMREAD_UNCHANGED)
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
        dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32) # Una imagen de 208 px de ancho tiene columnas 0…207. Si pusieras W en lugar de W−1, le estarías pidiendo al warp que la esquina derecha caiga en la columna 208, que no existe, y perderías una columna de píxeles por la derecha.
        M = cv2.getPerspectiveTransform(src, dst) # homografía que lleva el marco a un rectángulo perfecto

        pre = rgb * alpha[..., None]                       # premultiplicar. alpha tiene forma (H,W) y rgb tiene (H,W,3), por eso el None, añade una dime mas al final
        pre = cv2.warpPerspective(pre, M, (W, H), flags=cv2.INTER_CUBIC)
        alpha = cv2.warpPerspective(alpha, M, (W, H), flags=cv2.INTER_CUBIC)
        alpha = np.clip(alpha, 0, 1)
        rgb = pre / np.maximum(alpha[..., None], 1e-4)     # des-premultiplicar
        rgb = np.clip(rgb, 0, 1)

        if "rect_interior" in meta:
            ri = rect_a_rectificado(meta["rect_interior"], M, W, H)
        else:
            mx, my = int(W * 0.14), int(H * 0.14)
            ri = (mx, my, W - mx, H - my)

        # montantes / travesaños opcionales del sidecar, también a coordenadas rectificadas
        yc, xc = (src[:, 1].mean()), (src[:, 0].mean())
        def _x(v): return float(cv2.perspectiveTransform(np.array([[[v, yc]]], np.float32), M)[0, 0, 0])
        def _y(v): return float(cv2.perspectiveTransform(np.array([[[xc, v]]], np.float32), M)[0, 0, 1])
        meta["fijos_x_rect"] = [(int(_x(a)), int(_x(b))) for a, b in meta.get("fijos_x", [])]
        meta["fijos_y_rect"] = [(int(_y(a)), int(_y(b))) for a, b in meta.get("fijos_y", [])]
        
        return ProductAsset(rgb=rgb, alpha=alpha, rect_interior=ri,
                            nine_slice=bool(meta.get("nine_slice", True)),
                            nombre=os.path.basename(png_path), meta=meta)

    def escalar(self, out_w, out_h):
        h, w = self.alpha.shape
        x0, y0, x1, y1 = self.rect_interior
        if not self.nine_slice:
            return escalar_cortes(self.rgb, self.alpha, [], [], out_w, out_h)   # escala todo igual
        fijos_x = [(0, x0), (x1, w)] + self.meta.get("fijos_x_rect", [])
        fijos_y = [(0, y0), (y1, h)] + self.meta.get("fijos_y_rect", [])
        return escalar_cortes(self.rgb, self.alpha, fijos_x, fijos_y, out_w, out_h)