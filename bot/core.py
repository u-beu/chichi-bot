import logging
import aiohttp
import discord
from discord.ext import commands
from .error_handler import setup_error_handlers
from .music import register_music_commands
from .subscriber import start_subscriber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True


class ChichiBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self):
        self.http_session = aiohttp.ClientSession()

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()


bot = ChichiBot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="명령어 도움 !help"))
    logger.info(f"봇 준비 완료: {bot.user}")
    start_subscriber(bot)

setup_error_handlers(bot)
register_music_commands(bot)

