# chichi-bot Root Guidelines

## Tech Stack
- Python 3.10+, Discord.py, PyTorch, Librosa

## Common Commands
- Run Bot: `python main.py`
- Run Worker: `python -m worker.main`
- Install Test Dependencies: `pip install -r requirements-dev.txt`
- Run All Tests: `pytest`

## Project Structure
- `bot/`: 사용자 명령 처리 및 Audio Playback을 담당하는 Discord bot
- `worker/`: Audio Analysis를 위한 PyTorch 기반 AI Inference Engine
- `tests/`: 프로젝트 구조와 일치하는 위치에 Unit/Integration Test 배치 (예: `tests/worker/`)
- `main.py`: bot 엔트리포인트 (`load_dotenv()` 후 `bot.core` import)
- `docs/`: 브랜치 규칙(`branching.md`), ADR(`adr/`) 등 프로젝트 문서
- `requirements-bot.txt` / `requirements-worker.txt` / `requirements-dev.txt`: 서브모듈별 의존성 및 테스트 의존성(두 파일 포함)

## Environment Variables
- `REDIS_URL`: bot/worker 공통 Redis 접속 URL (기본값 `redis://localhost:6379/0`)
- 서브모듈별 변수는 [bot/CLAUDE.md](bot/CLAUDE.md), [worker/CLAUDE.md](worker/CLAUDE.md) 참조

## Core Architecture Rules
- **Redis-based Asynchronous Messaging:**
  - Spring Boot - `chichi-bot` 간 모든 작업 요청, 상태 변경, 메타데이터 전달은 Redis List(Queue) 단일 메시지 버스로 비동기(`async/await`) 처리
  - `bot/`과 `worker/` 간 직접 통신 금지 (각각 독립적으로 Spring Boot와 데이터 송수신)
- **Submodule Data Flow:**
  - `bot/`:
    - 웹 UI/디스코드 채팅 재생 요청 수신 -> 디스코드 채널 음원 재생
    - 재생 음원 데이터(제목, 업로더, 썸네일, videoId, discordId) 메시지를 Redis Queue로 발행
  - `worker/`:
    - Spring Boot(`chichi`)의 음원 분석 요청 수신 -> PyTorch/Librosa 분석 수행
    - 분석 완료 데이터 메시지를 Redis Queue로 발행
- **Async & Non-blocking:** 모든 I/O Operation은 Non-blocking (`async/await`) 처리. CPU-bound 연산 작업은 Worker Process로 Offload
- **Memory Management:** 8GB RAM 환경을 고려하여 모든 Sub-module 전반에 걸쳐 엄격한 메모리 경계 준수
- **Keep It Simple (KISS Principle):**
  1. **No Extra Features:** 요청받은 기능 외 추가 구현 금지
  2. **No Over-Abstraction:** 일회성/단발성 코드에 추상화(Abstraction) 적용 금지
  3. **No Unrequested Flexibility:** 요청하지 않은 유연성이나 설정 가능성 추가 금지
  4. **No Defensive Over-Engineering:** 불가능한 시나리오에 대한 과도한 예외 처리 지양 (단, Memory/Network I/O 안정성 관련 처리는 제외)
  5. **Self-Review for Complexity:** 작성 전/후 스스로 *"시니어 개발자가 봤을 때 지나치게 복잡한가?"* 검토 후 단순하게 재작성

## Workflow Rules
- **Plan Mode & Approval:** 항상 Plan Mode로 동작. 코드 변경 전 Plan 제시 및 명시적 사용자 승인(Explicit User Approval) 필수
- **Clarity & Communication Rules:**
  1. **Clarify Assumptions:** 가정사항을 명확히 밝히고, 불확실한 부분은 사용자에게 질문
  2. **Present Options:** 여러 해석이 가능할 경우 임의 선택 없이 모든 가능성/대안 제시
  3. **Suggest Simpler Solutions:** 더 간단한 방안 언급 및 필요시 적극적인 반박/제안
  4. **Stop on Uncertainty:** 모호하거나 이해가 되지 않는 지점은 즉시 작업 중단 후 질문
- **Code Editing Scope Rules:**
  1. **No Unrelated Formatting:** 요청 범위 주변의 인접 코드, 주석, 서식 임의 수정 금지
  2. **No Unrequested Refactoring:** 정상 동작하는 기존 코드의 임의 리팩토링 금지
  3. **Match Existing Style:** 대상 파일의 기존 코드 스타일 엄격히 준수
  4. **Report Unused Code:** 미사용/불필요 코드 발견 시 직접 삭제하지 않고 사용자에게 보고
- **Task Verification Rules:**
  1. **Convert to Verifiable Goals:** 모든 과제는 검증 가능한 목표로 전환
     - **유효성 검사 추가:** 유효하지 않은 입력에 대한 테스트 작성 및 통과 확인
     - **버그 수정:** 버그 재현 테스트 작성 후 통과 확인
     - **리팩토링:** 작업 전후 기존 테스트 정상 통과 확인
  2. **Step-by-Step Plan & Verification:** Multi-step 작업은 간략한 계획 수립 후 단계별 검증 진행
  3. **Scope Verification:** 코드 작성 후 오직 요청한 사항만 수정되었는지 최종 검증
- **Branching & Workflow:** 작업 시작 전 [docs/branching.md](docs/branching.md) 규칙(`<type>/<issue-number>-<description>`, 이슈가 없으면 `<type>/<description>`)에 따라 새 Branch 생성 및 이동 (`main` 브랜치 직접 작업 금지)

## Output Style
- 서론/군더더기 없이 핵심 위주로 직관적이고 간결하게 답변
- 한국어로 항상 답변