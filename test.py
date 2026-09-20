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


if __name__ == "__main__":
    reemplazar_ventana(
        "./fachada_real.jpg",
        prompt="ventana corredera de dos hojas con persiana enrollable integrada. Perfilería de PVC o aluminio con acabado imitación madera de roble/cerezo en tono caoba-naranja, con veta de madera visible y realista. Cajón superior de persiana del mismo acabado, con las lamas horizontales enrollables parcialmente bajadas (visibles unas 6-7 lamas), terminando en un carril guía con dos topes/manivelas oscuros. Dos paneles de vidrio templado con tono grisáceo/espejado que refleja gradiente de blanco a gris claro de arriba a abajo, separados por un montante central vertical del mismo acabado madera. Marco perimetral robusto del mismo material y color. Perfil lateral izquierdo visible mostrando el grosor del marco en tono naranja/cobre más saturado. Fondo blanco puro de estudio, iluminación uniforme y suave, sin sombras duras, alta nitidez, estilo catálogo comercial de carpintería/ventanas. Resolución alta, enfoque nítido en toda la ventana, sin marcas de agua ni texto. Ajustar perspectiva e iluminación",
        modelo="sdxl", #"sd15",       # cambia a "sdxl" si tienes GPU
        output_path="resultado.jpg",
    )