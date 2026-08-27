import asyncio
import json
import logging

import redis

from api.config import BOT_QUEUE_KEY, REDIS_URL
from api.publisher import ACTION_PLAYBACK
from bot.music import handle_api_playback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
        guild_id = int(data["guild_id"])
        user_id = int(data["user_id"])
        query = data.get("query", "")
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"에러 발생: 부적절한 입력: {e}")
        return

    await handle_api_playback(bot, guild_id, user_id, query)


async def _subscriber_loop(bot):
    client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info(f"레디스 구독 시작(queue={BOT_QUEUE_KEY})")

    while True:
        try:
            result = await asyncio.to_thread(client.brpop, BOT_QUEUE_KEY, 0)
            if not result:
                continue
            _, payload = result
            await _process_command(bot, payload)
        except asyncio.CancelledError:
            logger.info("레디스 구독 중지")
            raise
        except redis.RedisError:
            logger.exception("에러 발생: 레디스: 재시작 3초")
            await asyncio.sleep(3)
        except Exception:
            logger.exception("에러 발생: 커맨드 처리과정")


def start_subscriber(bot):
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = bot.loop.create_task(_subscriber_loop(bot))
