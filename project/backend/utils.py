from __future__ import annotations
from typing import Tuple, Optional
import cv2
import numpy as np
from scipy.optimize import minimize
from simple_lama_inpainting import SimpleLama
import os

_LAMA = None 

def ordenar_puntos(pts: np.ndarray) -> np.ndarray:
    """Devuelve [arriba-izq, arriba-der, abajo-der, abajo-izq]."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1) # x + y de cada punto
    d = (pts[:, 1] - pts[:, 0]) # y - x de cad punto

    # La arriba-derecha tiene x grande e y pequeña, así que y−x es el mínimo (muy negativo).
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def _energia_bordes(quad: np.ndarray, grad: np.ndarray, n: int = 40) -> float:
    """Media de |gradiente| muestreada a lo largo de los 4 lados del cuadrilatero.

    Premia que las aristas caigan sobre bordes reales de la imagen (el marco),
    no sobre el interior difuso de la mascara.

    Mide cuánto "apoyan" los cuatro lados del cuadrilátero sobre bordes reales de la foto.
    
    La máscara de SAM es una mancha. Sus bordes son aproximados: puede comerse el marco, 
    incluir el alféizar, o quedarse corta en una esquina. Si solo optimizas IoU 
    contra esa mancha, el cuadrilátero se ajusta a los errores de la mancha.
    
    El píxel de pared y el píxel de marco tienen colores muy distintos, y ese salto está exactamente donde termina la ventana, con precisión de un píxel.


    Esta función mide si los cuatro lados del cuadrilátero propuesto caen encima de esos saltos. Da un número alto si sí, bajo si no. El optimizador lo usa para afinar lo que el IoU deja a medias.

    """
    h, w = grad.shape # grad es una imagen del mismo tamaño que la foto, pero en vez de color guarda cuánto cambia el brillo en ese punto. Negro donde la imagen es lisa, blanco donde hay un borde.
    total, cuenta = 0.0, 0

    '''quad = np.array([[300, 200],    # fila 0 → TL, arriba-izquierda
                 [620, 215],    # fila 1 → TR, arriba-derecha
                 [615, 680],    # fila 2 → BR, abajo-derecha
                 [295, 660]])   # fila 3 → BL, abajo-izquierda'''
    
    for i in range(4): # Recorre los 4 lados
        p0, p1 = quad[i], quad[(i + 1) % 4]
        t = np.linspace(0.05, 0.95, n)[:, None] # genera 40 números repartidos por igual entre 0.05 y 0.95.Son las posiciones relativas a lo largo del lado
        pts = p0[None, :] * (1 - t) + p1[None, :] * t # añade dim nueva de tam 1: p1[None, :]. Ejemplo: p0= [300 200]; p0[None, :]  →  [[300 200]]. Es la función para interpolar, los puntos resultantes están entre p0 y p1. Esta función s eobtiene de la distancia entre dos puntos, que da como resultado un vector que indica como se llega desde p0 a p1, el desplazamiento. Si avanzo una fracción t de ese camino, aprtiendo de p0, tengo: p0 + t . d = p0 + t . (p1 - p0). Se ve d como el vector del camino completo y t dice que fracción del camino se recorre: ejemplo: d = (8,4) dice ives 8 a la derecha y 4 hacia abajo siendo p0 = (2, 4) y p1 = (10, 8). t · d es solo el desplazamiento (“cuánto me he movido”), no una posición. Para saber dónde estás, hay que decir desde dónde empezaste, por eso se suma p0.
        xs = np.clip(pts[:, 0].astype(int), 0, w - 1) # np.clip(valor, minimo, maximo) si el valor es menor que el mínimo, devuelve el mínimo; si es mayor que el máximo, devuelve el máximo; si está dentro, lo devuelve tal cual. pts[:, 0] Recorre cada tupla y coge la primera columna
        ys = np.clip(pts[:, 1].astype(int), 0, h - 1)
        total += grad[ys, xs].sum() # grad[ys, xs] recupera las posiciones de grad
        cuenta += n
    return total / max(cuenta, 1)

def ajustar_cuadrilatero(mask: np.ndarray,
                         gray: Optional[np.ndarray] = None,
                         peso_bordes: float = 0.30) -> np.ndarray:
    """Ajusta un cuadrilatero en perspectiva al hueco.

    En vez de approxPolyDP (que falla en cuanto la mascara incluye alfeizar,
    reja o persiana), optimizamos las 8 coordenadas de las esquinas maximizando
    IoU con la mascara y, opcionalmente, la energia de borde sobre las aristas.

    Convierte la mancha irregular de SAM en un cuadrilátero de cuatro esquinas que respeta la perspectiva.
    """
    m = (mask > 127).astype(np.uint8)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) # Devuelve una tupla puntos de un contorno: [[[x1,y1]],[[x2,y2]]...] (columna, fila). Con CHAIN_APPROX_SIMPLE se comprimen ttramos recxtos y asi solo se guardan los extremos. Con RETR_EXTERNAL solo salen los contornos exteriores
    if not contours:
        raise ValueError("Mascara vacia")
    largest = max(contours, key=cv2.contourArea)

    init = ordenar_puntos(cv2.boxPoints(cv2.minAreaRect(largest))) # Se parte como inicio con el cuadrilátero que forma la máscara. MinAreaRect: Rectángulo rotado, de área mínima que encierra el contorno: ((cx, cy), (w, h), ángulo). Donde cx y cy es el centro

    grad = None
    if gray is not None:
        g = cv2.GaussianBlur(gray, (0, 0), 1.2) # Suaviza la imagen (en escala de grises), calcula el kernel con sigma 1.2. Se marcan mas los grises oscuros
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) # Derivada horizontal, cuanto cambia el brillo de izda a dcha. Usa CV_32F (float) para que los valores negativos no se pierdan,
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        grad = cv2.magnitude(gx, gy) # Fuerza del borde en cad píxel sin importar la magnitud: sqrt(gx² + gy²). Marca mas los perfiles
        grad /= (np.percentile(grad, 99) + 1e-6) # Normaliza dividiendo por el percentil 99. Así el 1% de píxeles más fuertes pasa de 1, y el resto queda escalado respecto a ellos. Es más robusto que dividir por el máximo, que un solo píxel extremo podría disparar. El 1e-6 evita dividir por cero en una imagen totalmente plana.
        grad = np.clip(grad, 0, 1) # Recorta lo que pasó de 1, dejando el rango final en [0, 1].

    area_ref = float(m.sum())
    lienzo = np.empty_like(m)

    def coste(p):
        # Planteo el problema como una optimización. Las incógnitas son las 8 coordenadas (4 esquinas × 2). La función de coste mide lo mal que va una propuesta
        q = p.reshape(4, 2).astype(np.float32)
        lienzo.fill(0)
        cv2.fillConvexPoly(lienzo, q.astype(np.int32), 1) # pinta el cuadrilátero propuesto relleno de unos en un lienzo negro.
        inter = float(np.count_nonzero(lienzo & m)) # píxeles que están en ambos (la intersección)
        union = float(np.count_nonzero(lienzo | m)) # píxeles en alguno de los dos (la unión).
        c = 1.0 - inter / max(union, 1.0)
        if grad is not None:
            c -= peso_bordes * _energia_bordes(q, grad)
        # penaliza degeneraciones
        if float(lienzo.sum()) < 0.3 * area_ref:
            c += 1.0
        return c

    res = minimize(coste, init.ravel(), method="Powell", options={"maxiter": 2000, "xtol": 0.5, "ftol": 1e-4}) # prueba valores y se queda con los que bajan el coste. Powell no necesita derivadas, que aquí no existen porque el coste es un conteo de píxeles. Empieza en minAreaRect y va empujando esquinas hasta que encaja. Se usa ravel pues minimize requiere un vector plano.
    quad = ordenar_puntos(res.x.reshape(4, 2))

    # si la optimizacion empeoro las cosas, nos quedamos con la inicial
    return quad if coste(quad.ravel()) <= coste(init.ravel()) else init

def get_center_tam_mask(m):
    """Centro y tamaño de una máscara: (cx, cy, ancho, alto)."""
    ys, xs = np.nonzero(np.asarray(m)) # Coordenadas de todos los píxeles de la máscara, los que no valen 0 o False. Devuelve par aimagen 2D un array con als filas y otro con las columnas.
    if xs.size == 0:
        return None
    return xs.mean(), ys.mean(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1 # ptp es peak to peak: la amplitud, máximo menos mínimo, es como xs.max() - xs.min(), la distancia entre el píxel más a la izquierda y el más a la derecha. Esto da el ancho

def tam_objetivo(quad: np.ndarray) -> Tuple[int, int]:
    """Tamano en pixeles que ocupa el cuadrilatero (media de lados opuestos)."""
    tl, tr, br, bl = quad
    w = 0.5 * (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) # es la distancia euclídea entre dos puntos
    h = 0.5 * (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr))
    return max(int(round(w)), 8), max(int(round(h)), 8)


def _color_anillo_pared(img, quad, grosor=0.10):
    """Color medio de la pared en un anillo ALREDEDOR del hueco.

    Medir dentro del hueco (como hacia ajustar_brillo del script original) toma
    el cristal oscuro de la ventana vieja y oscurece sistematicamente el render.
    """
    fuera = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(fuera, encoder_expandir(quad, 1 + grosor).astype(np.int32), 255)
    dentro = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(dentro, encoder_expandir(quad, 1 + grosor * 0.15).astype(np.int32), 255)
    anillo = cv2.subtract(fuera, dentro)
    px = img[anillo > 0]
    return tuple(np.median(px, axis=0).astype(float)) if len(px) else (128., 128., 128.)


def encoder_expandir(quad: np.ndarray, factor: float) -> np.ndarray:
    c = quad.mean(axis=0)
    return (c + (quad - c) * factor).astype(np.float32)


def _estimar_ruido(img, quad):
    """Sigma del ruido en la pared, para poder igualarlo en el parche pegado."""
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, encoder_expandir(quad, 1.6).astype(np.int32), 255)
    cv2.fillConvexPoly(m, encoder_expandir(quad, 1.05).astype(np.int32), 0)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    alta = g - cv2.GaussianBlur(g, (0, 0), 1.5)
    px = alta[m > 0]
    mad = np.median(np.abs(px - np.median(px)))
    return float(1.4826 * mad)      # equivalente a sigma para ruido gaussiano
    #return float(np.std(px)) if len(px) > 50 else 1.5


def _color_cielo(img):
    banda = img[: max(8, img.shape[0] // 10)]
    return tuple(np.percentile(banda.reshape(-1, 3), 75, axis=0).astype(float))

def debug_escena(escena: Escena, salida="debug_escena.jpg"):
    foto = cv2.imread(escena.ruta_foto)
    vis = foto.copy()
    ov = vis.copy()
    ov[escena.mask_hueco > 127] = (0, 200, 0)
    vis = cv2.addWeighted(ov, 0.30, vis, 0.70, 0)
    cv2.polylines(vis, [escena.quad.astype(np.int32)], True, (0, 0, 255), 3)
    for i, p in enumerate(escena.quad.astype(int)):
        cv2.circle(vis, tuple(p), 9, (255, 0, 0), -1)
        cv2.putText(vis, "TL TR BR BL".split()[i], tuple(p + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)
    cv2.imwrite(salida, vis)
    return vis

def medir_referencia(foto_bgr, quad_ref, frac_marco=0.20):
    """Brillo y color reales de una ventana YA EXISTENTE en la misma foto.

    Es el mejor patron posible: misma luz, mismo muro, misma camara, mismo
    balance de blancos. Mejor que cualquier constante que estimemos a ojo.
    """
    h, w = foto_bgr.shape[:2]
    fuera = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(fuera, quad_ref.astype(np.int32), 255)
    dentro = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(dentro, encoder_expandir(quad_ref, 1 - 2*frac_marco).astype(np.int32), 255)
    marco = cv2.subtract(fuera, dentro)

    pm = foto_bgr[marco > 0].astype(np.float32) / 255.0
    pv = foto_bgr[dentro > 0].astype(np.float32) / 255.0
    if len(pm) < 30 or len(pv) < 30:
        return None
    #return {"marco": np.median(pm, 0), "vidrio": np.median(pv, 0)}
    return {"marco": np.median(pm, 0).tolist(),"vidrio": np.median(pv, 0).tolist()}


def placa_limpia(image_bgr, mask, dilatar=14, lado_lama=896,
                 margen=0.40, device=None):
    """Borra la ventana vieja y reconstruye pared.

    Trabaja sobre un RECORTE alrededor del hueco, no sobre la foto entera:
    menos memoria y mejor calidad, porque LaMa rinde cerca de su resolucion
    de entrenamiento (~512 px) y se degrada con imagenes muy grandes.
    """
    global _LAMA
    H, W = image_bgr.shape[:2]
    k = np.ones((dilatar * 2 + 1, dilatar * 2 + 1), np.uint8)
    m = cv2.dilate((mask > 127).astype(np.uint8) * 255, k)

    ys, xs = np.where(m > 0)
    if len(xs) == 0:
        return image_bgr.copy()

    # --- recorte con margen: LaMa necesita ver pared alrededor para copiarla
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    mx, my = int((x1 - x0 + 1) * margen), int((y1 - y0 + 1) * margen)
    cx0, cy0 = max(0, x0 - mx), max(0, y0 - my)
    cx1, cy1 = min(W, x1 + mx + 1), min(H, y1 + my + 1)

    crop = image_bgr[cy0:cy1, cx0:cx1]
    crop_m = m[cy0:cy1, cx0:cx1]
    ch, cw = crop.shape[:2]

    # --- bajar a la escala de trabajo de LaMa
    esc = min(1.0, lado_lama / max(ch, cw))
    if esc < 1.0:
        sw, sh = int(cw * esc), int(ch * esc)
        peq = cv2.resize(crop, (sw, sh), interpolation=cv2.INTER_AREA)
        peq_m = cv2.resize(crop_m, (sw, sh), interpolation=cv2.INTER_NEAREST)
    else:
        peq, peq_m = crop, crop_m

    try:
        if _LAMA is None:
            
            _LAMA = SimpleLama(device=device) if device else SimpleLama()
        from PIL import Image
        out = _LAMA(Image.fromarray(peq[:, :, ::-1]), Image.fromarray(peq_m))

        # LaMa rellena hasta multiplo de 8 y NO deshace ese relleno:
        # hay que recortar a las dimensiones que le dimos.
        ph, pw = peq.shape[:2]
        rel_peq = np.array(out)[:ph, :pw, ::-1]

        rel = cv2.resize(rel_peq, (cw, ch), interpolation=cv2.INTER_CUBIC) \
            if esc < 1.0 else rel_peq
    except Exception as e:
        print(f"[placa] LaMa fallo ({type(e).__name__}: {e}); usando cv2.inpaint")
        rel = cv2.inpaint(crop, crop_m, 7, cv2.INPAINT_TELEA)

    # --- pegar SOLO dentro de la mascara: el resto de la foto no se toca
    a = cv2.GaussianBlur(crop_m.astype(np.float32) / 255.0, (0, 0), 2.0)[..., None]
    salida = image_bgr.copy()
    salida[cy0:cy1, cx0:cx1] = (crop.astype(np.float32) * (1 - a) +
                                rel.astype(np.float32) * a).astype(np.uint8)
    return salida


def encoger_quad(quad: np.ndarray, frac_x: float, frac_y: float) -> np.ndarray:
    """Mete el cuadrilatero hacia dentro (retranqueo de la ventana en el hueco)."""
    tl, tr, br, bl = quad
    def lerp(a, b, t): return a * (1 - t) + b * t # lerp(tl, tr, 0.018) avanza un 1.8% del lado superior desde la esquina izquierda hacia la derecha.
    t_l, t_r = lerp(tl, tr, frac_x), lerp(tr, tl, frac_x)
    b_l, b_r = lerp(bl, br, frac_x), lerp(br, bl, frac_x)
    return np.array([lerp(t_l, b_l, frac_y), lerp(t_r, b_r, frac_y),
                     lerp(b_r, t_r, frac_y), lerp(b_l, t_l, frac_y)],
                    dtype=np.float32)

'''def lado_visible(quad: np.ndarray) -> str:
    """Desde que lado miramos, segun que arista vertical se ve mas corta.

    Si la arista izquierda es mas corta, la camara esta a la derecha y por tanto
    la jamba que se ve es la izquierda.
    """
    tl, tr, br, bl = quad
    izq = np.linalg.norm(bl - tl)
    der = np.linalg.norm(br - tr)
    if abs(izq - der) < 0.03 * max(izq, der):
        return "ninguno"
    return "izquierda" if izq < der else "derecha"'''


def _armonizar_por_referencia(rgb, alpha, rect_vidrio, ref,
                              fuerza=0.85, gain_max=3.0):
    """Lleva marco y vidrio del producto al brillo medido en una ventana real.

    Corrige exposicion, temperatura de color y oscuridad del cristal de una
    sola vez, porque la ganancia se calcula por canal BGR.
    """
    h, w = alpha.shape
    x0, y0, x1, y1 = [int(v) for v in rect_vidrio]

    m_vidrio = np.zeros((h, w), np.float32)
    cv2.rectangle(m_vidrio, (x0, y0), (x1, y1), 1.0, -1)
    m_vidrio = cv2.GaussianBlur(m_vidrio, (0, 0), max(1.0, 0.008 * max(w, h)))
    opaco = (alpha > 0.5).astype(np.float32)
    m_vidrio *= opaco
    m_marco = np.clip(1.0 - m_vidrio, 0, 1) * opaco

    out = rgb.astype(np.float32).copy()
    for mascara, clave in ((m_marco, "marco"), (m_vidrio, "vidrio")):
        sel = mascara > 0.5
        if sel.sum() < 30:
            continue
        actual = np.median(rgb[sel], 0)
        objetivo = np.array(ref[clave], np.float32)
        gain = np.clip(objetivo / np.maximum(actual, 1e-3), 1.0 / gain_max, gain_max)
        gain = 1.0 + (gain - 1.0) * fuerza
        out = out * (1 - mascara[..., None]) + out * gain[None, None, :] * mascara[..., None]

    return np.clip(out, 0, 1)


'''def _campo_iluminacion(placa, quad, sigma_rel=0.25):
    """Campo de luz de baja frecuencia normalizado, tomado de la pared.

    Multiplicarlo transfiere la variacion espacial de luz de la fachada
    (sombra del alero, degradado) SIN tocar el color base del producto.
    """
    w, h = tam_objetivo(quad)
    sigma = max(3.0, sigma_rel * max(w, h))
    lab = cv2.cvtColor(placa, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = cv2.GaussianBlur(lab[:, :, 0], (0, 0), sigma)
    return L / max(float(np.median(L)), 1e-3)'''


def _reflejo_cristal(pre, alpha, color_cielo, intensidad=0.22):
    """Degradado de cielo sobre el vidrio.

    Un PNG de estudio tiene el cristal plano; en exterior el cristal SIEMPRE
    refleja el cielo. Sin esto el montaje canta aunque todo lo demas este bien.
    """
    h, w = alpha.shape
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
    cielo = np.array(color_cielo, np.float32) / 255.0
    grad = cielo[None, None, :] * (1.0 - t) ** 1.6
    # solo donde hay producto, y mas fuerte en zonas lisas (el vidrio)
    '''lisura = 1.0 - np.clip(cv2.Laplacian(
        cv2.cvtColor(np.clip(pre, 0, 1), cv2.COLOR_BGR2GRAY), cv2.CV_32F, ksize=3) * 6, 0, 1)'''
    lisura = 1.0 - np.clip(np.abs(cv2.Laplacian(
        cv2.cvtColor(np.clip(pre, 0, 1), cv2.COLOR_BGR2GRAY), cv2.CV_32F, ksize=3)) * 6, 0, 1)
    peso = (intensidad * lisura * alpha)[..., None]
    return np.clip(pre * (1 - peso * 0.4) + grad * peso, 0, 1)


'''def _dibujar_jamba(img, quad_hueco, quad_ventana, color_pared, lado):
    """Pinta la jamba visible del retranqueo, para que la ventana no parezca plana."""
    if lado == "ninguno":
        return img
    ho, hi = quad_hueco, quad_ventana
    idx = (0, 3, 3, 0) if lado == "izquierda" else (1, 2, 2, 1)
    poly = np.array([ho[idx[0]], hi[idx[3]], hi[idx[2]], ho[idx[1]]], np.float32)
    capa = img.copy()
    col = tuple(float(c * 0.72) for c in color_pared)      # jamba en sombra
    cv2.fillConvexPoly(capa, poly.astype(np.int32), col)
    m = np.zeros(img.shape[:2], np.float32)
    cv2.fillConvexPoly(m, poly.astype(np.int32), 1.0)
    m = cv2.GaussianBlur(m, (0, 0), 1.2)[..., None]
    return (img.astype(np.float32) * (1 - m) + capa.astype(np.float32) * m).astype(np.uint8)
'''
def _oclusion_contacto(img, quad, fuerza=0.35, ancho_rel=0.035):
    """Oscurecimiento suave en el perimetro interior del hueco (contact shadow)."""
    h, w = img.shape[:2]
    m = np.zeros((h, w), np.float32)
    cv2.fillConvexPoly(m, quad.astype(np.int32), 1.0)
    interior = np.zeros((h, w), np.float32)
    cv2.fillConvexPoly(interior, encoder_expandir(quad, 1 - ancho_rel * 2).astype(np.int32), 1.0)
    banda = np.clip(m - interior, 0, 1)
    tw, th = tam_objetivo(quad)
    banda = cv2.GaussianBlur(banda, (0, 0), max(1.5, 0.02 * max(tw, th)))
    f = (1.0 - fuerza * banda)[..., None]
    return np.clip(img.astype(np.float32) * f, 0, 255).astype(np.uint8)


def filtrar_oclusores(acc, quad, margen=1.03):
    """Conserva solo las piezas que cruzan el borde del hueco (barandilla,
    bajante, cable). Una planta o cortina vista a traves del cristal queda
    entera dentro del hueco: esta detras, no delante."""
    dentro = np.zeros(acc.shape, np.uint8)
    cv2.fillConvexPoly(dentro, encoder_expandir(quad, margen).astype(np.int32), 255)
    n, lab = cv2.connectedComponents((acc > 127).astype(np.uint8))
    out = np.zeros_like(acc)
    for i in range(1, n):
        comp = lab == i
        if (comp & (dentro == 0)).any():
            out[comp] = 255
    return out if out.any() else None
 

def imread_u(ruta, flags=cv2.IMREAD_COLOR):
    """
    Reemplaza a img = cv2.imread(ruta), pues puede fallar para rutas con caracteres unicode
    """
    datos = np.fromfile(ruta, np.uint8) # Devuelve los bytes del archivo
    return cv2.imdecode(datos, flags) if datos.size else None # Decodifica los bytes y los convierte en una matriz de pixeles
 
def imwrite_u(ruta, img):
    ext = os.path.splitext(ruta)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if ok: buf.tofile(ruta)
    return ok


def luz_desde_referencia(ref, albedo_blanco=0.80, sat_max=0.15, luma_min=0.30):
    """Ganancia de luz (balance de blancos + exposicion) a partir del marco de
    la ventana de referencia, SOLO si ese marco es claro y neutro (PVC/aluminio
    blanco o gris claro). Si no lo es, no se puede separar color de luz -> None."""
    m = np.asarray(ref["marco"], np.float32)
    sat = (m.max() - m.min()) / max(m.max(), 1e-3)
    luma = float(m.mean())
    if sat > sat_max or luma < luma_min:
        return None
    return m / albedo_blanco          # luz por canal: la escena "pinta" el blanco asi
 
def armonizar_v2(rgb, alpha, m_vidrio, ref, fuerza=0.85, gain_max=3.0):
    """Marco: color_catalogo x luz de la escena (conserva el color del producto).
    Vidrio: se lleva al vidrio de la referencia (el vidrio no tiene "color de
    producto": es reflejo + interior oscuro)."""
    opaco = (alpha > 0.5).astype(np.float32)
    mv = m_vidrio * opaco
    mm = np.clip(1 - mv, 0, 1) * opaco
    out = rgb.astype(np.float32).copy()
    luz = luz_desde_referencia(ref)
    if luz is not None:
        g = 1 + (np.clip(luz, 1 / gain_max, gain_max) - 1) * fuerza
        out = out * (1 + (g - 1) * mm[..., None])
    sel = mv > 0.5
    if sel.sum() >= 30:
        act = np.median(rgb[sel], 0)
        g = np.clip(np.asarray(ref["vidrio"], np.float32) / np.maximum(act, 1e-3), 1 / gain_max, gain_max)
        g = 1 + (g - 1) * fuerza
        out = out * (1 + (g - 1) * mv[..., None])
    return np.clip(out, 0, 1)


def _campo_iluminacion(placa, quad, sigma_rel=0.25, sigma_px=8.0):
    """Igual que antes pero (a) a baja resolucion y (b) normalizado con la pared
    que rodea el hueco: el campo vale ~1 junto a la ventana y solo aporta la
    variacion de luz A TRAVES de ella (sombra de alero, degradado)."""
    H, W = placa.shape[:2]
    tw, th = tam_objetivo(quad)
    sigma = max(3.0, sigma_rel * max(tw, th))
    f = min(1.0, sigma_px / sigma)
    peq = cv2.resize(placa, (max(8, int(W * f)), max(8, int(H * f))), interpolation=cv2.INTER_AREA)
    L = cv2.cvtColor(peq, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
    L = cv2.GaussianBlur(L, (0, 0), sigma * f)
    anillo = np.zeros(L.shape, np.uint8)
    cv2.fillConvexPoly(anillo, (encoder_expandir(quad, 1.25) * f).astype(np.int32), 255)
    cv2.fillConvexPoly(anillo, (encoder_expandir(quad, 1.02) * f).astype(np.int32), 0)
    ref = float(np.median(L[anillo > 0])) if (anillo > 0).any() else float(np.median(L))
    return cv2.resize(L / max(ref, 1e-3), (W, H), interpolation=cv2.INTER_LINEAR)
 
def lados_visible(quad, umbral=0.03):
    tl, tr, br, bl = quad
    izq, der = np.linalg.norm(bl - tl), np.linalg.norm(br - tr)
    arr, aba = np.linalg.norm(tr - tl), np.linalg.norm(br - bl)
    lados = []
    if abs(izq - der) >= umbral * max(izq, der):
        lados.append("izquierda" if izq < der else "derecha")
    if aba - arr >= umbral * max(arr, aba):     # arriba mas corto: camara por debajo (foto desde la calle)
        lados.append("arriba")
    return lados
 
def dibujar_jamba(img, ho, hi, color_pared, lados):
    out = img.astype(np.float32)
    polys = {"izquierda": ([ho[0], hi[0], hi[3], ho[3]], 0.72),
             "derecha":   ([ho[1], hi[1], hi[2], ho[2]], 0.72),
             "arriba":    ([ho[0], ho[1], hi[1], hi[0]], 0.60)}   # intrados del dintel, mas oscuro
    for lado in lados:
        poly, oscuro = polys[lado]
        m = np.zeros(img.shape[:2], np.float32)
        cv2.fillConvexPoly(m, np.array(poly, np.float32).astype(np.int32), 1.0)
        m = cv2.GaussianBlur(m, (0, 0), 1.2)[..., None]
        col = np.array(color_pared, np.float32) * oscuro
        out = out * (1 - m) + col * m
    return out.clip(0, 255).astype(np.uint8)