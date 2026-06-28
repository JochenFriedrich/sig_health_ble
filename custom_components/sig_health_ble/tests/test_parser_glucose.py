"""Unit tests for Glucose Measurement (0x2A18) and Context (0x2A34) parsers."""
from __future__ import annotations

import struct
from datetime import datetime, timedelta

import pytest

from custom_components.sig_health_ble.devices.glucose.parser import (
    GlucoseMeasurement,
    GlucoseMeasurementContext,
    _sfloat_to_float,
    parse_glucose_measurement,
    parse_glucose_context,
    parse_racp_response,
)
from custom_components.sig_health_ble.devices.glucose.const import (
    FLAG_TIME_OFFSET, FLAG_CONCENTRATION_PRESENT, FLAG_CONCENTRATION_MOL,
    FLAG_SENSOR_STATUS,
    CTX_FLAG_MEAL, CTX_FLAG_TESTER_HEALTH, CTX_FLAG_HBA1C,
    CTX_FLAG_EXERCISE, CTX_FLAG_MEDICATION, CTX_FLAG_MEDICATION_LITERS,
    RACP_OP_RESPONSE, RACP_RESPONSE_SUCCESS, RACP_RESPONSE_NO_RECORDS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sfloat(mantissa: int, exponent: int) -> int:
    return ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)


def _encode_base_time(dt: datetime) -> bytes:
    return struct.pack(
        "<HBBBBB", dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    )


def _build_glucose_packet(
    seq: int = 1,
    base_time: datetime | None = None,
    time_offset: int | None = None,
    concentration: float | None = None,  # mmol/L if use_mol, mg/dL otherwise
    use_mol: bool = True,
    sample_type: int = 0x1,
    sample_location: int = 0x1,
    sensor_status: int | None = None,
) -> bytes:
    if base_time is None:
        base_time = datetime(2025, 6, 1, 8, 0, 0)
    flags = 0
    if time_offset is not None:
        flags |= FLAG_TIME_OFFSET
    if concentration is not None:
        flags |= FLAG_CONCENTRATION_PRESENT
        if use_mol:
            flags |= FLAG_CONCENTRATION_MOL
    if sensor_status is not None:
        flags |= FLAG_SENSOR_STATUS

    data = bytearray([flags])
    data += struct.pack("<H", seq)
    data += _encode_base_time(base_time)
    if time_offset is not None:
        data += struct.pack("<h", time_offset)
    if concentration is not None:
        if use_mol:
            raw_val = concentration / 1000.0
            mantissa = round(raw_val / 1e-5)
        else:
            raw_val = concentration / 100000.0
            mantissa = round(raw_val / 1e-5)
        data += struct.pack("<H", _sfloat(mantissa, -5))
        data.append(((sample_type & 0xF) << 4) | (sample_location & 0xF))
    if sensor_status is not None:
        data += struct.pack("<H", sensor_status)
    return bytes(data)


def _build_context_packet(
    seq: int = 1,
    meal: int | None = None,
    tester: int = 0x1,
    health: int = 0x5,
    hba1c_pct: float | None = None,
    exercise_duration_s: int | None = None,
    exercise_intensity_pct: int | None = None,
    medication_id: int | None = None,
    medication_amount: float | None = None,
    medication_liters: bool = False,
) -> bytes:
    flags = 0
    if meal is not None:           flags |= CTX_FLAG_MEAL
    if tester or health:           flags |= CTX_FLAG_TESTER_HEALTH
    if hba1c_pct is not None:     flags |= CTX_FLAG_HBA1C
    if exercise_duration_s is not None: flags |= CTX_FLAG_EXERCISE
    if medication_id is not None:  flags |= CTX_FLAG_MEDICATION
    if medication_liters:          flags |= CTX_FLAG_MEDICATION_LITERS

    data = bytearray([flags])
    data += struct.pack("<H", seq)
    if meal is not None:
        data.append(meal)
    if flags & CTX_FLAG_TESTER_HEALTH:
        data.append(((tester & 0xF) << 4) | (health & 0xF))
    if exercise_duration_s is not None:
        data += struct.pack("<HB", exercise_duration_s, exercise_intensity_pct or 0)
    if medication_id is not None:
        data.append(medication_id)
        mantissa = round((medication_amount or 0) / 1e-3)
        data += struct.pack("<H", _sfloat(mantissa, -3))
    if hba1c_pct is not None:
        frac = hba1c_pct / 100.0
        mantissa = round(frac / 1e-3)
        data += struct.pack("<H", _sfloat(mantissa, -3))
    return bytes(data)


