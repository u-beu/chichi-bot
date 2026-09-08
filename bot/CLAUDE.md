# chichi-bot/bot Guidelines

## Tech Stack
- Python 3.10+, discord.py, redis-py (asyncio), ffmpeg

## Common Commands
- Run Bot: `python main.py`

## Development Rules
- **Modular Structure:** Use `discord.ext.commands.Cog` to structure bot commands and event listeners.
- **Redis Subscriber:** Run Redis Pub/Sub listener on a dedicated non-blocking asyncio background task (`playback` channel).
- **Metadata Sync:**
    - Use a shared `aiohttp.ClientSession` (managed during bot lifecycle) for REST API calls to `chichi` (Spring).
    - Do NOT create a new HTTP session per request.
- **Audio Streaming:**
    - Utilize `ffmpeg` for voice channel audio processing with proper reconnection options.
    - Safely handle disconnects, channel permission checks, and audio buffer cleanup.
- **Error Handling:** Log Discord API and network errors gracefully without crashing the bot event loop.

## Output Style
- Concise responses only.