import json

import pytest
from unittest.mock import AsyncMock

from bot.music import SPRING_QUEUE_KEY, SPRING_RESULT_QUEUE_KEY, send_play_history, send_playback_failure


class TestSendPlayHistory:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "song, expected_payload",
        [
            (
                {"title": "T", "uploader": "U", "image": "I", "video_id": "V"},
                {"title": "T", "uploader": "U", "image": "I", "videoId": "V", "discordId": 123},
            ),
            (
                {},
                {
                    "title": "Unknown Title",
                    "uploader": "Unknown Uploader",
                    "image": "null",
                    "videoId": None,
                    "discordId": 123,
                },
            ),
        ],
        ids=["all_fields_present", "missing_fields_use_defaults"],
    )
    async def test_builds_camel_case_payload(self, song, expected_payload):
        """[목적] song dict를 Redis LPUSH payload(camelCase)로 변환하는 매핑 규칙을 검증

        [검증]
        1. 모든 필드가 있을 때 title/uploader/image/videoId/discordId로 그대로 매핑됨
        2. 필드가 없을 때 title/uploader/image/videoId에 기본값이 채워짐
        3. 두 경우 모두 lpush가 SPRING_QUEUE_KEY를 키로 호출됨
        """
        redis_client = AsyncMock()

        await send_play_history(song, 123, redis_client)

        redis_client.lpush.assert_called_once()
        key, payload_json = redis_client.lpush.call_args[0]
        assert key == SPRING_QUEUE_KEY
        assert json.loads(payload_json) == expected_payload

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        """[목적] redis_client.lpush에서 예외가 발생해도 호출자에게 전파되지 않는지 검증

        [검증]
        1. 예외 발생 시에도 함수가 정상적으로 반환됨(로깅만 수행)
        """
        redis_client = AsyncMock()
        redis_client.lpush.side_effect = Exception("redis down")

        # 예외가 전파되지 않고 로깅만 되어야 함
        await send_play_history({"title": "T"}, 1, redis_client)


class TestSendPlaybackFailure:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        ["not_in_voice", "video_too_long", "search_failed", "no_permission", "connect_failed", "playback_failed"],
    )
    async def test_builds_status_payload(self, status):
        """[목적] 재생 실패 알림 payload 형식과 발행 키를 status별로 검증

        [검증]
        1. lpush가 SPRING_RESULT_QUEUE_KEY를 키로 호출됨
        2. payload가 discordId와 전달받은 status를 가짐
        """
        redis_client = AsyncMock()

        await send_playback_failure(123, redis_client, status)

        redis_client.lpush.assert_called_once()
        key, payload_json = redis_client.lpush.call_args[0]
        assert key == SPRING_RESULT_QUEUE_KEY
        assert json.loads(payload_json) == {"discordId": 123, "status": status}

    @pytest.mark.asyncio
    async def test_exception_is_swallowed(self):
        """[목적] redis_client.lpush에서 예외가 발생해도 호출자에게 전파되지 않는지 검증

        [검증]
        1. 예외 발생 시에도 함수가 정상적으로 반환됨(로깅만 수행)
        """
        redis_client = AsyncMock()
        redis_client.lpush.side_effect = Exception("redis down")

        await send_playback_failure(1, redis_client, "not_in_voice")
