import logging

from fastapi import FastAPI

from api.routers import health, playback

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chichi Bot API", version="0.1.0")

app.include_router(health.router)
app.include_router(playback.router)
