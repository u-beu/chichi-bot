# chichi-bot/worker Guidelines

## Tech Stack
- Python 3.10+, PyTorch, Librosa, NumPy

## Common Commands
- Run Worker: `python worker.py`

## Development Rules
- **Model Inference:** Perform music classification, feature extraction (Spectrogram/MFCC), and genre/mood tagging tasks using lightweight models.
- **Resource Limits (for 8GB RAM Mac):**
    - Keep idle RAM footprint under 1.5 GB.
    - Dynamically select compute devices: prioritize `mps` (Apple Silicon GPU) when available, falling back to `cpu`.
- **Memory & Resource Management:**
    - Enforce `@torch.no_grad()` or `with torch.no_grad():` on ALL inference routines to prevent gradient memory allocation.
    - Explicitly trigger Garbage Collection (`gc.collect()`) and clear cache (`torch.cuda.empty_cache()` or `mps` equivalents) right after processing each audio batch.
    - Unload heavy model weights from RAM when the worker is idle for extended periods.
- **Audio Processing Optimization:**
    - NEVER load full-length uncompressed audio into RAM.
    - Slice audio to a maximum duration of **30–60 seconds** and resample to a lower target rate (e.g., `sr=22050` or `16000`) on load (`librosa.load(..., duration=30, sr=22050)`).
    - Separate audio preprocessing pipelines from PyTorch inference models.
- **Execution & Isolation:** Run inference in isolated worker processes/threads to keep the main bot/API runtimes responsive and non-blocking.

## Output Style
- Concise responses only.