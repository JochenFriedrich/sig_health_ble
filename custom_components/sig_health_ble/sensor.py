"""Sensor platform for SIG Health BLE — dispatches to device sub-packages."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_DEVICE_TYPE, DEVICE_TYPE_SCALE, DEVICE_TYPE_BPM, DEVICE_TYPE_GLUCOSE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device_type: str = entry.data[CONF_DEVICE_TYPE]

    if device_type == DEVICE_TYPE_BPM:
        from .devices.bpm.sensor import async_setup_entry as _setup
    elif device_type == DEVICE_TYPE_GLUCOSE:
        from .devices.glucose.sensor import async_setup_entry as _setup
    elif device_type == DEVICE_TYPE_SCALE:
        from .devices.scale.sensor import async_setup_entry as _setup
    else:
        raise ValueError(f"Unknown device type: {device_type}")

    await _setup(hass, entry, async_add_entities)
