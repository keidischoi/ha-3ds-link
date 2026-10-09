"""3ds — Home Assistant 의 온습도 · 기기 상태 · 카메라 사진을 G7 사이트(HA 연결 플러그인)로 보냄.

통합 하나 = 사이트의 기기 하나. 사이트가 이 Home Assistant 로 접속하는 일은 없고, 여기서 보내기만 함.

보내는 방식은 사이트 관리자가 정함 (켤 때 · 값을 보낼 때마다 사이트가 알려 줌):
 - change  값이 변하면 보냄 (습도 · 온도가 정한 만큼 변했을 때, 너무 잦지 않게 최소 간격) + 변화가 없어도 가끔 한 번
 - interval 정한 주기마다 보냄
 어느 쪽이든 상태 엔티티(프린터 상태 · 스위치)가 바뀌면 조금 뒤 바로 한 번, 카메라를 골랐으면 가동 중일 때 작은 사진 한 장.

Home Assistant 가 올라가도 덜 흔들리게: 오래 유지돼 온 기본 기능(상태 읽기 · 타이머 · 상태 변화 듣기 · 웹 요청)만 쓰고,
버전에 따라 달라질 수 있는 것(카메라 · 사진 줄이기)은 따로 감싸 실패해도 값 보내기는 계속 됨.
"""

from __future__ import annotations

from datetime import timedelta
import io
import logging
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)

