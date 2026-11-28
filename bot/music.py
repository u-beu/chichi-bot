import asyncio
import json
import logging
import os
from typing import Optional
import discord
import yt_dlp
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPRING_PLAY_HISTORY_QUEUE_KEY = os.getenv("SPRING_PLAY_HISTORY_QUEUE_KEY", "spring:play-history")
SPRING_PLAYBACK_FAILURE_QUEUE_KEY = os.getenv("SPRING_PLAYBACK_FAILURE_QUEUE_KEY", "spring:playback-failure")
MAX_DURATION = 7200
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'noplaylist': True,
}
FFMPEG_OPTIONS = {
    'before_options': (
        '-reconnect 1 '
        '-reconnect_streamed 1 '
        '-reconnect_delay_max 5 '
        '-probesize 32M '
        '-analyzeduration 0 '
        '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"'
    ),
    'options': (
        '-vn '
        '-bufsize 128k'
    )
}

guild_music_queues = {}
guild_pause_tasks = {}
PAUSE_TIMEOUT_SEC = 20 * 60

class VideoTooLongError(Exception):
    def __init__(self, duration, max_duration):
        super().__init__(f"영상 길이({duration}s)는 {max_duration}s(2시간) 미만이어야 합니다.")
        self.duration = duration
        self.max_duration = max_duration
  
def get_song_info(query: str, *, from_url: bool = False):
    extract_target = query if from_url else f"ytsearch1:{query}"

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(extract_target, download=False)

        if 'entries' in info:
            info = info['entries'][0]

        duration = info['duration']
        if duration > MAX_DURATION:
            raise VideoTooLongError(duration, MAX_DURATION)

        return {
            'source': info['url'],
            'title': info['title'],
            'uploader': info['uploader'],
            'image': info['thumbnail'],
            'video_id': info['display_id']
        }

async def get_info_async(ctx: commands.Context, query: str, *, is_url: bool = False):
    loop = ctx.bot.loop
    return await loop.run_in_executor(None, lambda: get_song_info(query, from_url=is_url))


async def send_play_history(song: dict, discord_id: int, redis_client):
    data = {
        "title": song.get('title', 'Unknown Title'),
        "uploader": song.get('uploader', 'Unknown Uploader'),
        "image": song.get('image', 'null'),
        "videoId": song.get('video_id'),
        "discordId": int(discord_id)
    }

    try:
        await redis_client.lpush(SPRING_PLAY_HISTORY_QUEUE_KEY, json.dumps(data))
        logger.info(f"Redis 전송 성공: {song['title']}")
    except Exception as e:
        logger.exception("예외 발생: %s", e)


async def send_playback_failure(discord_id: int, redis_client, status: str):
    data = {
        "discordId": int(discord_id),
        "status": status
    }

    try:
        await redis_client.lpush(SPRING_PLAYBACK_FAILURE_QUEUE_KEY, json.dumps(data))
        logger.info(f"Redis 재생 실패 전송 성공: {discord_id} ({status})")
    except Exception as e:
        logger.exception("예외 발생: %s", e)


def find_voice_channel(guild: discord.Guild, discord_id: int):
    return next((vc for vc in guild.voice_channels if discord_id in vc.voice_states), None)


async def handle_api_playback(bot: commands.Bot, discord_id: int, query: str) -> Optional[str]:
    """재생 처리에 실패하면 실패 status(문자열)를, 성공하면 None을 반환."""
    guild = next((g for g in bot.guilds if find_voice_channel(g, discord_id)), None)
    if not guild:
        logger.info(f"handle api playback 음성 채널 접속 길드 없음: {discord_id}")
        return "not_in_voice"

    loop= bot.loop or asyncio.get_running_loop()
    try:
        song = await loop.run_in_executor(None, lambda: get_song_info(query, from_url=False))
    except VideoTooLongError:
        return "video_too_long"
    except Exception:
        logger.exception("예외 발생: 곡 정보 조회 실패: %s", query)
        return "search_failed"

    if not find_voice_channel(guild, discord_id):
        logger.info(f"handle api playback 검색 중 음성 채널 이탈: {discord_id}")
        return "not_in_voice"

    queue = guild_music_queues.setdefault(guild.id, [])
    queue.insert(0, song)

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
        return None

    try:
        return await play_music(bot, guild, discord_id, is_refresh=False)
    except Exception:
        logger.exception("예외 발생: 재생 시작 실패")
        return "playback_failed"


