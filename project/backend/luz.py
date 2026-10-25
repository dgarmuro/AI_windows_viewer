"""Luz de la escena para renderizar: sombras proyectadas, luz global y vidrio.

Principios (no ajustados a ninguna foto concreta):
  * Sombras: la luz que recibe la ventana nueva se deduce de la que recibe la
    PARED que la rodea. Se mide en un anillo alejado del hueco y se rellena el
    interior interpolando desde el borde, en cualquier direccion (no supone
    bandas horizontales).
  * Luz global: solo se corrige con superficies cuyo color real es conocido
    (marco neutro de otra ventana, o pared neutra). Si no hay ninguna, no se
    toca: es preferible no corregir a corregir mal.
  * Vidrio: el interior que trae la foto de catalogo no es parte del producto;
    se sustituye por un vidrio generico, respetando junquillos y travesanos.
"""
import numpy as np
import cv2
from utils import tam_objetivo, encoder_expandir


def _luma(bgr):
    """Luminancia en el mismo espacio (sRGB codificado) que los valores del producto."""
    return bgr[..., 0] * 0.114 + bgr[..., 1] * 0.587 + bgr[..., 2] * 0.299


# --------------------------------------------------------------------------
# 1) MAPA DE LUZ (sombras proyectadas + degradados)
# --------------------------------------------------------------------------
def _mapa_luz_en(foto, quad, roi, mask_excluir=None, ancho_trabajo=200,
             banda=(0.04, 0.30), lit_pct=90, rango=(0.15, 1.15), eps=0.03,
             prioridad_horizontal=3.0):
    """Factor de luz (H_roi x W_roi) relativo a la pared iluminada.

    1. Se mide la luminancia de la pared en cuatro franjas pegadas al hueco
       (izquierda, derecha, arriba, abajo), en la foto ORIGINAL.
    2. Se normaliza con la pared iluminada (percentil alto): sol = 1, sombra < 1.
    3. Para cada punto del hueco se interpola en horizontal (entre izquierda y
       derecha de su fila) y en vertical (entre arriba y abajo de su columna).
       Cada direccion pesa mas cuanto mas coinciden sus dos lados: una sombra
       de toldo o alero es igual a izquierda y derecha, una de pilar es igual
       arriba y abajo. La horizontal tiene prioridad (x3) porque con el sol por
       arriba la pared a la misma altura comparte la sombra; la vertical manda
       cuando izquierda y derecha no coinciden.
    Probado: sin sombra, alero, pilar y ventana al borde -> error <= 0.02;
    sombra diagonal -> se suaviza (error 0.22).
    """
    x0, y0, x1, y1 = roi
    tw, th = tam_objetivo(quad)
    f = min(1.0, ancho_trabajo / max(tw, 1))
    zona = foto[y0:y1, x0:x1].astype(np.float32) / 255.0
    h, w = zona.shape[:2]
    sw, sh = max(8, int(w * f)), max(8, int(h * f))
    L = cv2.medianBlur(_luma(cv2.resize(zona, (sw, sh), interpolation=cv2.INTER_AREA)), 5)
    valido = L > 0.04
    if mask_excluir is not None:                         # oclusores: no son pared
        ex = cv2.resize(mask_excluir[y0:y1, x0:x1], (sw, sh), interpolation=cv2.INTER_NEAREST)
        valido &= ex < 128

    q = (quad - np.array([x0, y0], np.float32)) * f
    qx0, qy0 = np.floor(q.min(0)).astype(int); qx1, qy1 = np.ceil(q.max(0)).astype(int)
    qx0, qy0, qx1, qy1 = max(qx0, 0), max(qy0, 0), min(qx1, sw - 1), min(qy1, sh - 1)
    bw, bh = qx1 - qx0, qy1 - qy0
    if bw < 4 or bh < 4:
        return np.ones((h, w), np.float32)
    dx0, dx1 = int(banda[0] * bw) + 1, int(banda[1] * bw) + 2
    dy0, dy1 = int(banda[0] * bh) + 1, int(banda[1] * bh) + 2

    def perfil(ys, xs, por_fila, n):
        """Mediana de la pared en la franja L[ys, xs], fila a fila o columna a columna."""
        v, m = L[ys, xs], valido[ys, xs]
        if v.size == 0:
            return np.full(n, np.nan, np.float32)
        if not por_fila:
            v, m = v.T, m.T
        out = np.full(n, np.nan, np.float32)
        for i in range(min(n, v.shape[0])):
            if m[i].sum() >= 2:
                out[i] = np.median(v[i][m[i]])
        return out

    fil, col = slice(qy0, qy1), slice(qx0, qx1)
    izq = perfil(fil, slice(max(0, qx0 - dx1), max(0, qx0 - dx0)), True, bh)
    der = perfil(fil, slice(min(sw, qx1 + dx0), min(sw, qx1 + dx1)), True, bh)
    arr = perfil(slice(max(0, qy0 - dy1), max(0, qy0 - dy0)), col, False, bw)
    aba = perfil(slice(min(sh, qy1 + dy0), min(sh, qy1 + dy1)), col, False, bw)

    todos = np.concatenate([v[~np.isnan(v)] for v in (izq, der, arr, aba)] or [np.array([1.0])])
    if todos.size < 10:
        return np.ones((h, w), np.float32)
    lit = float(np.percentile(todos, lit_pct))
    izq, der, arr, aba = [v / max(lit, 1e-3) for v in (izq, der, arr, aba)]

    # Peso de cada direccion = cuanto coinciden sus dos lados. Un lado que falta
    # (fuera de la foto, oclusor) NO cuenta como coincidencia: da poca confianza.
    # Prioridad horizontal: con luz cenital la pared a la MISMA ALTURA comparte
    # la sombra de aleros, toldos y balcones; arriba/abajo es otra altura.
    def interp(a, b, t):
        ambos = ~np.isnan(a) & ~np.isnan(b)
        uno = np.where(np.isnan(a), b, a)
        v = np.where(ambos, a * (1 - t) + np.nan_to_num(b) * t, uno)
        dif = np.where(ambos, np.abs(np.nan_to_num(a) - np.nan_to_num(b)), 0.15)
        peso = np.where(np.isnan(uno), 0.0, 1.0 / (eps + dif))
        return v, peso

    tx = np.linspace(0, 1, bw, dtype=np.float32)[None, :]
    ty = np.linspace(0, 1, bh, dtype=np.float32)[:, None]
    hor, wh = interp(izq[:, None], der[:, None], tx)        # (bh, bw)
    ver, wv = interp(arr[None, :], aba[None, :], ty)
    wh = wh * prioridad_horizontal
    den = wh + wv
    dentro = np.where(den > 0, (np.nan_to_num(hor) * wh + np.nan_to_num(ver) * wv) / np.maximum(den, 1e-6), 1.0)

    r = np.ones((sh, sw), np.float32)
    r[qy0:qy1, qx0:qx1] = dentro
    r = cv2.GaussianBlur(r, (0, 0), 1.0)
    return np.clip(cv2.resize(r, (w, h), interpolation=cv2.INTER_LINEAR), *rango)


