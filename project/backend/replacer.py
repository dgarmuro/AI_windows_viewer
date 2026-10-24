from typing import Optional
from utils import (armonizar_v2, filtrar_oclusores, imread_u, imwrite_u,
                   _campo_iluminacion, lados_visible, dibujar_jamba,
                   ordenar_puntos, ajustar_cuadrilatero, tam_objetivo, encoder_expandir,
                   placa_limpia, _color_anillo_pared, _estimar_ruido, _color_cielo,
                   medir_referencia, encoger_quad, _reflejo_cristal,
                   _oclusion_contacto, debug_escena)
from detector_class import DetectorVentanas
from escena_class import Escena
from product_class import ProductAsset
import cv2
import numpy as np
import os


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
    ruta_foto = os.path.abspath(ruta_foto)

    foto = imread_u(ruta_foto)
    if foto is None:
        raise FileNotFoundError(ruta_foto)
    H, W = foto.shape[:2]

    escala = min(1.0, lado_deteccion / max(H, W))
    peq = cv2.resize(foto, (int(W * escala), int(H * escala)),interpolation=cv2.INTER_AREA) if escala < 1 else foto
    quad_ref = None
    if quad_manual is not None: # Para cuando se seleccionan las 4 esquinas previamente
        quad = ordenar_puntos(np.asarray(quad_manual, np.float32))
        mask_full = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask_full, quad.astype(np.int32), 255)
        iou = 1.0
    else:
        detector = detector or DetectorVentanas()
        masks = detector(peq) # Se comporta como función por el método __call__
        masks.sort(key=lambda m: -int((m > 127).sum()))
        mask = masks[min(indice_ventana, len(masks) - 1)]

        gray = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY) # Con esto se pasa a HxW para que ajustar enciuentre bordes, que son saltos de brillo, al hacer lo de gray se queda solo con el brillo.
        quad_peq = ajustar_cuadrilatero(mask, gray)

        # metrica de calidad: si el quad no cuadra con la mascara, hay que revisar
        test = np.zeros_like(mask)
        cv2.fillConvexPoly(test, quad_peq.astype(np.int32), 255)
        b1, b2 = test > 127, mask > 127
        iou = float(np.count_nonzero(b1 & b2)) / max(np.count_nonzero(b1 | b2), 1)

        sx, sy = W / peq.shape[1], H / peq.shape[0]
        factor = np.array([sx, sy], np.float32)


        idx = min(indice_ventana, len(masks) - 1)
        for i, m_alt in enumerate(masks):
            if i == idx:
                continue
            try:
                quad_ref = ajustar_cuadrilatero(m_alt, gray) * factor
                break
            except Exception:
                continue
        quad = quad_peq * factor 
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
                try:
                    for m in detector(peq, prompt=p):
                        acc |= cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
                except RuntimeError:
                    pass

            oclusores = filtrar_oclusores(cv2.bitwise_and(acc, zona), quad)
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
        ref_foto=(medir_referencia(foto, quad_ref) if quad_ref is not None else None))



def renderizar(escena, asset, foto_orig=None, retranqueo=0.018, reflejo=0.22,
                  grano=True, supersample=1.6, blur_pre=0.0, margen_roi=1.45):
    """Renderiza SOLO en un recorte alrededor de la ventana y lo pega en la placa."""
    placa_full = escena.placa
    H, W = placa_full.shape[:2]
    # --- ROI: cuadrilatero ampliado (jamba, sombra, oclusores caben de sobra)
    zona = encoder_expandir(escena.quad, margen_roi)
    x0, y0 = np.floor(zona.min(0)).astype(int); x1, y1 = np.ceil(zona.max(0)).astype(int)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    off = np.array([x0, y0], np.float32)
    placa = placa_full[y0:y1, x0:x1]
    h, w = placa.shape[:2]
    quad_hueco = escena.quad - off
    quad_win = encoger_quad(quad_hueco, retranqueo, retranqueo * 0.6)
 
    tw, th = tam_objetivo(quad_win)
    pre, a, m_vid = asset.escalar(int(tw * supersample), int(th * supersample))
    if blur_pre > 0:
        pre = cv2.GaussianBlur(pre, (0, 0), blur_pre); a = cv2.GaussianBlur(a, (0, 0), blur_pre)
    rgb = pre / np.maximum(a[..., None], 1e-4)
    if escena.ref_foto is not None:
        rgb = armonizar_v2(rgb, a, m_vid, escena.ref_foto)
    if reflejo > 0:   # reflejo solo en el vidrio
        r = _reflejo_cristal(rgb, a * m_vid, escena.color_cielo_bgr, reflejo)
        rgb = r
    pre = rgb * a[..., None]
 
    hs, ws = a.shape
    src = np.array([[0, 0], [ws - 1, 0], [ws - 1, hs - 1], [0, hs - 1]], np.float32)
    M = cv2.getPerspectiveTransform(src, quad_win)
    pre_w = cv2.warpPerspective(pre, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    a_w = np.clip(cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0), 0, 1)
 
    campo = _campo_iluminacion(placa_full, escena.quad)[y0:y1, x0:x1, None]
    pre_w = np.clip(pre_w * campo, 0, 1)
 
    fondo = dibujar_jamba(placa, quad_hueco, quad_win, escena.color_pared_bgr, lados_visible(quad_hueco))
    out = fondo.astype(np.float32) / 255.0 * (1 - a_w[..., None]) + pre_w
    out = np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out = _oclusion_contacto(out, quad_hueco)
 
    if grano and escena.sigma_ruido > 0.2:
        rng = np.random.default_rng(0)
        n = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), 0.7)
        n *= escena.sigma_ruido / max(float(n.std()), 1e-6)        # grano con la misma sigma pero no "blanco"
        zona_g = a_w.copy()
        if escena.mask_hueco is not None:                          # tambien jamba y parche de LaMa
            mh = cv2.dilate(escena.mask_hueco[y0:y1, x0:x1], np.ones((15, 15), np.uint8)).astype(np.float32) / 255
            zona_g = np.maximum(zona_g, mh)
        out = np.clip(out.astype(np.float32) + n[..., None] * zona_g[..., None], 0, 255).astype(np.uint8)
 
    if escena.mask_oclusores is not None and foto_orig is not None:
        mo = cv2.GaussianBlur(escena.mask_oclusores[y0:y1, x0:x1].astype(np.float32) / 255.0, (0, 0), 0.8)[..., None]
        orig = foto_orig[y0:y1, x0:x1].astype(np.float32)
        out = (out.astype(np.float32) * (1 - mo) + orig * mo + 0.5).astype(np.uint8)
 
    res = placa_full.copy()
    res[y0:y1, x0:x1] = out
    return res



import sys

if __name__ == "__main__":
    foto = os.path.join("resources", sys.argv[1])       # ej. fachada_real4.jpg
    png = os.path.join("resources", sys.argv[2])        # ej. replace3.png

    detector = DetectorVentanas()
    escena = analizar_fachada(foto, detector=detector)
    foto_orig = imread_u(escena.ruta_foto)

    asset = ProductAsset.cargar(png)
    img = renderizar(escena, asset, foto_orig=foto_orig)

    nombre = os.path.splitext(sys.argv[1])[0] + "__" + os.path.splitext(sys.argv[2])[0]
    imwrite_u(f"resultado_{nombre}.jpg", img)
    print("->", f"resultado_{nombre}.jpg")