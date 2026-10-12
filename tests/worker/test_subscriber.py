import asyncio
import json

import pytest
import redis
from unittest.mock import AsyncMock, MagicMock, patch

from worker.subscriber import SPRING_ANALYSIS_QUEUE_KEY, _process_request, subscriber_loop


class TestProcessRequest:
    @pytest.mark.asyncio
    async def test_valid_request_runs_analysis_and_pushes_result(self):
        """[목적] 정상적인 videoId 요청이 분석을 실행하고 결과를 결과 큐로 전송하는지 검증

        [검증]
        1. run_in_executor를 통해 analyze_video가 video_id로 호출됨
        2. 분석 결과가 SPRING_ANALYSIS_QUEUE_KEY로 lpush됨
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", return_value={"videoId": "abc123", "genre": "pop", "mood": "happy"}) as mock_analyze:
            await _process_request(client, payload)

        mock_analyze.assert_called_once_with("abc123")
        client.lpush.assert_called_once_with(
            SPRING_ANALYSIS_QUEUE_KEY,
            json.dumps({"videoId": "abc123", "genre": "pop", "mood": "happy"}),
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        ["not-json", json.dumps({}), json.dumps({"videoId": ""})],
        ids=["invalid_json", "missing_video_id", "empty_video_id"],
    )
    async def test_invalid_payload_skips_analysis(self, payload):
        """[목적] JSON 파싱 실패 또는 videoId 누락 시 분석을 실행하지 않는지 검증

        [검증]
        1. analyze_video가 호출되지 않음
        2. lpush가 호출되지 않음
        """
        client = MagicMock()
        client.lpush = AsyncMock()

        with patch("worker.subscriber.analyze_video") as mock_analyze:
            await _process_request(client, payload)

        mock_analyze.assert_not_called()
        client.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_analysis_failure_skips_task_without_raising(self):
        """[목적] 분석 실패 시 예외가 전파되지 않고 해당 태스크만 skip되는지 검증

        [검증]
        1. 예외가 밖으로 전파되지 않음
        2. lpush가 호출되지 않음
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", side_effect=Exception("분석 실패")):
            await _process_request(client, payload)

        client.lpush.assert_not_called()

    @pytest.mark.asyncio
    async def test_lpush_redis_error_is_logged_not_raised(self):
        """[목적] 결과 전송 중 RedisError가 발생해도 예외가 전파되지 않는지 검증

        [검증]
        1. redis.RedisError가 밖으로 전파되지 않음
        """
        client = MagicMock()
        client.lpush = AsyncMock(side_effect=redis.RedisError("boom"))
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", return_value={"videoId": "abc123"}):
            await _process_request(client, payload)


class TestSubscriberLoop:
    @pytest.mark.asyncio
    async def test_processes_message_then_stops(self):
        """[목적] brpop으로 받은 메시지를 _process_request로 전달하는지 검증

        [검증]
        1. CancelledError 발생 시 예외가 그대로 전파됨
        2. _process_request가 수신한 payload로 호출됨
        """
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(
            side_effect=[("worker:analysis-requests", "payload"), asyncio.CancelledError()]
        )

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_process.assert_called_once_with(fake_client, "payload")

    @pytest.mark.asyncio
    async def test_skips_empty_result(self):
        """[목적] brpop 결과가 없을 때(None) 메시지 처리를 건너뛰는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. _process_request가 호출되지 않음
        """
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[None, asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_redis_error(self):
        """[목적] RedisError 발생 시 3초 대기 후 루프를 계속하는지 검증

        [검증]
        1. asyncio.sleep(3)이 호출됨
        2. 이후 CancelledError로 루프가 종료됨
        """
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[redis.RedisError("boom"), asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_sleep.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_swallows_generic_exception_and_continues(self):
        """[목적] 일반 예외가 발생해도 루프가 중단되지 않고 계속되는지 검증

        [검증]
        1. 예외가 전파되지 않고 다음 반복(CancelledError)까지 루프가 유지됨
        """
        fake_client = MagicMock()
        fake_client.brpop = AsyncMock(side_effect=[Exception("boom"), asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()
