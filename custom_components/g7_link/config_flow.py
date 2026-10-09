"""G7 연결 — 설정 화면 (사이트 주소 · 연결 코드 → 붙일 곳 → 센서 고르기)."""

from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_AUTO,
    CONF_BULK,
    CONF_CAMERA,
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_EQUIPMENT_ID,
    CONF_HA_DEVICE,
    CONF_HUM,
    CONF_HUMIDITY_MAX,
    CONF_INTERVAL,
    CONF_ITEMS,
    CONF_JOB,
    CONF_KEY,
    CONF_LOCATION,
    CONF_NAME,
    CONF_PRINTER_ID,
    CONF_PROGRESS,
    CONF_PUSH_URL,
    CONF_REMAINING,
    CONF_SENSORS,
    CONF_SITE,
    CONF_SNAP_PUBLIC,
    CONF_STATE,
    CONF_TARGET,
    CONF_TEMP,
    CONF_TEMP_MAX,
    CONF_TOKEN,
    DOMAIN,
    ENTITY_KEYS,
    HUB_PATH,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class InvalidCode(Exception):
    """연결 코드가 틀림."""


class CannotConnect(Exception):
    """사이트에 닿지 않음."""


class Rejected(Exception):
    """사이트가 거절 (말을 그대로 보임)."""


async def _hub(hass: HomeAssistant, site: str, code: str) -> dict[str, Any]:
    """사이트에서 붙일 수 있는 곳 목록을 받아 옴."""
    try:
        resp = await async_get_clientsession(hass).get(f"{site}{HUB_PATH}{code}", timeout=_TIMEOUT)
        if resp.status == 404:
            raise InvalidCode
        if resp.status != 200:
            raise CannotConnect
        data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect from err
    if not isinstance(data, dict) or not data.get("ok"):
        raise InvalidCode
    return data


async def _save(hass: HomeAssistant, site: str, code: str, device_id: int | None, body: dict[str, Any]) -> dict[str, Any]:
    """사이트에 기기를 만들거나 고침."""
    url = f"{site}{HUB_PATH}{code}/devices" + (f"/{device_id}" if device_id else "")
    session = async_get_clientsession(hass)
    try:
        resp = await (session.put if device_id else session.post)(url, json=body, timeout=_TIMEOUT)
        if resp.status == 404:
            raise InvalidCode
        data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect from err
    if not isinstance(data, dict) or not data.get("ok"):
        raise Rejected(str((data or {}).get("message") or ""))
    return data.get("device") or {}


async def _delete(hass: HomeAssistant, site: str, code: str, device_id: int) -> None:
    """사이트의 기기를 지움 (안 돼도 넘어감 — 사이트 화면에서 지울 수 있음)."""
    try:
        resp = await async_get_clientsession(hass).delete(f"{site}{HUB_PATH}{code}/devices/{device_id}", timeout=_TIMEOUT)
        resp.release()
    except (aiohttp.ClientError, TimeoutError):
        pass


def _describe(hass: HomeAssistant, hum_entity: str) -> tuple[str, str]:
    """습도 센서 하나 → (이름, 같은 기기의 온도 센서). 이름은 구역 › 기기 › 센서 이름 순으로 찾음. 못 찾으면 센서 이름만."""
    name, temp = "", ""
    state = hass.states.get(hum_entity)
    friendly = str(state.attributes.get("friendly_name") or "") if state is not None else ""
    try:
        from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

        ent_reg = er.async_get(hass)
        entry = ent_reg.async_get(hum_entity)
        device = dr.async_get(hass).async_get(entry.device_id) if entry is not None and entry.device_id else None
        area_id = (entry.area_id if entry is not None else None) or (device.area_id if device is not None else None)
        area = ar.async_get(hass).async_get_area(area_id) if area_id else None
        if device is not None:
            name = str(device.name_by_user or device.name or "")
            for other in er.async_entries_for_device(ent_reg, device.id):
                if other.domain != "sensor" or other.entity_id == hum_entity:
                    continue
                st = hass.states.get(other.entity_id)
                cls = other.device_class or other.original_device_class or (st.attributes.get("device_class") if st is not None else None)
                if cls == "temperature":
                    temp = other.entity_id
                    break
        if not name and area is not None:
            name = str(area.name or "")
    except Exception:  # noqa: BLE001 — 기기 · 구역 정보는 없어도 됨 (버전이 달라져도 연결은 되게)
        pass
    if not name:
        name = friendly.replace("습도", "").replace("Humidity", "").replace("humidity", "").strip() or hum_entity.split(".", 1)[-1]
    return name[:40], temp


