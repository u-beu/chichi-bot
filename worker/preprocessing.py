import logging

import audioread.ffdec
import librosa
import numpy as np
from transformers import ASTFeatureExtractor

from .model import MODEL_ID

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TARGET_SR = 16000
MAX_DURATION_SEC = 30
CHUNK_SEC = 10
MIN_CHUNK_SEC = 5

_feature_extractor = None


class AudioDecodingError(Exception):
    """네트워크 오류 또는 ffmpeg 디코딩 실패로 오디오 로드에 실패했을 때 발생."""


def load_audio(source_url: str, *, duration: float = MAX_DURATION_SEC, sr: int = TARGET_SR) -> np.ndarray:
    """스트리밍 URL에서 오디오를 최대 duration초만 로드하고 sr로 리샘플링. 전체 길이를 RAM에 올리지 않음.

    librosa.load에 URL 문자열을 그대로 넘기면 audioread가 로컬 파일 백엔드(rawread)를 먼저 시도하다가
    OSError로 바로 실패해 ffmpeg 백엔드까지 가지 못한다. audioread.ffdec.FFmpegAudioFile로 ffmpeg 백엔드를
    직접 열어 librosa.load에 전달해 스트리밍 URL을 강제로 ffmpeg가 디코딩하게 한다.
    """
    try:
        reader = audioread.ffdec.FFmpegAudioFile(source_url)
        y, _ = librosa.load(reader, duration=duration, sr=sr, mono=True)
    except Exception as e:
        raise AudioDecodingError(f"오디오 로드 실패(네트워크 또는 디코딩 오류): {source_url}") from e
    return y.astype(np.float32)


def extract_features(y: np.ndarray, *, sr: int = TARGET_SR) -> np.ndarray:
    """로드된 파형을 CHUNK_SEC초 단위로 나눠 조각별 AST 입력 특징(n_chunks x max_length x mel bins)을 추출.

    마지막 조각이 MIN_CHUNK_SEC초 미만이면(첫 조각 제외) 대부분이 패딩이라 평균을 왜곡하므로 버린다.
    """
    global _feature_extractor
    if _feature_extractor is None:
        _feature_extractor = ASTFeatureExtractor.from_pretrained(MODEL_ID)
    chunk_len = CHUNK_SEC * sr
    chunks = [y[i:i + chunk_len] for i in range(0, len(y), chunk_len)]
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK_SEC * sr:
        chunks.pop()
    inputs = _feature_extractor(chunks, sampling_rate=sr, return_tensors="np")
    return inputs["input_values"].astype(np.float32)


def preprocess(source_url: str) -> np.ndarray:
    """오디오 로드 + AST 특징 추출을 한 번에 수행하는 전처리 파이프라인의 공개 엔트리포인트."""
    y = load_audio(source_url)
    return extract_features(y)