# ── SFLOAT ─────────────────────────────────────────────────────────────────────

class TestSfloat:
    def test_nan_returns_none(self):
        assert _sfloat_to_float(0x07FF) is None

    def test_small_positive(self):
        # 5.5e-3 mol/L = 5500 mmol/L ... check the machinery works
        raw = _sfloat(55, -4)   # 55 × 10^-4 = 0.0055
        assert _sfloat_to_float(raw) == pytest.approx(0.0055, rel=0.01)


# ── Basic glucose parsing ──────────────────────────────────────────────────────

class TestBasicGlucoseParsing:
    def test_mol_l_conversion(self):
        m = parse_glucose_measurement(_build_glucose_packet(concentration=5.5, use_mol=True))
        assert m.is_valid
        assert m.glucose_mmol_l == pytest.approx(5.5, abs=0.05)
        assert m.glucose_mg_dl  == pytest.approx(5.5 * 18.016, abs=1.0)
        assert m.concentration_unit_raw == "mol/L"

    def test_kg_l_conversion(self):
        m = parse_glucose_measurement(_build_glucose_packet(concentration=100, use_mol=False))
        assert m.is_valid
        assert m.glucose_mg_dl  == pytest.approx(100.0, abs=1.0)
        assert m.glucose_mmol_l == pytest.approx(100 / 18.016, abs=0.1)
        assert m.concentration_unit_raw == "kg/L"

    def test_sequence_number(self):
        m = parse_glucose_measurement(_build_glucose_packet(seq=42))
        assert m.sequence_number == 42

    def test_base_time_parsed(self):
        ts = datetime(2025, 3, 15, 7, 30, 0)
        m = parse_glucose_measurement(_build_glucose_packet(base_time=ts))
        assert m.base_time == ts

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            parse_glucose_measurement(b"\x00\x01\x00")

    def test_no_concentration_not_valid(self):
        m = parse_glucose_measurement(_build_glucose_packet(concentration=None))
        assert not m.is_valid
        assert m.glucose_mmol_l is None

    def test_sample_type_and_location(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=6.0, sample_type=0x1, sample_location=0x1)
        )
        assert m.sample_type == "Capillary Whole Blood"
        assert m.sample_location == "Finger"

    def test_raw_stored(self):
        pkt = _build_glucose_packet(concentration=5.5)
        assert parse_glucose_measurement(pkt).raw == pkt


# ── Time offset ────────────────────────────────────────────────────────────────

class TestTimeOffset:
    def test_positive_offset(self):
        base = datetime(2025, 1, 1, 12, 0, 0)
        m = parse_glucose_measurement(_build_glucose_packet(base_time=base, time_offset=30))
        assert m.time_offset_minutes == 30
        assert m.timestamp == base + timedelta(minutes=30)

    def test_negative_offset(self):
        base = datetime(2025, 1, 1, 12, 0, 0)
        m = parse_glucose_measurement(_build_glucose_packet(base_time=base, time_offset=-15))
        assert m.time_offset_minutes == -15
        assert m.timestamp == base + timedelta(minutes=-15)

    def test_no_offset_timestamp_equals_base(self):
        base = datetime(2025, 6, 1, 8, 0, 0)
        m = parse_glucose_measurement(_build_glucose_packet(base_time=base))
        assert m.timestamp == base


# ── Sensor status ──────────────────────────────────────────────────────────────

class TestSensorStatus:
    def test_result_too_high_flag(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0020)
        )
        assert m.sensor_result_too_high is True
        assert m.sensor_result_too_low is False
        assert m.status_raw == 0x0020

    def test_battery_low_flag(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0001)
        )
        assert m.device_battery_low is True

    def test_general_fault_flag(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0400)
        )
        assert m.general_device_fault is True

    def test_no_status_when_flag_not_set(self):
        m = parse_glucose_measurement(_build_glucose_packet(concentration=5.5))
        assert m.device_battery_low is None
        assert m.status_raw is None


# ── Status derived properties ──────────────────────────────────────────────────

class TestStatusDerivedProperties:
    def test_measurement_valid_true_when_all_zero(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0000)
        )
        assert m.measurement_valid is True
        assert m.status_summary == "OK"
        assert m.status_flags_hex == "0x0000"

    def test_measurement_valid_false_when_bits_set(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0001)
        )
        assert m.measurement_valid is False

    def test_measurement_valid_none_without_status_field(self):
        m = parse_glucose_measurement(_build_glucose_packet(concentration=5.5))
        assert m.measurement_valid is None
        assert m.status_summary is None

    def test_status_summary_lists_known_flags(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x0021)
        )
        assert "battery_low" in m.status_summary
        assert "result_too_high" in m.status_summary

    def test_status_summary_reports_unknown_bits(self):
        m = parse_glucose_measurement(
            _build_glucose_packet(concentration=5.5, sensor_status=0x1000)
        )
        assert "unknown" in m.status_summary


