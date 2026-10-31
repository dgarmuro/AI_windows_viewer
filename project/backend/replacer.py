from typing import Optional
from utils import (armonizar_v2, filtrar_oclusores, imread_u, imwrite_u,
                   _campo_iluminacion, lados_visible, dibujar_jamba,
                   ordenar_puntos, ajustar_cuadrilatero, tam_objetivo, encoder_expandir,
                   placa_limpia, _color_anillo_pared, _estimar_ruido, _color_cielo,
                   medir_referencia, encoger_quad, _reflejo_cristal,
                   _oclusion_contacto, debug_escena,get_center_tam_mask)
from detector_class import DetectorVentanas
from escena_class import Escena
from product_class import ProductAsset
import cv2
import numpy as np
import os
from luz import mapa_luz, luz_global, mascara_cristal, vidrio_generico, vidrio_de_referencia
from marcar_interior import marcar_interior
from auto_interior import detectar_interiores_fachada, contornos_parecidos
import sys

def analizar_fachada(ruta_foto: str,
        detector: Optional[DetectorVentanas] = None,
        indice_ventana: int = 0,
        quad_manual: Optional[np.ndarray] = None,
        quad_interior: Optional[np.ndarray] = None,
        detectar_hueco_interior: bool = True,
        lado_deteccion: int = 1280,
        detectar_oclusores: bool = True) -> Escena:
    """Analisis completo de una foto. Se hace una vez y se cachea.
    quad_manual   : contorno del hueco puesto a mano (salta la deteccion).
    quad_interior : plano de la ventana vieja puesto a mano. Si no se da y detectar_hueco_interior=True, se detecta comparando con las demas ventanas parecidas de la foto (auto_interior.py).
    """
    ruta_foto = os.path.abspath(ruta_foto)
    foto = imread_u(ruta_foto)
    if foto is None: raise FileNotFoundError(ruta_foto)
    
    H, W = foto.shape[:2]
 
    escala = min(1.0, lado_deteccion / max(H, W))
    peq = cv2.resize(foto, (int(W * escala), int(H * escala)), interpolation=cv2.INTER_AREA) if escala < 1 else foto
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
        idx = min(indice_ventana, len(masks) - 1)
        mask = masks[idx]
 
        gray = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
        quad_peq = ajustar_cuadrilatero(mask, gray)
 
        test = np.zeros_like(mask)
        cv2.fillConvexPoly(test, quad_peq.astype(np.int32), 255)
        b1, b2 = test > 127, mask > 127
        iou = float(np.count_nonzero(b1 & b2)) / max(np.count_nonzero(b1 | b2), 1)
 
        sx, sy = W / peq.shape[1], H / peq.shape[0]
        factor = np.array([sx, sy], np.float32) # es cuántos píxeles originales hay por cada píxel pequeño en horizontal.
        ref = get_center_tam_mask(mask > 127)
        candidatas = []
        for i, m_alt in enumerate(masks):
            if i == idx:
                continue
            try:
                m_data = get_center_tam_mask(m_alt > 127)
                if m_data is None:
                    continue
                dx = abs(m_data[0] - ref[0]) / ref[2]                        # distancia horizontal, en anchos de ventana
                dy = abs(m_data[1] - ref[1]) / ref[3]                        # distancia vertical, en altos de ventana
                tam = abs(np.log((m_data[2] * m_data[3]) / (ref[2] * ref[3])))    # 0 si son del mismo tamaño
                candidatas.append((dx + 2.0 * dy + tam, i))             # cambiar de planta penaliza el doble
                
                #quad_ref = ajustar_cuadrilatero(m_alt, gray) * factor # Ventana de referencia, otra que haya en la fachada, para copiar propiedades de luz y eso. Aqui deberia coger la mas cercana mejor
                #break
            except Exception:
                continue

        quad_ref = None
        for _, i in sorted(candidatas): # de la más parecida a la menos
            try:
                quad_ref = ajustar_cuadrilatero(masks[i], gray) * factor  # vecina más próxima: misma planta, cerca y de tamaño parecido
                break
            except Exception:
                continue

        quad = quad_peq * factor # Se vuelve al tam original
        mask_full = cv2.resize(mask, (W, H), interpolation=cv2.INTER_NEAREST)
 
    print(f"[analisis] quad IoU={iou:.3f}  hueco={tam_objetivo(quad)} px")
    if iou < 0.85:
        print("[analisis] AVISO: ajuste dudoso, conviene corregir esquinas a mano")
 
    # --- plano de la ventana vieja, AUTOMATICO: con todas las ventanas parecidas
    #     de la fachada (recercado votado entre todas, jamba por ventana)
    if quad_interior is None and detectar_hueco_interior and quad_manual is None:
        try:
            otras = contornos_parecidos(masks, idx, factor)
            if otras:
                interiores, info = detectar_interiores_fachada(foto, [quad] + otras)
                qi = interiores[0]
                frac = cv2.contourArea(qi) / max(cv2.contourArea(quad), 1.0)
                print(f"[analisis] interior automatico con {len(otras) + 1} ventanas: "
                      f"ocupa {frac:.0%} del hueco, jambas {info['jamba'][0]}")
                if 0.35 <= frac <= 0.97:
                    quad_interior = qi
            else:
                print("[analisis] no hay ventanas parecidas en la foto: se usa el contorno")
        except Exception as e:
            print(f"[analisis] deteccion del interior omitida: {e}")
 
    quad_pared, dilatar = None, 14
    if quad_interior is not None:
        quad_pared = quad                                   # el contorno es la pared
        quad = ordenar_puntos(np.asarray(quad_interior, np.float32))
        mask_full = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(mask_full, quad.astype(np.int32), 255)
        dilatar = 2                                         # no comerse la jamba real
        print(f"[analisis] plano interior: {tam_objetivo(quad)} px (se conservan recercado y jamba)")
    quad_muro = quad_pared if quad_pared is not None else quad   # donde empieza la pared
 
    oclusores = None
    if detectar_oclusores and detector is not None and detector.backend == "sam3":
        try:
            zona = np.zeros((H, W), np.uint8)
            cv2.fillConvexPoly(zona, encoder_expandir(quad_muro, 1.25).astype(np.int32), 255)
            acc = np.zeros((H, W), np.uint8)
            for p in ("railing", "plant", "awning", "pipe", "cable"):
                try:
                    for m in detector(peq, prompt=p):
                        acc |= cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
                except RuntimeError:
                    pass
            oclusores = filtrar_oclusores(cv2.bitwise_and(acc, zona), quad_muro)
        except Exception as e:
            print(f"[analisis] oclusores omitidos: {e}")
 
    if detector is not None:
        detector.liberar()
    print("[analisis] generando placa limpia...")
    placa = placa_limpia(foto, mask_full, dilatar=dilatar)
 
    return Escena(ruta_foto=ruta_foto, quad=quad, placa=placa, mask_hueco=mask_full,
                  mask_oclusores=oclusores,
                  color_pared_bgr=_color_anillo_pared(foto, quad_muro),
                  color_cielo_bgr=_color_cielo(foto),
                  sigma_ruido=_estimar_ruido(foto, quad_muro),
                  iou_ajuste=iou,
                  quad_ref=quad_ref,
                  ref_foto=(medir_referencia(foto, quad_ref) if quad_ref is not None else None),
                  quad_pared=quad_pared)


