# chichi-bot/bot Guidelines

## Tech Stack
- Python 3.10+, discord.py, redis-py (asyncio), ffmpeg, yt-dlp

## Common Commands
- Run Bot: `python -m bot.main`

## Development Rules
- **Modular Structure:** `discord.ext.commands.Cog` 기반 명령어 및 이벤트 리스너 모듈화
- **Redis Subscriber:** 
  - 독립 비동기(`asyncio`) 백그라운드 태스크로 Redis List (`bot:commands` 키, `BRPOP` 방식) 메시지 소비
  - 봇 재시작 시에도 중단 기간 내 발행 메시지가 손실 없이 처리되도록 구조 유지
- **Metadata Sync:** `chichi` (Spring Boot) 백엔드로의 재생 상태/메타데이터 전달 시 Redis 메시지 버스 활용
- **Audio Streaming:**
  - 음성 채널 오디오 처리 시 적절한 재연결 옵션이 포함된 `FFmpeg` 활용
  - 채널 연결 해제, 권한 확인, 오디오 버퍼 정리 작업의 안전한 처리
- **Error Handling:** Discord API 및 네트워크 에러 예외 처리 및 로깅 (봇 이벤트 루프 중단 금지)