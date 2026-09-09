"""
send_play_history()의 "매 호출마다 새 aiohttp.ClientSession() 생성" vs
"세션 하나를 재사용" 방식의 지연시간을 로컬 mock 서버 기준으로 실측 비교한다.

운영 서버(https://ub-chichi.site)를 호출하지 않으므로 부작용이 없다.

실행:
    python scripts/bench_session.py
"""
import asyncio
import statistics
import time

from aiohttp import web, ClientSession

HOST = "127.0.0.1"
N = 200


async def handle_post(request: web.Request) -> web.Response:
    await request.json()
    return web.json_response({"ok": True})


async def start_mock_server():
    app = web.Application()
    app.router.add_post("/api/bot/recent-played-song", handle_post)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HOST, 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://{HOST}:{port}/api/bot/recent-played-song"


PAYLOAD = {
    "title": "bench-title",
    "uploader": "bench-uploader",
    "image": "null",
    "videoId": "bench-video-id",
    "discordId": 123456789,
}


async def scenario_new_session_per_call(url: str, n: int) -> list[float]:
    """변경 전: 매 호출마다 ClientSession() 생성 -> POST 1회 -> close."""
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        async with ClientSession() as session:
            async with session.post(url, json=PAYLOAD) as resp:
                await resp.json()
        samples.append((time.perf_counter() - start) * 1000)
    return samples


async def scenario_shared_session(url: str, n: int) -> list[float]:
    """변경 후: 세션 1개를 재사용해 N회 POST."""
    samples = []
    async with ClientSession() as session:
        for _ in range(n):
            start = time.perf_counter()
            async with session.post(url, json=PAYLOAD) as resp:
                await resp.json()
            samples.append((time.perf_counter() - start) * 1000)
    return samples


def report(name: str, samples: list[float]) -> float:
    total = sum(samples)
    mean = statistics.mean(samples)
    stdev = statistics.stdev(samples)
    print(f"[{name}] N={len(samples)} 총={total:.2f}ms 평균={mean:.4f}ms/req stdev={stdev:.4f}ms")
    return mean


async def main():
    runner, url = await start_mock_server()
    try:
        # 워밍업 (서버/이벤트루프 초기 콜드스타트 배제)
        await scenario_shared_session(url, 10)

        before = await scenario_new_session_per_call(url, N)
        after = await scenario_shared_session(url, N)

        mean_before = report("변경 전: 매번 새 세션", before)
        mean_after = report("변경 후: 세션 재사용", after)

        improvement = (1 - mean_after / mean_before) * 100
        print(f"\n요청당 평균 지연시간 개선: {mean_before:.4f}ms -> {mean_after:.4f}ms ({improvement:.1f}% 감소)")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
