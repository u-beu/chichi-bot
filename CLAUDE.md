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
- `bot/`: Discord bot handling user commands and audio playback.
- `api/`: Lightweight FastAPI management server.
- `worker/`: PyTorch-based AI inference engine for audio analysis.
- Place unit/integration tests under the `tests/` directory mirroring the project structure (e.g., `tests/api/`, `tests/worker/`).

## Core Architecture Rules
- **Shared Session:** Maintain a single shared `aiohttp.ClientSession` across the bot runtime. NEVER instantiate new sessions per HTTP request.
- **Async & Non-blocking:** All I/O operations must be non-blocking (`async/await`). Offload heavy CPU-bound tasks to worker processes.
- **Memory Management:** Strictly enforce memory boundaries for the 8GB RAM environment across all sub-modules.

## Output Style
- Concise responses only.

# Output Instructions

## Pull Request Guidelines
- When creating or updating Pull Requests (`gh pr create`, `gh pr edit`), DO NOT include session links or automated signatures at the bottom of the PR description (e.g., `https://claude.ai/code/session_...`).