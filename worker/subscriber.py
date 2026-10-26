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
WORKER_PROCESSING_KEY = f"{WORKER_QUEUE_KEY}:processing"
SPRING_ANALYSIS_QUEUE_KEY = os.getenv("SPRING_ANALYSIS_QUEUE_KEY", "spring:analysis-results")
IDLE_UNLOAD_SEC = 600
RESULT_CACHE_TTL_SEC = 600
RESULT_CACHE_KEY_PREFIX = "worker:result:"
ANALYSIS_TIMEOUT_SEC = 300

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


def _kill_executor() -> None:
    """멈춘 분석 프로세스를 강제 종료. _shutdown_executor는 wait=True라 멈춘 자식을 다시 기다리므로 별도 경로."""
    global _executor
    if _executor is not None:
        # 표준 API에 실행 중인 자식을 강제 종료하는 수단이 없어 private 속성 접근
        for process in list(_executor._processes.values()):
            process.kill()
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None
        logger.info("분석 프로세스 강제 종료(타임아웃)")


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

    cache_key = f"{RESULT_CACHE_KEY_PREFIX}{video_id}"
    try:
        cached = await client.get(cache_key)
    except redis.RedisError:
        logger.exception(f"예외 발생: 결과 캐시 조회 실패 videoId={video_id}")
        cached = None
    if cached:
        logger.info(f"분석 결과 캐시 재발행 videoId={video_id}")
        await _publish(client, json.loads(cached))
        return

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(_get_executor(), analyze_video, video_id),
            ANALYSIS_TIMEOUT_SEC,
        )
    except Exception as e:
        logger.exception(f"예외 발생: 분석 실패, 실패 결과 전송 videoId={video_id}")
        if isinstance(e, BrokenProcessPool):
            _shutdown_executor()
        elif isinstance(e, asyncio.TimeoutError):
            _kill_executor()
        result = {"videoId": video_id, "error": type(e).__name__}

    if "error" not in result:
        try:
            await client.set(cache_key, json.dumps(result), ex=RESULT_CACHE_TTL_SEC)
        except redis.RedisError:
            logger.exception(f"예외 발생: 결과 캐시 저장 실패 videoId={video_id}")

    await _publish(client, result)


async def _recover_processing(client: redis_asyncio.Redis) -> None:
    """이전 실행에서 처리 중이던 요청(processing 리스트)을 재처리하지 않고 WorkerCrashed로 통보.

    같은 요청이 크래시(OOM 등)를 반복 유발하면 재기동마다 큐가 막히므로 재처리하지 않는다.
    """
    while payload := await client.lpop(WORKER_PROCESSING_KEY):
        try:
            video_id = json.loads(payload).get("videoId")
        except (json.JSONDecodeError, AttributeError):
            video_id = None
        if not isinstance(video_id, str) or not video_id:
            logger.warning(f"에러 발생: 미완료 요청 부적합, 폐기: {payload}")
            continue
        logger.warning(f"미완료 요청 WorkerCrashed 통보 videoId={video_id}")
        await _publish(client, {"videoId": video_id, "error": "WorkerCrashed"})


async def subscriber_loop() -> None:
    client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"레디스 구독 시작(queue={WORKER_QUEUE_KEY})")

    try:
        try:
            await _recover_processing(client)
        except redis.RedisError:
            logger.exception("예외 발생: 레디스: 미완료 요청 복구 실패")

        while True:
            try:
                payload = await client.blmove(WORKER_QUEUE_KEY, WORKER_PROCESSING_KEY, IDLE_UNLOAD_SEC, "RIGHT", "LEFT")
                if not payload:
                    _shutdown_executor()
                    continue
                try:
                    await _process_request(client, payload)
                except Exception:
                    logger.exception("예외 발생: 태스크 처리과정")
                await client.lrem(WORKER_PROCESSING_KEY, 1, payload)
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
