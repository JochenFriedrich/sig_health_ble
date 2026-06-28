"""BPM composite measurement sensor.

Add this to devices/bpm/sensor.py — import BPMMeasurementSensor and
append it to the entities list in async_setup_entry.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPressure
from homeassistant.helpers.device_registry import DeviceInfo

from ...measurement_sensor import MeasurementSensor
from ...const import DOMAIN
from .const import UNIT_MMHG, UNIT_KPA
from .coordinator import BPMCoordinator
from .parser import BloodPressureMeasurement


class BPMMeasurementSensor(MeasurementSensor):
    """All BPM fields in one entity.  State = systolic pressure."""

    _attr_name = "Measurement"
    _attr_icon = "mdi:heart-pulse"
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: BPMCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_measurement"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Bluetooth SIG",
            model="Blood Pressure Monitor (0x1810)",
        )

    @property
    def native_unit_of_measurement(self) -> str:
        m: BloodPressureMeasurement | None = self.coordinator.data
        if m is None:
            return UNIT_MMHG
        return UnitOfPressure.KPA if m.unit == UNIT_KPA else UNIT_MMHG

    def _primary_value(self, m: BloodPressureMeasurement) -> Any:
        return m.systolic

    def _attributes(self, m: BloodPressureMeasurement) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "diastolic": m.diastolic,
            "mean_arterial_pressure": m.mean_arterial_pressure,
            "unit": m.unit,
            "pulse_rate": m.pulse_rate,
            "user_id": m.user_id,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
            # Measurement status
            "measurement_valid": m.measurement_valid,
            "status_summary": m.status_summary,
            "body_movement_detected": m.body_movement_detected,
            "cuff_too_loose": m.cuff_too_loose,
            "irregular_pulse": m.irregular_pulse,
            "pulse_rate_out_of_range": m.pulse_rate_out_of_range,
            "measurement_position_error": m.measurement_position_error,
            # Diagnostic
            "status_flags_raw": m.status_flags_hex,
            "raw_hex": m.raw.hex() if m.raw else None,
        }
        return attrs
