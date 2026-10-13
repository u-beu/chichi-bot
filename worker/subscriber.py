import asyncio
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import redis
import redis.asyncio as redis_asyncio

from .analyzer import analyze_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
WORKER_QUEUE_KEY = os.getenv("WORKER_QUEUE_KEY", "worker:analysis-requests")
SPRING_ANALYSIS_QUEUE_KEY = os.getenv("SPRING_ANALYSIS_QUEUE_KEY", "spring:analysis-results")
IDLE_UNLOAD_SEC = 600

_executor = None


def _get_executor() -> ProcessPoolExecutor:
    """모델이 상주하는 단일 분석 프로세스를 지연 생성. 동시 분석 1건으로 메모리 상한을 보장."""
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=1)
    return _executor


def _shutdown_executor() -> None:
    """분석 프로세스를 종료해 모델 가중치 RAM을 반환. 다음 요청 시 _get_executor가 재생성."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("분석 프로세스 종료(모델 언로드)")


async def _publish(client: redis_asyncio.Redis, message: dict) -> None:
    try:
        await client.lpush(SPRING_ANALYSIS_QUEUE_KEY, json.dumps(message))
        logger.info(f"분석 결과 전송 성공 videoId={message['videoId']}")
    except redis.RedisError:
        logger.exception(f"예외 발생: 결과 전송 실패 videoId={message['videoId']}")


async def _process_request(client: redis_asyncio.Redis, payload: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(f"에러 발생: 부적합 json 형식: {payload}")
        return

    video_id = data.get("videoId") if isinstance(data, dict) else None
    if not isinstance(video_id, str) or not video_id:
        logger.warning(f"에러 발생: videoId 누락 또는 부적합: {payload}")
        return

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(_get_executor(), analyze_video, video_id)
    except Exception as e:
        logger.exception(f"예외 발생: 분석 실패, 실패 결과 전송 videoId={video_id}")
        if isinstance(e, BrokenProcessPool):
            _shutdown_executor()
        result = {"videoId": video_id, "error": type(e).__name__}

    await _publish(client, result)


async def subscriber_loop() -> None:
    client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"레디스 구독 시작(queue={WORKER_QUEUE_KEY})")

    try:
        while True:
            try:
                result = await client.brpop(WORKER_QUEUE_KEY, IDLE_UNLOAD_SEC)
                if not result:
                    _shutdown_executor()
                    continue
                _, payload = result
                await _process_request(client, payload)
            except asyncio.CancelledError:
                logger.info("레디스 구독 중지")
                raise
            except redis.RedisError:
                logger.exception("예외 발생: 레디스: 재시작 3초")
                await asyncio.sleep(3)
            except Exception:
                logger.exception("예외 발생: 태스크 처리과정")
    finally:
        await client.aclose()
        _shutdown_executor()
