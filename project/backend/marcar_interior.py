"""Marcar a mano el plano de la ventana vieja (persiana, cristal) dentro del hueco.

Muestra un recorte ampliado alrededor del contorno detectado (en rojo) y pide
4 clics en las esquinas de la ventana vieja: lo que queda entre el rojo y esos
4 puntos (recercado, jamba, alfeizar) se conserva de la foto real.

Teclas: u = deshacer el ultimo clic, q = cancelar (devuelve None).
"""
import cv2
import numpy as np
from utils import ordenar_puntos, encoder_expandir


def marcar_interior(foto, quad_ext, lado_vista=900, margen=1.6):
    H, W = foto.shape[:2]
    z = encoder_expandir(np.asarray(quad_ext, np.float32), margen)
    x0, y0 = np.clip(np.floor(z.min(0)).astype(int), 0, [W - 1, H - 1])
    x1, y1 = np.clip(np.ceil(z.max(0)).astype(int), 1, [W, H])
    recorte = foto[y0:y1, x0:x1]
    esc = lado_vista / max(recorte.shape[:2])            # aqui SI se amplia: clics precisos
    vista = cv2.resize(recorte, None, fx=esc, fy=esc,
                       interpolation=cv2.INTER_CUBIC if esc > 1 else cv2.INTER_AREA)
    q_vista = ((np.asarray(quad_ext, np.float32) - [x0, y0]) * esc).astype(np.int32)
    cv2.polylines(vista, [q_vista], True, (0, 0, 255), 2)
    base = vista.copy()
    pts = []
    titulo = "4 esquinas de la ventana vieja (u=deshacer, q=cancelar)"

    def pintar():
        vista[:] = base
        for i, (px, py) in enumerate(pts):
            p = (int((px - x0) * esc), int((py - y0) * esc))
            cv2.circle(vista, p, 6, (0, 220, 255), -1)
            cv2.putText(vista, str(i + 1), (p[0] + 8, p[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
        if len(pts) >= 2:
            cv2.polylines(vista, [np.array([((px - x0) * esc, (py - y0) * esc) for px, py in pts],
                                           np.int32)], len(pts) == 4, (0, 220, 255), 1)
        cv2.imshow(titulo, vista)

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x0 + x / esc, y0 + y / esc))     # a coordenadas de la foto completa
            pintar()

    cv2.namedWindow(titulo)
    cv2.setMouseCallback(titulo, on_mouse)
    pintar()
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k == ord("u") and pts:
            pts.pop(); pintar()
        if k == ord("q"):
            pts.clear(); break
        if len(pts) == 4:
            cv2.waitKey(400)                             # que se vea el cuarto punto
            break
    cv2.destroyAllWindows()
    return ordenar_puntos(np.array(pts, np.float32)) if len(pts) == 4 else None