def after_playing(bot: commands.Bot, guild: discord.Guild, discord_id: int, ctx: commands.Context=None, error=None):
    if error:
        logger.error("에러 발생: %s", error, exc_info=error)

    async def next():
        if error:
            await send_playback_failure(discord_id, bot.redis_client, "playback_failed")

        voice_client = discord.utils.get(bot.voice_clients, guild=guild)
        if not voice_client or not voice_client.is_connected():
            return 
        
        member_voice_channel = find_voice_channel(guild, discord_id)
        if not member_voice_channel:
            guild_music_queues.pop(guild.id, None)
            await voice_client.disconnect()
            return

        queue = guild_music_queues.get(guild.id, [])
        if not queue:
            guild_music_queues.pop(guild.id, None)
            target_channel = ctx if ctx else member_voice_channel
            try:
                await target_channel.send("❌ 빈 대기열입니다. 재생을 종료합니다.")
            except Exception:
                pass
            await voice_client.disconnect()
            return

        try:
            status = await play_music(bot, guild, discord_id, ctx=ctx, is_refresh=True)
        except Exception:
            logger.exception("예외 발생: 다음 곡 재생 실패")
            status = "playback_failed"
        if status:
            await send_playback_failure(discord_id, bot.redis_client, status)

    asyncio.run_coroutine_threadsafe(next(), bot.loop)


async def play_music(bot: commands.Bot, guild: discord.Guild, discord_id: int, ctx: commands.Context=None, *, is_refresh: bool) -> Optional[str]:
    """재생을 시작하지 못한 사유가 있으면 실패 status(문자열)를 반환."""

    member_voice_channel = find_voice_channel(guild, discord_id)
    if not member_voice_channel:
        return

    permissions = member_voice_channel.permissions_for(guild.me)
    if not permissions.connect or not permissions.speak:
        target_channel = ctx if ctx else member_voice_channel
        await target_channel.send("⛔ 해당 음성 채널에 연결 권한이 없습니다.")
        return "no_permission"

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)

    try:
        if voice_client and voice_client.is_connected():
            if voice_client.channel != member_voice_channel:
                await voice_client.move_to(member_voice_channel)
        else:
            voice_client = await member_voice_channel.connect()
    except Exception:
        logger.exception("예외 발생: 음성 채널 연결 실패")
        target_channel = ctx if ctx else member_voice_channel
        await target_channel.send("⚠️ 음성 채널 연결에 실패했습니다.")
        return "connect_failed"

    queue = guild_music_queues.get(guild.id, [])
    if not queue: return
    song = queue.pop(0)

    if is_refresh:
        try:
            webUrl=f"https://www.youtube.com/watch?v={song['video_id']}"
            loop = bot.loop or asyncio.get_running_loop()
            song = await loop.run_in_executor(None, lambda: get_song_info(webUrl, from_url=True))
        except Exception as e:
            logger.exception("예외 발생: 음원 정보 갱신 실패: %s", e)

    asyncio.create_task(send_play_history(song, discord_id, bot.redis_client))
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['source'], **FFMPEG_OPTIONS))

    voice_client.play(source, after=lambda e: after_playing(bot, guild, discord_id, ctx, e))
    
    target_channel = ctx if ctx else member_voice_channel
    try:
        await target_channel.send(f"🎶 재생중: **{song['title']}**")
    except Exception as e:
        logger.exception("예외 발생: %s", e)

async def _require_voice(ctx) -> bool:
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("⛔ 음성 채널에서 호출해주세요.")
        return False
    return True


async def _pause_timeout(ctx, guild_id: int, voice_client):
    await asyncio.sleep(PAUSE_TIMEOUT_SEC)
    guild_pause_tasks.pop(guild_id, None)
    if voice_client.is_connected() and voice_client.is_paused():
        guild_music_queues.pop(guild_id, None)
        await voice_client.disconnect()
        await ctx.send("⏹️ 일시정지가 너무 길어 재생을 종료합니다.")


