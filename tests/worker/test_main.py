from unittest.mock import patch

from worker.main import main


class TestMain:
    def test_runs_subscriber_loop(self):
        """[목적] main()이 asyncio.run(subscriber_loop())을 호출하는지 검증

        [검증]
        1. asyncio.run이 호출됨
        """
        with patch("worker.main.asyncio.run") as mock_run, \
                patch("worker.main.subscriber_loop") as mock_loop:
            main()

        mock_loop.assert_called_once()
        mock_run.assert_called_once()

    def test_keyboard_interrupt_is_absorbed(self):
        """[목적] KeyboardInterrupt가 발생해도 예외가 밖으로 전파되지 않는지 검증

        [검증]
        1. main() 호출이 예외 없이 종료됨
        """
        with patch("worker.main.asyncio.run", side_effect=KeyboardInterrupt), \
                patch("worker.main.subscriber_loop"):
            main()
