"""Parser for the Bluetooth SIG Blood Pressure Measurement characteristic (0x2A35)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

from .const import (
    FLAG_UNIT_KPA, FLAG_TIMESTAMP, FLAG_PULSE_RATE,
    FLAG_USER_ID, FLAG_MEASUREMENT_STATUS,
    UNIT_MMHG, UNIT_KPA,
)

_LOGGER = logging.getLogger(__name__)

_SFLOAT_NAN     = 0x07FF
_SFLOAT_NRES    = 0x0800
_SFLOAT_POS_INF = 0x07FE
_SFLOAT_NEG_INF = 0x0802


def _sfloat_to_float(raw: int) -> Optional[float]:
    raw &= 0xFFFF
    if raw in (_SFLOAT_NAN, _SFLOAT_NRES, _SFLOAT_POS_INF, _SFLOAT_NEG_INF):
        return None
    exponent = raw >> 12
    if exponent >= 8:
        exponent -= 16
    mantissa = raw & 0x0FFF
    if mantissa >= 0x0800:
        mantissa -= 0x1000
    return round(mantissa * (10 ** exponent), 4)


@dataclass
class BloodPressureMeasurement:
    systolic: Optional[float] = None
    diastolic: Optional[float] = None
    mean_arterial_pressure: Optional[float] = None
    unit: str = UNIT_MMHG
    pulse_rate: Optional[float] = None
    timestamp: Optional[datetime] = None
    user_id: Optional[int] = None
    body_movement_detected: Optional[bool] = None
    cuff_too_loose: Optional[bool] = None
    irregular_pulse: Optional[bool] = None
    pulse_rate_out_of_range: Optional[bool] = None
    measurement_position_error: Optional[bool] = None
    # Raw status uint16 — None if FLAG_MEASUREMENT_STATUS was not set
    status_raw: Optional[int] = None
    raw: bytes = field(default_factory=bytes, repr=False)
    # History
    _history: list[BloodPressureMeasurement] = None

    @property
    def is_valid(self) -> bool:
        return self.systolic is not None and self.diastolic is not None

    @property
    def measurement_valid(self) -> Optional[bool]:
        """True when status field is present and all bits are 0 (clean reading)."""
        if self.status_raw is None:
            return None
        return self.status_raw == 0

    @property
    def status_flags_hex(self) -> Optional[str]:
        """Raw status as hex string, e.g. '0x0006'. None if not present."""
        if self.status_raw is None:
            return None
        return f"0x{self.status_raw:04x}"

    @property
    def status_summary(self) -> Optional[str]:
        """Human-readable list of active status flags, or 'OK'."""
        if self.status_raw is None:
            return None
        if self.status_raw == 0:
            return "OK"
        _KNOWN = {
            0x0001: "body_movement",
            0x0002: "cuff_too_loose",
            0x0004: "irregular_pulse",
            0x0018: "pulse_rate_out_of_range",
            0x0020: "measurement_position_error",
        }
        active = [label for mask, label in _KNOWN.items() if self.status_raw & mask]
        unknown = self.status_raw & ~0x003F
        if unknown:
            active.append(f"unknown(0x{unknown:04x})")
        return ", ".join(active) if active else "OK"


def parse_blood_pressure_measurement(data: bytes) -> BloodPressureMeasurement:
    if len(data) < 7:
        raise ValueError(f"BP Measurement too short: {len(data)} bytes (need ≥7)")

    result = BloodPressureMeasurement(raw=data)
    flags = data[0]
    result.unit = UNIT_KPA if (flags & FLAG_UNIT_KPA) else UNIT_MMHG

    sys_raw, dia_raw, map_raw = struct.unpack_from("<HHH", data, 1)
    result.systolic               = _sfloat_to_float(sys_raw)
    result.diastolic              = _sfloat_to_float(dia_raw)
    result.mean_arterial_pressure = _sfloat_to_float(map_raw)
    offset = 7

    if flags & FLAG_TIMESTAMP:
        if len(data) >= offset + 7:
            year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
            try:
                result.timestamp = datetime(year, month, day, hour, minute, second).astimezone()
            except ValueError:
                _LOGGER.warning("Invalid timestamp in BP measurement")
            offset += 7

    if flags & FLAG_PULSE_RATE:
        if len(data) >= offset + 2:
            (pr_raw,) = struct.unpack_from("<H", data, offset)
            result.pulse_rate = _sfloat_to_float(pr_raw)
            offset += 2

    if flags & FLAG_USER_ID and len(data) > offset:
        result.user_id = data[offset]
        offset += 1

    if flags & FLAG_MEASUREMENT_STATUS and len(data) >= offset + 2:
        (status,) = struct.unpack_from("<H", data, offset)
        result.status_raw                 = status
        result.body_movement_detected     = bool(status & 0x0001)
        result.cuff_too_loose             = bool(status & 0x0002)
        result.irregular_pulse            = bool(status & 0x0004)
        result.pulse_rate_out_of_range    = bool(status & 0x0018)
        result.measurement_position_error = bool(status & 0x0020)

    return result
