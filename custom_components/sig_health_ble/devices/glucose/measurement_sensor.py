"""Glucose composite measurement sensor.

Add this to devices/glucose/sensor.py — import GlucoseMeasurementSensor and
append it to the entities list in async_setup_entry.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from ...measurement_sensor import MeasurementSensor
from ...const import DOMAIN
from .coordinator import GlucoseCoordinator
from .parser import GlucoseMeasurement

UNIT_MMOL_L = "mmol/L"


class GlucoseMeasurementSensor(MeasurementSensor):
    """All glucose fields in one entity.  State = glucose in mmol/L."""

    _attr_name = "Measurement"
    _attr_icon = "mdi:water-percent"
    _attr_native_unit_of_measurement = UNIT_MMOL_L
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: GlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_measurement"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Bluetooth SIG",
            model="Glucose Meter (0x1808)",
        )

    def _primary_value(self, m: GlucoseMeasurement) -> Any:
        return m.glucose_mmol_l

    def _attributes(self, m: GlucoseMeasurement) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "glucose_mg_dl": m.glucose_mg_dl,
            "concentration_unit": m.concentration_unit_raw,
            "sequence_number": m.sequence_number,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            "time_offset_minutes": m.time_offset_minutes,
            "sample_type": m.sample_type,
            "sample_location": m.sample_location,
            # Sensor status
            "measurement_valid": m.measurement_valid,
            "status_summary": m.status_summary,
            "device_battery_low": m.device_battery_low,
            "sensor_malfunction": m.sensor_malfunction,
            "sample_size_insufficient": m.sample_size_insufficient,
            "strip_insertion_error": m.strip_insertion_error,
            "strip_type_incorrect": m.strip_type_incorrect,
            "sensor_result_too_high": m.sensor_result_too_high,
            "sensor_result_too_low": m.sensor_result_too_low,
            "sensor_temperature_too_high": m.sensor_temperature_too_high,
            "sensor_temperature_too_low": m.sensor_temperature_too_low,
            "general_device_fault": m.general_device_fault,
            "status_flags_raw": m.status_flags_hex,
        }
        # Context fields (only if context was reported by device)
        if m.context:
            ctx = m.context
            attrs.update({
                "meal": ctx.meal,
                "tester": ctx.tester,
                "health": ctx.health,
                "hba1c_pct": ctx.hba1c_pct,
                "carbohydrate": ctx.carbohydrate_id,
                "carbohydrate_kg": ctx.carbohydrate_kg,
                "medication": ctx.medication_id,
                "medication_amount": ctx.medication_amount,
                "medication_unit": ctx.medication_unit,
                "exercise_duration_s": ctx.exercise_duration_s,
                "exercise_intensity_pct": ctx.exercise_intensity_pct,
            })
        attrs["raw_hex"] = m.raw.hex() if m.raw else None
        return attrs