# 프린터 통합마다 센서 이름이 달라서, 이름에 든 낱말로 찾음 (앞에 있는 낱말일수록 먼저). Bambu Lab · Creality WS · Anycubic · Moonraker · OctoPrint · PrusaLink 등
_GUESS: dict[str, tuple[str, ...]] = {
    CONF_STATE: ("print_status", "print_state", "current_print_state", "printer_state", "job_state", "current_state", "print_stage", "status", "state"),
    CONF_PROGRESS: ("print_progress", "job_progress", "job_percentage", "progress", "percent"),
    CONF_REMAINING: ("print_time_left", "time_left", "remaining_time", "time_remaining", "remaining", "eta"),
    CONF_JOB: ("task_name", "job_name", "file_name", "filename", "gcode_file", "current_file", "print_job", "project_name"),
    CONF_TEMP: ("chamber_temp", "box_temp", "enclosure_temp", "chamber"),
    CONF_HUM: ("humidity",),
}


def _guess(hass: HomeAssistant, device_id: str) -> dict[str, str]:
    """HA 기기 하나에서 상태 · 진행률 · 남은 시간 · 작업 이름 · 내부 온도 · 카메라 엔티티를 찾음. 못 찾은 것은 비워 둠."""
    found: dict[str, str] = {}
    try:
        from homeassistant.helpers import entity_registry as er

        entries = [e for e in er.async_entries_for_device(er.async_get(hass), device_id) if not e.disabled_by]
    except Exception:  # noqa: BLE001 — 못 찾아도 손으로 고를 수 있음
        return found
    sensors = sorted((e.entity_id for e in entries if e.domain == "sensor"), key=len)
    for key, words in _GUESS.items():
        for word in words:
            hit = next((e for e in sensors if word in e.split(".", 1)[-1] and e not in found.values()), None)
            if hit:
                found[key] = hit
                break
    if CONF_STATE not in found:  # 상태 센서가 없으면 전원 스위치 · 「출력 중」 이진 센서로
        other = next((e.entity_id for e in entries if e.domain in ("binary_sensor", "switch") and any(w in e.entity_id for w in ("printing", "power", "plug", "state"))), None)
        if other:
            found[CONF_STATE] = other
    if CONF_HUM in found and CONF_TEMP not in found:
        _name, temp = _describe(hass, found[CONF_HUM])
        if temp:
            found[CONF_TEMP] = temp
    camera = next((e.entity_id for e in entries if e.domain == "camera"), None)
    if camera:
        found[CONF_CAMERA] = camera
    return found


def _norm(text: Any) -> str:
    """이름 견주기용 — 소문자, 글자 · 숫자만 (빈칸 · 기호 무시)."""
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").lower())


