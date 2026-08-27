import logging

import redis
from fastapi import FastAPI, HTTPException

from api.publisher import publish_playback
from api.schemas import PlaybackRequest, PlaybackResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chichi Bot API", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/playback", response_model=PlaybackResponse, status_code=202)
async def playback(request: PlaybackRequest):
    try:
        publish_playback(
            guild_id=request.guild_id,
            user_id=request.user_id,
            query=request.query,
        )
    except redis.RedisError as e:
        logger.exception("Redis publish failed")
        raise HTTPException(status_code=503, detail="Redis unavailable") from e

    return PlaybackResponse(
        status="queued",
        message="Command published to bot queue",
    )
