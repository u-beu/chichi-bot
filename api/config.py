import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BOT_QUEUE_KEY = os.getenv("BOT_QUEUE_KEY", "bot:commands")
