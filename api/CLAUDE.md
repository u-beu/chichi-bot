# chichi-bot/api Guidelines

## Tech Stack
- Python 3.10+, FastAPI, Uvicorn, Pydantic v2

## Common Commands
- Run Server: `uvicorn main:app --reload --port 8000`

## Development Rules
- **Role:** Provide lightweight REST endpoints for service health checks and manual trigger tasks for `worker`.
- **Lightweight Process:** NEVER load heavy PyTorch models directly inside this API process. Delegate ML/DL tasks asynchronously.
- **Router Structure:** Modularize endpoints using `fastapi.APIRouter` (e.g., `routers/health.py`, `routers/worker.py`). Do not pollute `main.py`.
- **Validation:** Use Pydantic v2 models for request validation and response schemas with explicit type hints.
- **Async Endpoints:** Declare endpoint handlers with `async def`. For CPU-bound or blocking operations, execute via background tasks or external queues.
- **CORS & Middleware:** Configure CORS middleware explicitly to allow internal requests from `chichi` (Spring) and local environments.

## Output Style
- Concise responses only.