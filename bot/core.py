import logging
import os
import discord
import redis.asyncio as redis_asyncio
from discord.ext import commands
from .error_handler import setup_error_handlers
from .music import MusicCog
from .subscriber import start_subscriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

intents = discord.Intents.default()
intents.message_content = True


class ChichiBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis_client: redis_asyncio.Redis | None = None

    async def setup_hook(self):
        self.redis_client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
        await self.add_cog(MusicCog(self))

    async def close(self):
        if self.redis_client:
            await self.redis_client.aclose()
        await super().close()


bot = ChichiBot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="명령어 도움 !help"))
    logger.info(f"봇 준비 완료: {bot.user}")
    start_subscriber(bot)

setup_error_handlers(bot)

