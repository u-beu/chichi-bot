import asyncio

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_ydl():
    """yt_dlp.YoutubeDL을 패치하고 extract_info 결과를 제어할 수 있는 인스턴스를 제공."""
    with patch("yt_dlp.YoutubeDL") as mock_ydl_class:
        ydl_instance = MagicMock()
        mock_ydl_class.return_value.__enter__.return_value = ydl_instance
        yield ydl_instance


@pytest.fixture
def make_permissions():
    """음성 채널 권한(connect/speak) 목 객체 팩토리."""
    def _make(connect=True, speak=True):
        perms = MagicMock()
        perms.connect = connect
        perms.speak = speak
        return perms
    return _make


@pytest.fixture
def member_in_voice_channel(make_permissions):
    """guild/member/voice_channel 묶음을 생성하는 팩토리. play_music/handle_api_playback 등에서 공통 사용."""
    def _make(guild_id=1, member_id=1, connect=True, speak=True):
        channel = MagicMock()
        channel.permissions_for.return_value = make_permissions(connect=connect, speak=speak)
        channel.send = AsyncMock()
        channel.connect = AsyncMock()

        member = MagicMock(id=member_id)
        member.voice.channel = channel

        guild = MagicMock(id=guild_id)
        return guild, member, channel
    return _make


@pytest.fixture
def voice_client_factory():
    """VoiceClient 목 객체 팩토리. is_playing/is_connected 등 상태를 제어."""
    def _make(is_playing=False, is_connected=True, channel=None):
        voice_client = MagicMock()
        voice_client.is_playing.return_value = is_playing
        voice_client.is_connected.return_value = is_connected
        voice_client.channel = channel
        voice_client.disconnect = AsyncMock()
        voice_client.move_to = AsyncMock()
        return voice_client
    return _make


@pytest_asyncio.fixture
async def mock_bot():
    """redis_client와 실행 중인 이벤트 루프를 가진 Bot 목.

    bot.loop은 반드시 테스트가 실제로 실행 중인 이벤트 루프를 참조해야 하므로
    (run_in_executor 등에서 사용), 비동기 fixture에서 get_running_loop()으로 가져온다.
    """
    bot = MagicMock()
    bot.loop = asyncio.get_running_loop()
    bot.redis_client = MagicMock()
    return bot


@pytest.fixture
def mock_ctx():
    """음성 채널에 있는 호출자를 가진 discord Context 목."""
    ctx = MagicMock()
    ctx.send = AsyncMock()
    ctx.author.voice.channel = MagicMock()
    ctx.guild.id = 1
    return ctx
