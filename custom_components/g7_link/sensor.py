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

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    ("filament_total", "filament", "total", "Filament rolls", "mdi:printer-3d-nozzle", "rolls", ("resin", "grams")),
    ("filament_low", "filament", "low", "Filament running low", "mdi:alert-circle-outline", "rolls", ("low_list",)),
    ("filament_empty", "filament", "empty", "Filament used up", "mdi:close-circle-outline", "rolls", ()),
)


# 0.6.0 big lists for the cards — kept out of the recorder (history database)
BIG = frozenset({"spools", "printers", "devices", "low_list", "g7", "site"})


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
    ents.append(ListSensor(coord, uid, site, "printers", "mdi:printer-3d", lambda p: p.get("state") in ("printing", "paused")))   # 0.6.0 state = printing now
    ents.append(ListSensor(coord, uid, site, "devices", "mdi:access-point-network", lambda d: bool(d.get("live"))))           # 0.6.0 state = sensors talking to the site
    async_add_entities(ents)

    # 0.6.1 one entity per storage box and per connected sensor on the site — new ones appear by themselves
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        data = coord.data or {}
        new: list[SensorEntity] = []
        for box in data.get("boxes") or []:
            if isinstance(box, dict) and box.get("key") and f"b:{box['key']}" not in known:
                known.add(f"b:{box['key']}")
                new.append(BoxSensor(coord, uid, site, str(box["key"]), str(box.get("name") or box["key"])))
        for dev in data.get("devices") or []:
            if isinstance(dev, dict) and dev.get("id") and f"d:{dev['id']}" not in known:
                known.add(f"d:{dev['id']}")
                new.append(SiteDeviceSensor(coord, uid, site, int(dev["id"]), str(dev.get("name") or dev["id"])))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coord.async_add_listener(_add_new))


class StatusSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = BIG

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, key: str, section: str, field: str, name: str, icon: str, unit: str | None, attrs: tuple[str, ...]) -> None:
        super().__init__(coord)
        self._section, self._field, self._attrs = section, field, attrs
        self._key, self._site = key, uid.split(":")[0]
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
        out = {k: part.get(k) for k in self._attrs if k in part}
        if self._key == "filament_total":   # 0.6.0 every spool for the stock card
            out["spools"] = (self.coordinator.data or {}).get("spools") or []
        return {**out, "g7": self._key, "site": self._site}


class BoxSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    """One storage box: state = rolls inside · attrs = low rolls, humidity, temperature, over limit."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:archive-outline"
    _attr_native_unit_of_measurement = "rolls"
    _unrecorded_attributes = BIG

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, key: str, name: str) -> None:
        super().__init__(coord)
        self._key, self._site = key, uid.split(":")[0]
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
        return {**{k: b.get(k) for k in ("name", "low", "humidity", "temp", "humidity_max", "over", "seen_at")}, "g7": "box", "site": self._site}


class ListSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    """0.6.0 a list from the site (printers · connected sensors): state = how many are active, the list in attributes."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = BIG

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, key: str, icon: str, active: Any) -> None:
        super().__init__(coord)
        self._key, self._site, self._active = key, uid.split(":")[0], active
        self._attr_unique_id = f"{uid}:{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_info = _device(site, uid)

    def _list(self) -> list[dict[str, Any]] | None:
        v = (self.coordinator.data or {}).get(self._key)
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else None

    @property
    def available(self) -> bool:
        return super().available and self._list() is not None

    @property
    def native_value(self) -> int | None:
        items = self._list()
        return None if items is None else sum(1 for x in items if self._active(x))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        items = self._list() or []
        return {self._key: items, "total": len(items), "g7": self._key, "site": self._site}


class SiteDeviceSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    """0.6.1 one sensor connected to the site (HA · SmartThings · Matter · MQTT · BLE …): state = online / offline / never.

    Temperature · humidity · where it is attached · how it connects · last message are attributes.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline", "never"]
    _attr_translation_key = "site_device"
    _unrecorded_attributes = BIG

    def __init__(self, coord: StatusCoordinator, uid: str, site: str, dev_id: int, name: str) -> None:
        super().__init__(coord)
        self._id, self._site = dev_id, uid.split(":")[0]
        self._attr_unique_id = f"{uid}:dev:{dev_id}"
        self._attr_name = name
        self._attr_device_info = _device(site, uid)

    def _dev(self) -> dict[str, Any] | None:
        for d in (self.coordinator.data or {}).get("devices") or []:
            if isinstance(d, dict) and d.get("id") == self._id:
                return d
        return None

    @property
    def available(self) -> bool:
        return super().available and self._dev() is not None

    @property
    def native_value(self) -> str | None:
        d = self._dev()
        if d is None:
            return None
        return "online" if d.get("live") else ("never" if d.get("never") else "offline")

    @property
    def icon(self) -> str:
        v = self.native_value
        return "mdi:access-point-check" if v == "online" else ("mdi:access-point-off" if v == "offline" else "mdi:access-point-remove")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._dev() or {}
        out = {"temperature": d.get("temp"), "humidity": d.get("humidity"), "attached_to": d.get("where"), "connection": d.get("source"),
               "ha_server": d.get("server"), "device_state": d.get("state"), "over_limit": d.get("over"), "company": d.get("company"), "last_seen": d.get("seen")}
        return {**{k: v for k, v in out.items() if v not in (None, "")}, "g7": "site_device", "site": self._site}
