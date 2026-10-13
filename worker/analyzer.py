import logging

from .audio_source import AudioSourceError, get_audio_source_url
from .inference import run_inference
from .preprocessing import AudioDecodingError, preprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def analyze_video(video_id: str) -> dict:
    """videoId 하나를 받아 소스 추출 -> 전처리 -> 추론까지 전체 파이프라인을 동기적으로 수행.

    CPU-bound이므로 호출 측(subscriber)이 run_in_executor로 감싸 이벤트 루프 블로킹을 방지해야 함.
    실패 시 예외를 그대로 올리며(skip 여부 판단은 호출자 책임), 결과에는 videoId를 포함해 반환.
    """
    try:
        source_url = get_audio_source_url(video_id)
    except AudioSourceError:
        logger.exception(f"예외 발생: 오디오 소스 추출 실패 videoId={video_id}")
        raise

    try:
        features = preprocess(source_url)
    except AudioDecodingError:
        logger.exception(f"예외 발생: 오디오 전처리 실패(네트워크/디코딩 오류) videoId={video_id}")
        raise

    result = run_inference(features)
    result["videoId"] = video_id
    return result
