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

from .const import CONF_CODE, CONF_SCOPES, CONF_SITE, DOMAIN
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
    ("recommended", "jobs", "recommended", "Requests recommended to the company", "mdi:star-circle-outline", None, ()),
)

# 0.7.0 each category is its own device (its own box on the device page) under the site device
CATS = {"notices": ("Notices · orders", "알림 · 주문"), "orders": ("Notices · orders", "알림 · 주문"), "jobs": ("Requests · bids", "의뢰 · 입찰"),
        "filament": ("Filament stock", "필라멘트 재고"), "boxes": ("Storage boxes", "보관함"), "devices": ("Connected sensors", "연결된 센서"), "printers": ("Printers", "프린터")}
CAT_KEY = {"orders": "notices"}


# 0.6.0 big lists for the cards — kept out of the recorder (history database)
BIG = frozenset({"spools", "printers", "devices", "low_list", "g7", "site"})


class StatusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads hub/{code}/status every 5 minutes."""

    def __init__(self, hass: HomeAssistant, site: str, code: str, scope: str = "all") -> None:
        super().__init__(hass, _LOGGER, name=f"3DSSync status {urlparse(site).netloc} {scope}", update_interval=SCAN)
        self.site, self.code, self.scope = site, code, scope
        self.scopes: list[dict[str, str]] = []   # what the site offers (personal · each company) — filled by the first answer

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            rest = f"{self.code}/status" + ("" if self.scope == "all" else f"?scope={self.scope}")
            resp = await hub_request(async_get_clientsession(self.hass), "GET", self.site, rest, hass=self.hass, timeout=_TIMEOUT)
            if resp.status != 200:
                resp.release()
                raise UpdateFailed(f"site answered {resp.status} (IoT link plugin 1.19.0+ needed)")
            data = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            raise UpdateFailed(str(err)) from err
        if not isinstance(data, dict) or not data.get("ok") or not isinstance(data.get("status"), dict):
            raise UpdateFailed("no status from the site")
        if isinstance(data.get("scopes"), list):
            self.scopes = [s for s in data["scopes"] if isinstance(s, dict) and s.get("key")]
        return data["status"]


def _device(site: str, uid: str) -> dict[str, Any]:
    host = urlparse(site).netloc or site
    return {"identifiers": {(DOMAIN, f"status:{uid}")}, "name": f"3DSSync — {host}", "manufacturer": "3DS", "model": "Site status", "configuration_url": site}


class Ctx:
    """0.7.0 one scope of one site: where its sensors go (a device per category) and how they are named."""

    def __init__(self, hass: HomeAssistant, site: str, uid: str, scope: str, scope_name: str) -> None:
        self.site, self.uid, self.scope, self.scope_name = site, uid, scope, scope_name
        self.host = urlparse(site).netloc or site
        self.ko = str(getattr(hass.config, "language", "") or "").startswith("ko")
        self.base = uid if scope == "all" else f"{uid}|{scope}"   # unique id start
        self.label = f"{self.host} · {scope_name}" if scope_name else self.host   # the card groups by this

    def device(self, cat: str) -> dict[str, Any]:
        cat = CAT_KEY.get(cat, cat)
        en, ko = CATS.get(cat, (cat, cat))
        name = ko if self.ko else en
        parent = f"status:{self.uid}" if self.scope == "all" else f"status:{self.base}"   # 0.7.1 categories sit under their personal / company device
        return {"identifiers": {(DOMAIN, f"status:{self.base}:{cat}")}, "name": f"{self.scope_name} {name}".strip(),
                "manufacturer": "3DS", "model": "3DSSync", "via_device": (DOMAIN, parent), "configuration_url": self.site}

    def scope_device(self) -> dict[str, Any] | None:
        """0.7.1 👤 personal / 🏢 company — groups that scope's category devices (site → scope → category)."""
        if self.scope == "all":
            return None
        return {"identifiers": {(DOMAIN, f"status:{self.base}")}, "name": f"3DSSync {self.scope_name}", "manufacturer": "3DS",
                "model": "Personal" if self.scope == "me" else "Company", "via_device": (DOMAIN, f"status:{self.uid}"), "configuration_url": self.site}


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
    host = urlparse(site).netloc or site
    uid = host + ":" + hashlib.sha1(code.encode()).hexdigest()[:10]   # two accounts on one site stay apart · the code itself is not shown
    probe = StatusCoordinator(hass, site, code)
    await probe.async_refresh()   # failure → sensors unavailable, keeps retrying
    # the site device (parent of the category devices)
    from homeassistant.helpers import device_registry as dr

    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **_device(site, uid))
    names = {s["key"]: str(s.get("name") or s["key"]) for s in probe.scopes}
    saved = [s for s in (conf.get(CONF_SCOPES) or []) if isinstance(s, str)]
    if names:
        chosen = [s for s in (saved or list(names)) if s in names] or list(names)
    elif saved and not probe.last_update_success:   # site not reachable now → the saved choice (names come back on the next start)
        chosen = saved
        names = {s: ("👤" if s == "me" else "🏢 #" + s[2:]) for s in saved}
    else:
        chosen = ["all"]   # old site without scopes → everything as before
    keep: list[str] = []
    for scope in chosen:
        coord = probe if scope == "all" else StatusCoordinator(hass, site, code, scope)
        if coord is not probe:
            await coord.async_refresh()
        ctx = Ctx(hass, site, uid, scope, names.get(scope, ""))
        keep.append(ctx.base + "|")
        if (sd := ctx.scope_device()) is not None:
            dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **sd)
        _setup_scope(hass, entry, coord, ctx, async_add_entities)
    if probe.last_update_success:
        _cleanup(hass, entry, uid, keep)


