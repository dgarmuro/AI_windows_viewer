from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from utils import imread_u, imwrite_u
import numpy as np

@dataclass
class Escena:
    ruta_foto: str
    quad: np.ndarray                    # 4x2: donde va la ventana nueva (plano de la vieja)
    placa: np.ndarray                   # BGR uint8, resolucion completa
    mask_hueco: np.ndarray              # uint8 0/255
    mask_oclusores: Optional[np.ndarray]  # lo que va POR DELANTE de la ventana
    color_pared_bgr: Tuple[float, float, float]
    color_cielo_bgr: Tuple[float, float, float]
    sigma_ruido: float
    iou_ajuste: float
    quad_ref: Optional[np.ndarray] = None
    ref_foto: Optional[dict] = None
    quad_pared: Optional[np.ndarray] = None   # contorno exterior del hueco (recercado incluido)

    def guardar(self, carpeta: str):
        os.makedirs(carpeta, exist_ok=True)
        imwrite_u(os.path.join(carpeta, "placa.png"), self.placa)
        imwrite_u(os.path.join(carpeta, "hueco.png"), self.mask_hueco)
        if self.mask_oclusores is not None:
            imwrite_u(os.path.join(carpeta, "oclusores.png"), self.mask_oclusores)

        meta = {k: v for k, v in asdict(self).items()
                if k not in ("placa", "mask_hueco", "mask_oclusores", "quad_ref", "quad_pared")}
        meta["quad"] = self.quad.tolist()
        meta["quad_ref"] = self.quad_ref.tolist() if self.quad_ref is not None else None
        meta["quad_pared"] = self.quad_pared.tolist() if self.quad_pared is not None else None

        with open(os.path.join(carpeta, "escena.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @staticmethod
    def cargar(carpeta: str) -> "Escena":
        placa = imread_u(os.path.join(carpeta, "placa.png"))
        if placa is None:
            raise FileNotFoundError(f"{carpeta}/placa.png")

        with open(os.path.join(carpeta, "escena.json"), encoding="utf-8") as f:
            meta = json.load(f)

        occ_p = os.path.join(carpeta, "oclusores.png")
        return Escena(ruta_foto=meta["ruta_foto"],
                      quad=np.array(meta["quad"], np.float32),
                      placa=placa,
                      mask_hueco=imread_u(os.path.join(carpeta, "hueco.png"), 0),
                      mask_oclusores=imread_u(occ_p, 0) if os.path.exists(occ_p) else None,
                      color_pared_bgr=tuple(meta["color_pared_bgr"]),
                      color_cielo_bgr=tuple(meta["color_cielo_bgr"]),
                      sigma_ruido=meta["sigma_ruido"],
                      iou_ajuste=meta["iou_ajuste"],
                      quad_ref=(np.array(meta["quad_ref"], np.float32) if meta.get("quad_ref") else None),
                      ref_foto=meta.get("ref_foto"),
                      quad_pared=(np.array(meta["quad_pared"], np.float32) if meta.get("quad_pared") else None))