"""Unit tests for the Bluetooth SIG 0x2A35 Blood Pressure Measurement parser."""
from __future__ import annotations

import struct
from datetime import datetime

import pytest

from custom_components.sig_health_ble.devices.bpm.parser import (
    BloodPressureMeasurement,
    _sfloat_to_float,
    parse_blood_pressure_measurement,
)
from custom_components.sig_health_ble.devices.bpm.const import (
    FLAG_TIMESTAMP,
    FLAG_PULSE_RATE,
    FLAG_USER_ID,
    FLAG_MEASUREMENT_STATUS,
    UNIT_MMHG,
    UNIT_KPA,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sfloat(mantissa: int, exponent: int) -> int:
    return ((exponent & 0x0F) << 12) | (mantissa & 0x0FFF)


def _build_packet(
    systolic: int = 120,
    diastolic: int = 80,
    mean_ap: int = 93,
    exponent: int = 0,
    flags: int = 0,
    pulse_rate: int | None = None,
    timestamp: datetime | None = None,
    user_id: int | None = None,
    status: int | None = None,
) -> bytes:
    data = bytearray([flags])
    for v in (systolic, diastolic, mean_ap):
        data += struct.pack("<H", _sfloat(v, exponent))
    if flags & FLAG_TIMESTAMP and timestamp is not None:
        data += struct.pack(
            "<HBBBBB",
            timestamp.year, timestamp.month, timestamp.day,
            timestamp.hour, timestamp.minute, timestamp.second,
        )
    if flags & FLAG_PULSE_RATE and pulse_rate is not None:
        data += struct.pack("<H", _sfloat(pulse_rate, 0))
    if flags & FLAG_USER_ID and user_id is not None:
        data.append(user_id)
    if flags & FLAG_MEASUREMENT_STATUS and status is not None:
        data += struct.pack("<H", status)
    return bytes(data)


# ── SFLOAT ─────────────────────────────────────────────────────────────────────

class TestSfloat:
    def test_integer_value(self):
        assert _sfloat_to_float(_sfloat(120, 0)) == pytest.approx(120.0)

    def test_decimal_value(self):
        assert _sfloat_to_float(_sfloat(120, -1)) == pytest.approx(12.0)

    def test_nan_returns_none(self):
        assert _sfloat_to_float(0x07FF) is None

    def test_nres_returns_none(self):
        assert _sfloat_to_float(0x0800) is None

    def test_pos_inf_returns_none(self):
        assert _sfloat_to_float(0x07FE) is None

    def test_neg_inf_returns_none(self):
        assert _sfloat_to_float(0x0802) is None

    def test_negative_mantissa(self):
        # Negative mantissa: -5 × 10^0 = -5
        raw = _sfloat(-5 & 0x0FFF, 0)
        assert _sfloat_to_float(raw) == pytest.approx(-5.0)


# ── Basic parsing ──────────────────────────────────────────────────────────────

class TestParseBasic:
    def test_minimal_packet_mmhg(self):
        m = parse_blood_pressure_measurement(_build_packet(120, 80, 93))
        assert m.systolic == pytest.approx(120.0)
        assert m.diastolic == pytest.approx(80.0)
        assert m.mean_arterial_pressure == pytest.approx(93.0)
        assert m.unit == UNIT_MMHG
        assert m.is_valid is True

    def test_minimal_packet_kpa(self):
        m = parse_blood_pressure_measurement(
            _build_packet(160, 107, 124, exponent=-1, flags=0x01)
        )
        assert m.unit == UNIT_KPA
        assert m.systolic == pytest.approx(16.0)

    def test_too_short_raises(self):
        with pytest.raises(ValueError, match="too short"):
            parse_blood_pressure_measurement(b"\x00\x78\x00\x50\x00")

    def test_nan_systolic_not_valid(self):
        pkt = bytearray(_build_packet(120, 80, 93))
        struct.pack_into("<H", pkt, 1, 0x07FF)
        m = parse_blood_pressure_measurement(bytes(pkt))
        assert m.systolic is None
        assert m.is_valid is False

    def test_raw_bytes_stored(self):
        pkt = _build_packet(120, 80, 93)
        m = parse_blood_pressure_measurement(pkt)
        assert m.raw == pkt


# ── Optional fields ────────────────────────────────────────────────────────────

class TestTimestamp:
    def test_timestamp_parsed(self):
        ts = datetime(2024, 11, 5, 8, 30, 0)
        m = parse_blood_pressure_measurement(
            _build_packet(125, 82, 96, flags=FLAG_TIMESTAMP, timestamp=ts)
        )
        assert m.timestamp == ts

    def test_no_timestamp_when_flag_not_set(self):
        m = parse_blood_pressure_measurement(_build_packet(125, 82, 96))
        assert m.timestamp is None


class TestPulseRate:
    def test_pulse_rate_parsed(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_PULSE_RATE, pulse_rate=72)
        )
        assert m.pulse_rate == pytest.approx(72.0)

    def test_no_pulse_when_flag_not_set(self):
        assert parse_blood_pressure_measurement(_build_packet(120, 80, 93)).pulse_rate is None


