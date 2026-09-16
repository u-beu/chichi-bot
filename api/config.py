import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BOT_QUEUE_KEY = os.getenv("BOT_QUEUE_KEY", "bot:commands")
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://ub-chichi.site,http://localhost:3000,http://localhost:8080,http://localhost:5173",
).split(",")
