"""SIG Health BLE integration for Home Assistant.

Supports:
  • Blood Pressure Monitors  (Bluetooth SIG 0x1810)
  • Glucose Meters           (Bluetooth SIG 0x1808)
  • Weight Scales            (Bluetooth SIG 0x181D / 0x181B)

Architecture: local_push — advertisement callback triggers BLE connection,
GATT notify/indicate delivers data, coordinator publishes to sensor entities.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    async_register_callback,
    BluetoothCallbackMatcher,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    CONF_BONDED_PROXY,
    DEVICE_TYPE_SCALE,
    DEVICE_TYPE_BPM,
    DEVICE_TYPE_GLUCOSE,
)
from .devices.scale.const import CONF_SCALE_MODEL
from .config_flow import _apply_options_to_coordinator

if TYPE_CHECKING:
    from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SIG Health BLE from a config entry."""
    address: str     = entry.data[CONF_ADDRESS]
    device_type: str = entry.data[CONF_DEVICE_TYPE]

    coordinator = _build_coordinator(hass, entry, address, device_type)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Apply saved bonded proxy (BPM + Glucose always; Scale only if bonding_required)
    bonded_proxy = entry.data.get(CONF_BONDED_PROXY)
    if bonded_proxy and getattr(coordinator, "bonding_required", False):
        coordinator.bonded_proxy = bonded_proxy
        _LOGGER.debug(
            "[%s] Bonded proxy restored from config entry: %s",
            address, bonded_proxy,
        )

    # Apply saved scale options
    if entry.options and device_type == DEVICE_TYPE_SCALE:
        _apply_options_to_coordinator(hass, entry.entry_id, entry.options)

    await coordinator.async_config_entry_first_refresh()

    @callback
    def _ble_callback(service_info: BluetoothServiceInfoBleak, change) -> None:
        coordinator.handle_advertisement(service_info)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _ble_callback,
            BluetoothCallbackMatcher(address=address),
            BluetoothScanningMode.ACTIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _build_coordinator(
    hass: HomeAssistant, entry: ConfigEntry, address: str, device_type: str
):
    """Instantiate the right coordinator for the device type."""
    name = entry.title

    if device_type == DEVICE_TYPE_BPM:
        from .devices.bpm.coordinator import BPMCoordinator
        return BPMCoordinator(hass, address, name, entry_id=entry.entry_id)

    if device_type == DEVICE_TYPE_GLUCOSE:
        from .devices.glucose.coordinator import GlucoseCoordinator
        return GlucoseCoordinator(hass, address, name, entry_id=entry.entry_id)

    if device_type == DEVICE_TYPE_SCALE:
        from .devices.scale.coordinator import ScaleCoordinator
        model = entry.data.get(CONF_SCALE_MODEL, "")
        return ScaleCoordinator(
            hass, address, name, model,
            config_entry=entry, entry_id=entry.entry_id
        )

    raise ValueError(f"Unknown device type: {device_type}")
