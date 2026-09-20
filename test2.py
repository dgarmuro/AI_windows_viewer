from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from segment_anything import sam_model_registry, SamPredictor
from diffusers import StableDiffusionXLInpaintPipeline, StableDiffusionInpaintPipeline
import cv2
import numpy as np
import torch
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

def detectar_bbox_documento_grounding_dino(image_pil):
    """
    Detecta una caja de la ventana usando Grounding DINO.
    """
    model_id = "IDEA-Research/grounding-dino-base"

    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(DEVICE)

    text = "the exact window. glass window. house window"

    inputs = processor(
        images=image_pil,
        text=text,
        return_tensors="pt"
    ).to(DEVICE)

    with torch.no_grad():
        outputs = model(**inputs)

    results = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        threshold=0.25,
        text_threshold=0.25,
        target_sizes=[image_pil.size[::-1]]
    )[0]

    boxes = results["boxes"].cpu().numpy()
    scores = results["scores"].cpu().numpy()

    if len(boxes) == 0:
        raise RuntimeError("Grounding DINO no detectó ventana")

    best_idx = int(np.argmax(scores))
    box = boxes[best_idx].astype(int)

    # box = [x1, y1, x2, y2]
    return box


def segmentar_con_sam(image_bgr, bbox, sam_checkpoint, model_type="vit_b"):
    """
    Segmenta la ventana usando SAM a partir de la bbox detectada.
    """
    sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
    sam.to(device=DEVICE)

    predictor = SamPredictor(sam)

    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    predictor.set_image(image_rgb)

    masks, scores, logits = predictor.predict(
        box=np.array(bbox),
        multimask_output=True
    )

    best = int(np.argmax(scores))
    mask = masks[best].astype("uint8") * 255

    return mask


def debug_mascara(
    image_bgr: np.ndarray,
    mask: np.ndarray,
    output_path: str = "debug_mask_corners.jpg",
    alpha: float = 0.35
):
    vis = image_bgr.copy()

    mask_bool = mask > 0
    overlay = vis.copy()
    overlay[mask_bool] = (0, 255, 0)

    vis = cv2.addWeighted(overlay, alpha, vis, 1 - alpha, 0)
    cv2.imwrite(output_path, vis)
    return vis


def window_detector(image_path, sam_checkpoint="sam_vit_l_0b3195.pth"):
    """
    Devuelve (image_bgr, mask) -- necesitamos image_bgr para el inpainting posterior,
    a la misma resolución en la que se calculó la máscara.
    """
    image_raw = cv2.imread(image_path)
    if image_raw is None:
        raise FileNotFoundError(image_path)

    h, w = image_raw.shape[:2]
    max_side = 800
    scale = max_side / max(h, w)

    new_w = int(round(w * scale / 14) * 14)
    new_h = int(round(h * scale / 14) * 14)

    image_bgr = cv2.resize(image_raw, (new_w, new_h), interpolation=cv2.INTER_AREA)

    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    image_pil = Image.fromarray(image_rgb)

    bbox = detectar_bbox_documento_grounding_dino(image_pil)
    print("BBox:", bbox)

    mask = segmentar_con_sam(
        image_bgr,
        bbox,
        sam_checkpoint=sam_checkpoint,
        model_type="vit_l"
    )
    debug_mascara(image_bgr, mask)
    return image_bgr, mask


# ---------------------------------------------------------------------------
# NUEVO: refinado de máscara, inpainting y blending
# ---------------------------------------------------------------------------

def refinar_mascara(mask, feather_px=15):
    """
    Limpia bordes irregulares y difumina el contorno para una transición suave.
    """
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    feathered = cv2.GaussianBlur(mask, (feather_px * 2 + 1, feather_px * 2 + 1), 0)
    return feathered


def _tamano_valido_difusion(w, h, base=8, objetivo=1024):
    """
    Los modelos de difusión trabajan mejor cerca de su resolución nativa (1024 en SDXL,
    512 en SD1.5) y necesitan dimensiones múltiplo de 8. Escalamos manteniendo el aspecto.
    """
    scale = objetivo / max(w, h)
    new_w = max(base, int(round(w * scale / base) * base))
    new_h = max(base, int(round(h * scale / base) * base))
    return new_w, new_h


_PIPE_CACHE = {}


