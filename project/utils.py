from typing import Tuple
import numpy as np


def ordenar_puntos(pts: np.ndarray) -> np.ndarray:
    """Devuelve [arriba-izq, arriba-der, abajo-der, abajo-izq]."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1) # x + y de cada punto
    d = (pts[:, 1] - pts[:, 0]) # y - x de cad punto

    # La arriba-derecha tiene x grande e y pequeña, así que y−x es el mínimo (muy negativo).
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def tam_objetivo(quad: np.ndarray) -> Tuple[int, int]:
    """Tamano en pixeles que ocupa el cuadrilatero (media de lados opuestos)."""
    tl, tr, br, bl = quad
    w = 0.5 * (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) # es la distancia euclídea entre dos puntos
    h = 0.5 * (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr))
    return max(int(round(w)), 8), max(int(round(h)), 8)
