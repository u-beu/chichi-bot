from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from bot.music import register_music_commands


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

    with patch("bot.music.get_stream_url_by_yt_url") as mock_link, \
            patch("bot.music.play_music") as mock_play_music:
        await play_cmd.callback(mock_ctx, arg="https://youtu.be/test")

        mock_link.assert_called_once_with("https://youtu.be/test")
        mock_play_music.assert_called_once_with(mock_ctx, False)


@pytest.mark.asyncio
async def test_play_command_check_add():
    bot = commands.Bot(command_prefix="!", intents=None, help_command=None)
    register_music_commands(bot)
    play_cmd = bot.get_command("play")

    mock_ctx = MagicMock()
    mock_ctx.author.voice = MagicMock(channel=MagicMock())
    mock_ctx.send = AsyncMock()

    mock_voice_client = MagicMock()
    mock_voice_client.is_playing.return_value = True

    with patch("bot.music.get_stream_url_by_query", return_value={'title':'Test Song'}) as mock_query, \
            patch("bot.music.play_music", new=AsyncMock()) as mock_play_music, \
            patch("discord.utils.get", return_value=mock_voice_client):

        await play_cmd.callback(mock_ctx, arg="--add test_song")

        mock_query.assert_called_once_with("test_song")
        mock_play_music.assert_not_called()

    mock_ctx.send.assert_called_once_with("✅ 대기열 추가: **Test Song**")