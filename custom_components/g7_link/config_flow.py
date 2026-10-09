"""G7 연결 — 설정 화면 (사이트 주소 · 연결 코드 → 붙일 곳 → 센서 고르기)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BULK,
    CONF_CAMERA,
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_DEVICES,
    CONF_EQUIPMENT_ID,
    CONF_HUM,
    CONF_HUMIDITY_MAX,
    CONF_INTERVAL,
    CONF_JOB,
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
            if user_input[CONF_TARGET] == CONF_BULK:
                return await self.async_step_bulk()
            self._where = {CONF_TARGET: user_input[CONF_TARGET]}
            if user_input[CONF_TARGET] == "other":
                return await self.async_step_sensors()
            return await self.async_step_where()
        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET, default=CONF_BULK): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=CONF_BULK, label="✨ 온습도 센서 여러 개를 한꺼번에 (필라멘트 · 레진 보관함)")]
                        + [selector.SelectOptionDict(value=k, label=str(v) + " — 하나씩") for k, v in targets.items()],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="target", data_schema=schema)

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
            return await self.async_step_sensors()
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

    async def async_step_sensors(self, user_input: dict[str, Any] | None = None):
        """④ 센서 고르기 → 사이트에 기기를 만듦."""
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        schema = _sensor_schema(self._where[CONF_TARGET], bool(self._hub.get("snapshot", True)), int(self._hub.get("next_min") or self._hub.get("interval_min") or 10))
        if user_input is not None:
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
        return self.async_show_form(step_id="sensors", data_schema=schema, errors=errors, description_placeholders=placeholders)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return G7LinkOptionsFlow(config_entry)


class G7LinkOptionsFlow(config_entries.OptionsFlow):
    """센서 · 알림 기준 바꾸기 (사이트의 기기도 같이 고침)."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if self._entry.data.get(CONF_BULK):
            return await self.async_step_bulk(user_input)
        entry = self._entry
        data = entry.data
        errors: dict[str, str] = {}
        placeholders = {"message": ""}
        schema = _sensor_schema(data.get(CONF_TARGET, "other"), bool(data.get("snapshot", True)), int(data.get("interval_min") or 10))
        if user_input is not None:
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
