import gc
import logging

import numpy as np
import torch

from .model import GENRE_LABELS, MOOD_LABELS, get_device, get_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _release_memory(device: torch.device) -> None:
    """태스크 처리 직후 가비지 컬렉션 및 mps 캐시 해제."""
    gc.collect()
    if device.type == "mps":
        torch.mps.empty_cache()


def run_inference(mfcc: np.ndarray) -> dict:
    """MFCC np.ndarray(n_mfcc x time)를 받아 torch.no_grad() 범위 내에서 추론, genre/mood 딕셔너리로 반환."""
    n_mfcc = mfcc.shape[0]
    model = get_model(n_mfcc=n_mfcc)
    device = get_device()

    features = torch.from_numpy(mfcc).to(dtype=torch.float32)
    features = features.mean(dim=1).to(device)

    with torch.no_grad():
        genre_logits, mood_logits = model(features)
        genre_idx = int(torch.argmax(genre_logits).item())
        mood_idx = int(torch.argmax(mood_logits).item())

    _release_memory(device)

    return {"genre": GENRE_LABELS[genre_idx], "mood": MOOD_LABELS[mood_idx]}
