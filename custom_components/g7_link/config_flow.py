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
    CONF_CAMERA,
    CONF_CODE,
    CONF_DEVICE_ID,
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
            self._where = {CONF_TARGET: user_input[CONF_TARGET]}
            if user_input[CONF_TARGET] == "other":
                return await self.async_step_sensors()
            return await self.async_step_where()
        schema = vol.Schema(
            {
                vol.Required(CONF_TARGET, default=next(iter(targets))): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[selector.SelectOptionDict(value=k, label=str(v)) for k, v in targets.items()],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="target", data_schema=schema)

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
        schema = _sensor_schema(self._where[CONF_TARGET], bool(self._hub.get("snapshot", True)), int(self._hub.get("interval_min") or 10))
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
                        "interval_min": self._hub.get("interval_min"),
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
