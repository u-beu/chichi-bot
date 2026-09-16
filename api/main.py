import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import ALLOWED_ORIGINS
from api.routers import health, playback

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chichi Bot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(playback.router)