def _scan(hass: HomeAssistant, hub: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """⚡ 알아서 찾기 — 사이트의 내 프린터 · 필라멘트 보관 위치와 이름이 맞는 HA 기기 · 습도 센서를 찾음.

    돌려주는 것: {key: {label, matched, name, body(사이트에 만들 내용), conf(이 통합이 읽을 센서)}} — 이미 사이트에 연결한 것은 뺌.
     - 프린터: 별명 · 기종 · 브랜드+기종이 HA 기기 이름/모델에 들어 있고, 그 기기에 상태 센서가 있으면 맞는 것 (가장 길게 맞는 기기)
     - 보관함: 습도 센서(와 그 기기 · 구역 이름)에 필라멘트 보관 위치가 들어 있으면 그 위치로. 안 맞는 습도 센서도 목록에는 넣음 (체크는 꺼 둠)
    """
    out: dict[str, dict[str, Any]] = {}
    existing = [d for d in (hub.get("devices") or []) if isinstance(d, dict)]
    have_printers = {int(d.get("printer_id") or 0) for d in existing}
    have_hum = {str((d.get("entities") or {}).get("hum") or "") for d in existing}
    ent_reg = None
    devices: list[Any] = []
    try:
        from homeassistant.helpers import device_registry as dr, entity_registry as er

        ent_reg = er.async_get(hass)
        devices = list(dr.async_get(hass).devices.values())
    except Exception:  # noqa: BLE001 — 기기 정보를 못 읽으면 프린터는 못 찾고 습도 센서만
        devices = []
    used: set[str] = set()
    for p in hub.get("printers") or []:
        pid = int(p.get("id") or 0)
        if not pid or pid in have_printers:
            continue
        words = [w for w in (_norm(p.get("nickname")), _norm(p.get("model")), _norm(f"{p.get('brand', '')}{p.get('model', '')}")) if len(w) >= 2]
        if not words:
            words = [w for w in (_norm(p.get("name")),) if len(w) >= 2]
        best: Any = None
        best_found: dict[str, str] = {}
        best_score = 0
        for dev in devices:
            if dev.id in used:
                continue
            text = _norm(f"{dev.name_by_user or ''} {dev.name or ''} {dev.model or ''}")
            score = max((len(w) for w in words if w in text), default=0)
            if score <= best_score:
                continue
            found = _guess(hass, dev.id)
            if CONF_STATE not in found:
                continue
            best, best_found, best_score = dev, found, score
        if best is None:
            continue
        used.add(best.id)
        body: dict[str, Any] = {CONF_TARGET: "printer", CONF_PRINTER_ID: pid, CONF_NAME: "", CONF_HUMIDITY_MAX: "", CONF_TEMP_MAX: ""}
        for key in ENTITY_KEYS:
            body[key] = best_found.get(key, "")
        out[f"p:{pid}"] = {
            "label": f"🖨️ {p.get('name')}  ←  {best.name_by_user or best.name}",
            "matched": True,
            "name": str(p.get("name") or ""),
            "body": body,
            "conf": dict(best_found),
        }
    locations = sorted((str(x) for x in (hub.get("locations") or []) if len(_norm(x)) >= 2), key=len, reverse=True)
    for state in hass.states.async_all("sensor"):
        if state.attributes.get("device_class") not in ("humidity", "moisture"):
            continue
        ent = state.entity_id
        if ent in have_hum:
            continue
        reg = ent_reg.async_get(ent) if ent_reg is not None else None
        if reg is not None and reg.device_id in used:
            continue  # 프린터 기기에 딸린 습도는 프린터 쪽에서 이미 씀
        name, temp = _describe(hass, ent)
        friendly = str(state.attributes.get("friendly_name") or ent)
        text = _norm(f"{name} {friendly}")
        loc = next((x for x in locations if _norm(x) in text or (len(_norm(name)) >= 2 and _norm(name) in _norm(x))), None)
        place = loc or name
        out[f"h:{ent}"] = {
            "label": f"🧵 {loc}  ←  {friendly}" if loc else f"🧵 {friendly} (새 보관함: {name})",
            "matched": loc is not None,
            "name": place,
            "body": {CONF_TARGET: "location", CONF_LOCATION: place, CONF_NAME: place, CONF_HUM: ent, CONF_TEMP: temp, CONF_HUMIDITY_MAX: 40},
            "conf": {CONF_HUM: ent, **({CONF_TEMP: temp} if temp else {})},
        }
    return out


def _item_key(device: dict[str, Any]) -> str:
    """여러 대짜리 통합의 기기 하나를 가리는 이름 (예전 「한꺼번에」로 만든 것은 습도 센서로)."""
    return str(device.get(CONF_KEY) or f"h:{device.get(CONF_HUM) or device.get(CONF_DEVICE_ID)}")


def _items_schema(options: dict[str, str], default: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ITEMS, default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[selector.SelectOptionDict(value=k, label=v) for k, v in options.items()],
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


async def _connect(hass: HomeAssistant, site: str, code: str, key: str, cand: dict[str, Any]) -> dict[str, Any]:
    """찾은 것 하나를 사이트에 만들고, 이 통합이 기억할 내용을 돌려줌."""
    device = await _save(hass, site, code, None, cand["body"])
    return {
        CONF_KEY: key,
        CONF_DEVICE_ID: int(device.get("id") or 0),
        CONF_TOKEN: device.get("token", ""),
        CONF_PUSH_URL: device.get("push_url", ""),
        CONF_NAME: str(device.get("name") or cand.get("name") or ""),
        **cand["conf"],
    }


def _pair(hass: HomeAssistant, sensors: dict[str, Any]) -> dict[str, Any]:
    """습도 센서만 고르고 온도 칸을 비워 뒀으면 같은 기기의 온도 센서를 같이 붙임 (온도를 직접 골랐으면 그대로)."""
    hum = sensors.get(CONF_HUM)
    if hum and not sensors.get(CONF_TEMP):
        _name, temp = _describe(hass, str(hum))
        if temp:
            sensors = {**sensors, CONF_TEMP: temp}
    return sensors


def _bulk_schema(default: list[str] | None = None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SENSORS, default=default or []): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor"], device_class=["humidity", "moisture"], multiple=True)
            ),
            vol.Optional(CONF_HUMIDITY_MAX): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=100, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
        }
    )