def cargar_pipeline_inpainting(modelo="sd15", device=DEVICE):
    """
    modelo:
      - "sd15": runwayml/stable-diffusion-inpainting (ligero, recomendable para probar en CPU)
      - "sdxl": diffusers/stable-diffusion-xl-1.0-inpainting-0.1 (mejor calidad, necesita GPU
                para no tardar demasiado; en CPU puede tardar >15 min por imagen)
    """
    if modelo in _PIPE_CACHE:
        return _PIPE_CACHE[modelo]

    dtype = torch.float16 if device == "cuda" else torch.float32

    if modelo == "sdxl":
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
            torch_dtype=dtype
        )
        objetivo = 1024
    else:
        pipe = StableDiffusionInpaintPipeline.from_pretrained(
            "runwayml/stable-diffusion-inpainting",
            torch_dtype=dtype
        )
        objetivo = 512

    pipe = pipe.to(device)
    _PIPE_CACHE[modelo] = (pipe, objetivo)
    return _PIPE_CACHE[modelo]


def inpaint_ventana(image_bgr, mask, prompt, negative_prompt=None, modelo="sd15",
                     steps=30, guidance_scale=7.5, device=DEVICE):
    """
    Genera la ventana nueva dentro de la máscara. Devuelve una imagen BGR
    del mismo tamaño que image_bgr.
    """
    if negative_prompt is None:
        negative_prompt = "distorsionado, borroso, geometria irregular, mal dibujado, marco torcido"

    h, w = image_bgr.shape[:2]
    pipe, objetivo = cargar_pipeline_inpainting(modelo=modelo, device=device)
    gen_w, gen_h = _tamano_valido_difusion(w, h, objetivo=objetivo)

    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    image_pil = Image.fromarray(image_rgb).resize((gen_w, gen_h), Image.LANCZOS)
    mask_pil = Image.fromarray(mask).convert("L").resize((gen_w, gen_h), Image.LANCZOS)

    resultado = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt,
        image=image_pil,
        mask_image=mask_pil,
        guidance_scale=guidance_scale,
        num_inference_steps=steps,
        strength=0.99,
    ).images[0]

    resultado = resultado.resize((w, h), Image.LANCZOS)
    resultado_bgr = cv2.cvtColor(np.array(resultado), cv2.COLOR_RGB2BGR)
    return resultado_bgr


def blend_final(image_bgr_original, image_bgr_generado, mask):
    """
    Fusión tipo Poisson para integrar el parche generado con la luz/color
    de la foto original (evita que se note el retoque).
    """
    mask_bin = (mask > 127).astype(np.uint8) * 255
    ys, xs = np.where(mask_bin > 0)
    if len(xs) == 0:
        raise ValueError("Máscara vacía, no se puede hacer blending")
    center = (int(xs.mean()), int(ys.mean()))

    blended = cv2.seamlessClone(
        image_bgr_generado, image_bgr_original, mask_bin, center, cv2.NORMAL_CLONE
    )
    return blended


def reemplazar_ventana(image_path, prompt, sam_checkpoint="sam_vit_l_0b3195.pth",
                        modelo="sd15", output_path="resultado.jpg"):
    """
    Pipeline completo: detección -> segmentación -> refinado -> inpainting -> blending.
    """
    image_bgr, mask_raw = window_detector(image_path, sam_checkpoint=sam_checkpoint)

    print("Refinando máscara...")
    mask = refinar_mascara(mask_raw)

    print(f"Generando inpainting (modelo={modelo})... esto puede tardar en CPU")
    generado = inpaint_ventana(image_bgr, mask, prompt, modelo=modelo, device=DEVICE)

    print("Blending final...")
    final = blend_final(image_bgr, generado, mask)

    cv2.imwrite(output_path, final)
    print(f"Guardado en {output_path}")
    return final


# ---------------------------------------------------------------------------
# RAMA CATÁLOGO: encajar un PNG real de la ventana en el hueco detectado
# ---------------------------------------------------------------------------

def ordenar_puntos(pts):
    """
    Ordena 4 puntos como [arriba-izq, arriba-der, abajo-der, abajo-izq],
    que es el orden que espera cv2.getPerspectiveTransform.
    """
    pts = np.array(pts, dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]

    return np.array([tl, tr, br, bl], dtype=np.float32)


def obtener_esquinas_desde_mascara(mask):
    """
    Intenta ajustar un cuadrilátero al contorno de la máscara (mejor si la ventana
    está en perspectiva/ángulo). Si no consigue exactamente 4 puntos, cae al
    rectángulo mínimo rotado (minAreaRect) como respaldo.
    """
    contours, _ = cv2.findContours((mask > 127).astype(np.uint8),
                                    cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    largest = max(contours, key=cv2.contourArea)

    peri = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, 0.02 * peri, True)

    if len(approx) == 4:
        pts = approx.reshape(4, 2)
    else:
        rect = cv2.minAreaRect(largest)
        pts = cv2.boxPoints(rect)

    return ordenar_puntos(pts)