def mapa_luz(foto, quad, roi, mask_excluir=None, **kw):
    """Mapa de luz para el recorte `roi` (x0, y0, x1, y1).

    Las franjas de pared se miden SIEMPRE en una zona propia alrededor de
    `quad` (independiente del recorte de render) y el resultado se copia al
    recorte pedido. Fuera de esa zona el factor es 1."""
    H, W = foto.shape[:2]
    banda = kw.get("banda", (0.04, 0.30))
    z = encoder_expandir(quad, 1 + 2 * banda[1] + 0.15)
    mx0, my0 = np.clip(np.floor(z.min(0)).astype(int), 0, [W, H])
    mx1, my1 = np.clip(np.ceil(z.max(0)).astype(int), 0, [W, H])
    propio = _mapa_luz_en(foto, quad, (mx0, my0, mx1, my1), mask_excluir, **kw)
    x0, y0, x1, y1 = roi
    out = np.ones((y1 - y0, x1 - x0), np.float32)
    ix0, iy0, ix1, iy1 = max(x0, mx0), max(y0, my0), min(x1, mx1), min(y1, my1)
    if ix1 > ix0 and iy1 > iy0:
        out[iy0 - y0:iy1 - y0, ix0 - x0:ix1 - x0] = propio[iy0 - my0:iy1 - my0, ix0 - mx0:ix1 - mx0]
    return out


