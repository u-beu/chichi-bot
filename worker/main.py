import asyncio
import logging
import signal

from dotenv import load_dotenv

load_dotenv()

from .subscriber import subscriber_loop  # noqa: E402  (subscriber가 import 시점에 환경변수를 읽으므로 load_dotenv 이후 import)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _run() -> None:
    """SIGTERM/SIGINT를 받으면 구독 태스크를 취소해 subscriber_loop의 정리(finally)가 실행되도록 한다."""
    task = asyncio.create_task(subscriber_loop())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        logger.info("워커 종료")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
