import cv2
import sys
import os
import numpy as np
from scipy.optimize import minimize
from typing import Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.detector_class import DetectorVentanas
from backend.utils import ordenar_puntos


def ver(x, titulo):
    x = x.astype(np.float32)
    x = cv2.normalize(x, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    cv2.imshow(titulo, x)


def show_img(img):
    cv2.imshow("Mi Ventana de OpenCV", img)
    
    cv2.waitKey(0)
    
    cv2.destroyAllWindows()

PATH_IMG = "../backend/resources/real_2.jpg"
PATH_IMG_REPLACER = "../backend/resources/replace2.png"

img = cv2.imread(PATH_IMG)

img_replacer = cv2.imread(PATH_IMG_REPLACER,cv2.IMREAD_UNCHANGED) # cv2.IMREAD_UNCHANGED apra canal alfa, solo lo soporta PNG

print(img.shape) # (4096, 3072, 3)
print(img_replacer.shape) # (357, 698, 4)

'''print(img[:,:, 2])

print(img_replacer[:,:, 3])'''

# Escalar

H, W = img.shape[0], img.shape[1]
escala = min(1.0, 1280 / max(H, W)) # La altura o ancho siempre se mantendrá como 1280 si es el valor mayor, y el otro se escala la proporción correspondiente
peq = cv2.resize(img, (int(W * escala), int(H * escala)), interpolation=cv2.INTER_AREA) if escala < 1 else img

print(peq.shape) # (1280, 960, 3)


'''show_img(img)
show_img(peq)'''

# Máscaras detector
detector = DetectorVentanas()
masks = detector(peq)
print(len(masks))

mask_total = np.zeros_like(masks[0])
for m in masks:
    mask_total |= m  # bitwise_or

resultado = peq.copy()
overlay = resultado.copy()

overlay[mask_total > 0] = (0, 255, 0)

resultado = cv2.addWeighted(overlay, 0.4, resultado, 0.6, 0)
#show_img(resultado)

# Ajustar perspectiva con el optimizador
def _energia_bordes(quad: np.ndarray, grad: np.ndarray, n: int = 40) -> float:
   
    h, w = grad.shape # grad es una imagen del mismo tamaño que la foto, pero en vez de color guarda cuánto cambia el brillo en ese punto. Negro donde la imagen es lisa, blanco donde hay un borde.
    total, cuenta = 0.0, 0

    for i in range(4): # Recorre los 4 lados
        p0, p1 = quad[i], quad[(i + 1) % 4]
        t = np.linspace(0.05, 0.95, n)[:, None] # genera 40 números repartidos por igual entre 0.05 y 0.95.Son las posiciones relativas a lo largo del lado
        pts = p0[None, :] * (1 - t) + p1[None, :] * t # añade dim nueva de tam 1: p1[None, :]. Ejemplo: p0= [300 200]; p0[None, :]  →  [[300 200]] 
        xs = np.clip(pts[:, 0].astype(int), 0, w - 1) # np.clip(valor, minimo, maximo) si el valor es menor que el mínimo, devuelve el mínimo; si es mayor que el máximo, devuelve el máximo; si está dentro, lo devuelve tal cual.
        ys = np.clip(pts[:, 1].astype(int), 0, h - 1)
        total += grad[ys, xs].sum()
        cuenta += n
    return total / max(cuenta, 1)

def coste(p,lienzo, area_ref, peso_bordes = 0.30):
    # Planteo el problema como una optimización. Las incógnitas son las 8 coordenadas (4 esquinas × 2). La función de coste mide lo mal que va una propuesta
    q = p.reshape(4, 2).astype(np.float32) # Pues se ha hecho ravel
    lienzo.fill(0)
    cv2.fillConvexPoly(lienzo, q.astype(np.int32), 1) # pinta el cuadrilátero propuesto relleno de unos en un lienzo negro.
    inter = float(np.count_nonzero(lienzo & m)) # píxeles que están en ambos (la intersección)
    union = float(np.count_nonzero(lienzo | m)) # píxeles en alguno de los dos (la unión).
    c = 1.0 - inter / max(union, 1.0)
    if grad is not None:
        c -= peso_bordes * _energia_bordes(q, grad) # Donde el brillo cambia más bruscamente es donde está el marco, estos son valores altos, por eso se restan. Esto es porque dos candidatos pueden tener mismo IoU, para distinguir cual es mejor se mira la energía de bordes, que es alta si los lados están sobre un borde real y bajos si en una zona lisa.
    # penaliza degeneraciones
    if float(lienzo.sum()) < 0.3 * area_ref:
        c += 1.0
    return c

gray = cv2.cvtColor(peq, cv2.COLOR_BGR2GRAY)
print(gray.shape) #(1234, 1280)
'''show_img(gray)
exit()'''

quad_acumulado = []
for mask_single in masks:
    m = (mask_single == 255).astype(np.uint8) # o > 127
    print(np.unique(mask_single))
   

    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE) # Devuelve una tupla puntos de un contorno: [[[x1,y1]],[[x2,y2]]...] (columna, fila). Con CHAIN_APPROX_SIMPLE se comprimen ttramos recxtos y asi solo se guardan los extremos. Con RETR_EXTERNAL solo salen los contornos exteriores
    if not contours:
        raise ValueError("Mascara vacia")
    '''
    cv2.drawContours(peq.copy(), contours, -1, (0, 0, 255),2) # -1 para dibujar todos, BGR color, y el 2 es el grosor, con -1 rellena interior
    show_img(resultado)'''
    
    largest = max(contours, key=cv2.contourArea)

    print(cv2.minAreaRect(largest)) # Rectángulo rotado, de área mínima que encierra el contorno: ((cx, cy), (w, h), ángulo). Donde cx y cy es el centro

    box = cv2.boxPoints(cv2.minAreaRect(largest))
    box = box.astype(np.int32) # Los vértices

    '''resultado = peq.copy()
    print(box)
    cv2.drawContours(resultado, [box], 0, (0, 0, 255), 2)
    show_img(resultado)'''
   
    init = ordenar_puntos(cv2.boxPoints(cv2.minAreaRect(largest))) # Se parte como inicio con el cuadrilátero que forma la máscara

    grad = None
    if gray is not None:
        g = cv2.GaussianBlur(gray, (0, 0), 1.2) # Suaviza la imagen (en escala de grises), calcula el kernel con sigma 1.2. Se marcan mas los grises oscuros
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) # Derivada horizontal, cuanto cambia el brillo de izda a dcha. Usa CV_32F (float) para que los valores negativos no se pierdan,
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        grad = cv2.magnitude(gx, gy) # Fuerza del borde en cad píxel sin importar la magnitud: sqrt(gx² + gy²). Marca mas los perfiles
        grad /= (np.percentile(grad, 99) + 1e-6) # Normaliza dividiendo por el percentil 99. Así el 1% de píxeles más fuertes pasa de 1, y el resto queda escalado respecto a ellos. Es más robusto que dividir por el máximo, que un solo píxel extremo podría disparar. El 1e-6 evita dividir por cero en una imagen totalmente plana.
        grad = np.clip(grad, 0, 1) # Recorta lo que pasó de 1, dejando el rango final en [0, 1].


        '''ver(gray, "1 gris")
        ver(g, "2 suavizada")
        ver(gx, "3 Sobel X (bordes verticales)")
        ver(gy, "4 Sobel Y (bordes horizontales)")
        ver(cv2.magnitude(gx, gy), "5 magnitud sin normalizar")
        ver(grad, "6 final")
        cv2.waitKey(0)
        cv2.destroyAllWindows()'''



    area_ref = float(m.sum()) # Los 1s en la máscara
    lienzo = np.empty_like(m) # lienzo vacío con el tamaño de la máscara

    # TEST ENERGIA:
    h, w = grad.shape
    quad = init.copy()
    print(quad)

    '''for i in range(4):
        p0, p1 = quad[i], quad[(i + 1) % 4]

        print(p0)
        print(p0[None, :]) # [[ 65.53029 564.45074]]
        print()
        print(p1)
        

        t = np.linspace(0.05, 0.95, 40)[:, None] # genera 40 números repartidos por igual entre 0.05 y 0.95.Son las posiciones relativas a lo largo del lado
        pts = p0[None, :] * (1 - t) + p1[None, :] * t # añade dim nueva de tam 1: p1[None, :]. Ejemplo: p0= [300 200]; p0[None, :]  →  [[300 200]]. Es la función para interpolar, los puntos resultantes están entre p0 y p1. Esta función s eobtiene de la distancia entre dos puntos, que da como resultado un vector que indica como se llega desde p0 a p1, el desplazamiento. Si avanzo una fracción t de ese camino, aprtiendo de p0, tengo: p0 + t . d = p0 + t . (p1 - p0). Se ve d como el vector del camino completo y t dice que fracción del camino se recorre: ejemplo: d = (8,4) dice ives 8 a la derecha y 4 hacia abajo siendo p0 = (2, 4) y p1 = (10, 8). t · d es solo el desplazamiento (“cuánto me he movido”), no una posición. Para saber dónde estás, hay que decir desde dónde empezaste, por eso se suma p0.
        print(pts)
        print()
        print(pts[:, 0]) # Recorre cada tupla y coge la primera columna
       
        xs = np.clip(pts[:, 0].astype(int), 0, w - 1) # np.clip(valor, minimo, maximo) si el valor es menor que el mínimo, devuelve el mínimo; si es mayor que el máximo, devuelve el máximo; si está dentro, lo devuelve tal cual.
        ys = np.clip(pts[:, 1].astype(int), 0, h - 1)
        total += grad[ys, xs].sum() # Recupera las posiciones de grad
        cuenta += 40'''
   
    historial = [init.ravel().copy()]

    def guardar(xk):
        historial.append(xk.copy())

    res = minimize(coste, init.ravel(), args=(lienzo, area_ref), method="Powell",callback=guardar, options={"maxiter": 2000, "xtol": 0.5, "ftol": 1e-4}) # prueba valores y se queda con los que bajan el coste. Powell no necesita derivadas, que aquí no existen porque el coste es un conteo de píxeles. Empieza en minAreaRect y va empujando esquinas hasta que encaja.
    quad = ordenar_puntos(res.x.reshape(4, 2))
    quad_acumulado.append(quad)

resultado = peq.copy()

'''for quad in quad_acumulado:
    pts = quad.astype(np.int32)
    cv2.polylines(resultado, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
    for (x, y) in pts:
        cv2.circle(resultado, (int(x), int(y)), 6, (0, 0, 255), -1)

show_img(resultado)'''


'''import matplotlib.pyplot as plt

costes = [coste(x, lienzo, area_ref) for x in historial]
plt.plot(costes, marker="o")
plt.xlabel("iteración"); plt.ylabel("coste")
plt.show()

vis = peq.copy()
n = len(historial)
for k, x in enumerate(historial):
    f = k / max(n - 1, 1)
    color = (0, int(255 * f), int(255 * (1 - f)))      # BGR: rojo -> verde
    cv2.polylines(vis, [x.reshape(4, 2).astype(np.int32)], True, color, 2)
show_img(vis)'''

exit()
# si la optimizacion empeoro las cosas, nos quedamos con la inicial
quad_ref = quad if coste(quad.ravel(),lienzo, area_ref) <= coste(init.ravel(),lienzo, area_ref) else init


############################
# Quad interior
############################

###########################
# Oclusores
###########################