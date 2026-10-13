import asyncio
import importlib
import signal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import worker.main as main_module
from worker.main import _run, main


class TestMain:
    def test_runs_run_coroutine(self):
        """[목적] main()이 asyncio.run(_run())을 호출하는지 검증

        [검증]
        1. asyncio.run이 호출됨
        """
        with patch("worker.main.asyncio.run") as mock_run, \
                patch("worker.main._run") as mock_inner:
            main()

        mock_inner.assert_called_once()
        mock_run.assert_called_once()

    def test_loads_dotenv_on_import(self):
        """[목적] worker.main import 시 subscriber import보다 먼저 load_dotenv가 호출되는지 검증

        [검증]
        1. load_dotenv가 한 번 호출됨
        """
        with patch("dotenv.load_dotenv") as mock_dotenv:
            importlib.reload(main_module)

        mock_dotenv.assert_called_once()


class TestRun:
    @pytest.mark.asyncio
    async def test_registers_signal_handlers_that_cancel_task(self):
        """[목적] SIGTERM/SIGINT 수신 시 구독 태스크가 취소되고 예외 없이 종료되는지 검증

        [검증]
        1. SIGTERM, SIGINT 핸들러가 등록됨
        2. 등록된 핸들러 호출 시 구독 태스크가 취소되어 _run이 CancelledError 없이 반환됨
        """
        handlers = {}
        loop = asyncio.get_running_loop()

        async def fake_loop():
            await asyncio.sleep(10)

        def fake_add(sig, callback, *args):
            handlers[sig] = callback
            if sig == signal.SIGINT:
                loop.call_soon(callback)

        with patch("worker.main.subscriber_loop", fake_loop), \
                patch.object(loop, "add_signal_handler", side_effect=fake_add):
            await _run()

        assert set(handlers) == {signal.SIGTERM, signal.SIGINT}
