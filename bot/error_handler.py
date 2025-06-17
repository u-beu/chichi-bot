from discord.ext import commands
from discord.ext.commands import CommandNotFound
from .music import VideoTooLongError

def setup_error_handlers(bot):
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, CommandNotFound):
            await ctx.send("❓ 명령어를 찾을 수 없습니다.")
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if isinstance(original, VideoTooLongError):
                await ctx.send(f"❌ 해당 영상({original.duration // 60}분)은 너무 깁니다.")
            else:
                await ctx.send("⚠️ 오류가 발생했습니다.")
                raise error
        else:
            await ctx.send("⚠️ 오류가 발생했습니다.")
            raise error
