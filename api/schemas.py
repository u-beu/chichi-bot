from typing import Annotated

from pydantic import BaseModel, Field


class PlaybackRequest(BaseModel):
    guild_id: Annotated[int, Field(gt=0)]
    user_id: Annotated[int, Field(gt=0)]
    query: Annotated[str, Field(min_length=1)]


class PlaybackResponse(BaseModel):
    status: str
    message: str
