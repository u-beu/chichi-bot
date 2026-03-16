import asyncio
import pytest

from unittest.mock import AsyncMock, MagicMock, patch
from discord.ext import commands

from bot.music import music_queue, play_music, register_music_commands


@pytest.mark.asyncio
async def test_play_command_user_not_in_voice():
    bot = commands.Bot(command_prefix="!", intents=None, help_command=None)
    register_music_commands(bot)
    play_cmd = bot.get_command("play")

    mock_ctx = MagicMock()
    mock_ctx.author.voice = None
    mock_ctx.send = AsyncMock()

    await play_cmd.callback(mock_ctx, arg="test song")

    mock_ctx.send.assert_called_once_with("⛔ 음성 채널에서 호출해주세요.")


@pytest.mark.asyncio
async def test_play_command_check_link():
    bot = commands.Bot(command_prefix="!", intents=None, help_command=None)
    register_music_commands(bot)
    play_cmd = bot.get_command("play")

    mock_ctx = MagicMock()
    mock_ctx.author.voice = MagicMock(channel=MagicMock())
    mock_ctx.send = AsyncMock()
    mock_ctx.bot = bot

    with patch("bot.music.get_info_async", new_callable=AsyncMock) as mock_get_info, \
            patch("bot.music.play_music") as mock_play_music:
        mock_get_info.return_value = {"source": "test-source",
                                      "title": "test-title",
                                      "video_id": "test-videoId"}
        await play_cmd.callback(mock_ctx, arg="https://youtu.be/test")

        mock_get_info.assert_called_once_with(mock_ctx, "https://youtu.be/test", is_url=True)
        mock_play_music.assert_called_once_with(mock_ctx, False)


@pytest.mark.asyncio
async def test_play_command_check_add():
    bot = commands.Bot(command_prefix="!", intents=None, help_command=None)
    register_music_commands(bot)
    play_cmd = bot.get_command("play")

    mock_ctx = MagicMock()
    mock_ctx.author.voice = MagicMock(channel=MagicMock())
    mock_ctx.send = AsyncMock()

    mock_ctx.bot = MagicMock()
    mock_ctx.bot.loop = asyncio.get_event_loop()

    mock_ctx.guild.id = 1

    mock_voice_client = MagicMock()
    mock_voice_client.is_playing.return_value = True
    mock_voice_client.is_connected.return_value = True

    with patch("bot.music.get_info_async", new_callable=AsyncMock) as mock_get_info, \
            patch("bot.music.play_music") as mock_play_music, \
            patch("discord.utils.get", return_value=mock_voice_client), \
            patch("bot.music.music_queue", {}) as mock_music_queue:
        mock_get_info.return_value = {"source": "test-source",
                                      "title": "test-title",
                                      "video_id": "test-videoId"}

        await play_cmd.callback(mock_ctx, arg="--add test_song")

        assert len(mock_music_queue[mock_ctx.guild.id]) == 1
        assert mock_music_queue[mock_ctx.guild.id][0]["title"] == "test-title"

        mock_play_music.assert_not_called()
        mock_ctx.send.assert_called_once_with("✅ 대기열 추가: **test-title**")


@pytest.mark.asyncio
async def test_after_playing():
    mock_ctx = MagicMock()
    mock_ctx.guild.id = 1
    mock_ctx.author.id = 2
    mock_ctx.author.voice.channel = MagicMock()
    mock_ctx.send = AsyncMock()

    mock_ctx.bot = MagicMock()
    mock_ctx.bot.loop = asyncio.get_event_loop()
    mock_ctx.bot.voice_clients = []

    music_queue[mock_ctx.guild.id] = [
        {"title": "test-title1", "source": "test_source_url1", "video_id": "test-videoId1"},
        {"title": "test-title2", "source": "test_source_url2", "video_id": "test-videoId2"}
    ]

    mock_voice_client = MagicMock()
    mock_voice_client.is_connected.return_value = True

    with patch("discord.utils.get", return_value=mock_voice_client), \
            patch("bot.music.get_info_async", new_callable=AsyncMock), \
            patch("bot.music.send_play_history", new_callable=AsyncMock), \
            patch("discord.FFmpegPCMAudio") as mock_ffmpeg, \
            patch("discord.PCMVolumeTransformer"), \
            patch("asyncio.run_coroutine_threadsafe", new_callable=AsyncMock) as mock_threadsafe:
        mock_future = MagicMock()
        mock_threadsafe.return_value = mock_future

        mock_ffmpeg.return_value = MagicMock()

        await play_music(mock_ctx, refresh=False)
        assert len(music_queue[mock_ctx.guild.id]) == 1

        _, kwargs = mock_voice_client.play.call_args
        after_callback = kwargs.get('after')
        after_callback(None)

        assert mock_threadsafe.called

        await play_music(mock_ctx, refresh=True)
        assert len(music_queue[mock_ctx.guild.id]) == 0


@pytest.mark.asyncio
async def test_send_play_history():
    song = {
        "title": "test-title",
        "uploader": "test-uploader",
        "image": "https://test/image.jpg",
        "video_id": "test-videoId"
    }
    discord_id = "123456789"
    mock_response = AsyncMock()
    mock_response.status = 200

    mock_session = AsyncMock()
    mock_session.post.return_value.__aenter__.return_value = mock_response
    mock_session.__aenter__.return_value = mock_session
    with patch("aiohttp.ClientSession", return_value=mock_session):
        from bot.music import send_play_history
        await send_play_history(song, discord_id)

        assert mock_session.post.called
        mock_session.post.assert_called_once()

        args, kwargs = mock_session.post.call_args
        assert args[0] == "https://ub-chichi.site/api/bot/recent-played-song"
        assert kwargs["json"]["title"] == "test-title"
        assert kwargs["json"]["uploader"] == "test-uploader"
        assert kwargs["json"]["image"] == "https://test/image.jpg"
        assert kwargs["json"]["videoId"] == "test-videoId"
        assert kwargs["json"]["discordId"] == int(discord_id)