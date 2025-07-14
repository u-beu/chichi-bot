import yt_dlp
import discord
import asyncio
import logging
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")
PROXY_HOST = os.getenv("PROXY_HOST")
PROXY_PORT = os.getenv("PROXY_PORT")

logging.basicConfig(level=logging.INFO)

MAX_DURATION = 7200
proxy_url=f"http://{PROXY_USERNAME}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"
logging.info(f"proxy url:{proxy_url}")

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'noplaylist': True,
    'extract_audio': True,
    'proxy': proxy_url,
    'cookiefile': '/app/cookies.txt',
    'cacerts': '/app/proxy-ca.crt',
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    }
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -bufsize 512k'
}

music_queue = {}
currently_playing = {}

class VideoTooLongError(Exception):
    def __init__(self, duration, max_duration):
        super().__init__(f"영상 길이({duration}s)는 {max_duration}s(2시간) 미만이어야 합니다.")
        self.duration = duration
        self.max_duration = max_duration

def get_stream_url_by_query(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if 'entries' in info:
            info = info['entries'][0]

        duration = info['duration']
        if duration > MAX_DURATION:
            raise VideoTooLongError(duration, MAX_DURATION)

        return {
            'source': info['url'],
            'title': info['title'],
            'webpage_url': info['webpage_url']
        }


def get_stream_url_by_yt_url(youtube_url):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        if 'entries' in info:
            info = info['entries'][0]

        duration = info['duration']
        if duration > MAX_DURATION:
            raise VideoTooLongError(duration, MAX_DURATION)

        return {
            'source': info['url'],
            'title': info['title'],
            'webpage_url': info['webpage_url']
        }


async def play_music(ctx, refresh):
    if len(music_queue) == 0:
        await ctx.send("❌ 빈 대기열입니다. 재생을 종료합니다.")
        return

    voice_client = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)
    if not voice_client or not voice_client.is_connected():
        channel = ctx.author.voice.channel
        voice_client = await channel.connect()

    song = music_queue[ctx.guild.id].pop(0)
    if not refresh:
        currently_playing[ctx.guild.id] = song
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song['source'], **FFMPEG_OPTIONS))
    else:
        refresh_song = get_stream_url_by_yt_url(song['webpage_url'])
        currently_playing[ctx.guild.id] = refresh_song
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(refresh_song['source'], **FFMPEG_OPTIONS))

    def after_playing(error):
        if error:
            logging.info("에러 발생:", error)
        voice_client = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)

        if len(music_queue[ctx.guild.id]) == 0:
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
            song = get_stream_url_by_yt_url(arg)
        else:
            song = get_stream_url_by_query(arg)

        if not song:
            await ctx.send("❌ 노래 탐색에 실패했습니다.")
            return

        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if is_add:
            music_queue.setdefault(ctx.guild.id, []).append(song)
            await ctx.send(f"✅ 대기열 추가: **{song['title']}**")
            if voice_client and voice_client.is_playing():
                return
            else:
                await ctx.send(f"▶️ 즉시 재생합니다.")
                await play_music(ctx, True)
                return

        if voice_client and voice_client.is_playing():
            current_song = currently_playing.get(ctx.guild.id)
            if current_song:
                music_queue.setdefault(ctx.guild.id, []).insert(0, current_song)
            voice_client.stop()

        music_queue.setdefault(ctx.guild.id, []).insert(0, song)
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
        music_queue.setdefault(ctx.guild.id, []).insert(0, current_song)

        if voice_client:
            await voice_client.disconnect()
            await ctx.send("🛑 노래 재생을 중지합니다.")

    @bot.command()
    async def resume(ctx):
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if voice_client and voice_client.is_playing():
            await ctx.send("🎶 이미 노래를 재생 중입니다.")
            return

        if not music_queue.get(ctx.guild.id) or len(music_queue) == 0:
            await ctx.send("❌ 빈 대기열입니다.")
            return

        await ctx.send("✅ 다시 재생합니다.")
        await play_music(ctx, True)

    @bot.command()
    async def queue(ctx):
        queue_list = music_queue.get(ctx.guild.id, [])

        if not queue_list:
            await ctx.send("빈 대기열")
            return

        queue_message = "**🗒️대기열 목록:**\n"
        for idx, song in enumerate(queue_list[:10], start=1):
            queue_message += f"{idx}. {song['title']}\n"

        if len(queue_list) > 10:
            queue_message += f"...외 {len(queue_list) - 10}곡 더 있음"

        await ctx.send(queue_message)

    @bot.command()
    async def clear(ctx):
        queue_list = music_queue.get(ctx.guild.id, [])
        queue_list.clear()
        await ctx.send("▶️ 대기열 목록 초기화")

    @bot.command(name="help")
    async def custom_help(ctx):
        await ctx.send("[명령어 도움말]\n\n")
        await ctx.send("🔵 **!play** <검색어/유튜브 링크> : 요청한 노래를 즉시 재생합니다.\n(재생 중이던 노래가 있을 경우 다시 대기열에 넣습니다.)\n\n" +
                       "🔵 **!play --add** <검색어/유튜브 링크> : 요청한 노래를 대기열 리스트에 추가합니다.\n(현재 재생 중인 노래를 유지합니다.)\n\n" +
                       "🟡 **!skip** : 대기열 리스트에서 다음 곡을 재생합니다.\n\n" +
                       "🔴 **!stop** : 현재 재생중인 노래를 중단합니다.\n(대기열 리스트는 중단한 노래를 포함해 유지됩니다.)\n\n" +
                       "🟢 **!resume** : 대기열 리스트를 기준으로 노래를 다시 재생합니다.\n\n" +
                       "🟣 **!queue** : 대기열 리스트를 확인합니다.\n\n" +
                       "🟣 **!clear** : 대기열 리스트를 초기화합니다.(리스트의 노래를 모두 삭제합니다.)\n\n")