# ── Context parsing ────────────────────────────────────────────────────────────

class TestContextParsing:
    def test_meal_parsed(self):
        ctx = parse_glucose_context(_build_context_packet(seq=5, meal=0x01))
        assert ctx.sequence_number == 5
        assert ctx.meal == "Preprandial"

    def test_tester_health_parsed(self):
        ctx = parse_glucose_context(_build_context_packet(tester=0x01, health=0x05))
        assert ctx.tester == "Self"
        assert ctx.health == "No Health Issues"

    def test_hba1c_parsed(self):
        ctx = parse_glucose_context(_build_context_packet(hba1c_pct=6.5))
        assert ctx.hba1c_pct == pytest.approx(6.5, abs=0.1)

    def test_exercise_fields(self):
        ctx = parse_glucose_context(
            _build_context_packet(exercise_duration_s=1800, exercise_intensity_pct=70)
        )
        assert ctx.exercise_duration_s == 1800
        assert ctx.exercise_intensity_pct == 70

    def test_medication_kg(self):
        ctx = parse_glucose_context(
            _build_context_packet(medication_id=0x01, medication_amount=0.005)
        )
        assert ctx.medication_id == "Rapid Acting Insulin"
        assert ctx.medication_amount == pytest.approx(0.005, abs=0.001)
        assert ctx.medication_unit == "kg"

    def test_medication_liters(self):
        ctx = parse_glucose_context(
            _build_context_packet(medication_id=0x01, medication_amount=0.01, medication_liters=True)
        )
        assert ctx.medication_unit == "L"

    def test_context_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            parse_glucose_context(b"\x00\x01")


# ── RACP response ──────────────────────────────────────────────────────────────

class TestRACPResponse:
    def test_success_response(self):
        data = bytes([RACP_OP_RESPONSE, 0x00, 0x01, RACP_RESPONSE_SUCCESS])
        op, req, code = parse_racp_response(data)
        assert op == RACP_OP_RESPONSE
        assert code == RACP_RESPONSE_SUCCESS

    def test_no_records_response(self):
        _, _, code = parse_racp_response(
            bytes([RACP_OP_RESPONSE, 0x00, 0x01, RACP_RESPONSE_NO_RECORDS])
        )
        assert code == RACP_RESPONSE_NO_RECORDS

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            parse_racp_response(b"\x06\x00")


# ── Context linking ────────────────────────────────────────────────────────────

class TestContextLinking:
    """Simulate the coordinator's context-linking logic (no HA needed)."""

    def test_context_linked_by_sequence_number(self):
        m = parse_glucose_measurement(_build_glucose_packet(seq=7, concentration=7.2))
        ctx = parse_glucose_context(_build_context_packet(seq=7, meal=0x02))

        measurements = {m.sequence_number: m}
        contexts = {ctx.sequence_number: ctx}
        for seq, c in contexts.items():
            if seq in measurements:
                measurements[seq].context = c

        assert measurements[7].context is not None
        assert measurements[7].context.meal == "Postprandial"

    def test_unmatched_context_not_linked(self):
        m = parse_glucose_measurement(_build_glucose_packet(seq=1, concentration=5.0))
        ctx = parse_glucose_context(_build_context_packet(seq=99, meal=0x01))

        measurements = {m.sequence_number: m}
        contexts = {ctx.sequence_number: ctx}
        for seq, c in contexts.items():
            if seq in measurements:
                measurements[seq].context = c

        assert measurements[1].context is None

    def test_latest_record_selected_by_timestamp(self):
        """Coordinator picks the measurement with the most recent timestamp."""
        t1 = datetime(2025, 1, 1, 8, 0, 0)
        t2 = datetime(2025, 1, 2, 8, 0, 0)
        m1 = parse_glucose_measurement(_build_glucose_packet(seq=1, base_time=t1, concentration=5.0))
        m2 = parse_glucose_measurement(_build_glucose_packet(seq=2, base_time=t2, concentration=7.0))

        measurements = [m1, m2]
        with_ts = [m for m in measurements if m.timestamp is not None]
        latest = max(with_ts, key=lambda m: m.timestamp)
        assert latest.sequence_number == 2
        assert latest.glucose_mmol_l == pytest.approx(7.0, abs=0.1)
