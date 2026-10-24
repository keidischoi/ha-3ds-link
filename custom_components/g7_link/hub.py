"""사이트 허브 주소 — 플러그인 이름이 바뀌어도 (custom-ha_link → custom-iot_link) 그대로 되게.

새 주소(`/api/plugins/custom-iot_link/hub/`)를 먼저 묻고, 플러그인의 답(`{"ok": …}` JSON)이 아니면
(그 주소가 없음 = 아직 예전 플러그인) 예전 주소(`/api/plugins/custom-ha_link/hub/`)로.
사이트마다 맞은 주소를 기억해 두므로 보통은 한 번만 요청함.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

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


async def server_headers(hass: Any) -> dict[str, str]:
    """0.4.0 이 HA 서버가 누구인지 — 사이트가 HA 서버마다 기기를 나눠 보여 줌 (탭 · 대기 칸).

    X-G7-Server = HA 인스턴스 ID (서버마다 다르고 바뀌지 않음) · X-G7-Server-Name = HA 위치 이름 (설정 › 시스템 › 일반).
    못 얻으면 빈 사전 (사이트는 「서버 이름 없음」으로 둠).
    """
    if hass is None:
        return {}
    try:
        from homeassistant.helpers import instance_id

        sid = await instance_id.async_get(hass)
    except Exception:  # noqa: BLE001 — 머리글만 빠지고 나머지는 그대로
        return {}
    name = str(getattr(getattr(hass, "config", None), "location_name", "") or "Home Assistant")
    return {"X-G7-Server": str(sid).replace("-", "")[:64], "X-G7-Server-Name": quote(name[:60], safe="")}


async def hub_request(session: Any, method: str, site: str, rest: str, *, hass: Any = None, **kwargs: Any) -> aiohttp.ClientResponse:
    """허브 요청 — `rest` 는 경로 뒤쪽 (연결 코드 · /devices …). 마지막 응답을 돌려줌 (본문은 다시 읽을 수 있음).

    0.4.0 `hass` 를 주면 이 HA 서버 머리글을 붙임.
    """
    if hass is not None:
        kwargs["headers"] = {**(await server_headers(hass)), **(kwargs.get("headers") or {})}
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
