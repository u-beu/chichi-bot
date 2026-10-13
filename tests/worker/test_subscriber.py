import asyncio
import json
from concurrent.futures.process import BrokenProcessPool

import pytest
import redis
from unittest.mock import AsyncMock, MagicMock, patch

import worker.subscriber as subscriber_module
from worker.subscriber import (
    IDLE_UNLOAD_SEC,
    SPRING_ANALYSIS_QUEUE_KEY,
    _get_executor,
    _process_request,
    _shutdown_executor,
    subscriber_loop,
)


@pytest.fixture(autouse=True)
def inline_executor():
    """실제 자식 프로세스를 띄우지 않도록 _get_executor를 None(기본 스레드 풀)으로 대체."""
    with patch("worker.subscriber._get_executor", return_value=None):
        yield


class TestProcessRequest:
    @pytest.mark.asyncio
    async def test_valid_request_runs_analysis_and_pushes_result(self):
        """[목적] 정상적인 videoId 요청이 분석을 실행하고 결과를 결과 큐로 전송하는지 검증

        [검증]
        1. analyze_video가 video_id로 호출됨
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
        ["not-json", json.dumps({}), json.dumps({"videoId": ""}), json.dumps(["abc123"]), json.dumps({"videoId": 123})],
        ids=["invalid_json", "missing_video_id", "empty_video_id", "non_dict_json", "non_string_video_id"],
    )
    async def test_invalid_payload_skips_analysis(self, payload):
        """[목적] JSON 파싱 실패, 비-dict JSON, videoId 누락/비문자열 시 분석을 실행하지 않는지 검증

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
    async def test_analysis_failure_publishes_error_without_raising(self):
        """[목적] 분석 실패 시 예외가 전파되지 않고 결과 큐에 예외 클래스명이 error로 발행되는지 검증

        [검증]
        1. 예외가 밖으로 전파되지 않음
        2. {"videoId", "error": 예외 클래스명}이 SPRING_ANALYSIS_QUEUE_KEY로 lpush됨 (예외 메시지는 포함되지 않음)
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", side_effect=ValueError("https://stream.example.com/audio?sig=secret")):
            await _process_request(client, payload)

        client.lpush.assert_called_once_with(
            SPRING_ANALYSIS_QUEUE_KEY,
            json.dumps({"videoId": "abc123", "error": "ValueError"}),
        )

    @pytest.mark.asyncio
    async def test_broken_process_pool_resets_executor(self):
        """[목적] 분석 프로세스가 비정상 종료(BrokenProcessPool)되면 풀을 폐기하고 error를 발행하는지 검증

        [검증]
        1. _shutdown_executor가 호출됨
        2. error 메시지가 lpush됨
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", side_effect=BrokenProcessPool("dead")), \
                patch("worker.subscriber._shutdown_executor") as mock_shutdown:
            await _process_request(client, payload)

        mock_shutdown.assert_called_once()
        client.lpush.assert_called_once()

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


class TestExecutor:
    def test_get_executor_creates_single_worker_pool_once(self):
        """[목적] 분석 프로세스 풀이 max_workers=1로 지연 생성되어 재사용되는지 검증

        [검증]
        1. ProcessPoolExecutor가 max_workers=1로 한 번만 생성됨
        2. 두 번 호출해도 같은 인스턴스가 반환됨
        """
        subscriber_module._executor = None
        with patch("worker.subscriber.ProcessPoolExecutor") as mock_pool:
            first = _get_executor()
            second = _get_executor()
        subscriber_module._executor = None

        mock_pool.assert_called_once_with(max_workers=1)
        assert first is second

    def test_shutdown_executor_releases_pool(self):
        """[목적] 풀 종료 시 shutdown이 호출되고 다음 호출에서 재생성되도록 초기화되는지 검증

        [검증]
        1. executor.shutdown(wait=True)가 호출됨
        2. 모듈의 _executor가 None으로 초기화됨
        """
        fake_pool = MagicMock()
        subscriber_module._executor = fake_pool

        _shutdown_executor()

        fake_pool.shutdown.assert_called_once_with(wait=True)
        assert subscriber_module._executor is None

    def test_shutdown_executor_is_noop_without_pool(self):
        """[목적] 풀이 없을 때 종료 호출이 예외 없이 무시되는지 검증

        [검증]
        1. 예외가 발생하지 않음
        """
        subscriber_module._executor = None

        _shutdown_executor()


class TestSubscriberLoop:
    @pytest.mark.asyncio
    async def test_processes_message_then_stops(self):
        """[목적] brpop으로 받은 메시지를 _process_request로 전달하는지 검증

        [검증]
        1. CancelledError 발생 시 예외가 그대로 전파됨
        2. _process_request가 수신한 payload로 호출됨
        """
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        fake_client.brpop = AsyncMock(
            side_effect=[("worker:analysis-requests", "payload"), asyncio.CancelledError()]
        )

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_process.assert_called_once_with(fake_client, "payload")

    @pytest.mark.asyncio
    async def test_idle_timeout_unloads_model_and_skips_processing(self):
        """[목적] brpop이 idle 타임아웃으로 None을 반환하면 분석 프로세스를 종료하고 처리를 건너뛰는지 검증

        [검증]
        1. brpop이 IDLE_UNLOAD_SEC 타임아웃으로 호출됨
        2. _shutdown_executor가 idle 처리와 종료 정리로 총 2회 호출됨
        3. CancelledError가 전파되고 _process_request는 호출되지 않음
        """
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        fake_client.brpop = AsyncMock(side_effect=[None, asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._shutdown_executor") as mock_shutdown, \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.brpop.assert_any_call("worker:analysis-requests", IDLE_UNLOAD_SEC)
        assert mock_shutdown.call_count == 2
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_redis_error(self):
        """[목적] RedisError 발생 시 3초 대기 후 루프를 계속하는지 검증

        [검증]
        1. asyncio.sleep(3)이 호출됨
        2. 이후 CancelledError로 루프가 종료됨
        """
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
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
        fake_client.aclose = AsyncMock()
        fake_client.brpop = AsyncMock(side_effect=[Exception("boom"), asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

    @pytest.mark.asyncio
    async def test_cleans_up_client_and_executor_on_cancel(self):
        """[목적] 구독 루프가 취소돼도 Redis client와 분석 프로세스가 정리되는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. client.aclose()가 호출됨
        3. _shutdown_executor가 호출됨
        """
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        fake_client.brpop = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._shutdown_executor") as mock_shutdown:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.aclose.assert_awaited_once()
        mock_shutdown.assert_called_once()
