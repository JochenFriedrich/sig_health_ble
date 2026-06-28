"""Sensor platform for Blood Pressure Monitor devices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...base_entity import SigHealthBleEntity
from ...const import DOMAIN
from ...diagnostic_sensor import create_proxy_diagnostic_sensor
from .const import UNIT_MMHG, UNIT_KPA
from .coordinator import BPMCoordinator
from .parser import BloodPressureMeasurement
from .measurement_sensor import BPMMeasurementSensor

_ATTRIBUTION = "Bluetooth SIG Blood Pressure Service (0x1810)"


@dataclass(frozen=True, kw_only=True)
class BPMSensorDescription(SensorEntityDescription):
    value_fn: Callable[[BloodPressureMeasurement], Any] = lambda _: None
    optional: bool = False  # if True, unavailable until device reports this field


_PRESSURE_DESCRIPTIONS: tuple[BPMSensorDescription, ...] = (
    BPMSensorDescription(
        key="systolic",
        name="Systolic Pressure",
        icon="mdi:heart-pulse",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m: m.systolic,
    ),
    BPMSensorDescription(
        key="diastolic",
        name="Diastolic Pressure",
        icon="mdi:heart",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m: m.diastolic,
    ),
    BPMSensorDescription(
        key="mean_arterial_pressure",
        name="Mean Arterial Pressure",
        icon="mdi:gauge",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda m: m.mean_arterial_pressure,
    ),
)

_PULSE_DESCRIPTION = BPMSensorDescription(
    key="pulse_rate",
    name="Pulse Rate",
    icon="mdi:heart-flash",
    native_unit_of_measurement="bpm",
    state_class=SensorStateClass.MEASUREMENT,
    suggested_display_precision=0,
    value_fn=lambda m: m.pulse_rate,
)

_STATUS_DESCRIPTIONS: tuple[BPMSensorDescription, ...] = (
    BPMSensorDescription(
        key="body_movement",
        name="Body Movement Detected",
        icon="mdi:run",
        value_fn=lambda m: m.body_movement_detected,
    ),
    BPMSensorDescription(
        key="irregular_pulse",
        name="Irregular Pulse Detected",
        icon="mdi:heart-broken",
        value_fn=lambda m: m.irregular_pulse,
    ),
    BPMSensorDescription(
        key="cuff_too_loose",
        name="Cuff Too Loose",
        icon="mdi:bandage",
        value_fn=lambda m: m.cuff_too_loose,
    ),
    BPMSensorDescription(
        key="measurement_position_error",
        name="Measurement Position Error",
        icon="mdi:arm-flex",
        value_fn=lambda m: m.measurement_position_error,
    ),
)

_TIMESTAMP_DESCRIPTION = BPMSensorDescription(
    key="measurement_time",
    name="Last Measurement Time",
    icon="mdi:clock-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    value_fn=lambda m: m.timestamp,
)

_USER_ID_DESCRIPTION = BPMSensorDescription(
    key="user_id",
    name="User ID",
    icon="mdi:account",
    value_fn=lambda m: m.user_id,
)

# ── Measurement quality / status ───────────────────────────────────────────────
# Only present when the device includes the optional Measurement Status field.
_MEASUREMENT_QUALITY_DESCRIPTIONS: tuple[BPMSensorDescription, ...] = (
    BPMSensorDescription(
        key="measurement_valid",
        name="Measurement Valid",
        icon="mdi:check-circle-outline",
        optional=True,
        value_fn=lambda m: m.measurement_valid,
    ),
    BPMSensorDescription(
        key="status_flags_raw",
        name="Status Flags",
        icon="mdi:flag-outline",
        optional=True,
        value_fn=lambda m: m.status_flags_hex,
    ),
    BPMSensorDescription(
        key="status_summary",
        name="Status Summary",
        icon="mdi:list-status",
        optional=True,
        value_fn=lambda m: m.status_summary,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BPMCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[BPMSensor] = []
    for desc in _PRESSURE_DESCRIPTIONS:
        entities.append(BPMPressureSensor(coordinator, entry, desc))
    entities.append(BPMSensor(coordinator, entry, _PULSE_DESCRIPTION))
    for desc in _STATUS_DESCRIPTIONS:
        entities.append(BPMSensor(coordinator, entry, desc))
    entities.append(BPMSensor(coordinator, entry, _TIMESTAMP_DESCRIPTION))
    entities.append(BPMSensor(coordinator, entry, _USER_ID_DESCRIPTION))
    for desc in _MEASUREMENT_QUALITY_DESCRIPTIONS:
        entities.append(BPMSensor(coordinator, entry, desc))
    entities.append(create_proxy_diagnostic_sensor(
        coordinator, entry,
        device_identifiers={(DOMAIN, coordinator.address)},
        device_name=coordinator.device_name,
        device_manufacturer="Bluetooth SIG",
        device_model="Blood Pressure Monitor (0x1810)",
    ))
    entities.append(BPMMeasurementSensor(coordinator, entry))
    async_add_entities(entities)


class BPMSensor(SigHealthBleEntity):
    entity_description: BPMSensorDescription
    _attr_has_entity_name = True
    _attr_attribution = _ATTRIBUTION

    def __init__(
        self,
        coordinator: BPMCoordinator,
        entry: ConfigEntry,
        description: BPMSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Bluetooth SIG",
            model="Blood Pressure Monitor (0x1810)",
        )

    @property
    def native_value(self) -> Any:
        m = self.coordinator.data
        if m is None:
            return self._attr_native_value  # restored value
        return self.entity_description.value_fn(m)

    @property
    def available(self) -> bool:
        if not super().available or self.coordinator.data is None:
            return False
        if self.entity_description.optional:
            return self.entity_description.value_fn(self.coordinator.data) is not None
        return True

    @property
    def extra_state_attributes(self) -> dict:
        m = self.coordinator.data
        if m is None:
            return {}
        attrs: dict = {"raw_hex": m.raw.hex(), "unit_from_device": m.unit}
        if m.timestamp:
            attrs["device_timestamp"] = m.timestamp.isoformat()
        if m.user_id is not None:
            attrs["user_id"] = m.user_id
        return attrs

    def _restore_value(self, state: str) -> Any:
        # Pressure/pulse sensors are numeric; others (bool, timestamp) stay as string
        try:
            return float(state)
        except (ValueError, TypeError):
            return state


class BPMPressureSensor(BPMSensor):
    @property
    def native_unit_of_measurement(self) -> str:
        m = self.coordinator.data
        if m is None:
            return UNIT_MMHG
        if m.unit == UNIT_KPA:
            return UnitOfPressure.KPA
        return "mmHg"