class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    @commands.command()
    async def play(self, ctx, *, arg=None):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("⛔ 음성 채널에서 호출해주세요.")
            return

        if arg is None:
            arg = "최신곡 모음"

        args = arg.split()

        is_add = False
        is_url = False

        if "--add" in args:
            is_add = True
            args.remove("--add")

        arg = " ".join(args)

        if "https://" in arg:
            is_url = True

        song = await get_info_async(ctx, arg, is_url=is_url)
        if not song:
            await ctx.send("❌ 노래 탐색에 실패했습니다.")
            return

        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            if is_add:
                guild_music_queues.setdefault(ctx.guild.id, []).append(song)
                await ctx.send(f"✅ 대기열 추가: **{song['title']}**")
                return
            else:
                guild_music_queues.setdefault(ctx.guild.id, []).insert(0, song)
                voice_client.stop()
                await ctx.send(f"▶️ 현재 곡을 중단하고 즉시 재생합니다.")
                return

        guild_music_queues.setdefault(ctx.guild.id, []).insert(0, song)
        await ctx.send(f"▶️ 즉시 재생합니다.")
        await play_music(ctx.bot, ctx.guild, ctx.author.id, ctx=ctx, is_refresh=False)

    @commands.command()
    async def skip(self, ctx):
        if not await _require_voice(ctx):
            return
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            await ctx.send("⏭️ 다음 곡을 재생합니다.")
            voice_client.stop()

    @commands.command()
    async def stop(self, ctx):
        if not await _require_voice(ctx):
            return
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)
        guild_music_queues.pop(ctx.guild.id, None)

        if voice_client:
            await voice_client.disconnect()
            await ctx.send("🛑 노래 재생을 중지합니다.")

    @commands.command()
    async def pause(self, ctx):
        if not await _require_voice(ctx):
            return
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if not (voice_client and voice_client.is_playing()):
            await ctx.send("❌ 재생 중인 노래가 없습니다.")
            return

        voice_client.pause()
        old_task = guild_pause_tasks.pop(ctx.guild.id, None)
        if old_task:
            old_task.cancel()
        guild_pause_tasks[ctx.guild.id] = asyncio.create_task(_pause_timeout(ctx, ctx.guild.id, voice_client))
        await ctx.send("⏸️ 일시정지합니다. 20분 안에 !resume 하지 않으면 재생을 종료합니다.")

    @commands.command()
    async def resume(self, ctx):
        if not await _require_voice(ctx):
            return
        voice_client = discord.utils.get(self.bot.voice_clients, guild=ctx.guild)

        if not (voice_client and voice_client.is_paused()):
            await ctx.send("❌ 일시정지 상태가 아닙니다.")
            return

        task = guild_pause_tasks.pop(ctx.guild.id, None)
        if task:
            task.cancel()
        voice_client.resume()
        await ctx.send("▶️ 다시 재생합니다.")

    @commands.command()
    async def queue(self, ctx):
        queue = guild_music_queues.get(ctx.guild.id, [])

        if not queue:
            await ctx.send("빈 대기열")
            return

        queue_message = "**🗒️대기열 목록:**\n"
        for idx, song in enumerate(queue[:10], start=1):
            queue_message += f"{idx}. {song['title']}\n"

        if len(queue) > 10:
            queue_message += f"...외 {len(queue) - 10}곡 더 있음"

        await ctx.send(queue_message)

    @commands.command()
    async def clear(self, ctx):
        if not await _require_voice(ctx):
            return
        guild_music_queues.pop(ctx.guild.id, None)
        await ctx.send("▶️ 대기열 목록 초기화")

    @commands.command(name="help")
    async def custom_help(self, ctx):
        await ctx.send("[명령어 도움말]\n\n")
        await ctx.send("🔵 **!play** <검색어/유튜브 링크> : 요청한 노래를 즉시 재생합니다.\n(재생 중이던 노래가 있을 경우 다시 대기열에 넣습니다.)\n\n" +
                       "🔵 **!play --add** <검색어/유튜브 링크> : 요청한 노래를 대기열 리스트에 추가합니다.\n(현재 재생 중인 노래를 유지합니다.)\n\n" +
                       "🟡 **!skip** : 대기열 리스트에서 다음 곡을 재생합니다.\n\n" +
                       "🔴 **!stop** : 재생을 종료하고 대기열을 비운 뒤 음성 채널에서 나갑니다.\n\n" +
                       "⏸️ **!pause** : 현재 재생중인 노래를 일시정지합니다. (20분 후 자동 종료)\n\n" +
                       "🟢 **!resume** : 일시정지한 노래를 이어서 재생합니다.\n\n" +
                       "🟣 **!queue** : 대기열 리스트를 확인합니다.\n\n" +
                       "🟣 **!clear** : 대기열 리스트를 초기화합니다.(리스트의 노래를 모두 삭제합니다.)\n\n")
