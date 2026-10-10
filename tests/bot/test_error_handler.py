import pytest
from unittest.mock import AsyncMock, MagicMock

from discord.ext import commands
from discord.ext.commands import CommandNotFound

from bot.error_handler import setup_error_handlers
from bot.music import VideoTooLongError


def _get_handler():
    bot = MagicMock()
    captured = {}

    def fake_event(func):
        captured["on_command_error"] = func
        return func

    bot.event = fake_event
    setup_error_handlers(bot)
    return captured["on_command_error"]


class TestOnCommandError:
    @pytest.mark.asyncio
    async def test_command_not_found_sends_guidance_message(self):
        """[목적] CommandNotFound 에러 발생 시 안내 메시지를 전송하는지 검증

        [검증]
        1. "❓ 명령어를 찾을 수 없습니다." 메시지가 전송됨
        """
        handler = _get_handler()
        ctx = MagicMock()
        ctx.send = AsyncMock()

        await handler(ctx, CommandNotFound())

        ctx.send.assert_called_once_with("❓ 명령어를 찾을 수 없습니다.")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "original_error, expected_message",
        [
            (VideoTooLongError(7500, 7200), "❌ 해당 영상(125분)은 너무 깁니다."),
            (ValueError("boom"), "⚠️ 오류가 발생했습니다."),
        ],
        ids=["video_too_long_sends_duration_message", "other_error_sends_generic_message"],
    )
    async def test_command_invoke_error_branches_by_original_exception(self, original_error, expected_message):
        """[목적] CommandInvokeError로 감싸진 원본 예외 타입에 따라 메시지가 분기되는지 검증

        [검증]
        1. 원본 예외가 VideoTooLongError이면 영상 길이(분)를 포함한 안내 메시지가 전송됨
        2. 원본 예외가 그 외 예외이면 일반 오류 메시지가 전송됨
        """
        handler = _get_handler()
        ctx = MagicMock()
        ctx.send = AsyncMock()

        error = commands.CommandInvokeError(original_error)

        await handler(ctx, error)

        ctx.send.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_unrelated_exception_sends_generic_message(self):
        """[목적] CommandInvokeError가 아닌 예외도 일반 오류 메시지로 처리되는지 검증

        [검증]
        1. "⚠️ 오류가 발생했습니다." 메시지가 전송됨
        """
        handler = _get_handler()
        ctx = MagicMock()
        ctx.send = AsyncMock()

        await handler(ctx, RuntimeError("boom"))

        ctx.send.assert_called_once_with("⚠️ 오류가 발생했습니다.")
