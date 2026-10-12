import asyncio
import logging

from .subscriber import subscriber_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        asyncio.run(subscriber_loop())
    except KeyboardInterrupt:
        logger.info("워커 종료")


if __name__ == "__main__":
    main()
