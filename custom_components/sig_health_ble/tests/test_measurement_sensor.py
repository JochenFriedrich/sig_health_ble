"""Unit tests for the composite MeasurementSensor and its device subclasses."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest


# ── Helpers shared across subtests ─────────────────────────────────────────────

def _make_coordinator(data=None):
    coord = MagicMock()
    coord.data = data
    coord.address = "AA:BB:CC:DD:EE:FF"
    coord.device_name = "Test Device"
    return coord


def _make_entry(entry_id="test_entry"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"scale_model": "BF720", "manufacturer": "Beurer"}
    return entry


# ── BPMMeasurementSensor ───────────────────────────────────────────────────────

class TestBPMMeasurementSensor:
    def _make(self, m=None):
        from custom_components.sig_health_ble.devices.bpm.parser import (
            BloodPressureMeasurement,
        )
        from custom_components.sig_health_ble.devices.bpm.sensor import (
            BPMMeasurementSensor,
        )
        sensor = BPMMeasurementSensor.__new__(BPMMeasurementSensor)
        sensor.coordinator = _make_coordinator(m)
        sensor._attr_native_value = None
        sensor._attr_unique_id = "test_bpm_measurement"
        sensor._attr_device_info = {}
        return sensor

    def _measurement(self, **kwargs):
        from custom_components.sig_health_ble.devices.bpm.parser import (
            BloodPressureMeasurement,
        )
        defaults = dict(
            systolic=120.0, diastolic=80.0, mean_arterial_pressure=93.0,
            unit="mmHg", pulse_rate=72.0,
            timestamp=datetime(2025, 1, 1, 8, 0, 0),
            user_id=1, raw=b"\x00" * 9,
        )
        defaults.update(kwargs)
        return BloodPressureMeasurement(**defaults)

    def test_state_is_systolic(self):
        sensor = self._make(self._measurement(systolic=122.0))
        assert sensor.native_value == pytest.approx(122.0)

    def test_state_none_when_no_data(self):
        sensor = self._make(None)
        assert sensor.native_value is None

    def test_diastolic_in_attributes(self):
        sensor = self._make(self._measurement(diastolic=78.0))
        assert sensor.extra_state_attributes["diastolic"] == pytest.approx(78.0)

    def test_pulse_rate_in_attributes(self):
        sensor = self._make(self._measurement(pulse_rate=65.0))
        assert sensor.extra_state_attributes["pulse_rate"] == pytest.approx(65.0)

    def test_timestamp_as_isoformat(self):
        ts = datetime(2025, 6, 1, 8, 30, 0)
        sensor = self._make(self._measurement(timestamp=ts))
        assert sensor.extra_state_attributes["timestamp"] == ts.isoformat()

    def test_none_values_omitted_from_attributes(self):
        m = self._measurement(pulse_rate=None, user_id=None, timestamp=None)
        sensor = self._make(m)
        attrs = sensor.extra_state_attributes
        assert "pulse_rate" not in attrs
        assert "user_id" not in attrs
        assert "timestamp" not in attrs

    def test_status_fields_in_attributes(self):
        from custom_components.sig_health_ble.devices.bpm.parser import (
            BloodPressureMeasurement,
        )
        m = self._measurement(
            status_raw=0x0001,
            body_movement_detected=True,
            cuff_too_loose=False,
            irregular_pulse=False,
            pulse_rate_out_of_range=False,
            measurement_position_error=False,
        )
        sensor = self._make(m)
        attrs = sensor.extra_state_attributes
        assert attrs["body_movement_detected"] is True
        assert attrs["measurement_valid"] is False
        assert "status_summary" in attrs

    def test_empty_raw_handled(self):
        m = self._measurement(raw=b"")
        sensor = self._make(m)
        # Should not raise
        _ = sensor.extra_state_attributes

    def test_unit_mmhg_default(self):
        from custom_components.sig_health_ble.devices.bpm.sensor import (
            BPMMeasurementSensor,
        )
        sensor = self._make(None)
        assert sensor.native_unit_of_measurement == "mmHg"

    def test_unit_kpa_when_measurement_says_kpa(self):
        from homeassistant.const import UnitOfPressure
        m = self._measurement(unit="kPa")
        sensor = self._make(m)
        assert sensor.native_unit_of_measurement == UnitOfPressure.KPA


# ── GlucoseMeasurementSensor ──────────────────────────────────────────────────

class TestGlucoseMeasurementSensor:
    def _make(self, m=None):
        from custom_components.sig_health_ble.devices.glucose.sensor import (
            GlucoseMeasurementSensor,
        )
        sensor = GlucoseMeasurementSensor.__new__(GlucoseMeasurementSensor)
        sensor.coordinator = _make_coordinator(m)
        sensor._attr_native_value = None
        sensor._attr_unique_id = "test_glucose_measurement"
        sensor._attr_device_info = {}
        return sensor

    def _measurement(self, **kwargs):
        from custom_components.sig_health_ble.devices.glucose.parser import (
            GlucoseMeasurement,
        )
        defaults = dict(
            sequence_number=1,
            base_time=datetime(2025, 1, 1, 8, 0, 0),
            glucose_mmol_l=5.5,
            glucose_mg_dl=99.1,
            concentration_unit_raw="mol/L",
            sample_type="Capillary Whole Blood",
            sample_location="Finger",
            raw=b"\x02" * 10,
        )
        defaults.update(kwargs)
        return GlucoseMeasurement(**defaults)

    def test_state_is_mmol_l(self):
        sensor = self._make(self._measurement(glucose_mmol_l=7.2))
        assert sensor.native_value == pytest.approx(7.2)

    def test_state_none_when_no_data(self):
        assert self._make(None).native_value is None

    def test_mg_dl_in_attributes(self):
        sensor = self._make(self._measurement(glucose_mg_dl=129.6))
        assert sensor.extra_state_attributes["glucose_mg_dl"] == pytest.approx(129.6)

    def test_sample_fields_in_attributes(self):
        sensor = self._make(self._measurement())
        attrs = sensor.extra_state_attributes
        assert attrs["sample_type"] == "Capillary Whole Blood"
        assert attrs["sample_location"] == "Finger"

    def test_context_fields_included_when_present(self):
        from custom_components.sig_health_ble.devices.glucose.parser import (
            GlucoseMeasurementContext,
        )
        ctx = GlucoseMeasurementContext(
            sequence_number=1,
            meal="Preprandial",
            tester="Self",
            health="No Health Issues",
            hba1c_pct=6.5,
        )
        m = self._measurement()
        m.context = ctx
        sensor = self._make(m)
        attrs = sensor.extra_state_attributes
        assert attrs["meal"] == "Preprandial"
        assert attrs["hba1c_pct"] == pytest.approx(6.5)
        assert attrs["tester"] == "Self"

    def test_context_fields_absent_when_no_context(self):
        sensor = self._make(self._measurement())
        attrs = sensor.extra_state_attributes
        assert "meal" not in attrs
        assert "hba1c_pct" not in attrs

    def test_none_status_fields_omitted(self):
        sensor = self._make(self._measurement())
        attrs = sensor.extra_state_attributes
        # No status flag set → all None → should be absent
        assert "device_battery_low" not in attrs
        assert "sensor_result_too_high" not in attrs

    def test_status_field_included_when_set(self):
        m = self._measurement(
            status_raw=0x0020,
            sensor_result_too_high=True,
            device_battery_low=False,
        )
        sensor = self._make(m)
        attrs = sensor.extra_state_attributes
        assert attrs["sensor_result_too_high"] is True
        # False is not None, should still be included
        assert attrs["device_battery_low"] is False

    def test_timestamp_isoformat(self):
        ts = datetime(2025, 3, 15, 7, 30, 0)
        m = self._measurement(base_time=ts)
        sensor = self._make(m)
        assert sensor.extra_state_attributes["timestamp"] == ts.isoformat()


# ── ScaleMeasurementSensor ────────────────────────────────────────────────────

class TestScaleMeasurementSensor:
    def _make(self, m=None):
        from custom_components.sig_health_ble.devices.scale.sensor import (
            ScaleMeasurementSensor,
        )
        sensor = ScaleMeasurementSensor.__new__(ScaleMeasurementSensor)
        sensor.coordinator = _make_coordinator(m)
        sensor._attr_native_value = None
        sensor._attr_unique_id = "test_scale_measurement"
        sensor._attr_device_info = {}
        return sensor

    def _weight_only(self, kg=80.0):
        from custom_components.sig_health_ble.devices.scale.parser import (
            WeightMeasurement, ScaleMeasurement,
        )
        w = WeightMeasurement(
            weight_kg=kg,
            weight_lb=round(kg / 0.45359237, 2),
            unit="kg",
            raw=b"\x00" * 3,
        )
        return ScaleMeasurement(weight=w)

    def _full_measurement(self):
        from custom_components.sig_health_ble.devices.scale.parser import (
            WeightMeasurement, BodyCompositionMeasurement, ScaleMeasurement,
        )
        ts = datetime(2025, 6, 1, 7, 0, 0)
        w = WeightMeasurement(
            weight_kg=82.0, weight_lb=180.8, unit="kg",
            bmi=25.3, height_m=1.80, height_in=70.9,
            timestamp=ts, user_id=1, raw=b"\x08" * 10,
        )
        bcm = BodyCompositionMeasurement(
            body_fat_percent=18.5,
            muscle_percent=46.0,
            muscle_mass_kg=38.0,
            fat_free_mass_kg=66.9,
            soft_lean_mass_kg=63.1,
            body_water_mass_kg=42.0,
            impedance_ohm=450.0,
            basal_metabolism_kj=7500.0,
            weight_kg=82.0,
            height_m=1.80,
            bmi=25.3,
            timestamp=ts,
            raw=b"\x09" * 10,
        )
        return ScaleMeasurement(weight=w, body_composition=bcm)

    def test_state_is_weight_kg(self):
        sensor = self._make(self._weight_only(75.0))
        assert sensor.native_value == pytest.approx(75.0, abs=0.01)

    def test_state_none_when_no_data(self):
        assert self._make(None).native_value is None

    def test_weight_lb_in_attributes(self):
        sensor = self._make(self._weight_only(80.0))
        assert sensor.extra_state_attributes["weight_lb"] == pytest.approx(
            80.0 / 0.45359237, abs=0.1
        )

    def test_body_composition_fields_in_attributes(self):
        sensor = self._make(self._full_measurement())
        attrs = sensor.extra_state_attributes
        assert attrs["body_fat_percent"] == pytest.approx(18.5)
        assert attrs["muscle_percent"] == pytest.approx(46.0)
        assert attrs["muscle_mass_kg"] == pytest.approx(38.0)
        assert attrs["fat_free_mass_kg"] == pytest.approx(66.9)
        assert attrs["soft_lean_mass_kg"] == pytest.approx(63.1)
        assert attrs["body_water_mass_kg"] == pytest.approx(42.0)
        assert attrs["impedance_ohm"] == pytest.approx(450.0)
        assert attrs["basal_metabolism_kj"] == pytest.approx(7500.0)

    def test_bmi_in_attributes(self):
        sensor = self._make(self._full_measurement())
        assert sensor.extra_state_attributes["bmi"] == pytest.approx(25.3)

    def test_height_cm_in_attributes(self):
        sensor = self._make(self._full_measurement())
        assert sensor.extra_state_attributes["height_cm"] == pytest.approx(180.0, abs=0.2)

    def test_timestamp_isoformat(self):
        sensor = self._make(self._full_measurement())
        assert "timestamp" in sensor.extra_state_attributes

    def test_weight_source_label_weight_service(self):
        sensor = self._make(self._full_measurement())
        assert sensor.extra_state_attributes["weight_source"] == "weight_scale_service"

    def test_weight_source_label_bcm_fallback(self):
        from custom_components.sig_health_ble.devices.scale.parser import (
            BodyCompositionMeasurement, ScaleMeasurement,
        )
        bcm = BodyCompositionMeasurement(
            body_fat_percent=20.0, weight_kg=70.0, raw=b"\x00" * 4
        )
        m = ScaleMeasurement(body_composition=bcm)
        sensor = self._make(m)
        assert sensor.extra_state_attributes.get("weight_source") == "body_composition_service"

    def test_none_body_composition_fields_omitted(self):
        sensor = self._make(self._weight_only())
        attrs = sensor.extra_state_attributes
        assert "body_fat_percent" not in attrs
        assert "muscle_mass_kg" not in attrs

    def test_no_data_returns_empty_attributes(self):
        assert self._make(None).extra_state_attributes == {}


# ── MeasurementSensor base restore ────────────────────────────────────────────

class TestMeasurementSensorRestore:
    @pytest.mark.asyncio
    async def test_restores_last_numeric_state(self):
        """If no measurement yet, restored state is returned as native_value."""
        from custom_components.sig_health_ble.devices.bpm.sensor import (
            BPMMeasurementSensor,
        )
        sensor = BPMMeasurementSensor.__new__(BPMMeasurementSensor)
        sensor.coordinator = _make_coordinator(None)
        sensor._attr_native_value = None
        sensor._attr_unique_id = "test"
        sensor._attr_device_info = {}

        # Simulate what async_get_last_state returns
        last_state = MagicMock()
        last_state.state = "118.0"

        async def _get_last_state():
            return last_state

        sensor.async_get_last_state = _get_last_state

        # Also need super() to work — patch RestoreEntity
        from unittest.mock import AsyncMock, patch
        with patch(
            "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
            new_callable=AsyncMock,
        ):
            await sensor.async_added_to_hass()

        assert sensor._attr_native_value == pytest.approx(118.0)
        # native_value should return restored value when no coordinator data
        assert sensor.native_value == pytest.approx(118.0)

    @pytest.mark.asyncio
    async def test_ignores_unavailable_last_state(self):
        from custom_components.sig_health_ble.devices.bpm.sensor import (
            BPMMeasurementSensor,
        )
        sensor = BPMMeasurementSensor.__new__(BPMMeasurementSensor)
        sensor.coordinator = _make_coordinator(None)
        sensor._attr_native_value = None
        sensor._attr_unique_id = "test"
        sensor._attr_device_info = {}

        last_state = MagicMock()
        last_state.state = "unavailable"
        sensor.async_get_last_state = lambda: last_state

        from unittest.mock import AsyncMock, patch
        with patch(
            "homeassistant.helpers.restore_state.RestoreEntity.async_added_to_hass",
            new_callable=AsyncMock,
        ):
            await sensor.async_added_to_hass()

        assert sensor._attr_native_value is None
