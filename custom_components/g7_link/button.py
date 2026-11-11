"""0.8.0 「지금 새로 고침」 — one button per personal / company device (the device page's controls box).

The site is read every 5 minutes; this reads it now (after you changed stock or sensors on the site).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_ADD = "_button_add"      # entry_id → async_add_entities of this platform
_WAIT = "_button_wait"    # entry_id → coordinators the sensor platform made before this platform was ready


def offer(hass: HomeAssistant, entry: ConfigEntry, coords: list[tuple[Any, Any]]) -> None:
    """Called by the sensor platform with its coordinators (one per scope)."""
    store = hass.data.setdefault(DOMAIN, {})
    add = store.get(_ADD, {}).get(entry.entry_id)
    if add is None:
        store.setdefault(_WAIT, {})[entry.entry_id] = coords
        return
    add([RefreshButton(c, ctx) for c, ctx in coords])


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    store.setdefault(_ADD, {})[entry.entry_id] = async_add_entities
    waiting = store.get(_WAIT, {}).pop(entry.entry_id, None)
    if waiting:
        async_add_entities([RefreshButton(c, ctx) for c, ctx in waiting])

    def _forget() -> None:
        store.get(_ADD, {}).pop(entry.entry_id, None)
        store.get(_WAIT, {}).pop(entry.entry_id, None)

    entry.async_on_unload(_forget)


class RefreshButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coord: Any, ctx: Any) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{ctx.base}|refresh"
        self._attr_device_info = ctx.device()

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
