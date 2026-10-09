# chichi-bot/bot Guidelines

## Tech Stack
- Python 3.10+, discord.py, redis-py (asyncio), ffmpeg, yt-dlp

## Common Commands
- Bot 실행: `python main.py`

## Development Rules
- **Modular Structure:** `discord.ext.commands.Cog`를 사용하여 봇의 명령어 및 이벤트 리스너 구조화.
- **Redis Subscriber:** 독립된 비동기(non-blocking) `asyncio` 백그라운드 태스크를 통해 Redis List(`bot:commands` 키, `BRPOP` 방식)의 명령어 소비. 리스너가 중단된 동안 발행된 메시지도 손실 없이 봇 재시작 후 처리되도록 유지.
- **Metadata Sync:**
    - `chichi` (Spring) 백엔드로의 재생 상태/메타데이터 전달은 Redis를 메시지 버스로 사용할 것.
- **Audio Streaming:**
    - 음성 채널 오디오 처리에 적절한 재연결 옵션을 포함한 `ffmpeg` 활용.
    - 연결 해제, 채널 권한 확인, 오디오 버퍼 정리 작업의 안전한 처리.
- **Error Handling:** Discord API 및 네트워크 에러는 봇의 이벤트 루프가 중단되지 않도록 예외 처리하여 로깅.