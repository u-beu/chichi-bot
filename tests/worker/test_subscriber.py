import asyncio
import json
import time
from concurrent.futures.process import BrokenProcessPool

import pytest
import redis
from unittest.mock import AsyncMock, MagicMock, patch

import worker.subscriber as subscriber_module
from worker.subscriber import (
    IDLE_UNLOAD_SEC,
    RESULT_CACHE_KEY_PREFIX,
    RESULT_CACHE_TTL_SEC,
    SPRING_ANALYSIS_QUEUE_KEY,
    WORKER_PROCESSING_KEY,
    WORKER_QUEUE_KEY,
    _get_executor,
    _kill_executor,
    _process_request,
    _recover_processing,
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
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
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
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()

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
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
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
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
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
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", return_value={"videoId": "abc123"}):
            await _process_request(client, payload)

    @pytest.mark.asyncio
    async def test_cache_hit_republishes_without_analysis(self):
        """[목적] 캐시된 결과가 있으면 분석 없이 캐시된 결과를 재발행하는지 검증

        [검증]
        1. analyze_video가 호출되지 않음
        2. 캐시된 결과가 SPRING_ANALYSIS_QUEUE_KEY로 lpush됨
        """
        cached = {"videoId": "abc123", "genre": "pop", "mood": "happy"}
        client = MagicMock()
        client.lpush = AsyncMock()
        client.get = AsyncMock(return_value=json.dumps(cached))
        client.set = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video") as mock_analyze:
            await _process_request(client, payload)

        client.get.assert_called_once_with(f"{RESULT_CACHE_KEY_PREFIX}abc123")
        mock_analyze.assert_not_called()
        client.lpush.assert_called_once_with(SPRING_ANALYSIS_QUEUE_KEY, json.dumps(cached))

    @pytest.mark.asyncio
    async def test_success_result_is_cached_with_ttl(self):
        """[목적] 분석 성공 결과가 TTL과 함께 캐시에 저장되는지 검증

        [검증]
        1. 결과가 RESULT_CACHE_TTL_SEC 만료로 set됨
        """
        result = {"videoId": "abc123", "genre": "pop", "mood": "happy"}
        client = MagicMock()
        client.lpush = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", return_value=result):
            await _process_request(client, payload)

        client.set.assert_called_once_with(
            f"{RESULT_CACHE_KEY_PREFIX}abc123", json.dumps(result), ex=RESULT_CACHE_TTL_SEC
        )

    @pytest.mark.asyncio
    async def test_error_result_is_not_cached(self):
        """[목적] 분석 실패 결과는 캐시하지 않는지 검증 (일시적 실패 고착 방지)

        [검증]
        1. set이 호출되지 않음
        2. error 결과는 그대로 lpush됨
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", side_effect=ValueError("boom")):
            await _process_request(client, payload)

        client.set.assert_not_called()
        client.lpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_redis_error_falls_back_to_analysis(self):
        """[목적] 캐시 조회/저장에서 RedisError가 나도 요청이 유실되지 않고 분석·발행까지 진행되는지 검증

        [검증]
        1. 예외가 전파되지 않음
        2. analyze_video가 호출되고 결과가 lpush됨
        """
        result = {"videoId": "abc123", "genre": "pop", "mood": "happy"}
        client = MagicMock()
        client.lpush = AsyncMock()
        client.get = AsyncMock(side_effect=redis.RedisError("boom"))
        client.set = AsyncMock(side_effect=redis.RedisError("boom"))
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.analyze_video", return_value=result) as mock_analyze:
            await _process_request(client, payload)

        mock_analyze.assert_called_once_with("abc123")
        client.lpush.assert_called_once_with(SPRING_ANALYSIS_QUEUE_KEY, json.dumps(result))

    @pytest.mark.asyncio
    async def test_analysis_timeout_kills_executor_and_publishes_error(self):
        """[목적] 분석이 ANALYSIS_TIMEOUT_SEC를 넘기면 멈춘 프로세스를 강제 종료하고 error를 발행하는지 검증

        [검증]
        1. _kill_executor가 호출됨
        2. {"videoId", "error": "TimeoutError"}가 lpush되고 캐시에는 저장되지 않음
        """
        client = MagicMock()
        client.lpush = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        payload = json.dumps({"videoId": "abc123"})

        with patch("worker.subscriber.ANALYSIS_TIMEOUT_SEC", 0.05), \
                patch("worker.subscriber.analyze_video", side_effect=lambda _: time.sleep(0.3)), \
                patch("worker.subscriber._kill_executor") as mock_kill:
            await _process_request(client, payload)

        mock_kill.assert_called_once()
        client.set.assert_not_called()
        client.lpush.assert_called_once_with(
            SPRING_ANALYSIS_QUEUE_KEY,
            json.dumps({"videoId": "abc123", "error": "TimeoutError"}),
        )


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

    def test_kill_executor_kills_children_and_resets_pool(self):
        """[목적] 타임아웃 시 자식 프로세스를 kill하고 대기 없이 풀을 폐기하는지 검증

        [검증]
        1. 모든 자식 프로세스에 kill이 호출됨
        2. executor.shutdown(wait=False, cancel_futures=True)가 호출됨
        3. 모듈의 _executor가 None으로 초기화됨
        """
        child = MagicMock()
        fake_pool = MagicMock()
        fake_pool._processes = {1: child}
        subscriber_module._executor = fake_pool

        _kill_executor()

        child.kill.assert_called_once()
        fake_pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
        assert subscriber_module._executor is None

    def test_kill_executor_is_noop_without_pool(self):
        """[목적] 풀이 없을 때 강제 종료 호출이 예외 없이 무시되는지 검증

        [검증]
        1. 예외가 발생하지 않음
        """
        subscriber_module._executor = None

        _kill_executor()


def _make_client():
    """복구할 processing 요청이 없는 기본 Redis client mock."""
    client = MagicMock()
    client.aclose = AsyncMock()
    client.lpop = AsyncMock(return_value=None)
    client.lrem = AsyncMock()
    return client


class TestSubscriberLoop:
    @pytest.mark.asyncio
    async def test_processes_message_then_stops(self):
        """[목적] blmove로 받은 메시지를 _process_request로 전달하는지 검증

        [검증]
        1. CancelledError 발생 시 예외가 그대로 전파됨
        2. _process_request가 수신한 payload로 호출됨
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=["payload", asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_process.assert_called_once_with(fake_client, "payload")

    @pytest.mark.asyncio
    async def test_idle_timeout_unloads_model_and_skips_processing(self):
        """[목적] blmove가 idle 타임아웃으로 None을 반환하면 분석 프로세스를 종료하고 처리를 건너뛰는지 검증

        [검증]
        1. blmove가 IDLE_UNLOAD_SEC 타임아웃으로 호출됨
        2. idle 처리로 _shutdown_executor가 1회, 종료 정리로 _kill_executor가 1회 호출됨
        3. CancelledError가 전파되고 _process_request는 호출되지 않음
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=[None, asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._shutdown_executor") as mock_shutdown, \
                patch("worker.subscriber._kill_executor") as mock_kill, \
                patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.blmove.assert_any_call(
            WORKER_QUEUE_KEY, WORKER_PROCESSING_KEY, IDLE_UNLOAD_SEC, "RIGHT", "LEFT"
        )
        mock_shutdown.assert_called_once()
        mock_kill.assert_called_once()
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_retries_on_redis_error(self):
        """[목적] RedisError 발생 시 3초 대기 후 루프를 계속하는지 검증

        [검증]
        1. asyncio.sleep(3)이 호출됨
        2. 이후 CancelledError로 루프가 종료됨
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=[redis.RedisError("boom"), asyncio.CancelledError()])

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
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=[Exception("boom"), asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

    @pytest.mark.asyncio
    async def test_cleans_up_client_and_executor_on_cancel(self):
        """[목적] 구독 루프가 취소돼도 Redis client와 분석 프로세스가 정리되는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. client.aclose()가 호출됨
        3. _kill_executor가 호출되고 wait=True인 _shutdown_executor는 호출되지 않음
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._shutdown_executor") as mock_shutdown, \
                patch("worker.subscriber._kill_executor") as mock_kill:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.aclose.assert_awaited_once()
        mock_kill.assert_called_once()
        mock_shutdown.assert_not_called()

    @pytest.mark.asyncio
    async def test_removes_from_processing_after_success(self):
        """[목적] 처리 완료 후 processing 리스트에서 요청을 제거하는지 검증

        [검증]
        1. lrem이 processing 키, 수신한 payload로 호출됨
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=["payload", asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.lrem.assert_called_once_with(WORKER_PROCESSING_KEY, 1, "payload")

    @pytest.mark.asyncio
    async def test_process_failure_still_removes_from_processing(self):
        """[목적] 처리 중 일반 예외가 나도 processing에서 제거되어 재시작마다 통보되지 않는지 검증

        [검증]
        1. 예외가 전파되지 않고 루프가 유지됨
        2. lrem이 호출됨
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=["payload", asyncio.CancelledError()])

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock, side_effect=Exception("boom")):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.lrem.assert_called_once_with(WORKER_PROCESSING_KEY, 1, "payload")

    @pytest.mark.asyncio
    async def test_cancel_during_processing_keeps_in_processing(self):
        """[목적] 처리 중 취소(종료)되면 processing에 남겨 다음 기동 때 통보되도록 하는지 검증

        [검증]
        1. CancelledError가 전파됨
        2. lrem이 호출되지 않음
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(return_value="payload")

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._process_request", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.lrem.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovers_processing_before_consuming(self):
        """[목적] 시작 시 processing에 남은 요청을 소비 시작 전에 복구하는지 검증

        [검증]
        1. _recover_processing이 호출됨
        2. 복구 후 blmove 소비 루프가 시작됨
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._recover_processing", new_callable=AsyncMock) as mock_recover:
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        mock_recover.assert_awaited_once_with(fake_client)
        fake_client.blmove.assert_called_once()

    @pytest.mark.asyncio
    async def test_recover_redis_error_does_not_stop_loop(self):
        """[목적] 복구 중 RedisError가 나도 소비 루프에 진입하는지 검증

        [검증]
        1. 예외가 전파되지 않고 blmove 루프에 진입함
        """
        fake_client = _make_client()
        fake_client.blmove = AsyncMock(side_effect=asyncio.CancelledError())

        with patch("worker.subscriber.redis_asyncio.from_url", return_value=fake_client), \
                patch("worker.subscriber._recover_processing", new_callable=AsyncMock, side_effect=redis.RedisError("boom")):
            with pytest.raises(asyncio.CancelledError):
                await subscriber_loop()

        fake_client.blmove.assert_called_once()


class TestRecoverProcessing:
    @pytest.mark.asyncio
    async def test_leftover_request_publishes_worker_crashed_without_analysis(self):
        """[목적] processing에 남은 요청을 재처리하지 않고 WorkerCrashed로 통보하는지 검증

        [검증]
        1. 결과 큐로 {"videoId", "error": "WorkerCrashed"}가 발행됨
        2. 분석(_process_request)은 호출되지 않음
        """
        client = MagicMock()
        client.lpop = AsyncMock(side_effect=[json.dumps({"videoId": "abc"}), None])
        client.lpush = AsyncMock()

        with patch("worker.subscriber._process_request", new_callable=AsyncMock) as mock_process:
            await _recover_processing(client)

        client.lpop.assert_called_with(WORKER_PROCESSING_KEY)
        client.lpush.assert_awaited_once_with(
            SPRING_ANALYSIS_QUEUE_KEY, json.dumps({"videoId": "abc", "error": "WorkerCrashed"})
        )
        mock_process.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload", ["not-json", json.dumps({"x": 1}), json.dumps([1])])
    async def test_invalid_leftover_is_dropped_without_publish(self, payload):
        """[목적] 부적합한 남은 요청은 발행 없이 폐기하는지 검증

        [검증]
        1. 결과 큐로 아무것도 발행되지 않음
        2. 예외가 전파되지 않음
        """
        client = MagicMock()
        client.lpop = AsyncMock(side_effect=[payload, None])
        client.lpush = AsyncMock()

        await _recover_processing(client)

        client.lpush.assert_not_called()

