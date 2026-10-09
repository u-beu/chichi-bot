# Legacy FastAPI(api 모듈) 작업 내역

과거 `api/` 모듈(FastAPI 기반 관리 서버) 운영 시절 `TODO.md`에 기록되어 있던 작업 항목 아카이브. Spring 백엔드가 Redis에 직접 push하는 방식으로 전환되며 `api/` 모듈이 삭제되어([#29](https://github.com/u-beu/chichi-bot/issues/29)) 더 이상 유효하지 않다.

- [x] **API 라우터 미분리** (api/CLAUDE.md)
  - 문제: `/health`, `/playback` 엔드포인트가 모두 `api/main.py`에 직접 정의됨. `routers/health.py`, `routers/worker.py` 같은 `APIRouter` 분리가 없음.
  - 수정 방향: `api/routers/health.py`, `api/routers/playback.py`로 분리 후 `main.py`에서 `include_router()`로 조립.

- [x] **CORS 미설정** (api/CLAUDE.md)
  - 문제: Spring(`chichi`)·로컬 환경에서의 내부 요청을 허용하는 CORS 미들웨어가 `api/main.py`에 없음.
  - 수정 방향: `CORSMiddleware` 추가, 허용 origin은 환경변수(`api/config.py`)로 관리.

- [ ] **worker 수동 트리거 엔드포인트 없음** (api/CLAUDE.md) — api 모듈 삭제로 폐기
  - 문제: api/CLAUDE.md는 "worker에 대한 manual trigger task" 제공을 명시했으나 관련 엔드포인트가 없었음.
  - 수정 방향(당시 계획): worker 용도/설계 확정 후 `api/routers/worker.py`에 트리거 엔드포인트 추가. FastAPI 프로세스에서 직접 무거운 모델을 로드하지 말고 백그라운드 작업/큐로 위임.
