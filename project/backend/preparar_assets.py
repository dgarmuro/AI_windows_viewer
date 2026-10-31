import json
import os
import sys

import cv2
import numpy as np

from utils import ordenar_puntos, imread_u

AQUI = os.path.dirname(os.path.abspath(__file__))
SIDECAR_DIR = os.environ.get("SIDECAR_DIR", os.path.join(AQUI, "resources", "catalogo_imgs_json"))


def marcar_esquinas_png(png_path, lado_max=900):
    img = imread_u(png_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(png_path)

    # fondo de tablero para ver donde acaba la transparencia
    if img.ndim == 3 and img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        fondo = np.full(img[:, :, :3].shape, 190, np.uint8)
        fondo[::16, :] = 140
        fondo[:, ::16] = 140
        vis = (img[:, :, :3] * a + fondo * (1 - a)).astype(np.uint8)
    else:
        vis = img[:, :, :3].copy()

    h, w = vis.shape[:2]
    esc = min(1.0, lado_max / max(h, w))
    disp = cv2.resize(vis, (int(w * esc), int(h * esc)))
    base = disp.copy()
    pts, win = [], "6 clics: 4 esquinas marco + 2 del vidrio (u=deshacer, q=salir)"

    def pintar():
        disp[:] = base
        for i, p in enumerate(pts):
            q = (int(p[0] * esc), int(p[1] * esc))
            col = (0, 0, 255) if i < 4 else (0, 200, 255)
            cv2.circle(disp, q, 6, col, -1)
            cv2.putText(disp, str(i + 1), (q[0] + 9, q[1] - 9), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        cv2.imshow(win, disp)

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 6:
            pts.append((x / esc, y / esc))
            pintar()

    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    pintar()
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k == ord("u") and pts:
            pts.pop(); pintar()
        if k == ord("q") or len(pts) == 6:
            break
    cv2.destroyAllWindows()
    if len(pts) < 6:
        raise RuntimeError("Faltan clics")

    ext = ordenar_puntos(np.array(pts[:4], np.float32))
    (ix0, iy0), (ix1, iy1) = pts[4], pts[5]

    os.makedirs(SIDECAR_DIR, exist_ok=True)
    destino = os.path.join(SIDECAR_DIR, os.path.splitext(os.path.basename(png_path))[0] + ".json")
    meta = {}
    if os.path.exists(destino):
        with open(destino, encoding="utf-8") as f:
            meta = json.load(f)
    meta.update({
        "esquinas_exteriores": ext.round(1).tolist(),
        "rect_interior": [int(min(ix0, ix1)), int(min(iy0, iy1)), int(max(ix0, ix1)), int(max(iy0, iy1))],
        "nine_slice": meta.get("nine_slice", True),
    })
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Guardado {destino}")
    return meta


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for ruta in sys.argv[1:]:
        marcar_esquinas_png(ruta)