def cargar_ventana_png(png_path, alpha_threshold=10):
    """
    Carga el PNG de la ventana (con o sin canal alfa). Si tiene transparencia,
    recorta el margen transparente para que las esquinas de origen coincidan
    con el borde real de la ventana, no con el lienzo del PNG.
    Devuelve (bgr, alpha) donde alpha es 0-255, uint8.
    """
    img = cv2.imread(png_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(png_path)

    if img.shape[2] == 4:
        bgr = img[:, :, :3]
        alpha = img[:, :, 3]
    else:
        bgr = img
        alpha = np.full(img.shape[:2], 255, dtype=np.uint8)

    ys, xs = np.where(alpha > alpha_threshold)
    if len(xs) > 0:
        x0, x1 = xs.min(), xs.max()
        y0, y1 = ys.min(), ys.max()
        bgr = bgr[y0:y1 + 1, x0:x1 + 1]
        alpha = alpha[y0:y1 + 1, x0:x1 + 1]

    return bgr, alpha


def ajustar_brillo(ventana_bgr, image_bgr, mask):
    """
    Iguala el brillo medio del PNG con el de la zona del hueco en la foto original,
    para que no se note un salto de exposición al pegar.
    """
    zona = image_bgr[mask > 127]
    if len(zona) == 0:
        return ventana_bgr

    brillo_objetivo = cv2.cvtColor(zona.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV)[:, 0, 2].mean()

    hsv = cv2.cvtColor(ventana_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    brillo_actual = hsv[:, :, 2].mean()
    if brillo_actual < 1:
        return ventana_bgr

    factor = np.clip(brillo_objetivo / brillo_actual, 0.6, 1.6)  # limitar para no forzar demasiado
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * factor, 0, 255)

    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def encajar_ventana_png(image_bgr, mask, png_path, ajustar_luz=True, feather_px=6):
    """
    Deforma en perspectiva el PNG de la ventana para encajarlo en el hueco detectado
    y lo compone sobre la foto original usando alpha blending con bordes suavizados.
    """
    h_img, w_img = image_bgr.shape[:2]

    corners_dst = obtener_esquinas_desde_mascara(mask)
    ventana_bgr, ventana_alpha = cargar_ventana_png(png_path)

    if ajustar_luz:
        ventana_bgr = ajustar_brillo(ventana_bgr, image_bgr, mask)

    h_v, w_v = ventana_bgr.shape[:2]
    corners_src = np.array([[0, 0], [w_v - 1, 0], [w_v - 1, h_v - 1], [0, h_v - 1]], dtype=np.float32)

    H = cv2.getPerspectiveTransform(corners_src, corners_dst)

    warped_bgr = cv2.warpPerspective(ventana_bgr, H, (w_img, h_img))
    warped_alpha = cv2.warpPerspective(ventana_alpha, H, (w_img, h_img))

    # Solo pintamos donde el hueco detectado Y el propio PNG (su alpha) coinciden
    alpha_final = (warped_alpha.astype(np.float32) / 255.0) * (mask.astype(np.float32) / 255.0)
    if feather_px > 0:
        alpha_final = cv2.GaussianBlur(alpha_final, (feather_px * 2 + 1, feather_px * 2 + 1), 0)
    alpha_3c = cv2.merge([alpha_final] * 3)

    compuesto = image_bgr.astype(np.float32) * (1 - alpha_3c) + warped_bgr.astype(np.float32) * alpha_3c
    return compuesto.astype(np.uint8)


def reemplazar_ventana_con_catalogo(image_path, png_path,
                                     sam_checkpoint="sam_vit_l_0b3195.pth",
                                     output_path="resultado_catalogo.jpg"):
    """
    Pipeline completo con PNG real de catálogo: detección -> segmentación ->
    refinado -> homografía -> composición.
    """
    image_bgr, mask_raw = window_detector(image_path, sam_checkpoint=sam_checkpoint)

    print("Refinando máscara...")
    mask = refinar_mascara(mask_raw, feather_px=3)  # feather pequeño: el borde fino ya se hace en encajar_ventana_png

    print("Encajando ventana de catálogo...")
    final = encajar_ventana_png(image_bgr, mask, png_path)

    cv2.imwrite(output_path, final)
    print(f"Guardado en {output_path}")
    return final


if __name__ == "__main__":
    # Rama generativa (SDXL/SD1.5): describes la ventana por texto
    # reemplazar_ventana(
    #     "./test.jpeg",
    #     prompt="ventana de aluminio negro, doble hoja corredera, cristal moderno, fotorrealista, "
    #            "misma perspectiva, misma iluminacion",
    #     modelo="sd15",       # cambia a "sdxl" si tienes GPU
    #     output_path="resultado.jpg",
    # )

    # Rama catálogo: tienes el PNG real de la ventana que quieres meter
    reemplazar_ventana_con_catalogo(
        "./test.jpeg",
        "./replace2.png",
        output_path="resultado_catalogo.jpg",
    )