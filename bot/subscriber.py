import asyncio
import json
import logging

import redis

from api.config import BOT_QUEUE_KEY, REDIS_URL
from api.publisher import ACTION_PLAYBACK
from bot.music import handle_api_playback

logger = logging.getLogger(__name__)

_subscriber_task = None


async def _process_command(bot, payload: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in queue: %s", payload)
        return

    action = data.get("action")
    if action != ACTION_PLAYBACK:
        logger.warning("Unknown action: %s", action)
        return

    try:
        guild_id = int(data["guild_id"])
        user_id = int(data["user_id"])
        query = data.get("query", "")
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Invalid playback command: %s", e)
        return

    await handle_api_playback(bot, guild_id, user_id, query)


async def _subscriber_loop(bot):
    client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Redis subscriber started (queue=%s)", BOT_QUEUE_KEY)

    while True:
        try:
            result = await asyncio.to_thread(client.brpop, BOT_QUEUE_KEY, 0)
            if not result:
                continue
            _, payload = result
            await _process_command(bot, payload)
        except asyncio.CancelledError:
            logger.info("Redis subscriber stopped")
            raise
        except redis.RedisError:
            logger.exception("Redis error, retrying in 3s")
            await asyncio.sleep(3)
        except Exception:
            logger.exception("Command processing error")


def start_subscriber(bot):
    global _subscriber_task
    if _subscriber_task is not None and not _subscriber_task.done():
        return
    _subscriber_task = bot.loop.create_task(_subscriber_loop(bot))
