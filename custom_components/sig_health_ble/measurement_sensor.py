"""Composite measurement sensor — one entity per device, all readings as attributes.

The primary measurement value is the entity state (enabling Long-Term Statistics
and clean graphing). All other fields from the measurement dataclass are exposed
as extra_state_attributes so they can be referenced in ApexCharts, automations,
and templates without needing to track multiple entities.

ApexCharts example — body fat from the scale composite sensor:

  type: custom:apexcharts-card
  graph_span: 90d
  series:
    - entity: sensor.my_scale_measurement
      attribute: body_fat_percent
      statistics:
        type: mean
        period: day

Subclasses implement:
  _primary_value(data) → the state value (becomes the entity state)
  _attributes(data)    → dict of all other fields (None values auto-omitted)
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

DOMAIN = "sig_health_ble"


class MeasurementSensor(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Single composite sensor exposing all measurement fields as attributes.

    Designed to co-exist alongside the individual field sensors — both are
    registered; users can choose whichever suits their use case.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_available = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            if last_state.state not in ("unavailable", "unknown", None):
                try:
                    self._attr_native_value = float(last_state.state)
                    self._attr_available = True
                except (ValueError, TypeError):
                    pass

    @property
    def native_value(self) -> Any:
        data = self.coordinator.data
        if data is None:
            return self._attr_native_value
        return self._primary_value(data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        # Omit None values so the attribute list stays clean
        return {k: v for k, v in self._attributes(data).items() if v is not None}

    def _primary_value(self, data: Any) -> Any:
        raise NotImplementedError

    def _attributes(self, data: Any) -> dict[str, Any]:
        raise NotImplementedError
