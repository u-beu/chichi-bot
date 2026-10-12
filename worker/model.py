import logging

import torch
from transformers import ASTForAudioClassification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"

# AudioSet 527 클래스 중 장르/무드에 해당하는 라벨 부분집합 (model.config.label2id 키와 동일)
GENRE_LABELS = [
    "Pop music", "Hip hop music", "Rock music", "Classical music", "Electronic music",
    "Jazz", "Country", "Blues", "Reggae", "Heavy metal",
]
MOOD_LABELS = [
    "Happy music", "Sad music", "Tender music", "Exciting music", "Angry music", "Scary music",
]

_model = None


def get_device() -> torch.device:
    """mps 사용 가능하면 mps, cuda 사용 가능하면 cuda, 아니면 cpu 반환."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def get_model() -> ASTForAudioClassification:
    """지연 초기화된 전역 AST 사전학습 모델 싱글턴을 device에 올려서 반환.

    TODO: 장시간 idle 상태를 감지해 모델을 언로드하는 로직 추가 필요 (프로세스 오프로드 단계에서 구현).
    """
    global _model
    if _model is None:
        device = get_device()
        _model = ASTForAudioClassification.from_pretrained(MODEL_ID).to(device)
        _model.eval()
        logger.info(f"모델 초기화 완료 device={device}")
    return _model
