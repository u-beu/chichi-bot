# ADR 001: Pure Redis Architecture (FastAPI `api` 모듈 제거)

- **Status:** Accepted (승인됨)
- **Date:** 2026-10-09
- **Related:** Issue #29, branch `refactor/29-remove-api-module`

---

## 1. Context (배경 및 기존 구조)
Spring 백엔드(`chichi`)에서 디스코드 봇(`chichi-bot`)으로 재생 명령을 전달하기 위해 중간 중개 레이어로 `api/` 모듈(FastAPI)을 두고 활용했다. Spring이 Redis의 큐 키·payload 포맷 같은 내부 구현을 직접 알 필요 없이, Pydantic으로 검증된 명확한 HTTP 계약(`POST /playback`)만으로 명령을 전달할 수 있게 하기 위함이었다.

- **기존 흐름:** `chichi` (Spring) ➔ `api` (FastAPI `POST /playback`) ➔ Redis List (`bot:commands` LPUSH) ➔ `bot` (`subscriber.py` BRPOP)

---

## 2. Decision Driver (결정 요인)
1. **제한된 리소스 환경:** 8GB RAM 환경에서 단순 릴레이 역할만 하는 `uvicorn/FastAPI` 프로세스의 상시 점유 리소스 절감 필요.
2. **아키텍처 단순화 (KISS 원칙):** 서비스 간 통신 수단을 Redis 단일 메시지 버스로 통합하여 불필요한 네트워크 홉(Hop) 및 장애 지점 축소.
3. **헬스체크 방식 효율화:** 별도의 HTTP `/health` 엔드포인트를 애플리케이션 레벨에서 직접 운영하는 대신, Docker 자체 헬스체크로 가용성을 확인하는 것이 자원·시간적으로 더 효율적.

---

## 3. Options Considered (고려했던 대안들)

### Option A: 기존 FastAPI 중개 레이어 유지
- **장점:** Pydantic 스키마 기반 요청 검증, 명확한 HTTP REST 계약, 동기적 HTTP Status 응답 수신 가능.
- **단점:** 프로세스 상시 구동으로 메모리 점유, 불필요한 네트워크 홉 추가, 파편화된 통신 아키텍처.

### Option B: FastAPI 제거 및 Spring ➔ Redis 직접 LPUSH (선택)
- **장점:** 단일 홉 비동기 통신으로 아키텍처 단순화, 프로세스 및 포트(8000) 제거로 메모리 절약, 의존성 감소.
- **단점:** 동기적 에러 응답 수신 불가(Fire-and-Forget), 메시지 스펙 검증의 암묵화.

---

## 4. Decision (최종 결정)
**Option B 선택.** `api/` 모듈(FastAPI) 전체를 삭제하고, Spring 메인 서버가 Redis List(`bot:commands`)에 직접 `LPUSH`하도록 전환한다.

---

## 5. Consequences (결과 및 영향)

### Positive (개선된 점)
- **리소스 및 배포 단순화:** 상시 구동 프로세스(`uvicorn`) 및 포트(8000) 삭제로 메모리 절약 및 Docker Compose 배포 구조 간소화.
- **신뢰성 향상:** `Spring ➔ Redis` 단일 경로로 변경되어 중간 중개 레이어 장애 가능성 제거.
- **의존성 축소:** `fastapi`, `uvicorn[standard]` 등 모듈 제거로 보안 패치 및 패키지 관리 부담 감소.
- **통신 원칙 확립:** "서비스 간 메시지 전달은 Redis로 통일한다"는 일관된 Event-Driven 원칙 수립.
- **헬스체크 전환:** 애플리케이션 레벨 `/health` 엔드포인트 대신 Docker 자체 헬스체크로 가용성을 확인하도록 전환, 운영 비용 절감.

### Negative & Risks (향후 주의사항 및 리스크)
- **동기 응답 부재 (Fire-and-Forget):** REST 통신과 달리 Spring이 명령의 성공/실패 여부를 즉시 알 수 없음. (추후 실패 처리 필요 시 별도 응답 채널/큐 설계 필요)
- **메시지 스펙 검증의 암묵화:** Pydantic 스키마 검증이 사라졌으므로 `bot/subscriber.py`의 수신 파싱 로직이 유일한 스펙 표준이 됨. 포맷 불일치 시 봇은 경고 로그만 남기고 무시하므로 주의 필요.
- **동시 배포 필수:** Spring의 "Redis 직접 push" 적용과 `api` 모듈 삭제 배포는 **동시 교체**되어야 함. (단차 발생 시 재생 요청 유실 위험)