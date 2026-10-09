"""3ds 연결 — Home Assistant 의 온습도 · 기기 상태 · 카메라 사진을 G7 사이트(HA 연결 플러그인)로 보냄.

통합 하나 = 사이트의 기기 하나. 사이트가 이 Home Assistant 로 접속하는 일은 없고, 여기서 보내기만 함.
 - 10분마다 (사이트가 알려 준 간격) 값을 한 번
 - 상태 엔티티가 바뀌면 조금 뒤 한 번 더
 - 카메라를 골랐으면 가동 중일 때만 작은 사진 한 장
"""

from __future__ import annotations

from datetime import timedelta
import io
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CAMERA,
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_PUSH_URL,
    CONF_SITE,
    CONF_STATE,
    DEFAULT_INTERVAL_MIN,
    DEFAULT_SNAP_GAP_MIN,
    DEFAULT_SNAP_MAX,
    DOMAIN,
    HUB_PATH,
    ON_STATES,
    PAYLOAD_KEYS,
    SKIP_STATES,
    SNAP_WIDTH,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """통합 하나(= 기기 하나)를 시작."""
    pusher = Pusher(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = pusher
    pusher.start()
    entry.async_on_unload(pusher.stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """통합을 지우면 사이트의 기기도 지움 (안 되면 사이트 화면에서 지우면 됨)."""
    data = entry.data
    url = f"{data.get(CONF_SITE, '')}{HUB_PATH}{data.get(CONF_CODE, '')}/devices/{data.get(CONF_DEVICE_ID, 0)}"
    try:
        await async_get_clientsession(hass).delete(url, timeout=_TIMEOUT)
    except (aiohttp.ClientError, TimeoutError) as err:
        _LOGGER.debug("G7: 사이트의 기기를 지우지 못함: %s", err)


class Pusher:
    """값을 모아 사이트로 보냄."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.conf: dict[str, Any] = {**entry.data, **entry.options}
        self.title = entry.title
        self.push_url: str = self.conf.get(CONF_PUSH_URL, "")
        self.interval = max(1, int(self.conf.get("interval_min") or DEFAULT_INTERVAL_MIN))
        self.snap_gap = max(1, int(self.conf.get("snap_gap_min") or DEFAULT_SNAP_GAP_MIN))
        self.snap_max = int(self.conf.get("snap_max") or DEFAULT_SNAP_MAX)
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce: CALLBACK_TYPE | None = None
        self._last_snap = None

    @callback
    def start(self) -> None:
        self._unsubs.append(async_track_time_interval(self.hass, self._tick, timedelta(minutes=self.interval)))
        state_entity = self.conf.get(CONF_STATE)
        if state_entity:
            self._unsubs.append(async_track_state_change_event(self.hass, [state_entity], self._changed))
        # 켜고 조금 뒤 한 번 — 사이트 화면이 바로 🟢 로 바뀌게
        self._unsubs.append(async_call_later(self.hass, 20, self._tick))

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._debounce is not None:
            self._debounce()
            self._debounce = None

    @callback
    def _changed(self, event: Event) -> None:
        """상태가 바뀌면 5초 뒤에 한 번 (잇따라 바뀌면 마지막 것만)."""
        if self._debounce is not None:
            self._debounce()
        self._debounce = async_call_later(self.hass, 5, self._tick)

    async def _tick(self, _now: Any = None) -> None:
        self._debounce = None
        await self._push_values()
        await self._push_snapshot()

    def _value(self, key: str) -> str | None:
        entity_id = self.conf.get(key)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or str(state.state).lower() in SKIP_STATES:
            return None
        return str(state.state)

    async def _push_values(self) -> None:
        payload = {name: val for key, name in PAYLOAD_KEYS.items() if (val := self._value(key)) is not None}
        if not payload or not self.push_url:
            return
        try:
            resp = await async_get_clientsession(self.hass).post(self.push_url, json=payload, timeout=_TIMEOUT)
            if resp.status >= 400:
                _LOGGER.debug("G7 %s: 사이트가 받지 않음 (%s)", self.title, resp.status)
            resp.release()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("G7 %s: 보내지 못함: %s", self.title, err)

    def _running(self) -> bool:
        """상태 엔티티가 없으면 늘 보냄, 있으면 가동 중일 때만."""
        if not self.conf.get(CONF_STATE):
            return True
        val = self._value(CONF_STATE)
        return val is not None and val.lower() in ON_STATES

    async def _push_snapshot(self) -> None:
        camera_entity = self.conf.get(CONF_CAMERA)
        if not camera_entity or not self.push_url or not self.conf.get("snapshot", True) or not self._running():
            return
        now = dt_util.utcnow()
        if self._last_snap is not None and (now - self._last_snap) < timedelta(minutes=self.snap_gap):
            return
        try:
            from homeassistant.components.camera import async_get_image  # 카메라 통합이 없는 집에서도 켜지게 여기서 불러옴

            image = await async_get_image(self.hass, camera_entity, timeout=10, width=SNAP_WIDTH)
            content = await self.hass.async_add_executor_job(_small_jpeg, image.content, self.snap_max)
            if content is None:
                _LOGGER.debug("G7 %s: 사진을 작은 JPEG 로 만들지 못함", self.title)
                return
            resp = await async_get_clientsession(self.hass).post(
                f"{self.push_url}/snap", data=content, headers={"Content-Type": "image/jpeg"}, timeout=_TIMEOUT
            )
            if resp.status < 400:
                self._last_snap = now
            resp.release()
        except Exception as err:  # noqa: BLE001 — 카메라 종류마다 내는 오류가 달라 넓게 잡음 (사진은 없어도 됨)
            _LOGGER.debug("G7 %s: 사진을 보내지 못함: %s", self.title, err)


def _small_jpeg(content: bytes, limit: int) -> bytes | None:
    """가로 640 안쪽의 JPEG 로 (Pillow — Home Assistant 에 들어 있음). 이미 작고 JPEG 이면 그대로."""
    is_jpeg = content[:3] == b"\xff\xd8\xff"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(content)) as img:
            if is_jpeg and len(content) <= limit and img.width <= SNAP_WIDTH * 2:
                return content
            img = img.convert("RGB")
            if img.width > SNAP_WIDTH:
                img = img.resize((SNAP_WIDTH, max(1, round(img.height * SNAP_WIDTH / img.width))))
            for quality in (75, 60, 45):
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=quality)
                if out.tell() <= limit:
                    return out.getvalue()
    except Exception:  # noqa: BLE001
        pass
    return content if is_jpeg and len(content) <= limit else None
