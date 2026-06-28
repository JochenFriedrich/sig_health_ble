"""Diagnostic sensor showing the bonded/pinned ESPHome proxy status.

Available on BPM and Glucose devices (the ones using NotifyCoordinator with
proxy pinning support). Surfaces:
  - The configured bonded proxy (if pinning is enabled)
  - The most recently seen advertisement source (any proxy)
  - The proxy used for the last successful connection

This helps diagnose situations where habluetooth might be routing through
an unexpected proxy, or where pinning is silently dropping advertisements.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_BONDED_PROXY_DESCRIPTION = SensorEntityDescription(
    key="bonded_proxy_status",
    name="Bonded Proxy",
    icon="mdi:bluetooth-connect",
    entity_category=EntityCategory.DIAGNOSTIC,
)


def create_proxy_diagnostic_sensor(
    coordinator: Any,
    entry: ConfigEntry,
    device_identifiers: dict,
    device_name: str,
    device_manufacturer: str,
    device_model: str,
) -> "BondedProxySensor":
    """Factory used by BPM and Glucose sensor.py to add the diagnostic sensor."""
    return BondedProxySensor(
        coordinator, entry, device_identifiers,
        device_name, device_manufacturer, device_model,
    )


class BondedProxySensor(CoordinatorEntity, SensorEntity):
    """Reports which ESPHome proxy is pinned / was last used to connect."""

    entity_description = _BONDED_PROXY_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Any,
        entry: ConfigEntry,
        device_identifiers: dict,
        device_name: str,
        device_manufacturer: str,
        device_model: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_bonded_proxy_status"
        self._attr_device_info = DeviceInfo(
            identifiers=device_identifiers,
            name=device_name,
            manufacturer=device_manufacturer,
            model=device_model,
        )

    @property
    def native_value(self) -> str:
        coordinator = self.coordinator
        bonded = getattr(coordinator, "bonded_proxy", None)
        last_connected = getattr(coordinator, "last_connected_proxy", None)

        if bonded is None:
            return "Unpinned"
        if last_connected == bonded:
            return "Pinned (OK)"
        if last_connected and last_connected != bonded:
            return "Pinned (mismatch!)"
        return "Pinned (no connection yet)"

    @property
    def extra_state_attributes(self) -> dict:
        coordinator = self.coordinator
        return {
            "bonded_proxy": getattr(coordinator, "bonded_proxy", None),
            "last_seen_proxy": getattr(coordinator, "last_seen_proxy", None),
            "last_connected_proxy": getattr(coordinator, "last_connected_proxy", None),
        }

    @property
    def available(self) -> bool:
        return True  # always available, even before first measurement
