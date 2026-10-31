"""Plano de la ventana vieja dentro del hueco, sin clics.

Se trabaja sobre el recorte ENDEREZADO de cada hueco (el contorno pasa a ser
un rectangulo) y con TODAS las ventanas parecidas de la fachada a la vez:

  * Recercado: mismo ancho en los 4 lados y en todas las ventanas. Se estima
    sumando los perfiles de bordes de todas; un borde debil en cada ventana
    (granate contra marron) es fuerte en el conjunto.
  * Jamba: depende de la posicion de cada ventana respecto a la camara, asi
    que se decide POR VENTANA; por perspectiva se ve como mucho una lateral
    (izq o der) y una horizontal (arr o aba): la de borde mas fuerte.

Probado solo con 3 ventanas de una foto (casa roja): error medio 2-4 px,
maximo 4-11 px en huecos de ~130 px. Hay que validarlo con mas fotos
(evaluar_interior.py) antes de fiarse.
"""
import numpy as np, cv2
from utils import tam_objetivo, ordenar_puntos

def _enderezar(foto, quad, ancho=320):
    tw, th = tam_objetivo(quad)
    W = ancho; H = max(16, int(round(ancho * th / tw)))
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
    M = cv2.getPerspectiveTransform(np.asarray(quad, np.float32), dst)
    return cv2.warpPerspective(foto, M, (W, H), flags=cv2.INTER_AREA if tw > ancho else cv2.INTER_CUBIC), M

def _perfiles(g):
    """Bordes paralelos a cada lado, en funcion de la distancia al lado (px)."""
    H, W = g.shape
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)); gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    fy, fx = slice(int(.2 * H), int(.8 * H)), slice(int(.2 * W), int(.8 * W))
    # mediana a lo largo del lado: un borde RECTO y largo puntua, una textura no
    izq = np.median(gx[fy, :], 0); der = np.median(gx[fy, ::-1], 0)
    arr = np.median(gy[:, fx], 1); aba = np.median(gy[::-1, fx], 1)
    return izq, der, arr, aba

def _elegir(perfil, n, max_frac=0.32, frac_fuerte=0.5, ignora=3):
    """Distancia (px) del borde interior elegido para un lado: el pico MAS
    INTERIOR cuya fuerza es al menos `frac_fuerte` del pico mas fuerte
    (sin contar el propio contorno, i < ignora)."""
    lim = int(max_frac * n)
    p = np.convolve(perfil[:lim], np.ones(3) / 3, mode="same")
    if p.size <= ignora + 2:
        return 0
    tope = p[ignora:].max() + 1e-6
    picos = [i for i in range(ignora, len(p) - 1)
             if p[i] >= p[i - 1] and p[i] >= p[i + 1] and p[i] >= frac_fuerte * tope]
    return max(picos) if picos else 0


def detectar_interior_geom(foto, quad_ext, ancho=320, max_frac=0.32, frac_fuerte=0.5, devolver_debug=False):
    rect, M = _enderezar(foto, quad_ext, ancho)
    g = cv2.GaussianBlur(cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255, (0, 0), 1.0)
    H, W = g.shape
    izq, der, arr, aba = _perfiles(g)
    a = _elegir(izq, W, max_frac, frac_fuerte); b = _elegir(der, W, max_frac, frac_fuerte)
    c = _elegir(arr, H, max_frac, frac_fuerte); d = _elegir(aba, H, max_frac, frac_fuerte)
    q_rect = np.array([[a, c], [W - 1 - b, c], [W - 1 - b, H - 1 - d], [a, H - 1 - d]], np.float32)
    Minv = np.linalg.inv(M)
    q = cv2.perspectiveTransform(q_rect.reshape(-1, 1, 2), Minv).reshape(4, 2)
    if devolver_debug:
        return ordenar_puntos(q), dict(rect=rect, q_rect=q_rect, insets=(a, b, c, d))
    return ordenar_puntos(q)


# ===========================================================================
# Varias ventanas de la misma fachada: se suman sus evidencias
# ===========================================================================
LADOS = ("izq", "der", "arr", "aba")

def _perfiles_norm(foto, quad, ancho=320):
    rect, M = _enderezar(foto, quad, ancho)
    g = cv2.GaussianBlur(cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255, (0, 0), 1.0)
    out = {}
    for nom, p in zip(LADOS, _perfiles(g)):
        p = np.convolve(p, np.ones(3) / 3, mode="same")
        p[:int(0.04 * len(p) if nom in ('izq', 'der') else 0.04 * len(p))] = 0  # eco del propio contorno
        out[nom] = p / (p.max() + 1e-6)               # cada lado pesa lo mismo
    return out, M, rect.shape[:2]

