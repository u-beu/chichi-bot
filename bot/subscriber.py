import asyncio
import json
import logging
import os

import redis

from bot.music import handle_api_playback, send_playback_failure

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_QUEUE_KEY = os.getenv("BOT_QUEUE_KEY", "bot:commands")
BOT_PROCESSING_KEY = f"{BOT_QUEUE_KEY}:processing"
ACTION_PLAYBACK = "playback"


_subscriber_task = None


async def _process_command(bot, payload: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning(f"에러 발생: 부적합 json 형식: {payload}")
        return

    action = data.get("action")
    if action != ACTION_PLAYBACK:
        logger.warning(f"미등록 액션: {action}")
        return

    try:
        discord_id = int(data["discordId"])
        query = data.get("query", "")
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"에러 발생: 부적절한 입력: {e}")
        return

    if status := await handle_api_playback(bot, discord_id, query):
        await send_playback_failure(discord_id, bot.redis_client, status)


async def _requeue_processing(client):
    """이전 실행에서 처리 중이던 요청(processing 리스트)을 원래 큐로 되돌림."""
    while await client.lmove(BOT_PROCESSING_KEY, BOT_QUEUE_KEY, "LEFT", "RIGHT"):
        logger.warning("미완료 요청 복구")


async def _subscriber_loop(bot):
    client = bot.redis_client
    logger.info(f"레디스 구독 시작(queue={BOT_QUEUE_KEY})")

    try:
        await _requeue_processing(client)
    except redis.RedisError:
        logger.exception("예외 발생: 레디스: 미완료 요청 복구 실패")

    while True:
        try:
            payload = await client.blmove(BOT_QUEUE_KEY, BOT_PROCESSING_KEY, 0, "RIGHT", "LEFT")
            if not payload:
                continue
            try:
                await _process_command(bot, payload)
            except Exception:
                logger.exception("예외 발생: 커맨드 처리과정")
            await client.lrem(BOT_PROCESSING_KEY, 1, payload)
        except asyncio.CancelledError:
            logger.info("레디스 구독 중지")
            raise
        except redis.RedisError:
            logger.exception("예외 발생: 레디스: 재시작 3초")
            await asyncio.sleep(3)
        except Exception:
            logger.exception("예외 발생: 커맨드 처리과정")


def start_subscriber(bot):
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = bot.loop.create_task(_subscriber_loop(bot))


async def stop_subscriber():
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
    _subscriber_task = None
