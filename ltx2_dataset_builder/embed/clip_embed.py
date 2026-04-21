"""
CLIP-based frame embedding for style-agnostic character recognition.

Works on real footage, Pixar, anime, cartoons — anything CLIP was trained on.
Embeddings are 768-dim (clip-vit-large-patch14), normalized, compared via cosine similarity.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_clip_model = None
_clip_processor = None
_clip_model_name: Optional[str] = None


def get_clip_model(model_name: str = "openai/clip-vit-large-patch14"):
    """Lazy-load and cache the CLIP model on GPU (or CPU fallback)."""
    global _clip_model, _clip_processor, _clip_model_name
    if _clip_model is not None and _clip_model_name == model_name:
        return _clip_model, _clip_processor

    import torch
    from transformers import CLIPModel, CLIPProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info(f"Loading CLIP model {model_name!r} on {device}")
    _clip_model = CLIPModel.from_pretrained(model_name).to(device)
    _clip_model.eval()
    _clip_processor = CLIPProcessor.from_pretrained(model_name)
    _clip_model_name = model_name
    logger.info("CLIP model loaded")
    return _clip_model, _clip_processor


def embed_frame(frame_bgr: np.ndarray, model_name: str = "openai/clip-vit-large-patch14") -> np.ndarray:
    """
    Return a normalized CLIP image embedding for a single BGR frame.

    Args:
        frame_bgr: H×W×3 uint8 BGR numpy array (OpenCV format)
        model_name: HuggingFace model identifier

    Returns:
        Normalized float32 numpy array of shape (embedding_dim,)
    """
    import torch
    from PIL import Image

    model, processor = get_clip_model(model_name)

    # BGR → RGB → PIL
    frame_rgb = frame_bgr[:, :, ::-1]
    image = Image.fromarray(frame_rgb.astype(np.uint8))

    device = next(model.parameters()).device
    inputs = processor(images=image, return_tensors="pt").to(device)

    with torch.no_grad():
        features = model.get_image_features(**inputs)

    emb = features[0].cpu().float().numpy()
    norm = np.linalg.norm(emb)
    return emb / norm if norm > 0 else emb
