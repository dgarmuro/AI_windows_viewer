
from __future__ import annotations
import torch
from dataclasses import dataclass, field, asdict
from typing import List
import cv2
import numpy as np
from transformers import Sam3Model, Sam3Processor
import gc
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
from segment_anything import sam_model_registry, SamPredictor

class DetectorVentanas:
    """Envuelve SAM 3 (preferido) con fallback a Grounding DINO + SAM 1.
    """

    def __init__(self, backend: str = "auto",
                 sam_checkpoint: str = "sam_vit_l_0b3195.pth",
                 sam3_id: str = "facebook/sam3",
                 media_precision: bool = True):
        self.sam_checkpoint = sam_checkpoint
        self._sam3 = None
        self._dino = None
        self._sam1 = None

        if backend in ("auto", "sam3"):
            try:
                dev = "cuda" if torch.cuda.is_available() else "cpu"
                modelo = Sam3Model.from_pretrained(sam3_id)
                if dev == "cuda" and media_precision:
                    modelo = modelo.to(dev, torch.bfloat16)   # ~1.7 GB en vez de ~3.5
                else:
                    modelo = modelo.to(dev)
                modelo.eval()
                proc = Sam3Processor.from_pretrained(sam3_id)
                self._sam3 = (proc, modelo, dev)
                self.backend = "sam3"
                print(f"[detector] SAM 3 cargado en {dev}")
            except Exception as e:
                if backend == "sam3":
                    raise
                print(f"[detector] SAM 3 no disponible ({e}); usando DINO+SAM")
                self.backend = "dino_sam"
        else:
            self.backend = backend

    def liberar(self):
        """Suelta los pesos de la VRAM. Llamar cuando ya no haga falta detectar."""
        self._dino = None
        self._sam1 = None
        self._sam3 = None
        self.backend = "liberado"        # evita que se recargue sin querer
        gc.collect()
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    def _detectar_sam3(self, image_bgr, prompt):
        
        proc, modelo, dev = self._sam3

        # transformers espera PIL en RGB
        pil = Image.fromarray(image_bgr[:, :, ::-1])
        inputs = proc(images=pil, text=prompt, return_tensors="pt").to(dev)

        with torch.no_grad():
            outputs = modelo(**inputs)

        res = proc.post_process_instance_segmentation(
            outputs,
            threshold=0.5,           # confianza minima de la deteccion
            mask_threshold=0.5,      # umbral para binarizar la mascara
            target_sizes=inputs.get("original_sizes").tolist(),
        )[0]

        masks = res["masks"]
        if len(masks) == 0:
            raise RuntimeError(f"SAM 3 no detecto '{prompt}'")

        masks = masks.cpu().numpy()
        h, w = image_bgr.shape[:2]
        out = []
        for m in masks:
            m = (m > 0.5).astype(np.uint8) * 255
            if m.shape != (h, w):
                m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
            out.append(m)
        return out

    def __call__(self, image_bgr: np.ndarray, prompt: str = "window") -> List[np.ndarray]:
        """Devuelve una lista de mascaras uint8 (0/255), una por ventana."""
        if self.backend == "sam3":
            return self._detectar_sam3(image_bgr, prompt)
        return self._detectar_dino_sam(image_bgr)

    def _cargar_dino_sam(self):
        if self._dino is None:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            mid = "IDEA-Research/grounding-dino-base"
            self._dino = (AutoProcessor.from_pretrained(mid),
                          AutoModelForZeroShotObjectDetection.from_pretrained(mid).to(dev), dev)
        if self._sam1 is None:
            
            dev = self._dino[2]
            sam = sam_model_registry["vit_l"](checkpoint=self.sam_checkpoint).to(dev)
            self._sam1 = SamPredictor(sam)

    def _detectar_dino_sam(self, image_bgr):
        
        self._cargar_dino_sam()
        processor, model, dev = self._dino
        pil = Image.fromarray(image_bgr[:, :, ::-1])
        inputs = processor(images=pil, text="window.", return_tensors="pt").to(dev)
        with torch.no_grad():
            outputs = model(**inputs)
        r = processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=0.30, text_threshold=0.25,
            target_sizes=[pil.size[::-1]])[0]
        boxes = r["boxes"].cpu().numpy()
        if len(boxes) == 0:
            raise RuntimeError("Grounding DINO no detecto ventana")

        self._sam1.set_image(image_bgr[:, :, ::-1])
        masks = []
        for b in boxes:                       # TODAS las ventanas, no solo argmax
            m, _, _ = self._sam1.predict(box=b.astype(int),
                                         multimask_output=False)  # con caja, False
            masks.append(m[0].astype(np.uint8) * 255)
        return masks