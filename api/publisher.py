import json
from typing import Any

import redis

from api.config import BOT_QUEUE_KEY, REDIS_URL

ACTION_PLAYBACK = "playback"


def _redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


def publish_command(payload: dict[str, Any]) -> None:
    client = _redis_client()
    client.lpush(BOT_QUEUE_KEY, json.dumps(payload))


def publish_playback(guild_id: int, user_id: int, query: str) -> None:
    publish_command({
        "action": ACTION_PLAYBACK,
        "guild_id": guild_id,
        "user_id": user_id,
        "query": query.strip(),
    })
