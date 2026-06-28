"""Scale composite measurement sensor.

Add this to devices/scale/sensor.py — import ScaleMeasurementSensor and
append it to the entities list in async_setup_entry.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from ...measurement_sensor import MeasurementSensor
from ...const import DOMAIN
from .const import UNIT_KG, CONF_SCALE_MODEL
from .coordinator import ScaleCoordinator
from .parser import ScaleMeasurement

UNIT_PERCENT = "%"
UNIT_OHM = "Ω"
UNIT_KJ  = "kJ"
UNIT_CM  = "cm"
UNIT_LB  = "lb"


class ScaleMeasurementSensor(MeasurementSensor):
    """All scale fields in one entity.  State = weight in kg."""

    _attr_name = "Measurement"
    _attr_icon = "mdi:scale-bathroom"
    _attr_native_unit_of_measurement = UNIT_KG
    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: ScaleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_measurement"
        model        = entry.data.get(CONF_SCALE_MODEL, "")
        manufacturer = entry.data.get("manufacturer", "Unknown")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer=manufacturer,
            model=model or "Weight Scale (0x181D / 0x181B)",
        )

    def _primary_value(self, m: ScaleMeasurement) -> Any:
        return m.weight_kg

    def _attributes(self, m: ScaleMeasurement) -> dict[str, Any]:
        attrs: dict[str, Any] = {"bmi": m.bmi}

        if m.timestamp:
            attrs["timestamp"] = m.timestamp.isoformat()

        # Weight record fields
        if m.weight:
            w = m.weight
            attrs.update({
                "weight_lb": w.weight_lb,
                "weight_unit": w.unit,
                "height_cm": round(w.height_m * 100, 1) if w.height_m is not None else None,
                "height_in": w.height_in,
                "user_id": w.user_id,
                "weight_raw_hex": w.raw.hex() if w.raw else None,
            })

        # Body composition fields
        if m.body_composition:
            bcm = m.body_composition
            attrs.update({
                "body_fat_percent": bcm.body_fat_percent,
                "muscle_percent": bcm.muscle_percent,
                "muscle_mass_kg": bcm.muscle_mass_kg,
                "fat_free_mass_kg": bcm.fat_free_mass_kg,
                "soft_lean_mass_kg": bcm.soft_lean_mass_kg,
                "body_water_mass_kg": bcm.body_water_mass_kg,
                "impedance_ohm": bcm.impedance_ohm,
                "basal_metabolism_kj": bcm.basal_metabolism_kj,
                "bcm_raw_hex": bcm.raw.hex() if bcm.raw else None,
            })
            # bcm.weight_kg is the BCM-service weight — use as fallback label
            if bcm.weight_kg is not None and m.weight is None:
                attrs["weight_source"] = "body_composition_service"
            elif m.weight is not None:
                attrs["weight_source"] = "weight_scale_service"

        return attrs
