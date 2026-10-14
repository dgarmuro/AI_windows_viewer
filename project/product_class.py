from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Tuple
import cv2
import numpy as np
from utils import ordenar_puntos, tam_objetivo

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
        dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32) # Una imagen de 208 px de ancho tiene columnas 0…207. Si pusieras W en lugar de W−1, le estarías pidiendo al warp que la esquina derecha caiga en la columna 208, que no existe, y perderías una columna de píxeles por la derecha.
        M = cv2.getPerspectiveTransform(src, dst) # homografía que lleva el marco a un rectángulo perfecto

        pre = rgb * alpha[..., None]                       # premultiplicar. alpha tiene forma (H,W) y rgb tiene (H,W,3), por eso el None, añade una dime mas al final
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
    def escalar(self, out_w: int, out_h: int) -> Tuple[np.ndarray, np.ndarray, Tuple[int,int,int,int]]:
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
        oL, oR = max(1, int(round(L*k))), max(1, int(round(R*k)))
        oT, oB = max(1, int(round(T*k))), max(1, int(round(B*k)))

        # si el marco no cabe, lo comprimimos proporcionalmente
        if oL + oR >= out_w - 2:
            f = (out_w - 3) / (oL + oR)
            oL, oR = max(1, int(oL * f)), max(1, int(oR * f))
        if oT + oB >= out_h - 2:
            f = (out_h - 3) / (oT + oB)
            oT, oB = max(1, int(oT * f)), max(1, int(oB * f))
        
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
                    w_in, h_in = cb - ca, rb - ra
                    w_out, h_out = od - oc, ob - oa
                    interp = cv2.INTER_AREA if (w_out * h_out) < (w_in * h_in) else cv2.INTER_CUBIC
                    #interp = cv2.INTER_AREA if (od - oc) < (cb - ca) else cv2.INTER_CUBIC
                    r = cv2.resize(trozo, (od - oc, ob - oa), interpolation=interp)
                    out[oa:ob, oc:od] = r.reshape(ob - oa, od - oc, capa.shape[2])
            salidas.append(out)

        rect = (oL, oT, oL + mid_w, oT + mid_h)   # donde ha caido el vidrio
        return salidas[0], np.clip(salidas[1][:, :, 0], 0, 1), rect
        #return salidas[0], np.clip(salidas[1][:, :, 0], 0, 1)