"""0.5.0 Site → Home Assistant sensors (3DSSync).

The site (IoT link plugin 1.19.0+) answers GET hub/{code}/status with the account's
unread notices, orders, print-job bids, filament stock and storage boxes. One set of
sensors per site + link code, polled every 5 minutes. Old sites (no /status) just
leave the sensors unavailable.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import logging
from typing import Any
from urllib.parse import urlparse

import aiohttp

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .const import CONF_CODE, CONF_SITE, DOMAIN
from .hub import hub_request

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=20)
SCAN = timedelta(minutes=5)

# (key, section, field, name, icon, unit, attrs)
SENSORS: tuple[tuple[str, str, str, str, str, str | None, tuple[str, ...]], ...] = (
    ("unread", "notices", "unread", "Unread notices", "mdi:bell-badge", None, ("last", "last_at")),
    ("orders_active", "orders", "active", "Orders in progress", "mdi:package-variant", None, ("recent",)),
    ("bids_waiting", "jobs", "bids_waiting", "Bids on my requests", "mdi:hammer-wrench", None, ("bids_new_24h", "my_open")),
    ("my_bids", "jobs", "my_bids_pending", "My pending bids", "mdi:handshake", None, ()),
    ("jobs_open", "jobs", "site_open", "Open print requests", "mdi:clipboard-list", None, ()),
    ("filament_total", "filament", "total", "Filament rolls", "mdi:printer-3d-nozzle", "rolls", ("resin",)),
    ("filament_low", "filament", "low", "Filament running low", "mdi:alert-circle-outline", "rolls", ("low_list",)),
    ("filament_empty", "filament", "empty", "Filament used up", "mdi:close-circle-outline", "rolls", ()),
)


class StatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads hub/{code}/status every 5 minutes."""

    def __init__(self, hass: HomeAssistant, site: str, code: str) -> None:
        super().__init__(hass, _LOGGER, name=f"3DSSync status {urlparse(site).netloc}", update_interval=SCAN)
        self.site, self.code = site, code

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            resp = await hub_request(async_get_clientsession(self.hass), "GET", self.site, f"{self.code}/status", hass=self.hass, timeout=_TIMEOUT)
            if resp.status != 200:
                resp.release()
                raise UpdateFailed(f"site answered {resp.status} (IoT link plugin 1.19.0+ needed)")
            data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise UpdateFailed(str(err)) from err
        if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("status"), dict):
            raise UpdateFailed("no status from the site")
        return data["status"]


def _device(site: str, uid: str) -> dict[str, Any]:
    host = urlparse(site).netloc or site
    return {"identifiers": {(DOMAIN, f"status:{uid}")}, "name": f"3DSSync — {host}", "manufacturer": "3DS", "model": "Site status", "configuration_url": site}


OWNERS = "_status_owners"   # hass.data[DOMAIN][OWNERS] = {(site, code): entry_id}


def release_owner(hass: HomeAssistant, entry_id: str) -> None:
    owners = hass.data.get(DOMAIN, {}).get(OWNERS, {})
    for k in [k for k, v in owners.items() if v == entry_id]:
        owners.pop(k, None)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    conf = {**entry.data, **entry.options}
    site, code = str(conf.get(CONF_SITE, "")).rstrip("/"), str(conf.get(CONF_CODE, ""))
    if not site or not code:
        return
    # the same link code can be in several entries (one bulk + single devices) → only the first one makes the sensors
    owners = hass.data.setdefault(DOMAIN, {}).setdefault(OWNERS, {})
    if owners.setdefault((site, code), entry.entry_id) != entry.entry_id:
        return
    coord = StatusCoordinator(hass, site, code)
    await coord.async_refresh()   # failure → sensors unavailable, keeps retrying
    host = urlparse(site).netloc or site
    uid = host + ":" + hashlib.sha1(code.encode()).hexdigest()[:10]   # two accounts on one site stay apart · the code itself is not shown
    ents: list[SensorEntity] = [StatusSensor(coord, uid, site, *s) for s in SENSORS]
    for box in (coord.data or {}).get("boxes") or []:
        if isinstance(box, dict) and box.get("key"):
            ents.append(BoxSensor(coord, uid, site, str(box["key"]), str(box.get("name") or box["key"])))
    async_add_entities(ents)


class StatusSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, key: str, section: str, field: str, name: str, icon: str, unit: str | None, attrs: tuple[str, ...]) -> None:
        super().__init__(coord)
        self._section, self._field, self._attrs = section, field, attrs
        self._attr_unique_id = f"{uid}:{key}"
        self._attr_translation_key = key   # Korean / English names from translations/*.json (entity.sensor.<key>)
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = _device(site, uid)

    def _part(self) -> dict[str, Any] | None:
        part = (self.coordinator.data or {}).get(self._section)
        return part if isinstance(part, dict) else None

    @property
    def available(self) -> bool:
        return super().available and self._part() is not None

    @property
    def native_value(self) -> int | None:
        part = self._part()
        v = part.get(self._field) if part else None
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        part = self._part() or {}
        return {k: part.get(k) for k in self._attrs if k in part}


class BoxSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    """One storage box: state = rolls inside · attrs = low rolls, humidity, temperature, over limit."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:archive-outline"
    _attr_native_unit_of_measurement = "rolls"

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, key: str, name: str) -> None:
        super().__init__(coord)
        self._key = key
        self._attr_unique_id = f"{uid}:box:{hashlib.sha1(key.encode()).hexdigest()[:10]}"
        self._attr_translation_key = "box"
        self._attr_translation_placeholders = {"name": name}
        self._attr_device_info = _device(site, uid)

    def _box(self) -> dict[str, Any] | None:
        for b in (self.coordinator.data or {}).get("boxes") or []:
            if isinstance(b, dict) and b.get("key") == self._key:
                return b
        return None

    @property
    def available(self) -> bool:
        return super().available and self._box() is not None

    @property
    def native_value(self) -> int | None:
        b = self._box()
        return int(b.get("spools") or 0) if b else None

    @property
    def icon(self) -> str:
        b = self._box() or {}
        return "mdi:water-alert" if b.get("over") else ("mdi:archive-alert-outline" if b.get("low") else "mdi:archive-outline")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        b = self._box() or {}
        return {k: b.get(k) for k in ("name", "low", "humidity", "temp", "humidity_max", "over", "seen_at")}
