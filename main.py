import os
from dotenv import load_dotenv

load_dotenv()

from bot.core import bot  # noqa: E402  (bot 모듈이 import 시점에 환경변수를 읽으므로 load_dotenv 이후 import)

TOKEN = os.getenv("DISCORD_TOKEN")

if __name__ == "__main__":
    bot.run(TOKEN)
