"""사이트 허브 주소 — 플러그인 이름이 바뀌어도 (custom-ha_link → custom-iot_link) 그대로 되게.

새 주소(`/api/plugins/custom-iot_link/hub/`)를 먼저 묻고, 플러그인의 답(`{"ok": …}` JSON)이 아니면
(그 주소가 없음 = 아직 예전 플러그인) 예전 주소(`/api/plugins/custom-ha_link/hub/`)로.
사이트마다 맞은 주소를 기억해 두므로 보통은 한 번만 요청함.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import HUB_PATHS

# 사이트 주소 => 맞았던 허브 경로
_WORKED: dict[str, str] = {}


def _order(site: str) -> list[str]:
    first = _WORKED.get(site)
    return [first, *[p for p in HUB_PATHS if p != first]] if first else list(HUB_PATHS)


async def _is_plugin_answer(resp: aiohttp.ClientResponse) -> bool:
    """플러그인이 답한 것인지 (404 = 연결 코드가 틀림도 포함) — 본문 {"ok": …}."""
    try:
        data = await resp.json(content_type=None)
    except (ValueError, aiohttp.ClientError):
        return False
    return isinstance(data, dict) and "ok" in data


async def hub_request(session: Any, method: str, site: str, rest: str, **kwargs: Any) -> aiohttp.ClientResponse:
    """허브 요청 — `rest` 는 경로 뒤쪽 (연결 코드 · /devices …). 마지막 응답을 돌려줌 (본문은 다시 읽을 수 있음)."""
    paths = _order(site)
    resp: aiohttp.ClientResponse | None = None
    for i, path in enumerate(paths):
        resp = await session.request(method, f"{site}{path}{rest}", **kwargs)
        found = await _is_plugin_answer(resp)   # 플러그인은 늘 {"ok": …} 로 답함 (아니면 그 주소가 없음 · 다른 화면)
        if found:
            _WORKED[site] = path
        if found or i == len(paths) - 1:
            return resp
        resp.release()
    assert resp is not None
    return resp
