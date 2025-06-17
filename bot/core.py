import logging
import discord
from discord.ext import commands
from .error_handler import setup_error_handlers
from .music import register_music_commands

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Game(name="명령어 도움 !help"))
    logging.info(f"봇 준비 완료: {bot.user}")

setup_error_handlers(bot)
register_music_commands(bot)