def _entity(domains: list[str], device_class: str | list[str] | None = None) -> selector.EntitySelector:
    """엔티티 고르기 칸 — 종류(device_class)를 주면 그 종류의 센서만 목록에 나옴."""
    cfg: dict[str, Any] = {"domain": domains}
    if device_class:
        cfg["device_class"] = device_class
    return selector.EntitySelector(selector.EntitySelectorConfig(**cfg))


def _sensor_schema(target: str, snapshot: bool, site_interval: int = 10) -> vol.Schema:
    """센서 고르기 칸 — 붙이는 곳에 맞는 것만."""
    fields: dict[Any, Any] = {
        vol.Optional(CONF_NAME): str,
        vol.Optional(CONF_HUM): _entity(["sensor"], ["humidity", "moisture"]),   # 습도 센서만
        vol.Optional(CONF_TEMP): _entity(["sensor"], "temperature"),              # 온도 센서만
    }
    if target != "location":
        fields[vol.Optional(CONF_STATE)] = _entity(["sensor", "binary_sensor", "switch", "input_boolean", "light", "fan"])
    if target == "printer":
        fields[vol.Optional(CONF_PROGRESS)] = _entity(["sensor"])
        fields[vol.Optional(CONF_REMAINING)] = _entity(["sensor"])
        fields[vol.Optional(CONF_JOB)] = _entity(["sensor"])
    number = selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=100, step=1, mode=selector.NumberSelectorMode.BOX))
    fields[vol.Optional(CONF_HUMIDITY_MAX)] = number
    fields[vol.Optional(CONF_TEMP_MAX)] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=-40, max=400, step=1, mode=selector.NumberSelectorMode.BOX)
    )
    low = max(1, int(site_interval or 10))
    fields[vol.Optional(CONF_INTERVAL)] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=low, max=max(low, 180), step=1, mode=selector.NumberSelectorMode.BOX, unit_of_measurement="min")
    )
    if snapshot:
        fields[vol.Optional(CONF_CAMERA)] = _entity(["camera"])
        fields[vol.Optional(CONF_SNAP_PUBLIC, default=False)] = bool
    return vol.Schema(fields)


def _body(where: dict[str, Any], sensors: dict[str, Any]) -> dict[str, Any]:
    """사이트로 보낼 내용."""
    body: dict[str, Any] = dict(where)
    body[CONF_NAME] = (sensors.get(CONF_NAME) or "").strip()
    for key in ENTITY_KEYS:
        body[key] = sensors.get(key) or ""
    for key in (CONF_HUMIDITY_MAX, CONF_TEMP_MAX):
        val = sensors.get(key)
        body[key] = int(val) if val is not None else ""
    body[CONF_SNAP_PUBLIC] = bool(sensors.get(CONF_SNAP_PUBLIC))
    return body


def _has_entity(sensors: dict[str, Any]) -> bool:
    return any(sensors.get(k) for k in (CONF_HUM, CONF_TEMP, CONF_STATE))


