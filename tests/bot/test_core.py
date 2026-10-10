import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.core import ChichiBot


def _make_bot():
    intents = discord.Intents.default()
    return ChichiBot(command_prefix="!", intents=intents, help_command=None)


@pytest.mark.asyncio
async def test_setup_hook_creates_redis_client_and_adds_cog():
    """[목적] setup_hook 호출 시 redis_client를 생성하고 MusicCog를 등록하는지 검증

    [검증]
    1. redis_asyncio.from_url이 decode_responses=True로 호출됨
    2. bot.redis_client가 생성된 클라이언트로 설정됨
    3. add_cog가 호출되고 등록된 cog의 bot 참조가 올바름
    """
    bot = _make_bot()
    fake_redis_client = MagicMock()

    with patch("bot.core.redis_asyncio.from_url", return_value=fake_redis_client) as mock_from_url, \
            patch.object(bot, "add_cog", new_callable=AsyncMock) as mock_add_cog:
        await bot.setup_hook()

    mock_from_url.assert_called_once()
    _, kwargs = mock_from_url.call_args
    assert kwargs == {"decode_responses": True}
    assert bot.redis_client is fake_redis_client

    mock_add_cog.assert_called_once()
    added_cog = mock_add_cog.call_args[0][0]
    assert added_cog.bot is bot


@pytest.mark.asyncio
async def test_close_closes_redis_client_when_present():
    """[목적] redis_client가 설정되어 있을 때 close 호출 시 aclose가 실행되는지 검증

    [검증]
    1. redis_client.aclose가 호출됨
    2. 부모 클래스의 close가 호출됨
    """
    bot = _make_bot()
    fake_redis_client = AsyncMock()
    bot.redis_client = fake_redis_client

    with patch.object(commands.Bot, "close", new_callable=AsyncMock) as mock_super_close:
        await bot.close()

    fake_redis_client.aclose.assert_called_once()
    mock_super_close.assert_called_once()


@pytest.mark.asyncio
async def test_close_skips_redis_when_not_set():
    """[목적] redis_client가 없을 때 close 호출 시 aclose 호출 없이 부모 close만 실행되는지 검증

    [검증]
    1. 부모 클래스의 close가 호출됨
    """
    bot = _make_bot()
    assert bot.redis_client is None

    with patch.object(commands.Bot, "close", new_callable=AsyncMock) as mock_super_close:
        await bot.close()

    mock_super_close.assert_called_once()
