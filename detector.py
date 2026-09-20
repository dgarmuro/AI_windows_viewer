from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from segment_anything import sam_model_registry, SamPredictor
import cv2
import numpy as np
import torch
from PIL import Image

DEVICE = "cpu"

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
        raise RuntimeError("Grounding DINO no detectó documento")

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

def window_detector(image_path,sam_checkpoint="sam_vit_l_0b3195.pth"):
    image_raw = cv2.imread(image_path)
    if image_raw is None:
            raise FileNotFoundError(image_path)
    
    h, w = image_raw.shape[:2]
    max_side = 800
    scale = max_side / max(h, w)

    # Dino trabaja mejor con dims multiplos de 14 que es su patch. Grounding DINO de Hugging Face y SamPredictor ya gestionan internamente el redimensionamiento de las imágenes para sus respectivas redes.

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
    return image_bgr,mask



window_detector("./test.jpeg")