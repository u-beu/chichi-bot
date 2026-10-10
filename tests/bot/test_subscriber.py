import asyncio
import json

import pytest
import redis
from unittest.mock import AsyncMock, MagicMock, patch

import bot.subscriber as subscriber_module
from bot.subscriber import _process_command, _subscriber_loop, start_subscriber


@pytest.fixture(autouse=True)
def reset_subscriber_task():
    subscriber_module._subscriber_task = None
    yield
    subscriber_module._subscriber_task = None


class TestProcessCommand:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload_dict, expected_args",
        [
            ({"action": "playback", "guild_id": "1", "user_id": "2", "query": "song"}, (1, 2, "song")),
            ({"action": "playback", "guild_id": "1", "user_id": "2"}, (1, 2, "")),
        ],
        ids=["valid_payload_with_query", "valid_payload_defaults_query_to_empty_string"],
    )
    async def test_valid_playback_action_calls_handle_api_playback(self, payload_dict, expected_args):
        """[목적] 정상적인 playback action JSON을 받으면 handle_api_playback을 호출하는지 검증

        [검증]
        1. query 필드가 있으면 그 값 그대로 handle_api_playback이 호출됨
        2. query 필드가 없으면 빈 문자열로 기본값 처리되어 호출됨
        """
        bot = MagicMock()
        payload = json.dumps(payload_dict)

        with patch("bot.subscriber.handle_api_playback", new_callable=AsyncMock) as mock_handle:
            await _process_command(bot, payload)

        mock_handle.assert_called_once_with(bot, *expected_args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            "not-json",
            json.dumps({"action": "unknown"}),
            json.dumps({"action": "playback", "guild_id": "1"}),
            json.dumps({"action": "playback", "guild_id": "not-a-number", "user_id": "2"}),
        ],
        ids=["invalid_json", "unregistered_action", "missing_user_id", "invalid_guild_id_type"],
    )
    async def test_invalid_or_unregistered_payload_is_ignored(self, payload):
        """[목적] JSON 파싱 실패/미등록 action/필수 필드 누락/타입 오류 payload가 모두 무시되는지 검증

        [검증]
        1. 어떤 케이스든 handle_api_playback이 호출되지 않음
        """
        bot = MagicMock()

        with patch("bot.subscriber.handle_api_playback", new_callable=AsyncMock) as mock_handle:
            await _process_command(bot, payload)

        mock_handle.assert_not_called()


class TestSubscriberLoop:
    @pytest.mark.asyncio
    async def test_processes_message_then_stops(self):
        """[목적] brpop으로 받은 메시지를 _process_command로 전달하는지 검증

        [검증]
        1. CancelledError 발생 시 예외가 그대로 전파됨
        2. _process_command가 수신한 payload로 호출됨
        """
        bot = MagicMock()
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[("bot:commands", "payload"), asyncio.CancelledError()])

        with patch("bot.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("bot.subscriber._process_command", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        mock_process.assert_called_once_with(bot, "payload")

    @pytest.mark.asyncio
    async def test_skips_empty_result(self):
        """[목적] brpop 결과가 없을 때(None) 메시지 처리를 건너뛰는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. _process_command가 호출되지 않음
        """
        bot = MagicMock()
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[None, asyncio.CancelledError()])

        with patch("bot.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("bot.subscriber._process_command", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_redis_error(self):
        """[목적] RedisError 발생 시 3초 대기 후 루프를 계속하는지 검증

        [검증]
        1. asyncio.sleep(3)이 호출됨
        2. 이후 CancelledError로 루프가 종료됨
        """
        bot = MagicMock()
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[redis.RedisError("boom"), asyncio.CancelledError()])

        with patch("bot.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("bot.subscriber.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        mock_sleep.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_swallows_generic_exception_and_continues(self):
        """[목적] 일반 예외가 발생해도 루프가 중단되지 않고 계속되는지 검증

        [검증]
        1. 예외가 전파되지 않고 다음 반복(CancelledError)까지 루프가 유지됨
        """
        bot = MagicMock()
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[Exception("boom"), asyncio.CancelledError()])

        with patch("bot.subscriber.redis_asyncio.from_url", return_value=fake_client):
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)


class TestStartSubscriber:
    @staticmethod
    def _closing_create_task(return_value):
        def _create_task(coro):
            coro.close()
            return return_value

        return _create_task

    def test_creates_task_when_none_exists(self):
        """[목적] 기존 구독 태스크가 없을 때 새 태스크를 생성하는지 검증

        [검증]
        1. bot.loop.create_task가 호출됨
        2. 모듈의 _subscriber_task가 생성된 태스크로 갱신됨
        """
        bot = MagicMock()
        created_task = MagicMock()
        bot.loop.create_task = MagicMock(side_effect=self._closing_create_task(created_task))

        start_subscriber(bot)

        bot.loop.create_task.assert_called_once()
        assert subscriber_module._subscriber_task is created_task

    def test_skips_when_task_running(self):
        """[목적] 이미 실행 중인 구독 태스크가 있으면 중복 생성하지 않는지 검증

        [검증]
        1. bot.loop.create_task가 호출되지 않음
        2. 기존 태스크가 그대로 유지됨
        """
        bot = MagicMock()
        existing_task = MagicMock()
        existing_task.done.return_value = False
        subscriber_module._subscriber_task = existing_task

        start_subscriber(bot)

        bot.loop.create_task.assert_not_called()
        assert subscriber_module._subscriber_task is existing_task

    def test_restarts_when_previous_task_done(self):
        """[목적] 이전 구독 태스크가 완료 상태이면 새 태스크로 재시작하는지 검증

        [검증]
        1. bot.loop.create_task가 호출됨
        2. 모듈의 _subscriber_task가 새 태스크로 갱신됨
        """
        bot = MagicMock()
        done_task = MagicMock()
        done_task.done.return_value = True
        subscriber_module._subscriber_task = done_task

        new_task = MagicMock()
        bot.loop.create_task = MagicMock(side_effect=self._closing_create_task(new_task))

        start_subscriber(bot)

        bot.loop.create_task.assert_called_once()
        assert subscriber_module._subscriber_task is new_task
