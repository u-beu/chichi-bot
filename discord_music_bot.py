import asyncio
import logging
import os
import discord
import yt_dlp
from discord.ext import commands
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

music_queue = {}
currently_playing = {}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'default_search': 'ytsearch',
    'noplaylist': True,
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -bufsize 512k'
}

@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Game(name="명령어 도움 !help")
    )
    logging.info(f"봇 준비 완료: {bot.user}")

def get_stream_url_by_query(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if 'entries' in info:
            info = info['entries'][0]
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
        return {
            'source': info['url'],
            'title': info['title'],
            'webpage_url': info['webpage_url']
        }

async def play_music(ctx, refresh):
    if len(music_queue) == 0:
        await ctx.send("❌ 빈 대기열입니다. 재생을 종료합니다.")
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not voice_client or not voice_client.is_connected():
        channel = ctx.author.voice.channel
        voice_client = await channel.connect()
    else:
        await ctx.send("❌ 음성 채널에서 호출해주세요.")

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
        voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)

        if len(music_queue[ctx.guild.id]) == 0:
            fut = asyncio.run_coroutine_threadsafe(voice_client.disconnect(), bot.loop)
            try:
                fut.result()
            except Exception as e:
                logging.info(f"disconnect 중 예외 발생: {e}")

            fut = asyncio.run_coroutine_threadsafe(
                ctx.send("❌ 빈 대기열입니다. 재생을 종료합니다."), bot.loop)
            try:
                fut.result()
            except Exception as e:
                logging.info(f"ctx.send 중 예외 발생: {e}")
            return

        fut = asyncio.run_coroutine_threadsafe(play_music(ctx, True), bot.loop)
        try:
            fut.result()
        except Exception as e:
            logging.info(e)

    voice_client.play(source, after=after_playing)
    await ctx.send(f"🎶 재생중: **{song['title']}**")

@bot.command()
async def play(ctx, *, arg):
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
            await play_music(ctx, is_add)
            return

    if voice_client and voice_client.is_playing():
        current_song = currently_playing.get(ctx.guild.id)
        if current_song:
            music_queue.setdefault(ctx.guild.id, []).insert(0, current_song)
        voice_client.stop()

    music_queue.setdefault(ctx.guild.id, []).insert(0, song)
    await ctx.send(f"▶️ 즉시 재생합니다.")
    await play_music(ctx, is_add)

@bot.command()
async def skip(ctx):
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("⏭️ 다음 곡을 재생합니다.")

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

    if len(music_queue) == 0:
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
    await ctx.send("🔵 **!play** <검색어/유튜브 링크> : 요청한 노래를 즉시 재생합니다.(재생 중이던 노래가 있을 경우 다시 대기열에 넣습니다.)\n\n" +
                   "🔵 **!play --add** <검색어/유튜브 링크> : 요청한 노래를 대기열 리스트에 추가합니다.(현재 재생 중인 노래를 유지합니다.)\n\n" +
                   "🟡 **!skip** : 대기열 리스트에서 다음 곡을 재생합니다.\n\n" +
                   "🔴 **!stop** : 현재 재생중인 노래를 중단합니다.(대기열 리스트는 중단한 노래를 포함해 유지됩니다.)\n\n" +
                   "🟢 **!resume** : 대기열 리스트를 기준으로 노래를 다시 재생합니다.\n\n" +
                   "🟣 **!queue** : 대기열 리스트를 확인합니다.\n\n" +
                   "🟣 **!clear** : 대기열 리스트를 초기화합니다.(=노래를 모두 삭제합니다.)\n\n")

bot.run(TOKEN)
