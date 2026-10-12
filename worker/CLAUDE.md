# chichi-bot/worker Guidelines

## Tech Stack
- Python 3.10+, PyTorch, Librosa, NumPy, Redis, yt-dlp

## Common Commands
- Run Worker: `python -m worker.main`

## Development Rules
- **Model Inference:** 경량화 모델 기반 음악 분류, 특징 추출(Spectrogram/MFCC), 장르 및 분위기(genre/mood) 태깅 수행
- **Queue & Async Execution:**
  - Redis Queue(`BRPOP` 등) 기반 비동기 작업 수신
  - 메인 런타임 블로킹 방지를 위해 격리된 워커 프로세스/스레드에서 실행
- **Resource Limits (for 8GB RAM Mac):**
  - 대기 상태(idle) RAM 사용량 1.5 GB 이하 유지
  - 컴퓨팅 디바이스 동적 선택: Apple Silicon GPU(`mps`) 최우선 지정, 불가 시 CPU Fallback
- **Memory & Resource Management:**
  - **torch.no_grad():** 그래디언트 메모리 할당 방지를 위해 모든 추론 루틴에 `@torch.no_grad()` 또는 `with torch.no_grad():` 강제 적용
  - **Memory Cleanup:** 오디오 배치 처리 직후 가비지 컬렉션(`gc.collect()`) 호출 및 GPU 캐시(`torch.mps.empty_cache()` / `torch.cuda.empty_cache()`) 정리
  - **Model Unload:** 장시간 대기 상태 전환 시 대용량 모델 가중치 RAM 언로드
- **Audio Processing Pipeline & Data Flow:**
  - 비압축 전체 길이 오디오의 RAM 일괄 로드 엄격 금지
  - 오디오 로드 시 최대 30–60초 슬라이싱 및 낮은 샘플링 레이트 리샘플링 (`librosa.load(..., duration=30, sr=22050)`)
  - Librosa/NumPy 전처리 결과(`np.ndarray`) -> PyTorch Tensor(`torch.Tensor`) 변환 시 `torch.from_numpy()` 사용 및 `float32` 명시적 캐스팅
  - 오디오 전처리 파이프라인과 PyTorch 추론 모델의 명확한 분리
- **Error Handling & Resilience:**
  - 손상 파일/미지원 포맷 처리 시 `try-except` 예외 처리 및 로깅 후 태스크 안전 건너뛰기 (워커 프로세스 중단 금지)
  - Python `logging` 모듈 기반 처리 상태 및 에러 기록