class G7LinkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """통합 추가 = 기기 하나 붙이기."""

    VERSION = 1

    def __init__(self) -> None:
        self._site = ""
        self._code = ""
        self._hub: dict[str, Any] = {}
        self._where: dict[str, Any] = {}
        self._found: dict[str, str] = {}  # 고른 HA 기기에서 찾은 센서 (센서 고르기 칸에 미리 채움)
        self._cands: dict[str, dict[str, Any]] = {}  # ⚡ 알아서 찾은 것

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """① 사이트 주소 · 연결 코드."""
        errors: dict[str, str] = {}
        if user_input is not None:
            site = user_input[CONF_SITE].strip().rstrip("/")
            if not site.startswith(("http://", "https://")):
                site = "https://" + site
            code = user_input[CONF_CODE].strip().lower()
            try:
                self._hub = await _hub(self.hass, site, code)
            except InvalidCode:
                errors["base"] = "invalid_code"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                self._site, self._code = site, code
                return await self.async_step_target()
        prev = next(iter(self._async_current_entries()), None)
        seed = user_input or (prev.data if prev else {})
        schema = vol.Schema(
            {
                vol.Required(CONF_SITE, default=seed.get(CONF_SITE, "")): str,
                vol.Required(CONF_CODE, default=seed.get(CONF_CODE, "")): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_target(self, user_input: dict[str, Any] | None = None):
        """② 무엇에 붙일지."""
        targets = dict(self._hub.get("targets") or {"location": "location", "other": "other"})
        if not self._hub.get("printers"):
            targets.pop("printer", None)
        if not self._hub.get("equipment"):
            targets.pop("equipment", None)
        if user_input is not None:
            if user_input[CONF_TARGET] == CONF_AUTO:
                return await self.async_step_auto()
            if user_input[CONF_TARGET] == CONF_BULK:
                return await self.async_step_bulk()
            self._where = {CONF_TARGET: user_input[CONF_TARGET]}
            if user_input[CONF_TARGET] == "other":
                return await self.async_step_device()
            return await self.async_step_where()
        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET, default=CONF_AUTO): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=CONF_AUTO, label="⚡ 알아서 찾아 연결 (추천) — 내 프린터 · 필라멘트 보관함과 이름이 맞는 것")]
                        + [selector.SelectOptionDict(value=k, label=str(v) + " — 하나씩") for k, v in targets.items()],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="target", data_schema=schema)

    async def async_step_auto(self, user_input: dict[str, Any] | None = None):
        """③ ⚡ 알아서 찾아 연결 — 이름이 맞는 것을 체크해 보여 주고, 확인하면 한 번에 만듦."""
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        await self.async_set_unique_id(f"{self._site}#bulk")
        self._abort_if_unique_id_configured()
        if not self._cands:
            self._cands = _scan(self.hass, self._hub)
        if not self._cands:
            return self.async_abort(reason="nothing_found")
        if user_input is not None:
            devices: list[dict[str, Any]] = []
            for key in user_input.get(CONF_ITEMS) or []:
                cand = self._cands.get(key)
                if cand is None:
                    continue
                try:
                    devices.append(await _connect(self.hass, self._site, self._code, key, cand))
                except InvalidCode:
                    errors["base"] = "invalid_code"
                    break
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                    break
                except Rejected as err:
                    errors["base"] = "rejected"
                    placeholders["message"] = str(err)
                    break
            if devices:
                data = {
                    CONF_SITE: self._site,
                    CONF_CODE: self._code,
                    CONF_BULK: True,
                    CONF_DEVICES: devices,
                    "interval_min": self._hub.get("next_min") or self._hub.get("interval_min"),
                    "send_mode": self._hub.get("send_mode"),
                    "change_hum": self._hub.get("change_hum"),
                    "change_temp": self._hub.get("change_temp"),
                    "gap_sec": self._hub.get("gap_sec"),
                    "snap_gap_min": self._hub.get("snap_gap_min"),
                    "snap_max": self._hub.get("snap_max"),
                    "snapshot": bool(self._hub.get("snapshot", True)),
                }
                return self.async_create_entry(title=f"3ds 기기 {len(devices)}개", data=data, options={})
            errors.setdefault("base", "need_entity")
        schema = _items_schema({k: c["label"] for k, c in self._cands.items()}, [k for k, c in self._cands.items() if c["matched"]])
        return self.async_show_form(step_id="auto", data_schema=schema, errors=errors, description_placeholders=placeholders)

    async def async_step_bulk(self, user_input: dict[str, Any] | None = None):
        """③ 한꺼번에 — 습도 센서를 여러 개 고르면 센서마다 사이트에 보관함 기기를 만듦 (같은 기기의 온도 센서는 알아서 같이)."""
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        await self.async_set_unique_id(f"{self._site}#bulk")
        self._abort_if_unique_id_configured()
        if user_input is not None:
            picked = [e for e in (user_input.get(CONF_SENSORS) or []) if e]
            limit = user_input.get(CONF_HUMIDITY_MAX)
            devices: list[dict[str, Any]] = []
            last = ""
            for hum in picked:
                name, temp = _describe(self.hass, hum)
                body = {CONF_TARGET: "location", CONF_LOCATION: name, CONF_NAME: name, CONF_HUM: hum, CONF_TEMP: temp, CONF_HUMIDITY_MAX: int(limit) if limit is not None else ""}
                try:
                    device = await _save(self.hass, self._site, self._code, None, body)
                except InvalidCode:
                    last = "invalid_code"
                    break
                except CannotConnect:
                    last = "cannot_connect"
                    break
                except Rejected as err:
                    last = "rejected"
                    placeholders["message"] = str(err)
                    break
                devices.append({CONF_DEVICE_ID: int(device.get("id") or 0), CONF_TOKEN: device.get("token", ""), CONF_PUSH_URL: device.get("push_url", ""), CONF_NAME: str(device.get("name") or name), CONF_HUM: hum, CONF_TEMP: temp})
            if devices:
                data = {
                    CONF_SITE: self._site,
                    CONF_CODE: self._code,
                    CONF_BULK: True,
                    CONF_DEVICES: devices,
                    "interval_min": self._hub.get("next_min") or self._hub.get("interval_min"),
                    "send_mode": self._hub.get("send_mode"),
                    "change_hum": self._hub.get("change_hum"),
                    "change_temp": self._hub.get("change_temp"),
                    "gap_sec": self._hub.get("gap_sec"),
                    "snapshot": False,
                }
                return self.async_create_entry(title=f"3ds 보관함 센서 {len(devices)}개", data=data, options={})
            errors["base"] = last or "need_entity"
        return self.async_show_form(step_id="bulk", data_schema=_bulk_schema(), errors=errors, description_placeholders=placeholders)

    async def async_step_where(self, user_input: dict[str, Any] | None = None):
        """③ 어느 보관함 · 프린터 · 장비인지."""
        target = self._where[CONF_TARGET]
        if user_input is not None:
            if target == "location":
                self._where[CONF_LOCATION] = str(user_input[CONF_LOCATION]).strip()
            elif target == "printer":
                self._where[CONF_PRINTER_ID] = int(user_input[CONF_PRINTER_ID])
            else:
                self._where[CONF_EQUIPMENT_ID] = int(user_input[CONF_EQUIPMENT_ID])
            if target == "location":
                return await self.async_step_sensors()
            return await self.async_step_device()
        if target == "location":
            locations = [str(x) for x in (self._hub.get("locations") or [])]
            field: Any = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=locations, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN)
                )
                if locations
                else str
            )
            schema = vol.Schema({vol.Required(CONF_LOCATION): field})
        else:
            key = CONF_PRINTER_ID if target == "printer" else CONF_EQUIPMENT_ID
            items = self._hub.get("printers" if target == "printer" else "equipment") or []
            schema = vol.Schema(
                {
                    vol.Required(key): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[selector.SelectOptionDict(value=str(i["id"]), label=str(i["name"])) for i in items],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            )
        return self.async_show_form(step_id="where", data_schema=schema)

    async def async_step_device(self, user_input: dict[str, Any] | None = None):
        """④ (프린터 · 장비) Home Assistant 의 기기를 고르면 그 기기의 센서를 찾아 다음 화면에 채워 둠. 건너뛰어도 됨."""
        if user_input is not None:
            device_id = user_input.get(CONF_HA_DEVICE)
            self._found = _guess(self.hass, str(device_id)) if device_id else {}
            return await self.async_step_sensors()
        schema = vol.Schema({vol.Optional(CONF_HA_DEVICE): selector.DeviceSelector(selector.DeviceSelectorConfig())})
        return self.async_show_form(step_id="device", data_schema=schema)

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None):
        """⑤ 센서 고르기 → 사이트에 기기를 만듦."""
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        schema = _sensor_schema(self._where[CONF_TARGET], bool(self._hub.get("snapshot", True)), int(self._hub.get("next_min") or self._hub.get("interval_min") or 10))
        if user_input is not None:
            user_input = _pair(self.hass, user_input)
            if not _has_entity(user_input):
                errors["base"] = "need_entity"
            else:
                try:
                    device = await _save(self.hass, self._site, self._code, None, _body(self._where, user_input))
                except InvalidCode:
                    errors["base"] = "invalid_code"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Rejected as err:
                    errors["base"] = "rejected"
                    placeholders["message"] = str(err)
                else:
                    await self.async_set_unique_id(f"{self._site}#{device.get('id')}")
                    self._abort_if_unique_id_configured()
                    data = {
                        CONF_SITE: self._site,
                        CONF_CODE: self._code,
                        CONF_DEVICE_ID: int(device.get("id") or 0),
                        CONF_TOKEN: device.get("token", ""),
                        CONF_PUSH_URL: device.get("push_url", ""),
                        "interval_min": self._hub.get("next_min") or self._hub.get("interval_min"),
                        "send_mode": self._hub.get("send_mode"),
                        "change_hum": self._hub.get("change_hum"),
                        "change_temp": self._hub.get("change_temp"),
                        "gap_sec": self._hub.get("gap_sec"),
                        "snap_gap_min": self._hub.get("snap_gap_min"),
                        "snap_max": self._hub.get("snap_max"),
                        "snapshot": bool(self._hub.get("snapshot", True)),
                        **self._where,
                    }
                    options = {k: v for k, v in user_input.items() if k != CONF_NAME}
                    return self.async_create_entry(title=str(device.get("name") or "G7"), data=data, options=options)
            schema = self.add_suggested_values_to_schema(schema, user_input)
        elif self._found:
            schema = self.add_suggested_values_to_schema(schema, self._found)
        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors, description_placeholders=placeholders)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return G7LinkOptionsFlow(config_entry)


