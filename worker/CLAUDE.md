# chichi-bot/worker Guidelines

## Tech Stack
- Python 3.10+, PyTorch, Librosa, NumPy, Redis

## Common Commands
- Worker 실행: `python -m worker.main`

## Development Rules
- **Model Inference:** 경량화된 모델을 사용하여 음악 분류, 특징 추출(Spectrogram/MFCC), 장르 및 분위기(genre/mood) 태깅 작업 수행.
- **Queue & Async Execution:** Redis List/Queue(`BRPOP` 등)를 기반으로 작업 요청을 비동기 수신하며, 메인 보트/API 런타임의 블로킹을 방지하기 위해 격리된 워커 프로세스/스레드에서 실행.
- **Resource Limits (for 8GB RAM Mac):**
    - 대기 상태(idle)의 RAM 사용량을 1.5 GB 이하로 유지할 것.
    - 컴퓨팅 디바이스를 동적으로 선택할 것: 사용 가능한 경우 `mps` (Apple Silicon GPU)를 최우선으로 지정하고, 없을 경우 `cpu`로 릴리즈(fallback) 처리.
- **Memory & Resource Management:**
    - 그래디언트 메모리 할당을 방지하기 위해 **모든** 추론(Inference) 루틴에 `@torch.no_grad()` 또는 `with torch.no_grad():`를 강제 적용할 것.
    - 오디오 배치(batch) 처리가 끝난 직후 명시적으로 가비지 컬렉션(`gc.collect()`)을 호출하고 GPU/캐시(`torch.mps.empty_cache()` 또는 `torch.cuda.empty_cache()`)를 비울 것.
    - 워커가 장시간 대기 상태일 때는 메모리 부하가 큰 모델 가중치(weights)를 RAM에서 언로드(Unload)할 것.
- **Audio Processing Pipeline & Data Flow:**
    - 비압축 전체 길이 오디오를 RAM에 통째로 로드하는 행위를 엄격히 금지할 것.
    - 오디오 로드 시 최대 **30–60초** 길이로 슬라이싱하고, 낮춘 타겟 샘플링 레이트(예: `sr=22050` 또는 `16000`)로 리샘플링할 것 (`librosa.load(..., duration=30, sr=22050)`).
    - Librosa/NumPy 전처리 결과(`np.ndarray`)를 PyTorch 입력(`torch.Tensor`)으로 변환 시 `torch.from_numpy()`를 사용하고, `float32` 캐스팅을 명시할 것.
    - 오디오 전처리 파이프라인과 PyTorch 추론 모델을 명확히 분리할 것.
- **Error Handling & Resilience:**
    - 손상된 오디오 파일이나 지원되지 않는 포맷 처리 시 워커 프로세스가 중단되지 않도록 `try-except` 예외 처리를 수행하고, 에러 로그 남김 후 해당 태스크를 안전하게 건너뛸 것.
    - 모든 작업 수행 시 Python `logging` 모듈을 사용하여 처리 상태 및 에러 기록.