def detectar_interior(detector, foto, quad_ext, gray_lado=1024,
                      prompts=("roller shutter", "window glass", "window pane")):
    """Propone el plano de la ventana vieja dentro del contorno, o None si no
    hay jamba visible. Se ejecuta SAM 3 sobre un recorte ampliado del hueco."""
    H, W = foto.shape[:2]
    z = encoder_expandir(quad_ext, 1.3)
    x0, y0 = np.clip(np.floor(z.min(0)).astype(int), 0, [W - 1, H - 1])
    x1, y1 = np.clip(np.ceil(z.max(0)).astype(int), 1, [W, H])
    crop = foto[y0:y1, x0:x1]
    f = gray_lado / max(crop.shape[:2])
    crop = cv2.resize(crop, None, fx=f, fy=f,
                      interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    q = (quad_ext - [x0, y0]) * f
    hueco = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillConvexPoly(hueco, q.astype(np.int32), 255)
    area_hueco = (hueco > 0).sum()

    mejor = None
    for p in prompts:
        try:
            masks = detector(crop, prompt=p)
        except RuntimeError:
            continue
        for m in masks:
            m = m > 127
            dentro = (m & (hueco > 0)).sum()
            fuera = (m & (hueco == 0)).sum()
            if fuera > 0.10 * max(dentro, 1):              # se sale del hueco: es otra cosa
                continue
            frac = dentro / area_hueco
            if 0.35 <= frac <= 0.95 and (mejor is None or dentro > mejor[0]):
                mejor = (dentro, m)
    if mejor is None:
        return None                                        # sin jamba visible: interior = exterior
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    q_in = ajustar_cuadrilatero(mejor[1].astype(np.uint8) * 255, gray)
    return q_in / f + [x0, y0]                             # a coordenadas de la foto completa

def renderizar(escena, asset, foto_orig=None, retranqueo=0.018, reflejo=0.22,
                  grano=True, supersample=1.6, blur_pre=0.0, margen_roi=1.45, fuerza_luz=0.85):
    """Renderiza SOLO en un recorte alrededor de la ventana y lo pega en la placa.
 
    Si la escena tiene quad_pared (contorno exterior del hueco en la fachada),
    escena.quad es el PLANO de la ventana vieja: la nueva se coloca ahi, sin
    retranqueo ni jamba dibujada, porque recercado y jamba son los reales de la
    foto. La luz se mide siempre en la pared, alrededor de quad_pared."""
    quad_pared = getattr(escena, "quad_pared", None)
    if quad_pared is not None:
        retranqueo = 0.0
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
    foto_luz = foto_orig if foto_orig is not None else placa_full
 
    # a) vidrio: el interior de la foto de catalogo no es el producto
    cristal = mascara_cristal(rgb, a, m_vid)
    if asset.meta.get("vidrio", "generico") != "catalogo":
        base = vidrio_de_referencia(escena.ref_foto)
        base = base if base is not None else (0.09, 0.10, 0.11)
        rgb = rgb * (1 - cristal[..., None]) + vidrio_generico(*cristal.shape, base) * cristal[..., None]
 
    # b) luz global (exposicion + balance) solo si hay una superficie de color conocido
    qp = escena.quad if quad_pared is None else np.asarray(quad_pared, np.float32)
    luz = luz_global(foto_luz, qp, escena.ref_foto)
    if luz is not None:
        g = 1 + (np.clip(luz, 1 / 3, 3) - 1) * fuerza_luz
        rgb = np.clip(rgb * g[None, None, :], 0, 1)
 
    # c) reflejo de cielo solo en el cristal (no en marco ni junquillos)
    if reflejo > 0:
        rgb = _reflejo_cristal(rgb, a * cristal, escena.color_cielo_bgr, reflejo)
    pre = rgb * a[..., None]
 
    hs, ws = a.shape
    src = np.array([[0, 0], [ws - 1, 0], [ws - 1, hs - 1], [0, hs - 1]], np.float32)
    M = cv2.getPerspectiveTransform(src, quad_win)
    pre_w = cv2.warpPerspective(pre, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    a_w = np.clip(cv2.warpPerspective(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0), 0, 1)
 
    campo = mapa_luz(foto_luz, qp, (x0, y0, x1, y1), escena.mask_oclusores)[..., None]
    pre_w = np.clip(pre_w * campo, 0, 1)
 
    lados = lados_visible(quad_hueco) if quad_pared is None else []   # con jamba real no se dibuja
    fondo = dibujar_jamba(placa, quad_hueco, quad_win, escena.color_pared_bgr, lados)
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
 
 
 
 
 
 
 # python3 replacer.py real_2.jpg replace2.png --interior
 

if __name__ == "__main__":
    foto = os.path.join("resources", sys.argv[1])       # ej. fachada_real4.jpg
    png = os.path.join("resources", sys.argv[2])        # ej. replace3.png

    detector = DetectorVentanas()
    #escena = analizar_fachada(foto, detector=detector)

    escena = analizar_fachada(foto, detector=detector)          # detecta el contorno
    if len(sys.argv) > 3 and sys.argv[3] == "--interior":
       interior = marcar_interior(imread_u(escena.ruta_foto), escena.quad)
       if interior is not None:
           escena = analizar_fachada(foto, detector=detector, quad_manual=escena.quad, quad_interior=interior)
    
    foto_orig = imread_u(escena.ruta_foto)

    asset = ProductAsset.cargar(png)
    img = renderizar(escena, asset, foto_orig=foto_orig)

    nombre = os.path.splitext(sys.argv[1])[0] + "__" + os.path.splitext(sys.argv[2])[0]
    imwrite_u(f"resultado_{nombre}.jpg", img)
    print("->", f"resultado_{nombre}.jpg")