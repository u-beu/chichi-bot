import asyncio
import json

import pytest
import redis
from unittest.mock import AsyncMock, MagicMock, patch

import bot.subscriber as subscriber_module
from bot.subscriber import (
    BOT_PROCESSING_KEY,
    BOT_QUEUE_KEY,
    _process_command,
    _subscriber_loop,
    start_subscriber,
    stop_subscriber,
)


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
            ({"action": "playback", "discordId": "2", "query": "song"}, (2, "song")),
            ({"action": "playback", "discordId": "2"}, (2, "")),
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

        with patch("bot.subscriber.handle_api_playback", new_callable=AsyncMock, return_value=None) as mock_handle:
            await _process_command(bot, payload)

        mock_handle.assert_called_once_with(bot, *expected_args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status, expect_failure_sent",
        [("not_in_voice", True), ("search_failed", True), (None, False)],
        ids=["not_in_voice_sends_failure", "search_failed_sends_failure", "handled_sends_nothing"],
    )
    async def test_failure_notification_depends_on_handle_result(self, status, expect_failure_sent):
        """[목적] handle_api_playback이 반환한 실패 status에 따라 실패 알림 발행 여부가 달라지는지 검증

        [검증]
        1. status 문자열이 반환되면 discord_id, bot.redis_client, 해당 status로 send_playback_failure가 호출됨
        2. None(처리됨)이면 send_playback_failure가 호출되지 않음
        """
        bot = MagicMock()
        payload = json.dumps({"action": "playback", "discordId": "2", "query": "song"})

        with patch("bot.subscriber.handle_api_playback", new_callable=AsyncMock, return_value=status), \
                patch("bot.subscriber.send_playback_failure", new_callable=AsyncMock) as mock_failure:
            await _process_command(bot, payload)

        if expect_failure_sent:
            mock_failure.assert_called_once_with(2, bot.redis_client, status)
        else:
            mock_failure.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            "not-json",
            json.dumps({"action": "unknown"}),
            json.dumps({"action": "playback"}),
            json.dumps({"action": "playback", "discordId": "not-a-number"}),
        ],
        ids=["invalid_json", "unregistered_action", "missing_discord_id", "invalid_discord_id_type"],
    )
    async def test_invalid_or_unregistered_payload_is_ignored(self, payload):
        """[목적] JSON 파싱 실패/미등록 action/필수 필드 누락/타입 오류 payload가 모두 무시되는지 검증

        [검증]
        1. 어떤 케이스든 handle_api_playback과 send_playback_failure가 호출되지 않음
        """
        bot = MagicMock()

        with patch("bot.subscriber.handle_api_playback", new_callable=AsyncMock) as mock_handle, \
                patch("bot.subscriber.send_playback_failure", new_callable=AsyncMock) as mock_failure:
            await _process_command(bot, payload)

        mock_handle.assert_not_called()
        mock_failure.assert_not_called()


def _make_client(**overrides):
    """복구할 processing 요청이 없는 기본 Redis client mock."""
    client = MagicMock()
    client.lmove = AsyncMock(return_value=None)
    client.lrem = AsyncMock()
    for name, value in overrides.items():
        setattr(client, name, value)
    return client