def _cleanup(hass: HomeAssistant, entry: ConfigEntry, uid: str, keep: list[str]) -> None:
    """0.7.0 remove sensors of scopes no longer picked, and the 0.5/0.6 ones (one device, no scope)."""
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
        if ent.domain == "sensor" and ent.platform == DOMAIN and ent.unique_id.startswith(uid) and not any(ent.unique_id.startswith(k) for k in keep):
            reg.async_remove(ent.entity_id)


def _setup_scope(hass: HomeAssistant, entry: ConfigEntry, coord: "StatusCoordinator", ctx: Ctx, async_add_entities: AddEntitiesCallback) -> None:
    data = coord.data or {}
    ents: list[SensorEntity] = []
    for s in SENSORS:   # only what the site sends for this scope (a company has no notices · orders)
        part = data.get(s[1])
        if isinstance(part, dict) and s[2] in part:
            ents.append(StatusSensor(coord, ctx, *s))
    if isinstance(data.get("printers"), list):
        ents.append(ListSensor(coord, ctx, "printers", "mdi:printer-3d", lambda p: p.get("state") in ("printing", "paused")))   # state = printing now
    if isinstance(data.get("devices"), list):
        ents.append(ListSensor(coord, ctx, "devices", "mdi:access-point-network", lambda d: bool(d.get("live"))))           # state = sensors talking to the site
    async_add_entities(ents)

    # one entity per storage box and per connected sensor on the site — new ones appear by themselves
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        data = coord.data or {}
        new: list[SensorEntity] = []
        for box in data.get("boxes") or []:
            if isinstance(box, dict) and box.get("key") and f"b:{box['key']}" not in known:
                known.add(f"b:{box['key']}")
                new.append(BoxSensor(coord, ctx, str(box["key"]), str(box.get("name") or box["key"])))
        for dev in data.get("devices") or []:
            if isinstance(dev, dict) and dev.get("id") and f"d:{dev['id']}" not in known:
                known.add(f"d:{dev['id']}")
                new.append(SiteDeviceSensor(coord, ctx, int(dev["id"]), str(dev.get("name") or dev["id"])))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coord.async_add_listener(_add_new))



class StatusSensor(CoordinatorEntity[StatusCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = BIG

    def __init__(self, coord: StatusCoordinator, ctx: Ctx, key: str, section: str, field: str, name: str, icon: str, unit: str | None, attrs: tuple[str, ...]) -> None:
        super().__init__(coord)
        self._section, self._field, self._attrs = section, field, attrs
        self._key, self._site = key, ctx.label
        self._attr_unique_id = f"{ctx.base}|{key}"
        self._attr_translation_key = key   # Korean / English names from translations/*.json (entity.sensor.<key>)
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = ctx.device(section)

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

    def __init__(self, coord: StatusCoordinator, ctx: Ctx, key: str, name: str) -> None:
        super().__init__(coord)
        self._key, self._site = key, ctx.label
        self._attr_unique_id = f"{ctx.base}|box|{hashlib.sha1(key.encode()).hexdigest()[:10]}"
        self._attr_translation_key = "box"
        self._attr_translation_placeholders = {"name": name}
        self._attr_device_info = ctx.device("boxes")

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

    def __init__(self, coord: StatusCoordinator, ctx: Ctx, key: str, icon: str, active: Any) -> None:
        super().__init__(coord)
        self._key, self._site, self._active = key, ctx.label, active
        self._attr_unique_id = f"{ctx.base}|{key}"
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_device_info = ctx.device(key)

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

    def __init__(self, coord: StatusCoordinator, ctx: Ctx, dev_id: int, name: str) -> None:
        super().__init__(coord)
        self._id, self._site = dev_id, ctx.label
        self._attr_unique_id = f"{ctx.base}|dev|{dev_id}"
        self._attr_name = name
        self._attr_device_info = ctx.device("devices")

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
