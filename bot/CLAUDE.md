# chichi-bot/bot Guidelines

## Tech Stack
- Python 3.10+, discord.py, redis-py (asyncio), ffmpeg, yt-dlp

## Common Commands
- Run Bot: `python main.py`

## Development Rules
- **Modular Structure:** `discord.ext.commands.Cog` 기반 명령어 및 이벤트 리스너 모듈화
- **Redis Subscriber:**
  - 독립 비동기(`asyncio`) 백그라운드 태스크로 Redis List (`bot:commands` 키, `BLMOVE` 방식) 메시지 소비
  - 봇 재시작 시에도 중단 기간 내 발행 메시지가 손실 없이 처리되도록 구조 유지
  - 별도 Redis client를 만들지 않고 `bot.redis_client`를 공유. 종료 시(`ChichiBot.close()`) `stop_subscriber()`로 구독 태스크를 취소한 뒤 Redis client 종료
  - `BLMOVE`로 요청을 processing 리스트(`bot:commands:processing`)로 옮겨 처리하고, 처리 후 `LREM`으로 제거. 구독 시작 시 processing에 남은 요청을 원래 큐로 복구 (Redis 서버 6.2+ 필요)
  - 처리 중 예외는 로그 후 `LREM`(재시작마다 재처리 방지), 종료(취소)·크래시는 `LREM`하지 않아 다음 기동 때 재처리됨
  - at-least-once: `LREM` 직전 크래시 시 같은 요청이 한 번 더 처리되어 같은 곡이 중복 재생될 수 있음 (알려진 한계)
- **Queue Schema (Redis List):**
  - 요청: `bot:commands` (`BOT_QUEUE_KEY`) <- `{"action": "playback", "guild_id", "user_id", "query"}`
  - 발행: `spring:play-history` (`SPRING_QUEUE_KEY`) -> `{"title", "uploader", "image", "videoId", "discordId"}`
  - JSON 형식 오류, 미등록 `action`, `guild_id`/`user_id` 누락·부적합 요청은 경고 로그 후 폐기
- **Environment Variables:**
  - `DISCORD_TOKEN`: Discord bot 토큰
  - `BOT_QUEUE_KEY`: 요청 큐 키 (기본값 `bot:commands`)
  - `SPRING_QUEUE_KEY`: 재생 기록 발행 큐 키 (기본값 `spring:play-history`)
  - `main.py`가 `load_dotenv()`를 먼저 호출한 뒤 `bot` 모듈을 import (모듈 레벨 `os.getenv`가 `.env`를 읽도록)
- **Metadata Sync:** `chichi` (Spring Boot) 백엔드로의 재생 상태/메타데이터 전달 시 Redis 메시지 버스 활용
- **Audio Streaming:**
  - 음성 채널 오디오 처리 시 적절한 재연결 옵션이 포함된 `FFmpeg` 활용
  - 채널 연결 해제, 권한 확인 작업의 안전한 처리
  - 대기열이 비었거나 요청자가 음성 채널을 나가면 대기열 삭제 및 음성 연결 종료
  - 웹 UI(API) 재생 요청은 `!play`와 동일하게 재생 중이면 현재 곡을 중단하고 즉시 재생
- **Error Handling:** Discord API 및 네트워크 에러 예외 처리 및 로깅 (봇 이벤트 루프 중단 금지)