class G7LinkOptionsFlow(config_entries.OptionsFlow):
    """센서 · 알림 기준 바꾸기 (사이트의 기기도 같이 고침)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._cands: dict[str, dict[str, Any]] | None = None

    async def async_step_auto(self, user_input: dict[str, Any] | None = None):
        """여러 대짜리 통합의 구성 — 지금 연결한 것(체크됨) + 새로 찾은 것. 체크를 빼면 사이트에서도 지움."""
        entry = self._entry
        data = dict(entry.data)
        site, code = data.get(CONF_SITE, ""), data.get(CONF_CODE, "")
        devices: list[dict[str, Any]] = [d for d in (data.get(CONF_DEVICES) or []) if isinstance(d, dict)]
        current = {_item_key(d): d for d in devices}
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        if self._cands is None:
            try:
                hub = await _hub(self.hass, site, code)
            except InvalidCode:
                return self.async_abort(reason="invalid_code")
            except CannotConnect:
                return self.async_abort(reason="cannot_connect")
            self._cands = {k: c for k, c in _scan(self.hass, hub).items() if k not in current}
        if user_input is not None:
            picked = [k for k in (user_input.get(CONF_ITEMS) or []) if k]
            keep = [d for k, d in current.items() if k in picked]
            for key in picked:
                if key in current or key not in self._cands:
                    continue
                try:
                    keep.append(await _connect(self.hass, site, code, key, self._cands[key]))
                except InvalidCode:
                    errors["base"] = "invalid_code"
                    break
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                    break
                except Rejected as err:
                    errors["base"] = "rejected"
                    placeholders["message"] = str(err)
                    break
            if not errors:
                for key, gone in current.items():
                    if key not in picked:
                        await _delete(self.hass, site, code, int(gone.get(CONF_DEVICE_ID) or 0))
                data[CONF_DEVICES] = keep
                self.hass.config_entries.async_update_entry(entry, data=data, title=f"3ds 기기 {len(keep)}개")
                return self.async_create_entry(title="", data=dict(entry.options))
        options = {k: f"✔ {d.get(CONF_NAME) or k}" for k, d in current.items()}
        options.update({k: c["label"] for k, c in self._cands.items()})
        default = list(current) + [k for k, c in self._cands.items() if c["matched"]]
        return self.async_show_form(step_id="auto", data_schema=_items_schema(options, default), errors=errors, description_placeholders=placeholders)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if self._entry.data.get(CONF_BULK):
            return await self.async_step_auto(user_input)
        entry = self._entry
        data = entry.data
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        schema = _sensor_schema(data.get(CONF_TARGET, "other"), bool(data.get("snapshot", True)), int(data.get("interval_min") or 10))
        if user_input is not None:
            user_input = _pair(self.hass, user_input)
            if not _has_entity(user_input):
                errors["base"] = "need_entity"
            else:
                where = {k: data[k] for k in (CONF_TARGET, CONF_LOCATION, CONF_PRINTER_ID, CONF_EQUIPMENT_ID) if k in data}
                try:
                    await _save(self.hass, data[CONF_SITE], data[CONF_CODE], int(data[CONF_DEVICE_ID]), _body(where, user_input))
                except InvalidCode:
                    errors["base"] = "invalid_code"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Rejected as err:
                    errors["base"] = "rejected"
                    placeholders["message"] = str(err)
                else:
                    return self.async_create_entry(title="", data={k: v for k, v in user_input.items() if k != CONF_NAME})
        current = user_input if user_input is not None else dict(entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_bulk(self, user_input: dict[str, Any] | None = None):
        """한꺼번에 연결한 통합 — 센서를 더 고르면 사이트에 기기를 더 만들고, 빼면 지움 (그대로 둔 것은 건드리지 않음)."""
        entry = self._entry
        data = dict(entry.data)
        site, code = data.get(CONF_SITE, ""), data.get(CONF_CODE, "")
        devices: list[dict[str, Any]] = [d for d in (data.get(CONF_DEVICES) or []) if isinstance(d, dict)]
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        if user_input is not None:
            picked = [e for e in (user_input.get(CONF_SENSORS) or []) if e]
            limit = user_input.get(CONF_HUMIDITY_MAX)
            keep = [d for d in devices if d.get(CONF_HUM) in picked]
            have = {d.get(CONF_HUM) for d in keep}
            for hum in picked:
                if hum in have:
                    continue
                name, temp = _describe(self.hass, hum)
                body = {CONF_TARGET: "location", CONF_LOCATION: name, CONF_NAME: name, CONF_HUM: hum, CONF_TEMP: temp, CONF_HUMIDITY_MAX: int(limit) if limit is not None else ""}
                try:
                    device = await _save(self.hass, site, code, None, body)
                except InvalidCode:
                    errors["base"] = "invalid_code"
                    break
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                    break
                except Rejected as err:
                    errors["base"] = "rejected"
                    placeholders["message"] = str(err)
                    break
                keep.append({CONF_DEVICE_ID: int(device.get("id") or 0), CONF_TOKEN: device.get("token", ""), CONF_PUSH_URL: device.get("push_url", ""), CONF_NAME: str(device.get("name") or name), CONF_HUM: hum, CONF_TEMP: temp})
            if not errors:
                for gone in devices:
                    if gone.get(CONF_HUM) not in picked:
                        await _delete(self.hass, site, code, int(gone.get(CONF_DEVICE_ID) or 0))
                data[CONF_DEVICES] = keep
                self.hass.config_entries.async_update_entry(entry, data=data, title=f"3ds 보관함 센서 {len(keep)}개")
                return self.async_create_entry(title="", data=dict(entry.options))
        current = [d.get(CONF_HUM) for d in devices if d.get(CONF_HUM)]
        return self.async_show_form(step_id="bulk", data_schema=_bulk_schema(current), errors=errors, description_placeholders=placeholders)