class TestSubscriberLoop:
    @pytest.mark.asyncio
    async def test_processes_message_then_stops(self):
        """[목적] blmove로 받은 메시지를 _process_command로 전달하고 처리 후 processing에서 제거하는지 검증

        [검증]
        1. CancelledError 발생 시 예외가 그대로 전파됨
        2. blmove가 요청 큐 -> processing 리스트로 호출됨
        3. _process_command가 수신한 payload로 호출됨
        4. 처리 후 lrem으로 processing에서 제거됨
        """
        bot = MagicMock()
        fake_client = _make_client(blmove=AsyncMock(side_effect=["payload", asyncio.CancelledError()]))
        bot.redis_client = fake_client

        with patch("bot.subscriber._process_command", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        fake_client.blmove.assert_called_with(BOT_QUEUE_KEY, BOT_PROCESSING_KEY, 0, "RIGHT", "LEFT")
        mock_process.assert_called_once_with(bot, "payload")
        fake_client.lrem.assert_called_once_with(BOT_PROCESSING_KEY, 1, "payload")

    @pytest.mark.asyncio
    async def test_skips_empty_result(self):
        """[목적] blmove 결과가 없을 때(None) 메시지 처리를 건너뛰는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. _process_command와 lrem이 호출되지 않음
        """
        bot = MagicMock()
        fake_client = _make_client(blmove=AsyncMock(side_effect=[None, asyncio.CancelledError()]))
        bot.redis_client = fake_client

        with patch("bot.subscriber._process_command", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        mock_process.assert_not_called()
        fake_client.lrem.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_redis_error(self):
        """[목적] RedisError 발생 시 3초 대기 후 루프를 계속하는지 검증

        [검증]
        1. asyncio.sleep(3)이 호출됨
        2. 이후 CancelledError로 루프가 종료됨
        """
        bot = MagicMock()
        fake_client = _make_client(blmove=AsyncMock(side_effect=[redis.RedisError("boom"), asyncio.CancelledError()]))
        bot.redis_client = fake_client

        with patch("bot.subscriber.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
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
        fake_client = _make_client(blmove=AsyncMock(side_effect=[Exception("boom"), asyncio.CancelledError()]))
        bot.redis_client = fake_client

        with pytest.raises(asyncio.CancelledError):
            await _subscriber_loop(bot)

    @pytest.mark.asyncio
    async def test_command_failure_still_removes_from_processing(self):
        """[목적] 명령 처리 중 일반 예외가 나도 processing에서 제거되어 재시작마다 재처리되지 않는지 검증

        [검증]
        1. 예외가 전파되지 않고 lrem이 호출됨
        """
        bot = MagicMock()
        fake_client = _make_client(blmove=AsyncMock(side_effect=["payload", asyncio.CancelledError()]))
        bot.redis_client = fake_client

        with patch("bot.subscriber._process_command", new_callable=AsyncMock, side_effect=Exception("boom")):
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        fake_client.lrem.assert_called_once_with(BOT_PROCESSING_KEY, 1, "payload")

    @pytest.mark.asyncio
    async def test_cancel_during_processing_keeps_in_processing(self):
        """[목적] 처리 중 취소(종료)되면 processing에 남겨 다음 기동 때 복구되도록 하는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. lrem이 호출되지 않음
        """
        bot = MagicMock()
        fake_client = _make_client(blmove=AsyncMock(return_value="payload"))
        bot.redis_client = fake_client

        with patch("bot.subscriber._process_command", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await _subscriber_loop(bot)

        fake_client.lrem.assert_not_called()

    @pytest.mark.asyncio
    async def test_requeues_unfinished_requests_on_start(self):
        """[목적] 시작 시 processing에 남은 요청을 모두 원래 큐로 되돌린 뒤 소비를 시작하는지 검증

        [검증]
        1. lmove가 processing -> 요청 큐로 비어 있을 때까지 반복 호출됨
        2. 복구 후 blmove 소비 루프가 시작됨
        """
        bot = MagicMock()
        fake_client = _make_client(
            lmove=AsyncMock(side_effect=["a", "b", None]),
            blmove=AsyncMock(side_effect=asyncio.CancelledError()),
        )
        bot.redis_client = fake_client

        with pytest.raises(asyncio.CancelledError):
            await _subscriber_loop(bot)

        assert fake_client.lmove.call_count == 3
        fake_client.lmove.assert_called_with(BOT_PROCESSING_KEY, BOT_QUEUE_KEY, "LEFT", "RIGHT")
        fake_client.blmove.assert_called_once()

    @pytest.mark.asyncio
    async def test_requeue_redis_error_does_not_stop_loop(self):
        """[목적] 복구 중 RedisError가 나도 소비 루프는 계속 시작되는지 검증

        [검증]
        1. 예외가 전파되지 않고 blmove 루프에 진입함
        """
        bot = MagicMock()
        fake_client = _make_client(
            lmove=AsyncMock(side_effect=redis.RedisError("boom")),
            blmove=AsyncMock(side_effect=asyncio.CancelledError()),
        )
        bot.redis_client = fake_client

        with pytest.raises(asyncio.CancelledError):
            await _subscriber_loop(bot)

        fake_client.blmove.assert_called_once()


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


class TestStopSubscriber:
    @pytest.mark.asyncio
    async def test_cancels_running_task(self):
        """[목적] 실행 중인 구독 태스크를 취소하고 참조를 비우는지 검증

        [검증]
        1. 태스크가 cancelled 상태가 됨
        2. 모듈의 _subscriber_task가 None으로 초기화됨
        """
        task = asyncio.create_task(asyncio.sleep(10))
        subscriber_module._subscriber_task = task

        await stop_subscriber()

        assert task.cancelled()
        assert subscriber_module._subscriber_task is None

    @pytest.mark.asyncio
    async def test_noop_when_no_task(self):
        """[목적] 구독 태스크가 없을 때 예외 없이 넘어가는지 검증

        [검증]
        1. 예외 없이 완료되고 _subscriber_task는 None 유지
        """
        await stop_subscriber()

        assert subscriber_module._subscriber_task is None
