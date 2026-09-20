from bueno import *

def marcar_esquinas_png(png_path, lado_max=900):
    """Clic en 6 puntos y genera el sidecar JSON del producto.

    Orden: 4 esquinas EXTERIORES del marco (arriba-izq, arriba-der,
    abajo-der, abajo-izq) y luego 2 puntos del rectangulo interior de
    vidrio (esquina superior-izq y esquina inferior-der).
    """
    img = cv2.imread(png_path, cv2.IMREAD_UNCHANGED)
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

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN and len(pts) < 6:
            pts.append((x / esc, y / esc))
            col = (0, 0, 255) if len(pts) <= 4 else (0, 200, 255)
            cv2.circle(disp, (x, y), 6, col, -1)
            cv2.putText(disp, str(len(pts)), (x + 9, y - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            cv2.imshow(win, disp)

    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)
    cv2.imshow(win, disp)
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k == ord('u') and pts:                 # deshacer
            pts.pop()
            disp[:] = base
            for i, p in enumerate(pts):
                q = (int(p[0] * esc), int(p[1] * esc))
                cv2.circle(disp, q, 6, (0, 0, 255) if i < 4 else (0, 200, 255), -1)
            cv2.imshow(win, disp)
        if k == ord('q') or len(pts) == 6:
            break
    cv2.destroyAllWindows()

    if len(pts) < 6:
        raise RuntimeError("Faltan clics")

    ext = ordenar_puntos(np.array(pts[:4], np.float32))
    (ix0, iy0), (ix1, iy1) = pts[4], pts[5]

    meta = {
        "esquinas_exteriores": ext.tolist(),
        "rect_interior": [int(min(ix0, ix1)), int(min(iy0, iy1)),
                          int(max(ix0, ix1)), int(max(iy0, iy1))],
        "nine_slice": True,
    }
    destino = os.path.splitext(png_path)[0] + ".json"
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"Guardado {destino}")
    return meta


marcar_esquinas_png("./replace2.png")
