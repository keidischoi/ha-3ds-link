"""허브 주소 고르기 검사 (Home Assistant 없이) — python3 tests/test_hub.py  (aiohttp 필요)

사이트가 ① 예전 플러그인(custom-ha_link)만 ② 새 플러그인(custom-iot_link — 예전 주소도 받음) 일 때
새 주소를 먼저 묻고, 없으면 예전 주소로 가는지 · 틀린 연결 코드(플러그인의 404 {"ok": false})는 그대로 돌려주는지.
"""

import asyncio
import importlib
import pathlib
import sys
import types

from aiohttp import ClientSession, web

ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "g7_link"
pkg = types.ModuleType("g7_link")
pkg.__path__ = [str(ROOT)]  # __init__.py(Home Assistant 필요)를 건너뜀
sys.modules["g7_link"] = pkg
hub = importlib.import_module("g7_link.hub")
const = importlib.import_module("g7_link.const")

CODE = "a" * 32
passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    print(("ok   " if ok else "FAIL ") + label)
    passed, failed = passed + ok, failed + (not ok)


def site_app(plugin_ids: list[str], seen: list[str]) -> web.Application:
    app = web.Application()

    async def handler(req: web.Request) -> web.Response:
        seen.append(f"{req.method} {req.path}")
        if req.match_info["code"] != CODE:
            return web.json_response({"ok": False, "message": "연결 코드가 맞지 않아요."}, status=404)
        return web.json_response({"ok": True, "via": req.path.split("/")[3]})

    for pid in plugin_ids:
        base = f"/api/plugins/{pid}/hub/{{code}}"
        app.router.add_get(base, handler)
        app.router.add_post(base + "/devices", handler)
        app.router.add_delete(base + "/devices/{id}", handler)
    return app


async def run_site(plugin_ids: list[str]):
    seen: list[str] = []
    runner = web.AppRunner(site_app(plugin_ids, seen))
    await runner.setup()
    tcp = web.TCPSite(runner, "127.0.0.1", 0)
    await tcp.start()
    port = tcp._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}", seen


async def main() -> None:
    check(const.HUB_PATHS == ("/api/plugins/custom-iot_link/hub/", "/api/plugins/custom-ha_link/hub/"), "새 주소 먼저 · 예전 주소 다음")
    async with ClientSession() as s:
        # ① 예전 플러그인만
        runner, site, seen = await run_site(["custom-ha_link"])
        r = await hub.hub_request(s, "GET", site, CODE)
        d = await r.json()
        check(r.status == 200 and d["via"] == "custom-ha_link" and len(seen) == 1, "예전 플러그인만: 새 주소가 없으면 예전 주소로")
        seen.clear()
        r = await hub.hub_request(s, "POST", site, f"{CODE}/devices", json={"name": "x"})
        check(r.status == 200 and seen == [f"POST /api/plugins/custom-ha_link/hub/{CODE}/devices"], "맞았던 주소를 기억 (두 번째부터 한 번만)")
        r = await hub.hub_request(s, "GET", site, "b" * 32)
        check(r.status == 404 and (await r.json())["ok"] is False, "틀린 연결 코드는 플러그인의 404 그대로")
        await runner.cleanup()
        # ② 새 플러그인 (예전 주소도 받음)
        runner, site2, seen2 = await run_site(["custom-iot_link", "custom-ha_link"])
        r = await hub.hub_request(s, "DELETE", site2, f"{CODE}/devices/3")
        check(r.status == 200 and (await r.json())["via"] == "custom-iot_link" and len(seen2) == 1, "새 플러그인: 새 주소로 한 번에")
        seen2.clear()
        r = await hub.hub_request(s, "GET", site2, "b" * 32)
        check(r.status == 404 and len(seen2) == 1, "새 플러그인 + 틀린 코드: 예전 주소로 다시 묻지 않음")
        await runner.cleanup()
        # ②-1 예전 플러그인만인데 새 주소에 HTML 화면(200)이 나오는 사이트
        app = site_app(["custom-ha_link"], [])

        async def html(req: web.Request) -> web.Response:
            return web.Response(text="<html>spa</html>", content_type="text/html")

        app.router.add_get("/api/plugins/custom-iot_link/hub/{code}", html)
        r4 = web.AppRunner(app)
        await r4.setup()
        t4 = web.TCPSite(r4, "127.0.0.1", 0)
        await t4.start()
        site4 = f"http://127.0.0.1:{t4._server.sockets[0].getsockname()[1]}"
        r = await hub.hub_request(s, "GET", site4, CODE)
        check(r.status == 200 and (await r.json())["via"] == "custom-ha_link", "새 주소가 플러그인 답이 아니면(HTML) 예전 주소로")
        await r4.cleanup()
        # ③ 둘 다 없음
        runner, site3, seen3 = await run_site([])
        r = await hub.hub_request(s, "GET", site3, CODE)
        check(r.status == 404 and len(seen3) == 0, "플러그인이 없으면 404 (연결 코드 틀림과 같게)")
        await runner.cleanup()


asyncio.run(main())
print(f"\n통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
