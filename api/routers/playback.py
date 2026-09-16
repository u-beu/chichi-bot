import logging

import redis
from fastapi import APIRouter, HTTPException

from api.publisher import publish_playback
from api.schemas import PlaybackRequest, PlaybackResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/playback", response_model=PlaybackResponse, status_code=202)
async def playback(request: PlaybackRequest):
    try:
        publish_playback(
            guild_id=request.guild_id,
            user_id=request.user_id,
            query=request.query,
        )
    except redis.RedisError as e:
        logger.exception("예외 발생: %s", e)
        raise HTTPException(status_code=503, detail="레디스 불가능") from e

    return PlaybackResponse(
        status="성공",
        message="재생 요청 완료",
    )