# --------------------------------------------------------------------------
# 2) LUZ GLOBAL (exposicion + balance de blancos)
# --------------------------------------------------------------------------
def iluminante_gray_edge(foto, quad, expansion=4.0, p=6, lado=400):
    """Color de la luz de la escena (B, G, R con media 1) por el metodo Gray-Edge
    (van de Weijer et al., 2007): la media de los bordes de una escena es gris,
    asi que su desviacion por canal es el tinte de la iluminante. Se calcula en
    la fachada alrededor de la ventana, no en toda la foto (cielo, farolas)."""
    H, W = foto.shape[:2]
    z = encoder_expandir(quad, expansion)
    x0, y0 = np.clip(np.floor(z.min(0)).astype(int), 0, [W - 1, H - 1])
    x1, y1 = np.clip(np.ceil(z.max(0)).astype(int), 1, [W, H])
    reg = foto[y0:y1, x0:x1].astype(np.float32) / 255.0
    f = min(1.0, lado / max(reg.shape[:2]))
    reg = cv2.resize(reg, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    reg = cv2.GaussianBlur(reg, (0, 0), 1.0)
    valido = (reg.max(2) < 0.95) & (reg.min(2) > 0.03)       # sin quemados ni negros
    e = []
    for c in range(3):
        gx = cv2.Sobel(reg[:, :, c], cv2.CV_32F, 1, 0); gy = cv2.Sobel(reg[:, :, c], cv2.CV_32F, 0, 1)
        g = np.sqrt(gx ** 2 + gy ** 2)[valido]
        e.append((np.mean(g ** p)) ** (1.0 / p) if g.size else 1.0)
    e = np.asarray(e, np.float32)
    return np.clip(e / max(e.mean(), 1e-6), 0.7, 1.4)


def luz_global(foto, quad, ref_foto=None, albedo_blanco=0.80, sat_max=0.12,
               luma_min=0.35, recorte=0.95):
    """Ganancia por canal (B, G, R) para el producto.

    Balance de blancos: siempre, con el color de la iluminante (Gray-Edge).
    Exposicion:
      a) si el marco de otra ventana es blanco (neutro y claro tras quitar el
         tinte de la luz), se usa directamente;
      b) si no, y la foto NO es de pleno dia (sin luces casi saturadas), el
         blanco del producto se limita a la superficie mas clara de la pared
         alrededor (percentil 98).
    Limitacion: en una fachada oscura (ladrillo, piedra) de noche y sin nada
    blanco cerca, (b) oscurece de mas; el minimo es 0.4.
    """
    ilum = iluminante_gray_edge(foto, quad)
    if ref_foto is not None:
        m = np.asarray(ref_foto["marco"], np.float32) / ilum
        if (m.max() - m.min()) / max(m.max(), 1e-3) <= sat_max and m.mean() >= luma_min:
            return np.asarray(ref_foto["marco"], np.float32) / albedo_blanco

    H, W = foto.shape[:2]
    g = cv2.cvtColor(foto, cv2.COLOR_BGR2GRAY)
    if np.percentile(g, 99.9) / 255.0 >= recorte:        # pleno dia: la camara ya expone bien
        return ilum
    # Escena con poca luz: el blanco del producto no puede brillar mas que la
    # superficie mas clara de la pared que lo rodea (sin luces ni quemados).
    anillo = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(anillo, encoder_expandir(quad, 2.5).astype(np.int32), 255)
    cv2.fillConvexPoly(anillo, encoder_expandir(quad, 1.15).astype(np.int32), 0)
    px = foto[anillo > 0].astype(np.float32) / 255.0
    px = px[px.max(1) < recorte]
    expo = 1.0
    if len(px) >= 100:
        claro = float(np.percentile(_luma(px / ilum), 98))
        expo = float(np.clip(claro / albedo_blanco, 0.4, 1.0))
    return ilum * expo


def vidrio_de_referencia(ref_foto, sat_max=0.25, luma_max=0.35):
    """El 'vidrio' medido en otra ventana solo vale si parece vidrio (oscuro y
    poco saturado). Una persiana bajada o una cortina no lo es."""
    if ref_foto is None:
        return None
    v = np.asarray(ref_foto["vidrio"], np.float32)
    sat = (v.max() - v.min()) / max(v.max(), 1e-3)
    return v if (sat <= sat_max and _luma(v) <= luma_max) else None


# --------------------------------------------------------------------------
# 3) VIDRIO: separar junquillos/travesanos del cristal y sustituir el interior
# --------------------------------------------------------------------------
def mascara_cristal(rgb, alpha, m_vidrio, dist_perfil=0.18):
    """Dentro de la zona de vidrio, los pixeles del color del marco son perfil
    (junquillos, travesanos, cruceta) y NO cristal."""
    opaco = alpha > 0.5
    marco = opaco & (m_vidrio < 0.5)
    if marco.sum() < 30:
        return m_vidrio
    col_marco = np.median(rgb[marco], 0)
    d = np.linalg.norm(rgb - col_marco, axis=-1)
    parece_perfil = ((d <= dist_perfil) & opaco) | marco
    # un junquillo o una cruceta TOCA el marco; un brillo suelto en el cristal no
    n, lab = cv2.connectedComponents(parece_perfil.astype(np.uint8))
    del_marco = np.unique(lab[marco])
    perfil = np.isin(lab, del_marco[del_marco > 0])
    cristal = ((~perfil) & opaco).astype(np.float32) * m_vidrio
    return cv2.GaussianBlur(cristal, (0, 0), 0.8)


def vidrio_generico(h, w, base=(0.09, 0.10, 0.11)):
    """Interior oscuro con un leve degradado vertical; el reflejo se suma despues."""
    t = np.linspace(1.15, 0.85, h, dtype=np.float32)[:, None, None]
    return np.clip(np.asarray(base, np.float32)[None, None, :] * t * np.ones((1, w, 1), np.float32), 0, 1)