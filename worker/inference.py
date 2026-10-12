import gc
import logging

import numpy as np
import torch

from .model import GENRE_LABELS, MOOD_LABELS, get_device, get_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _release_memory(device: torch.device) -> None:
    """태스크 처리 직후 가비지 컬렉션 및 mps/cuda 캐시 해제."""
    gc.collect()
    if device.type == "mps":
        torch.mps.empty_cache()
    elif device.type == "cuda":
        torch.cuda.empty_cache()


def run_inference(features: np.ndarray) -> dict:
    """AST 입력 특징 np.ndarray(time x mel)를 받아 torch.no_grad() 범위 내에서 추론, genre/mood 딕셔너리로 반환.

    527개 AudioSet logits 중 GENRE_LABELS/MOOD_LABELS 부분집합에 해당하는 logits만 골라 각각 argmax.
    """
    model = get_model()
    device = get_device()
    label2id = model.config.label2id
    genre_ids = [label2id[label] for label in GENRE_LABELS]
    mood_ids = [label2id[label] for label in MOOD_LABELS]

    input_values = torch.from_numpy(features).to(dtype=torch.float32).unsqueeze(0).to(device)

    with torch.no_grad():
        logits = model(input_values=input_values).logits[0]
        genre_idx = int(torch.argmax(logits[genre_ids]).item())
        mood_idx = int(torch.argmax(logits[mood_ids]).item())

    _release_memory(device)

    return {"genre": GENRE_LABELS[genre_idx], "mood": MOOD_LABELS[mood_idx]}