class TestUserID:
    def test_user_id_parsed(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_USER_ID, user_id=2)
        )
        assert m.user_id == 2


# ── Measurement status ─────────────────────────────────────────────────────────

class TestMeasurementStatus:
    def test_body_movement_flag(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0001)
        )
        assert m.body_movement_detected is True
        assert m.cuff_too_loose is False
        assert m.status_raw == 0x0001

    def test_irregular_pulse_flag(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0004)
        )
        assert m.irregular_pulse is True

    def test_cuff_too_loose_flag(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0002)
        )
        assert m.cuff_too_loose is True

    def test_position_error_flag(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0020)
        )
        assert m.measurement_position_error is True

    def test_no_status_when_flag_not_set(self):
        m = parse_blood_pressure_measurement(_build_packet(120, 80, 93))
        assert m.status_raw is None
        assert m.body_movement_detected is None


# ── Derived properties: measurement_valid, status_flags_hex, status_summary ────

class TestStatusDerivedProperties:
    def test_measurement_valid_true_when_all_zero(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0000)
        )
        assert m.measurement_valid is True
        assert m.status_summary == "OK"
        assert m.status_flags_hex == "0x0000"

    def test_measurement_valid_false_when_bits_set(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0003)
        )
        assert m.measurement_valid is False

    def test_measurement_valid_none_when_no_status_field(self):
        m = parse_blood_pressure_measurement(_build_packet(120, 80, 93))
        assert m.measurement_valid is None
        assert m.status_flags_hex is None
        assert m.status_summary is None

    def test_status_summary_lists_known_flags(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0003)
        )
        assert "body_movement" in m.status_summary
        assert "cuff_too_loose" in m.status_summary

    def test_status_summary_reports_unknown_bits(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0100)
        )
        assert "unknown" in m.status_summary

    def test_status_flags_hex_format(self):
        m = parse_blood_pressure_measurement(
            _build_packet(120, 80, 93, flags=FLAG_MEASUREMENT_STATUS, status=0x0006)
        )
        assert m.status_flags_hex == "0x0006"


# ── Full packet ────────────────────────────────────────────────────────────────

class TestFullPacket:
    def test_full_packet(self):
        ts = datetime(2025, 3, 14, 9, 15, 30)
        flags = FLAG_TIMESTAMP | FLAG_PULSE_RATE | FLAG_USER_ID | FLAG_MEASUREMENT_STATUS
        m = parse_blood_pressure_measurement(
            _build_packet(
                systolic=122, diastolic=78, mean_ap=92,
                flags=flags,
                pulse_rate=65,
                timestamp=ts,
                user_id=1,
                status=0x0000,
            )
        )
        assert m.is_valid is True
        assert m.systolic == pytest.approx(122.0)
        assert m.diastolic == pytest.approx(78.0)
        assert m.mean_arterial_pressure == pytest.approx(92.0)
        assert m.pulse_rate == pytest.approx(65.0)
        assert m.timestamp == ts
        assert m.user_id == 1
        assert m.measurement_valid is True
        assert m.status_summary == "OK"
