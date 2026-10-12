import asyncio
import json
import logging
import os

import redis
import redis.asyncio as redis_asyncio

from .analyzer import analyze_video

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
WORKER_QUEUE_KEY = os.getenv("WORKER_QUEUE_KEY", "worker:analysis-requests")
SPRING_ANALYSIS_QUEUE_KEY = os.getenv("SPRING_ANALYSIS_QUEUE_KEY", "spring:analysis-results")


async def _process_request(client: redis_asyncio.Redis, payload: str) -> None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(f"에러 발생: 부적합 json 형식: {payload}")
        return

    video_id = data.get("videoId")
    if not video_id:
        logger.warning(f"에러 발생: videoId 누락: {payload}")
        return

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, analyze_video, video_id)
    except Exception:
        logger.exception(f"예외 발생: 분석 실패, 태스크 skip videoId={video_id}")
        return

    try:
        await client.lpush(SPRING_ANALYSIS_QUEUE_KEY, json.dumps(result))
        logger.info(f"분석 결과 전송 성공 videoId={video_id}")
    except redis.RedisError:
        logger.exception(f"예외 발생: 결과 전송 실패 videoId={video_id}")


async def subscriber_loop() -> None:
    client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"레디스 구독 시작(queue={WORKER_QUEUE_KEY})")

    while True:
        try:
            result = await client.brpop(WORKER_QUEUE_KEY, 0)
            if not result:
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
