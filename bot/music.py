import asyncio
import logging
import discord
import yt_dlp
import aiohttp
from discord.ext import commands

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_DURATION = 7200
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'noplaylist': True,
    'extract_audio': True
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -bufsize 512k'
}

guild_music_queues = {}


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


async def send_play_history(song: dict, discord_id: int):
    url = "https://ub-chichi.site/api/bot/recent-played-song"
    data = {
        "title": song.get('title', 'Unknown Title'),
        "uploader": song.get('uploader', 'Unknown Uploader'),
        "image": song.get('image', 'null'),
        "videoId": song.get('video_id'),
        "discordId": int(discord_id)
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as response:
                if response.status == 200:
                    logger.info(f"API 전송 성공: {song['title']}")
                else:
                    logger.info(f"API 전송 실패: {response.status}")
    except Exception as e:
        logger.exception("예외 발생: %s", e)


async def handle_api_playback(bot: commands.Bot, guild_id: int, user_id: int, query: str):
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.info(f"handle api playback 길드 없음: {guild_id}")
        return

    member = guild.get_member(user_id) or await guild.fetch_member(user_id)
    if not member or not member.voice or not member.voice.channel:
        logger.info(f"handle api playback 멤버 없음: {user_id}")
        return

    loop= bot.loop or asyncio.get_running_loop()
    song = await loop.run_in_executor(None, lambda: get_song_info(query, from_url=False))

    queue = guild_music_queues.setdefault(guild_id, [])
    queue.insert(0, song)

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if not voice_client:
        await play_music(bot, guild, member, is_refresh=False)


def after_playing(bot: commands.Bot, guild: discord.Guild, member: discord.Member, ctx: commands.Context=None, error=None):
    if error:
        logger.error("에러 발생: %s", error, exc_info=error)

    async def next():
        voice_client = discord.utils.get(bot.voice_clients, guild=guild)
        if not voice_client or not voice_client.is_connected():
            return 
        
        queue = guild_music_queues.get(guild.id, [])
        if not queue:
            target_channel = ctx if ctx else member.voice.channel
            try:
                await target_channel.send("❌ 빈 대기열입니다. 재생을 종료합니다.")
            except Exception:
                pass
            await voice_client.disconnect()
            return

        await play_music(bot, guild, member, ctx=ctx, is_refresh=True)

    asyncio.run_coroutine_threadsafe(next(), bot.loop)


async def play_music(bot: commands.Bot, guild: discord.Guild, member: discord.Member, ctx: commands.Context=None, *, is_refresh: bool):

    member_voice_channel=member.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=guild)

    if voice_client and voice_client.is_connected():
        if voice_client.channel != member_voice_channel:
            await voice_client.move_to(member_voice_channel)
    else:
        voice_client = await member_voice_channel.connect()

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

    asyncio.create_task(send_play_history(song, member.id))
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['source'], **FFMPEG_OPTIONS))

    voice_client.play(source, after=lambda e: after_playing(bot, guild, member, ctx, e))
    
    target_channel = ctx if ctx else member.voice.channel
    try:
        await target_channel.send(f"🎶 재생중: **{song['title']}**")
    except Exception as e:
        logger.exception("예외 발생: %s", e)

def register_music_commands(bot: commands.Bot):
    @bot.command()
    async def play(ctx, *, arg=None):
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

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_playing():
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
        await play_music(ctx.bot, ctx.guild, ctx.author, ctx=ctx, is_refresh=False)

    @bot.command()
    async def skip(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            await ctx.send("⏭️ 다음 곡을 재생합니다.")
            voice_client.stop()

    @bot.command()
    async def stop(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if voice_client:
            await voice_client.disconnect()
            await ctx.send("🛑 노래 재생을 중지합니다.")

    @bot.command()
    async def resume(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_playing():
            await ctx.send("🎶 이미 노래를 재생 중입니다.")
            return

        if not guild_music_queues.get(ctx.guild.id) or len(guild_music_queues) == 0:
            await ctx.send("❌ 빈 대기열입니다.")
            return

        await ctx.send("✅ 다시 재생합니다.")
        await play_music(ctx.bot, ctx.guild, ctx.author, ctx=ctx, is_refresh=True)

    @bot.command()
    async def queue(ctx):
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

    @bot.command()
    async def clear(ctx):
        queue = guild_music_queues.get(ctx.guild.id, [])
        queue.clear()
        await ctx.send("▶️ 대기열 목록 초기화")

    @bot.command(name="help")
    async def custom_help(ctx):
        await ctx.send("[명령어 도움말]\n\n")
        await ctx.send("🔵 **!play** <검색어/유튜브 링크> : 요청한 노래를 즉시 재생합니다.\n(재생 중이던 노래가 있을 경우 다시 대기열에 넣습니다.)\n\n" +
                       "🔵 **!play --add** <검색어/유튜브 링크> : 요청한 노래를 대기열 리스트에 추가합니다.\n(현재 재생 중인 노래를 유지합니다.)\n\n" +
                       "🟡 **!skip** : 대기열 리스트에서 다음 곡을 재생합니다.\n\n" +
                       "🔴 **!stop** : 현재 재생중인 노래를 중단합니다.\n\n" +
                       "🟢 **!resume** : 대기열 리스트를 기준으로 노래를 다시 재생합니다.\n\n" +
                       "🟣 **!queue** : 대기열 리스트를 확인합니다.\n\n" +
                       "🟣 **!clear** : 대기열 리스트를 초기화합니다.(리스트의 노래를 모두 삭제합니다.)\n\n")
