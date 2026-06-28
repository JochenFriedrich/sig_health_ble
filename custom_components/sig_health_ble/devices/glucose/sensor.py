"""Sensor platform for Glucose Meter devices."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ...base_entity import SigHealthBleEntity
from ...const import DOMAIN
from ...diagnostic_sensor import create_proxy_diagnostic_sensor
from .coordinator import GlucoseCoordinator
from .parser import GlucoseMeasurement
from .measurement_sensor import GlucoseMeasurementSensor

_ATTRIBUTION = "Bluetooth SIG Glucose Service (0x1808)"
UNIT_MMOL_L = "mmol/L"
UNIT_MG_DL  = "mg/dL"
UNIT_PERCENT = "%"


@dataclass(frozen=True, kw_only=True)
class GlucoseSensorDescription(SensorEntityDescription):
    value_fn: Callable[[GlucoseMeasurement], Any] = lambda _: None
    optional: bool = False


_CONCENTRATION_DESCRIPTIONS: tuple[GlucoseSensorDescription, ...] = (
    GlucoseSensorDescription(
        key="glucose_mmol_l", name="Glucose",
        icon="mdi:water-percent", native_unit_of_measurement=UNIT_MMOL_L,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda m: m.glucose_mmol_l,
    ),
    GlucoseSensorDescription(
        key="glucose_mg_dl", name="Glucose (mg/dL)",
        icon="mdi:water-percent", native_unit_of_measurement=UNIT_MG_DL,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0,
        value_fn=lambda m: m.glucose_mg_dl,
    ),
)

_META_DESCRIPTIONS: tuple[GlucoseSensorDescription, ...] = (
    GlucoseSensorDescription(
        key="sequence_number", name="Record Sequence Number",
        icon="mdi:counter", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda m: m.sequence_number,
    ),
    GlucoseSensorDescription(
        key="measurement_time", name="Last Measurement Time",
        icon="mdi:clock-outline", device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda m: m.timestamp,
    ),
    GlucoseSensorDescription(
        key="sample_type", name="Sample Type",
        icon="mdi:water", value_fn=lambda m: m.sample_type,
    ),
    GlucoseSensorDescription(
        key="sample_location", name="Sample Location",
        icon="mdi:map-marker", value_fn=lambda m: m.sample_location,
    ),
)

_STATUS_DESCRIPTIONS: tuple[GlucoseSensorDescription, ...] = (
    GlucoseSensorDescription(key="battery_low", name="Device Battery Low",
        icon="mdi:battery-low", value_fn=lambda m: m.device_battery_low),
    GlucoseSensorDescription(key="sensor_malfunction", name="Sensor Malfunction",
        icon="mdi:alert-circle", value_fn=lambda m: m.sensor_malfunction),
    GlucoseSensorDescription(key="result_too_high", name="Result Too High",
        icon="mdi:arrow-up-bold", value_fn=lambda m: m.sensor_result_too_high),
    GlucoseSensorDescription(key="result_too_low", name="Result Too Low",
        icon="mdi:arrow-down-bold", value_fn=lambda m: m.sensor_result_too_low),
    GlucoseSensorDescription(key="strip_insertion_error", name="Strip Insertion Error",
        icon="mdi:test-tube-off", value_fn=lambda m: m.strip_insertion_error),
    GlucoseSensorDescription(key="general_device_fault", name="General Device Fault",
        icon="mdi:alert", value_fn=lambda m: m.general_device_fault),
)

_MEASUREMENT_QUALITY_DESCRIPTIONS: tuple[GlucoseSensorDescription, ...] = (
    GlucoseSensorDescription(
        key="measurement_valid", name="Measurement Valid",
        icon="mdi:check-circle-outline", optional=True,
        value_fn=lambda m: m.measurement_valid,
    ),
    GlucoseSensorDescription(
        key="status_flags_raw", name="Status Flags",
        icon="mdi:flag-outline", optional=True,
        value_fn=lambda m: m.status_flags_hex,
    ),
    GlucoseSensorDescription(
        key="status_summary", name="Status Summary",
        icon="mdi:list-status", optional=True,
        value_fn=lambda m: m.status_summary,
    ),
)

_CONTEXT_DESCRIPTIONS: tuple[GlucoseSensorDescription, ...] = (
    GlucoseSensorDescription(key="meal", name="Meal", icon="mdi:food", optional=True,
        value_fn=lambda m: m.context.meal if m.context else None),
    GlucoseSensorDescription(key="tester", name="Tester", icon="mdi:account", optional=True,
        value_fn=lambda m: m.context.tester if m.context else None),
    GlucoseSensorDescription(key="health", name="Health Status", icon="mdi:heart", optional=True,
        value_fn=lambda m: m.context.health if m.context else None),
    GlucoseSensorDescription(
        key="hba1c", name="HbA1c", icon="mdi:percent",
        native_unit_of_measurement=UNIT_PERCENT,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        optional=True, value_fn=lambda m: m.context.hba1c_pct if m.context else None,
    ),
    GlucoseSensorDescription(key="carbohydrate", name="Carbohydrate", icon="mdi:food-apple",
        optional=True, value_fn=lambda m: m.context.carbohydrate_id if m.context else None),
    GlucoseSensorDescription(key="medication", name="Medication", icon="mdi:needle",
        optional=True, value_fn=lambda m: m.context.medication_id if m.context else None),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GlucoseCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        GlucoseSensor(coordinator, entry, desc)
        for desc in (
            *_CONCENTRATION_DESCRIPTIONS, *_META_DESCRIPTIONS,
            *_STATUS_DESCRIPTIONS, *_CONTEXT_DESCRIPTIONS,
            *_MEASUREMENT_QUALITY_DESCRIPTIONS,
        )
    ]
    entities.append(create_proxy_diagnostic_sensor(
        coordinator, entry,
        device_identifiers={(DOMAIN, coordinator.address)},
        device_name=coordinator.device_name,
        device_manufacturer="Bluetooth SIG",
        device_model="Glucose Meter (0x1808)",
    ))
    entities.append(GlucoseMeasurementSensor(coordinator, entry))
    async_add_entities(entities)


class GlucoseSensor(SigHealthBleEntity):
    entity_description: GlucoseSensorDescription
    _attr_has_entity_name = True
    _attr_attribution = _ATTRIBUTION

    def __init__(
        self, coordinator: GlucoseCoordinator, entry: ConfigEntry,
        description: GlucoseSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Bluetooth SIG",
            model="Glucose Meter (0x1808)",
        )

    @property
    def native_value(self) -> Any:
        m = self.coordinator.data
        if m is None:
            return self._attr_native_value
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
        attrs: dict = {
            "sequence_number": m.sequence_number,
            "raw_hex": m.raw.hex(),
            "concentration_unit_from_device": m.concentration_unit_raw,
        }
        if m.timestamp:
            attrs["device_timestamp"] = m.timestamp.isoformat()
        if m.context:
            ctx = m.context
            if ctx.exercise_duration_s is not None:
                attrs["exercise_duration_s"] = ctx.exercise_duration_s
                attrs["exercise_intensity_pct"] = ctx.exercise_intensity_pct
            if ctx.medication_amount is not None:
                attrs["medication_amount"] = ctx.medication_amount
                attrs["medication_unit"] = ctx.medication_unit
            if ctx.carbohydrate_kg is not None:
                attrs["carbohydrate_kg"] = ctx.carbohydrate_kg
        return attrs

    def _restore_value(self, state: str) -> Any:
        try:
            return float(state)
        except (ValueError, TypeError):
            return state