from .const import (
    CONF_CAMERA,
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_HUM,
    CONF_INTERVAL,
    CONF_PUSH_URL,
    CONF_SITE,
    CONF_STATE,
    CONF_TEMP,
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
_NET_ERRORS = (aiohttp.ClientError, TimeoutError, OSError)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """통합 하나를 시작 — 기기 하나짜리, 또는 한꺼번에 연결한 기기 여러 대."""
    conf: dict[str, Any] = {**entry.data, **entry.options}
    devices = conf.get(CONF_DEVICES)
    if isinstance(devices, list) and devices:
        shared = {k: v for k, v in conf.items() if k != CONF_DEVICES}
        confs = [{**shared, **d} for d in devices if isinstance(d, dict)]
    else:
        confs = [conf]
    pushers = [Pusher(hass, str(c.get("name") or entry.title), c, first=20 + i * 3) for i, c in enumerate(confs)]
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = pushers
    for pusher in pushers:
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
    devices = data.get(CONF_DEVICES)
    ids = [d.get(CONF_DEVICE_ID) for d in devices if isinstance(d, dict)] if isinstance(devices, list) and devices else [data.get(CONF_DEVICE_ID, 0)]
    for device_id in ids:
        url = f"{data.get(CONF_SITE, '')}{HUB_PATH}{data.get(CONF_CODE, '')}/devices/{device_id or 0}"
        try:
            resp = await async_get_clientsession(hass).delete(url, timeout=_TIMEOUT)
            resp.release()
        except _NET_ERRORS as err:
            _LOGGER.debug("3ds: 사이트의 기기를 지우지 못함: %s", err)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


class Pusher:
    """값을 모아 사이트로 보냄."""

    def __init__(self, hass: HomeAssistant, title: str, conf: dict[str, Any], first: int = 20) -> None:
        self.hass = hass
        self.conf: dict[str, Any] = conf
        self.title = title
        self._first = first  # 켠 뒤 처음 보낼 때까지 (초) — 기기가 여러 대면 조금씩 엇갈리게
        self.push_url: str = self.conf.get(CONF_PUSH_URL, "") or ""
        # 사이트가 정한 것 (만들 때 받아 둔 값으로 시작 → 켠 뒤 · 값을 보낼 때마다 사이트의 답으로 고침)
        self.mode: str = str(self.conf.get("send_mode") or "interval")
        self.delta_hum = float(self.conf.get("change_hum") or 1)
        self.delta_temp = float(self.conf.get("change_temp") or 0.5)
        self.gap = max(10, _int(self.conf.get("gap_sec"), 60))
        self.snap_gap = max(1, _int(self.conf.get("snap_gap_min"), DEFAULT_SNAP_GAP_MIN))
        self.snap_max = _int(self.conf.get("snap_max"), DEFAULT_SNAP_MAX)
        # 정해진 때마다 한 번 보내는 주기 (분) = 사이트가 알려 준 것과 내가 고른 것 중 긴 쪽
        self.interval = max(1, _int(self.conf.get("interval_min"), DEFAULT_INTERVAL_MIN), _int(self.conf.get(CONF_INTERVAL), 0))
        self._unsubs: list[Any] = []
        self._unsub_interval: Any = None
        self._debounce: Any = None
        self._pending: Any = None
        self._last_push = 0.0
        self._sent: dict[str, float] = {}
        self._last_snap = 0.0
        self._snap_ok = True  # 사이트가 「지금은 사진을 받지 않음」이라 하면 False (회원이 사이트를 안 보는 동안)

    # ── 켜고 끄기 ──

    @callback
    def start(self) -> None:
        self._set_interval(self.interval, force=True)
        self._unsubs.append(async_call_later(self.hass, 5, self._refresh_site))
        state_entity = self.conf.get(CONF_STATE)
        if state_entity:
            self._unsubs.append(async_track_state_change_event(self.hass, [state_entity], self._state_changed))
        values = [e for e in (self.conf.get(CONF_HUM), self.conf.get(CONF_TEMP)) if e]
        if values:
            self._unsubs.append(async_track_state_change_event(self.hass, values, self._value_changed))
        if self.conf.get(CONF_CAMERA):
            # 사진은 값과 따로 — 1분마다 「보낼 때가 됐나」만 보고, 실제로는 정한 간격에 한 장
            self._unsubs.append(async_track_time_interval(self.hass, self._snap_tick, timedelta(minutes=1)))
        # 켜고 조금 뒤 한 번 — 사이트 화면이 바로 🟢 로 바뀌게
        self._unsubs.append(async_call_later(self.hass, self._first, self._tick))

    @callback
    def stop(self) -> None:
        for unsub in self._unsubs:
            self._cancel(unsub)
        self._unsubs.clear()
        for name in ("_unsub_interval", "_debounce", "_pending"):
            self._cancel(getattr(self, name))
            setattr(self, name, None)

    @staticmethod
    def _cancel(unsub: Any) -> None:
        if unsub is None:
            return
        try:
            unsub()
        except Exception:  # noqa: BLE001 — 이미 끝난 타이머를 다시 끄는 것은 괜찮음
            pass

    @callback
    def _set_interval(self, minutes: int, force: bool = False) -> None:
        minutes = max(1, int(minutes))
        if not force and minutes == self.interval and self._unsub_interval is not None:
            return
        self.interval = minutes
        self._cancel(self._unsub_interval)
        self._unsub_interval = async_track_time_interval(self.hass, self._tick, timedelta(minutes=minutes))

    # ── 사이트가 정한 것 받기 ──

    @callback
    def _apply_site(self, data: dict[str, Any]) -> None:
        """사이트의 답(허브 · 값을 받은 답)에 든 것만 고침 — 없는 것은 예전 값 그대로."""
        if "snap" in data:
            self._snap_ok = bool(data.get("snap"))
        if data.get("mode") in ("change", "interval"):
            self.mode = str(data["mode"])
        elif data.get("send_mode") in ("change", "interval"):
            self.mode = str(data["send_mode"])
        hum = _float(data.get("change_hum"))
        if hum is not None and hum > 0:
            self.delta_hum = hum
        temp = _float(data.get("change_temp"))
        if temp is not None and temp > 0:
            self.delta_temp = temp
        if data.get("gap_sec") is not None:
            self.gap = max(10, _int(data.get("gap_sec"), self.gap))
        if data.get("snap_gap_min") is not None:
            self.snap_gap = max(1, _int(data.get("snap_gap_min"), self.snap_gap))
        site = _int(data.get("next_min"), 0)
        if site >= 1:
            self._set_interval(max(site, _int(self.conf.get(CONF_INTERVAL), 0)))

    async def _refresh_site(self, _now: Any = None) -> None:
        """켠 뒤 한 번 — 관리자가 바꾼 방식 · 주기를 받아 옴 (안 되면 예전 값 그대로)."""
        url = f"{self.conf.get(CONF_SITE, '')}{HUB_PATH}{self.conf.get(CONF_CODE, '')}"
        try:
            resp = await async_get_clientsession(self.hass).get(url, timeout=_TIMEOUT)
            if resp.status != 200:
                resp.release()
                return
            data = await resp.json(content_type=None)
        except (*_NET_ERRORS, ValueError):
            return
        if isinstance(data, dict) and data.get("ok"):
            self._apply_site(data)

    # ── 언제 보낼지 ──

    @callback
    def _state_changed(self, _event: Any) -> None:
        """상태(출력 시작 · 끝, 스위치)가 바뀌면 5초 뒤에 한 번 (잇따라 바뀌면 마지막 것만)."""
        self._cancel(self._debounce)
        self._debounce = async_call_later(self.hass, 5, self._tick)

    @callback
    def _value_changed(self, _event: Any) -> None:
        """습도 · 온도가 변함 — 「변하면 보내기」일 때, 지난번 보낸 값에서 정한 만큼 달라졌으면 보냄 (최소 간격은 지킴)."""
        if self.mode != "change" or self._pending is not None:
            return
        if not self._moved():
            return
        wait = self.gap - (time.monotonic() - self._last_push)
        self._pending = async_call_later(self.hass, max(2.0, wait), self._tick)

    def _moved(self) -> bool:
        for key, delta in ((CONF_HUM, self.delta_hum), (CONF_TEMP, self.delta_temp)):
            now = _float(self._value(key))
            if now is None:
                continue
            last = self._sent.get(key)
            if last is None or abs(now - last) >= delta:
                return True
        return False

    async def _tick(self, _now: Any = None) -> None:
        self._debounce = None
        self._cancel(self._pending)
        self._pending = None
        await self._push_values()

    # ── 값 보내기 ──

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
        self._last_push = time.monotonic()
        for key in (CONF_HUM, CONF_TEMP):
            val = _float(self._value(key))
            if val is not None:
                self._sent[key] = val
        try:
            resp = await async_get_clientsession(self.hass).post(self.push_url, json=payload, timeout=_TIMEOUT)
            if resp.status >= 400:
                _LOGGER.debug("3ds %s: 사이트가 받지 않음 (%s)", self.title, resp.status)
                resp.release()
                return
            try:
                answer = await resp.json(content_type=None)
            except ValueError:
                answer = None
            if isinstance(answer, dict):
                self._apply_site(answer)
        except _NET_ERRORS as err:
            _LOGGER.debug("3ds %s: 보내지 못함: %s", self.title, err)

    # ── 카메라 사진 (없어도 되는 것 — 무엇이 잘못돼도 값 보내기에는 영향 없음) ──

    def _running(self) -> bool:
        """상태 엔티티가 없으면 늘 보냄, 있으면 가동 중일 때만."""
        if not self.conf.get(CONF_STATE):
            return True
        val = self._value(CONF_STATE)
        return val is not None and val.lower() in ON_STATES

    async def _snap_tick(self, _now: Any = None) -> None:
        camera_entity = self.conf.get(CONF_CAMERA)
        if not camera_entity or not self.push_url or not self.conf.get("snapshot", True) or not self._snap_ok:
            return
        if time.monotonic() - self._last_snap < self.snap_gap * 60 or not self._running():
            return
        try:
            content = await self._camera_image(camera_entity)
            if content is None:
                return
            resp = await async_get_clientsession(self.hass).post(
                f"{self.push_url}/snap", data=content, headers={"Content-Type": "image/jpeg"}, timeout=_TIMEOUT
            )
            if resp.status < 400:
                self._last_snap = time.monotonic()
            resp.release()
        except Exception as err:  # noqa: BLE001 — 카메라 종류 · 버전마다 내는 오류가 달라 넓게 잡음
            _LOGGER.debug("3ds %s: 사진을 보내지 못함: %s", self.title, err)

    async def _camera_image(self, camera_entity: str) -> bytes | None:
        # 카메라 통합이 없는 집에서도 켜지게 여기서 불러옴
        from homeassistant.components.camera import async_get_image

        try:
            image = await async_get_image(self.hass, camera_entity, timeout=10, width=SNAP_WIDTH)
        except TypeError:
            image = await async_get_image(self.hass, camera_entity)  # 크기 지정을 받지 않는 버전
        content = getattr(image, "content", None)
        if not isinstance(content, (bytes, bytearray)):
            return None
        return await self.hass.async_add_executor_job(_small_jpeg, bytes(content), self.snap_max)


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
