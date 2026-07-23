"""Parser for Bluetooth SIG Glucose Measurement (0x2A18) and Context (0x2A34)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import logging

from .const import (
    FLAG_TIME_OFFSET, FLAG_CONCENTRATION_PRESENT, FLAG_CONCENTRATION_MOL,
    FLAG_SENSOR_STATUS,
    CTX_FLAG_CARBOHYDRATE, CTX_FLAG_MEAL, CTX_FLAG_TESTER_HEALTH,
    CTX_FLAG_EXERCISE, CTX_FLAG_MEDICATION, CTX_FLAG_MEDICATION_LITERS,
    CTX_FLAG_HBA1C, CTX_FLAG_EXTENDED,
    SAMPLE_TYPE, SAMPLE_LOCATION, MEAL_LABEL, TESTER_LABEL, HEALTH_LABEL,
    CARBOHYDRATE_LABEL, MEDICATION_LABEL,
    MOL_TO_MMOL, KG_L_TO_MG_DL,
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
    return round(mantissa * (10 ** exponent), 8)


def _parse_base_time(data: bytes, offset: int) -> tuple[Optional[datetime], int]:
    if len(data) < offset + 7:
        return None, offset
    year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
    try:
        return datetime(year, month, day, hour, minute, second).astimezone(), offset + 7
    except ValueError:
        _LOGGER.warning("Invalid Date Time at offset %d", offset)
        return None, offset + 7


@dataclass
class GlucoseMeasurementContext:
    sequence_number: int = 0
    carbohydrate_id: Optional[str] = None
    carbohydrate_kg: Optional[float] = None
    meal: Optional[str] = None
    tester: Optional[str] = None
    health: Optional[str] = None
    exercise_duration_s: Optional[int] = None
    exercise_intensity_pct: Optional[int] = None
    medication_id: Optional[str] = None
    medication_amount: Optional[float] = None
    medication_unit: Optional[str] = None
    hba1c_pct: Optional[float] = None
    raw: bytes = field(default_factory=bytes, repr=False)


@dataclass
class GlucoseMeasurement:
    sequence_number: int = 0
    base_time: Optional[datetime] = None
    time_offset_minutes: Optional[int] = None
    glucose_mmol_l: Optional[float] = None
    glucose_mg_dl: Optional[float] = None
    concentration_unit_raw: Optional[str] = None
    sample_type: Optional[str] = None
    sample_location: Optional[str] = None
    device_battery_low: Optional[bool] = None
    sensor_malfunction: Optional[bool] = None
    sample_size_insufficient: Optional[bool] = None
    strip_insertion_error: Optional[bool] = None
    strip_type_incorrect: Optional[bool] = None
    sensor_result_too_high: Optional[bool] = None
    sensor_result_too_low: Optional[bool] = None
    sensor_temperature_too_high: Optional[bool] = None
    sensor_temperature_too_low: Optional[bool] = None
    sensor_read_interrupted: Optional[bool] = None
    general_device_fault: Optional[bool] = None
    time_fault: Optional[bool] = None
    # Raw status uint16 — None if FLAG_SENSOR_STATUS not set
    status_raw: Optional[int] = None
    context: Optional[GlucoseMeasurementContext] = None
    raw: bytes = field(default_factory=bytes, repr=False)
    # History
    _history: list[GlucoseMeasurement] = None

    @property
    def measurement_valid(self) -> Optional[bool]:
        if self.status_raw is None:
            return None
        return self.status_raw == 0

    @property
    def status_flags_hex(self) -> Optional[str]:
        if self.status_raw is None:
            return None
        return f"0x{self.status_raw:04x}"

    @property
    def status_summary(self) -> Optional[str]:
        if self.status_raw is None:
            return None
        if self.status_raw == 0:
            return "OK"
        _KNOWN = {
            0x0001: "battery_low",
            0x0002: "sensor_malfunction",
            0x0004: "sample_size_insufficient",
            0x0008: "strip_insertion_error",
            0x0010: "strip_type_incorrect",
            0x0020: "result_too_high",
            0x0040: "result_too_low",
            0x0080: "temperature_too_high",
            0x0100: "temperature_too_low",
            0x0200: "read_interrupted",
            0x0400: "general_device_fault",
            0x0800: "time_fault",
        }
        active = [label for mask, label in _KNOWN.items() if self.status_raw & mask]
        unknown = self.status_raw & ~0x0FFF
        if unknown:
            active.append(f"unknown(0x{unknown:04x})")
        return ", ".join(active) if active else "OK"

    @property
    def timestamp(self) -> Optional[datetime]:
        if self.base_time is None:
            return None
        if self.time_offset_minutes is not None:
            return self.base_time + timedelta(minutes=self.time_offset_minutes)
        return self.base_time

    @property
    def is_valid(self) -> bool:
        return self.glucose_mmol_l is not None or self.glucose_mg_dl is not None


def parse_glucose_measurement(data: bytes) -> GlucoseMeasurement:
    if len(data) < 10:
        raise ValueError(f"Glucose Measurement too short: {len(data)} bytes (minimum 10)")

    result = GlucoseMeasurement(raw=data)
    flags = data[0]
    (result.sequence_number,) = struct.unpack_from("<H", data, 1)
    result.base_time, offset = _parse_base_time(data, 3)

    if flags & FLAG_TIME_OFFSET and len(data) >= offset + 2:
        (result.time_offset_minutes,) = struct.unpack_from("<h", data, offset)
        offset += 2

    if flags & FLAG_CONCENTRATION_PRESENT and len(data) >= offset + 3:
        (conc_raw,) = struct.unpack_from("<H", data, offset)
        offset += 2
        type_location_byte = data[offset]
        offset += 1
        conc_float = _sfloat_to_float(conc_raw)
        if flags & FLAG_CONCENTRATION_MOL:
            result.concentration_unit_raw = "mol/L"
            if conc_float is not None:
                result.glucose_mmol_l = round(conc_float * MOL_TO_MMOL, 2)
                result.glucose_mg_dl  = round(result.glucose_mmol_l * 18.016, 1)
        else:
            result.concentration_unit_raw = "kg/L"
            if conc_float is not None:
                result.glucose_mg_dl  = round(conc_float * KG_L_TO_MG_DL, 1)
                result.glucose_mmol_l = round(result.glucose_mg_dl / 18.016, 2)
        type_nibble     = (type_location_byte >> 4) & 0x0F
        location_nibble =  type_location_byte        & 0x0F
        result.sample_type     = SAMPLE_TYPE.get(type_nibble, f"Unknown(0x{type_nibble:X})")
        result.sample_location = SAMPLE_LOCATION.get(location_nibble, f"Unknown(0x{location_nibble:X})")

    if flags & FLAG_SENSOR_STATUS and len(data) >= offset + 2:
        (status,) = struct.unpack_from("<H", data, offset)
        result.status_raw                  = status
        result.device_battery_low          = bool(status & 0x0001)
        result.sensor_malfunction          = bool(status & 0x0002)
        result.sample_size_insufficient    = bool(status & 0x0004)
        result.strip_insertion_error       = bool(status & 0x0008)
        result.strip_type_incorrect        = bool(status & 0x0010)
        result.sensor_result_too_high      = bool(status & 0x0020)
        result.sensor_result_too_low       = bool(status & 0x0040)
        result.sensor_temperature_too_high = bool(status & 0x0080)
        result.sensor_temperature_too_low  = bool(status & 0x0100)
        result.sensor_read_interrupted     = bool(status & 0x0200)
        result.general_device_fault        = bool(status & 0x0400)
        result.time_fault                  = bool(status & 0x0800)

    return result


def parse_glucose_context(data: bytes) -> GlucoseMeasurementContext:
    if len(data) < 3:
        raise ValueError(f"Glucose Context too short: {len(data)} bytes")
    ctx = GlucoseMeasurementContext(raw=data)
    flags = data[0]
    (ctx.sequence_number,) = struct.unpack_from("<H", data, 1)
    offset = 3
    if flags & CTX_FLAG_EXTENDED and len(data) > offset:
        offset += 1
    if flags & CTX_FLAG_CARBOHYDRATE and len(data) > offset + 2:
        carb_id = data[offset]; offset += 1
        ctx.carbohydrate_id = CARBOHYDRATE_LABEL.get(carb_id, f"Unknown(0x{carb_id:X})")
        (carb_raw,) = struct.unpack_from("<H", data, offset); offset += 2
        ctx.carbohydrate_kg = _sfloat_to_float(carb_raw)
    if flags & CTX_FLAG_MEAL and len(data) > offset:
        meal = data[offset]; offset += 1
        ctx.meal = MEAL_LABEL.get(meal, f"Unknown(0x{meal:X})")
    if flags & CTX_FLAG_TESTER_HEALTH and len(data) > offset:
        th = data[offset]; offset += 1
        ctx.tester = TESTER_LABEL.get((th >> 4) & 0x0F, "Unknown")
        ctx.health = HEALTH_LABEL.get(th & 0x0F, "Unknown")
    if flags & CTX_FLAG_EXERCISE and len(data) >= offset + 3:
        (ctx.exercise_duration_s,) = struct.unpack_from("<H", data, offset); offset += 2
        ctx.exercise_intensity_pct = data[offset]; offset += 1
    if flags & CTX_FLAG_MEDICATION and len(data) >= offset + 3:
        med_id = data[offset]; offset += 1
        ctx.medication_id = MEDICATION_LABEL.get(med_id, f"Unknown(0x{med_id:X})")
        (med_raw,) = struct.unpack_from("<H", data, offset); offset += 2
        ctx.medication_amount = _sfloat_to_float(med_raw)
        ctx.medication_unit   = "L" if (flags & CTX_FLAG_MEDICATION_LITERS) else "kg"
    if flags & CTX_FLAG_HBA1C and len(data) >= offset + 2:
        (hba1c_raw,) = struct.unpack_from("<H", data, offset)
        val = _sfloat_to_float(hba1c_raw)
        ctx.hba1c_pct = round(val * 100, 2) if val is not None else None
    return ctx


def parse_racp_response(data: bytes) -> tuple[int, int, int]:
    if len(data) < 4:
        raise ValueError(f"RACP response too short: {len(data)} bytes")
    return data[0], data[2], data[3]
