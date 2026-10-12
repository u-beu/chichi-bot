import logging

import torch
import torch.nn as nn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GENRE_LABELS = ["unknown", "pop", "rock", "classical", "hiphop", "electronic"]
MOOD_LABELS = ["neutral", "happy", "sad", "energetic", "calm"]

_model = None


def get_device() -> torch.device:
    """mps 사용 가능하면 mps, 아니면 cpu 반환."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class GenreMoodModel(nn.Module):
    """실제 학습된 가중치가 없는 placeholder 분류기.

    입력: (n_mfcc,) 평균 풀링된 MFCC 벡터.
    출력: (genre_logits, mood_logits) 튜플.
    추후 실제 가중치로 state_dict만 교체하면 동일 인터페이스로 재사용 가능하도록 구조만 유지.
    """

    def __init__(self, n_mfcc: int = 40):
        super().__init__()
        self.genre_head = nn.Linear(n_mfcc, len(GENRE_LABELS))
        self.mood_head = nn.Linear(n_mfcc, len(MOOD_LABELS))

    def forward(self, x: torch.Tensor):
        return self.genre_head(x), self.mood_head(x)


def get_model(n_mfcc: int = 40) -> GenreMoodModel:
    """지연 초기화된 전역 모델 싱글턴을 device에 올려서 반환.

    TODO: 실제 가중치 연동 시 장시간 idle 상태를 감지해 모델을 언로드하는 로직 추가 필요
    (현재는 placeholder라 메모리 비용이 거의 없어 스킵).
    """
    global _model
    if _model is None:
        device = get_device()
        _model = GenreMoodModel(n_mfcc=n_mfcc).to(device)
        _model.eval()
        logger.info(f"모델 초기화 완료 device={device}")
    return _model
