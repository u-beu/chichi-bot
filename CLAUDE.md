# chichi-bot Root Guidelines

## Tech Stack
- Python 3.10+, Discord.py, FastAPI, PyTorch, Librosa, aiohttp

## Common Commands
- Run Bot: `python -m bot.main`
- Run API: `uvicorn api.main:app --reload --port 8000`
- Run Worker: `python -m worker.main`
- Run All Tests: `pytest`
- Run Module Test: `pytest tests/api/`

## Project Structure
- `bot/`: 사용자 명령 처리 및 Audio Playback을 담당하는 Discord bot.
- `api/`: 경량화된 FastAPI 관리 서버.
- `worker/`: Audio Analysis를 위한 PyTorch 기반 AI Inference Engine.
- Unit/Integration Test는 프로젝트 구조와 일치하도록 `tests/` 디렉터리 하위에 위치시킬 것 (예: `tests/api/`, `tests/worker/`).

## Core Architecture Rules
- **Shared Session:** Bot Runtime 전체에서 단일 Shared `aiohttp.ClientSession`을 유지할 것. HTTP Request마다 새로운 Session 생성 금지.
- **Async & Non-blocking:** 모든 I/O Operation은 Non-blocking (`async/await`)으로 처리할 것. CPU-bound 연산 작업은 Worker Process로 Offload할 것.
- **Memory Management:** 8GB RAM 환경을 고려하여 모든 Sub-module 전반에 걸쳐 Memory 경계를 엄격히 준수할 것.
- **Keep It Simple (KISS Principle):**
  1. **No Extra Features:** 요청받은 기능 외의 추가 기능을 구현하지 말 것.
  2. **No Over-Abstraction:** 일회성/단발성 코드에는 추상화(Abstraction)를 적용하지 말 것.
  3. **No Unrequested Flexibility:** 요청하지 않은 유연성이나 설정 가능성을 미리 추가하지 말 것.
  4. **No Defensive Over-Engineering:** 불가능한 시나리오에 대한 과도한 예외 처리를 지양할 것 (단, Memory/Network I/O 안정성 관련 처리는 제외).
  5. **Self-Review for Complexity:** 작성 전/후 스스로 *"시니어 개발자가 봤을 때 지나치게 복잡한가?"* 검토하고, 그렇다면 단순하게 다시 작성할 것.

## Workflow Rules
- **Plan Mode & Approval:** 항상 Plan Mode로 작동할 것. 코드 변경 전 반드시 Plan을 제시하고 명시적 승인(Explicit User Approval)을 먼저 얻을 것.
- **Clarity & Communication Rules:**
  1. **Clarify Assumptions:** 가정한 내용을 명확히 밝히고, 확실하지 않다면 사용자에게 질문할 것.
  2. **Present Options:** 여러 해석이 가능하면 임의 선택하지 말고 모든 가능성/대안을 제시할 것.
  3. **Suggest Simpler Solutions:** 더 간단한 방법이 있다면 언급하고, 필요시 적극적으로 반박/제안할 것.
  4. **Stop on Uncertainty:** 이해가 되지 않거나 애매한 부분은 즉시 작업을 멈추고 헷갈리는 요소를 질문할 것.
- **Code Editing Scope Rules:**
  1. **No Unrelated Formatting:** 요청 범위 주변의 인접 코드, 주석, 서식을 임의로 개선하거나 다듬지 말 것.
  2. **No Unrequested Refactoring:** 멀쩡히 동작하는 기존 코드를 임의로 리팩토링하지 말 것.
  3. **Match Existing Style:** 해당 파일의 기존 코드 스타일을 엄격히 준수할 것.
  4. **Report Unused Code:** 사용되지 않거나 관련 없는 코드를 발견하더라도 직접 삭제하지 말고 사용자에게 보고만 할 것.
- **Task Verification Rules:**
  1. **Convert to Verifiable Goals:** 모든 과제는 검증 가능한 목표로 전환할 것.
     - **유효성 검사 추가:** 유효하지 않은 입력에 대한 테스트 작성 및 통과 확인
     - **버그 수정:** 버그 상황을 재현하는 테스트 작성 후 해당 테스트 통과 확인
     - **리팩토링:** 리팩토링 전후 모두 기존 테스트가 정상 통과하는지 확인
  2. **Step-by-Step Plan & Verification:** Multi-step 작업은 간략한 계획을 세우고, 매 단계마다 검증 후 진행할 것.
  3. **Scope Verification:** 코드 작성 후 오직 요청한 사항만 수정되었는지 최종 확인할 것.
- **Branching & Workflow:**
  - 작업 시작 전 [docs/branching.md](docs/branching.md) 규칙(`/` 또는 `/-`)에 따라 새 Branch를 생성하고 이동할 것 (`main` 브랜치 직접 작업 금지).

## Output Style
- 서론/군더더기 없이 핵심 위주로 직관적이고 간결하게 답변할 것.
- Always respond in Korean (한국어로 항상 답변할 것).