"""Base entity class for all SIG Health BLE sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class SigHealthBleEntity(CoordinatorEntity, RestoreEntity, SensorEntity):
    """Base class for all SIG Health BLE sensor entities.

    Restores last known value on HA restart so:
      - The sensor never appears unavailable between measurements
      - Long-Term Statistics accumulates correctly (hourly job always
        sees a valid state rather than 'unavailable')
    """

    _attr_should_poll = False
    _attr_available   = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if last_state := await self.async_get_last_state():
            if last_state.state not in ("unavailable", "unknown", None):
                try:
                    self._attr_native_value = self._restore_value(last_state.state)
                    self._attr_available = True
                    _LOGGER.debug(
                        "[%s] Restored last state: %s",
                        self.unique_id, last_state.state,
                    )
                except (ValueError, TypeError):
                    pass  # non-numeric sensors (strings, booleans) — leave as-is

    def _restore_value(self, state: str) -> Any:
        """Convert the stored state string back to a native value.

        Override in subclasses that store non-float values (timestamps,
        strings, booleans).  Default implementation tries float conversion.
        """
        return float(state)

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