def _pico_cerca(p, centro, radio):
    a, b = max(3, centro - radio), min(len(p), centro + radio + 1)
    return a + int(np.argmax(p[a:b])) if b > a else centro

def _tramo(p, n):
    t = p[:n]
    return np.pad(t, (0, n - t.size))

def detectar_interiores_fachada(foto, quads_ext, ancho=320, max_rec=0.25, max_jamba=0.18,
                                radio=6, min_voto_jamba=0.25):
    """Plano interior de TODAS las ventanas de una fachada a la vez.

    Modelo: inset_lado = recercado (igual en los 4 lados y en todas las
    ventanas) + jamba (solo en los lados que la perspectiva deja ver; mismo
    ancho en todas). Ambos se estiman sumando los perfiles de bordes de todas
    las ventanas, asi un borde debil en cada una es fuerte en el conjunto.
    """
    perf = [_perfiles_norm(foto, q, ancho) for q in quads_ext]
    n = int(max_rec * ancho)
    # 1) recercado: voto de los 4 lados de todas las ventanas
    voto = np.zeros(n)
    for p, _, _ in perf:
        for nom in LADOS:
            voto += p[nom][:n]
            voto += _tramo(p[nom], n)
    voto = np.convolve(voto, np.ones(5) / 5, mode="same")
    i0 = int(0.04 * ancho)
    S = int(np.argmax(voto[i0:])) + i0
    rec_fuerte = voto[S] >= 1.5 * np.median(voto[i0:])   # hay recercado de verdad
    if not rec_fuerte:
        S = 0
    # 2) jamba, POR VENTANA: por perspectiva se ve como mucho una lateral
    #    (izq o der) y una horizontal (arr o aba): la de borde mas fuerte.
    nj = int(max_jamba * ancho)
    res, jambas = [], []
    for (p, M, (H, W)), q in zip(perf, quads_ext):
        s0 = {nom: (_pico_cerca(p[nom], S, radio) if S else 0) for nom in LADOS}
        cand = {}
        for nom in LADOS:
            seg = p[nom][s0[nom] + 4:s0[nom] + 4 + nj]
            if seg.size:
                r = int(np.argmax(seg)); cand[nom] = (float(seg[r]), r + 4)
            else:
                cand[nom] = (0.0, 0)
        ins = dict(s0)
        elegidas = {}
        for a_, b_ in (("izq", "der"), ("arr", "aba")):
            gan = a_ if cand[a_][0] >= cand[b_][0] else b_
            if cand[gan][0] >= min_voto_jamba:
                ins[gan] = s0[gan] + cand[gan][1]
                elegidas[gan] = cand[gan][1]
        jambas.append(elegidas)
        q_rect = np.array([[ins["izq"], ins["arr"]], [W - 1 - ins["der"], ins["arr"]],
                           [W - 1 - ins["der"], H - 1 - ins["aba"]], [ins["izq"], H - 1 - ins["aba"]]], np.float32)
        qi = cv2.perspectiveTransform(q_rect.reshape(-1, 1, 2), np.linalg.inv(M)).reshape(4, 2)
        res.append(ordenar_puntos(qi))
    jamba = jambas
    return res, dict(recercado=S, jamba=jamba)


def contornos_parecidos(masks, idx, factor, area_rel=(0.5, 2.0), aspecto_tol=0.25):
    """Contornos (minAreaRect, a resolucion completa) de las mascaras de SAM que
    se parecen a la ventana elegida: mismo tamano aproximado y proporcion.
    Puertas, balcones y escaparates quedan fuera y no estropean el voto."""
    def caja(m):
        cs, _ = cv2.findContours((m > 127).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            return None
        return ordenar_puntos(cv2.boxPoints(cv2.minAreaRect(max(cs, key=cv2.contourArea)))) * factor
    ref = caja(masks[idx])
    if ref is None:
        return []
    w0, h0 = tam_objetivo(ref); a0, r0 = w0 * h0, w0 / max(h0, 1)
    out = []
    for i, m in enumerate(masks):
        if i == idx:
            continue
        q = caja(m)
        if q is None:
            continue
        w, h = tam_objetivo(q)
        if area_rel[0] <= (w * h) / a0 <= area_rel[1] and abs((w / max(h, 1)) / r0 - 1) <= aspecto_tol:
            out.append(q)
    return out
