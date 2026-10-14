# chichi-bot/worker Guidelines

## Tech Stack
- Python 3.10+, PyTorch, Transformers, Librosa, NumPy, Redis, yt-dlp, ffmpeg (오디오 디코딩용 바이너리 필수)

## Common Commands
- Run Worker: `python -m worker.main`
- Run Worker (Docker): `docker build --build-arg TARGET=worker`로 worker 이미지를 빌드(기본값 `TARGET=bot`은 bot 이미지)하고 실행 명령을 `python -m worker.main`으로 지정. 모델 재다운로드 방지를 위해 `-v <volume>:/root/.cache/huggingface` 마운트

## Development Rules
- **Model Inference:** 사전학습 AST AudioSet 모델(`MIT/ast-finetuned-audioset-10-10-0.4593`) 단일 모델로 장르 및 분위기(genre/mood) 태깅 수행
  - AudioSet 527 클래스 중 `GENRE_LABELS`/`MOOD_LABELS` 부분집합 logits만 골라 argmax
  - 30초 음원을 10초씩 최대 3조각으로 분할해 각각 추론 후 logits 평균. 마지막 조각이 5초 미만이면(첫 조각 제외) 제외
- **Queue & Async Execution:**
  - Redis Queue(`BRPOP` 등) 기반 비동기 작업 수신
  - 메인 런타임 블로킹 방지를 위해 단일 분석 프로세스(`ProcessPoolExecutor(max_workers=1)`)에서 실행 (동시 분석 1건)
  - `SIGTERM`/`SIGINT` 수신 시 구독 태스크 취소 후 Redis client 및 분석 프로세스 정리
  - `BRPOP` 이후 크래시 시 해당 요청은 유실됨 (알려진 한계)
  - 결과 큐 발행(`LPUSH`) 실패 시 해당 결과는 로그만 남기고 유실됨 (알려진 한계)
  - 종료 시 `_shutdown_executor()`가 `wait=True`로 진행 중인 분석이 끝날 때까지 대기 (알려진 한계)
- **Queue Schema (Redis List):**
  - 요청: `worker:analysis-requests` (`WORKER_QUEUE_KEY`) <- `{"videoId": str}`
  - 결과: `spring:analysis-results` (`SPRING_ANALYSIS_QUEUE_KEY`) -> 성공 `{"videoId", "genre", "mood"}` / 실패 `{"videoId", "error"}`
  - 실패 결과의 `error`는 예외 클래스명(예: `AudioSourceError`, `AudioDecodingError`)만 전달하며 예외 메시지·스트리밍 URL은 포함하지 않음
  - JSON 형식 오류 또는 `videoId` 누락/비문자열 요청은 경고 로그 후 폐기 (결과 미발행)
- **Environment Variables:**
  - `WORKER_QUEUE_KEY`: 분석 요청 큐 키 (기본값 `worker:analysis-requests`)
  - `SPRING_ANALYSIS_QUEUE_KEY`: 분석 결과 큐 키 (기본값 `spring:analysis-results`)
- **Resource Limits (for 8GB RAM Mac):**
  - 대기 상태(idle) RAM 사용량 1.5 GB 이하 유지
  - 컴퓨팅 디바이스 동적 선택: Apple Silicon GPU(`mps`) 최우선 지정, 불가 시 `cuda`, 그다음 CPU Fallback
- **Memory & Resource Management:**
  - **torch.no_grad():** 그래디언트 메모리 할당 방지를 위해 모든 추론 루틴에 `@torch.no_grad()` 또는 `with torch.no_grad():` 강제 적용
  - **Memory Cleanup:** 오디오 배치 처리 직후 가비지 컬렉션(`gc.collect()`) 호출 및 GPU 캐시(`torch.mps.empty_cache()` / `torch.cuda.empty_cache()`) 정리
  - **Lazy Import:** 부모(subscriber) 프로세스는 `torch`/`transformers`/`librosa`를 import하지 않음. `analyze_video` 내부에서 지연 import하여 분석 자식 프로세스에서만 로드
  - **Model Unload:** 요청 없이 600초(`IDLE_UNLOAD_SEC`) 경과 시 분석 프로세스를 종료해 모델 가중치 RAM 언로드 (다음 요청 시 재생성)
- **Audio Processing Pipeline & Data Flow:**
  - 비압축 전체 길이 오디오의 RAM 일괄 로드 엄격 금지
  - 오디오 로드 시 30초 고정 슬라이싱 및 낮은 샘플링 레이트 리샘플링 (`librosa.load(..., duration=30, sr=16000)`, AST 입력 요건)
  - Librosa/NumPy/`ASTFeatureExtractor` 전처리 결과(`np.ndarray`) -> PyTorch Tensor(`torch.Tensor`) 변환 시 `torch.from_numpy()` 사용 및 `float32` 명시적 캐스팅
  - 오디오 전처리 파이프라인과 PyTorch 추론 모델의 명확한 분리
- **Error Handling & Resilience:**
  - 손상 파일/미지원 포맷 등 분석 실패 시 `try-except` 예외 처리 및 로깅 후 결과 큐에 `{"videoId", "error"}` 발행하고 태스크 안전 건너뛰기 (워커 프로세스 중단 금지)
  - 분석 프로세스 비정상 종료(`BrokenProcessPool`) 시 풀 폐기 후 다음 요청에서 재생성
  - 오디오 디코딩 실패 메시지의 URL은 `<url>`로 마스킹하고 원본 예외 체인을 차단해 로그에도 스트리밍 URL을 남기지 않음
  - Python `logging` 모듈 기반 처리 상태 및 에러 기록