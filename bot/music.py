# 음악 관련 유틸과 명령어 정의
import asyncio
import logging
import discord
import yt_dlp
import aiohttp
from discord.ext import commands

logging.basicConfig(level=logging.INFO)

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
currently_playing = {}


class VideoTooLongError(Exception):
    def __init__(self, duration, max_duration):
        super().__init__(f"영상 길이({duration}s)는 {max_duration}s(2시간) 미만이어야 합니다.")
        self.duration = duration
        self.max_duration = max_duration


async def handle_api_playback(bot, guild_id: int, user_id: int, query: str):
    query = (query or "").strip()
    if not query:
        logging.info("API playback: empty query")
        return

    guild = bot.get_guild(guild_id)
    if guild is None:
        logging.info("API playback: guild not found (%s)", guild_id)
        return

    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            logging.info("API playback: member not found (%s)", user_id)
            return

    if not member.voice or not member.voice.channel:
        logging.info("API playback: member not in voice channel (%s)", user_id)
        return

    user_channel = member.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=guild)

    if voice_client and voice_client.is_connected():
        if voice_client.channel != user_channel:
            await voice_client.move_to(user_channel)
    else:
        voice_client = await user_channel.connect()

    loop = bot.loop or asyncio.get_running_loop()
    try:
        song = await loop.run_in_executor(None, lambda: get_stream_url_by_query(query))
    except VideoTooLongError as e:
        logging.info("API playback: %s", e)
        return
    except Exception as e:
        logging.info("API playback: song lookup failed: %s", e)
        return

    queue = guild_music_queues.setdefault(guild_id, [])
    queue.insert(0, song)

    is_playing_now = voice_client.is_playing() or voice_client.is_paused()
    if not is_playing_now:
        await _play_next_for_guild(bot, guild, user_id)
    else:
        logging.info("API playback: queued %s", song["title"])


async def _play_next_for_guild(bot, guild, user_id):
    queue = guild_music_queues.get(guild.id, [])
    if not queue:
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=guild)
    if not voice_client or not voice_client.is_connected():
        return

    song = queue.pop(0)
    currently_playing[guild.id] = song
    asyncio.create_task(send_play_history(song, user_id))

    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['source'], **FFMPEG_OPTIONS))

    def after_playing(error):
        if error:
            logging.info(f"에러 발생: {error}")

        async def play_or_disconnect():
            next_voice_client = discord.utils.get(bot.voice_clients, guild=guild)
            if not next_voice_client or not next_voice_client.is_connected():
                return

            if guild_music_queues.get(guild.id, []):
                await _play_next_for_guild(bot, guild, user_id)
                return

            await next_voice_client.disconnect()

        asyncio.run_coroutine_threadsafe(play_or_disconnect(), bot.loop)


def get_stream_url_by_query(query, is_url=False):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        if is_url:
            info = ydl.extract_info(query, download=False)
        else:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)

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

async def get_info_async(ctx, query, is_url=False):
    loop = ctx.bot.loop
    return await loop.run_in_executor(None, lambda: get_stream_url_by_query(query, is_url))


async def send_play_history(song, discord_id):
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
                    logging.info(f"API 전송 성공: {song['title']}")
                else:
                    logging.info(f"API 전송 실패: {response.status}")
    except Exception as e:
        logging.info(f"API 요청 중 예외 발생: {e}")


async def play_music(ctx, refresh):
    queue = guild_music_queues.get(ctx.guild.id, [])
    if not queue:
        await ctx.send("❌ 빈 대기열입니다. 재생을 종료합니다.")
        return

    voice_client = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)
    if not voice_client or not voice_client.is_connected():
        channel = ctx.author.voice.channel
        voice_client = await channel.connect()

    song = guild_music_queues[ctx.guild.id].pop(0)

    if refresh:
        try:
            webUrl=f"https://www.youtube.com/watch?v={song['video_id']}"
            song = await get_info_async(ctx, webUrl, is_url=True)
        except Exception as e:
            logging.info(f"예외 발생: {e}")

    currently_playing[ctx.guild.id] = song
    asyncio.create_task(send_play_history(song, ctx.author.id))
    source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(song['source'], **FFMPEG_OPTIONS))

    def after_playing(error):
        if error:
            logging.info(f"에러 발생: {error}")
        voice_client = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)

        queue = guild_music_queues.get(ctx.guild.id, [])
        if not queue:
            fut = asyncio.run_coroutine_threadsafe(voice_client.disconnect(), ctx.bot.loop)
            try:
                fut.result()
            except Exception as e:
                logging.info(f"disconnect 중 예외 발생: {e}")

            fut = asyncio.run_coroutine_threadsafe(
                ctx.send("❌ 빈 대기열입니다. 재생을 종료합니다."), ctx.bot.loop)
            try:
                fut.result()
            except Exception as e:
                logging.info(f"ctx.send 중 예외 발생: {e}")

            return

        fut = asyncio.run_coroutine_threadsafe(play_music(ctx, True), ctx.bot.loop)
        try:
            fut.result()
        except Exception as e:
            logging.info(e)

    voice_client.play(source, after=after_playing)
    await ctx.send(f"🎶 재생중: **{song['title']}**")


def register_music_commands(bot: commands.Bot):
    @bot.command()
    async def play(ctx, *, arg=None):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("⛔ 음성 채널에서 호출해주세요.")
            return

        if arg is None:
            await play_music(ctx, True)
            return

        args = arg.split()

        is_add = False
        is_link = False

        if "--add" in args:
            is_add = True
            args.remove("--add")

        arg = " ".join(args)
        if "https://" in arg:
            is_link = True

        if is_link:
            song = await get_info_async(ctx, arg, is_link)
        else:
            song = await get_info_async(ctx, arg)

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
        await play_music(ctx, False)

    @bot.command()
    async def skip(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_playing():
            await ctx.send("⏭️ 다음 곡을 재생합니다.")
            voice_client.stop()

    @bot.command()
    async def stop(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
        current_song = currently_playing.get(ctx.guild.id)
        guild_music_queues.setdefault(ctx.guild.id, []).insert(0, current_song)

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
        await play_music(ctx, True)

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
