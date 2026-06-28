"""Parser for Weight Measurement (0x2A9D) and Body Composition Measurement (0x2A9C)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

from .const import (
    WM_FLAG_IMPERIAL, WM_FLAG_TIMESTAMP, WM_FLAG_USER_ID, WM_FLAG_BMI_HEIGHT,
    WM_WEIGHT_SI_RES, WM_WEIGHT_IMP_RES, WM_BMI_RES, WM_HEIGHT_SI_RES, WM_HEIGHT_IMP_RES,
    BCM_FLAG_IMPERIAL, BCM_FLAG_TIMESTAMP, BCM_FLAG_USER_ID,
    BCM_FLAG_BASAL_METABOLISM, BCM_FLAG_MUSCLE_PERCENTAGE, BCM_FLAG_MUSCLE_MASS,
    BCM_FLAG_FAT_FREE_MASS, BCM_FLAG_SOFT_LEAN_MASS, BCM_FLAG_BODY_WATER_MASS,
    BCM_FLAG_IMPEDANCE, BCM_FLAG_WEIGHT, BCM_FLAG_HEIGHT,
    UNIT_KG, UNIT_LB,
)

_LOGGER = logging.getLogger(__name__)

_SFLOAT_SPECIALS = {0x07FF, 0x0800, 0x07FE, 0x0802}


def _sfloat(raw: int) -> Optional[float]:
    raw &= 0xFFFF
    if raw in _SFLOAT_SPECIALS:
        return None
    exp = raw >> 12
    if exp >= 8: exp -= 16
    mant = raw & 0x0FFF
    if mant >= 0x0800: mant -= 0x1000
    return round(mant * (10 ** exp), 6)


def _parse_timestamp(data: bytes, offset: int) -> tuple[Optional[datetime], int]:
    if len(data) < offset + 7:
        return None, offset
    year, month, day, hour, minute, second = struct.unpack_from("<HBBBBB", data, offset)
    try:
        return datetime(year, month, day, hour, minute, second).astimezone(), offset + 7
    except ValueError:
        _LOGGER.warning("Invalid timestamp at offset %d", offset)
        return None, offset + 7


@dataclass
class WeightMeasurement:
    weight_kg: Optional[float] = None
    weight_lb: Optional[float] = None
    unit: str = UNIT_KG
    timestamp: Optional[datetime] = None
    user_id: Optional[int] = None
    bmi: Optional[float] = None
    height_m: Optional[float] = None
    height_in: Optional[float] = None
    raw: bytes = field(default_factory=bytes, repr=False)

    @property
    def is_valid(self) -> bool:
        return self.weight_kg is not None or self.weight_lb is not None


def parse_weight_measurement(data: bytes) -> WeightMeasurement:
    if len(data) < 3:
        raise ValueError(f"Weight Measurement too short: {len(data)} bytes")
    result = WeightMeasurement(raw=data)
    (flags,) = struct.unpack_from("<B", data, 0)
    (weight_raw,) = struct.unpack_from("<H", data, 1)
    offset = 3
    if flags & WM_FLAG_IMPERIAL:
        result.unit = UNIT_LB
        result.weight_lb = round(weight_raw / WM_WEIGHT_IMP_RES, 2)
        result.weight_kg = round(result.weight_lb * 0.45359237, 3)
    else:
        result.unit = UNIT_KG
        result.weight_kg = round(weight_raw / WM_WEIGHT_SI_RES, 3)
        result.weight_lb = round(result.weight_kg / 0.45359237, 2)
    if flags & WM_FLAG_TIMESTAMP:
        result.timestamp, offset = _parse_timestamp(data, offset)
    if flags & WM_FLAG_USER_ID and len(data) > offset:
        result.user_id = data[offset]; offset += 1
    if flags & WM_FLAG_BMI_HEIGHT and len(data) >= offset + 4:
        (bmi_raw, height_raw) = struct.unpack_from("<HH", data, offset)
        result.bmi = round(bmi_raw / WM_BMI_RES, 1)
        if flags & WM_FLAG_IMPERIAL:
            result.height_in = round(height_raw / WM_HEIGHT_IMP_RES, 1)
            result.height_m  = round(result.height_in * 0.0254, 3)
        else:
            result.height_m  = round(height_raw / WM_HEIGHT_SI_RES, 3)
            result.height_in = round(result.height_m / 0.0254, 1)
    return result


@dataclass
class BodyCompositionMeasurement:
    body_fat_percent: Optional[float] = None
    unit: str = UNIT_KG
    basal_metabolism_kj: Optional[float] = None
    muscle_percent: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    fat_free_mass_kg: Optional[float] = None
    soft_lean_mass_kg: Optional[float] = None
    body_water_mass_kg: Optional[float] = None
    impedance_ohm: Optional[float] = None
    weight_kg: Optional[float] = None
    height_m: Optional[float] = None
    bmi: Optional[float] = None
    timestamp: Optional[datetime] = None
    user_id: Optional[int] = None
    raw: bytes = field(default_factory=bytes, repr=False)

    @property
    def is_valid(self) -> bool:
        return self.body_fat_percent is not None

    def compute_bmi(self) -> None:
        if self.bmi is None and self.weight_kg and self.height_m and self.height_m > 0:
            self.bmi = round(self.weight_kg / (self.height_m ** 2), 1)


def parse_body_composition_measurement(data: bytes) -> BodyCompositionMeasurement:
    if len(data) < 4:
        raise ValueError(f"BCM too short: {len(data)} bytes")
    result = BodyCompositionMeasurement(raw=data)
    (flags,) = struct.unpack_from("<H", data, 0)
    (fat_raw,) = struct.unpack_from("<H", data, 2)
    result.body_fat_percent = fat_raw / 10.0
    offset = 4
    result.unit = UNIT_LB if (flags & BCM_FLAG_IMPERIAL) else UNIT_KG
    if flags & BCM_FLAG_TIMESTAMP:
        result.timestamp, offset = _parse_timestamp(data, offset)
    if flags & BCM_FLAG_USER_ID and len(data) > offset:
        result.user_id = data[offset]; offset += 1

    def _mass(raw: int, imp: bool) -> float:
        if imp: return round(raw / WM_WEIGHT_IMP_RES * 0.45359237, 3)
        return round(raw / WM_WEIGHT_SI_RES, 3)

    if flags & BCM_FLAG_BASAL_METABOLISM and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.basal_metabolism_kj = r / 10.0
    if flags & BCM_FLAG_MUSCLE_PERCENTAGE and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.muscle_percent = r / 10.0
    if flags & BCM_FLAG_MUSCLE_MASS and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.muscle_mass_kg = _mass(r, bool(flags & BCM_FLAG_IMPERIAL))
    if flags & BCM_FLAG_FAT_FREE_MASS and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.fat_free_mass_kg = _mass(r, bool(flags & BCM_FLAG_IMPERIAL))
    if flags & BCM_FLAG_SOFT_LEAN_MASS and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.soft_lean_mass_kg = _mass(r, bool(flags & BCM_FLAG_IMPERIAL))
    if flags & BCM_FLAG_BODY_WATER_MASS and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.body_water_mass_kg = _mass(r, bool(flags & BCM_FLAG_IMPERIAL))
    if flags & BCM_FLAG_IMPEDANCE and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.impedance_ohm = r / 10.0
    if flags & BCM_FLAG_WEIGHT and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset); offset += 2
        result.weight_kg = round(r * 0.045359237, 3) if (flags & BCM_FLAG_IMPERIAL) else r / 10.0
    if flags & BCM_FLAG_HEIGHT and len(data) >= offset + 2:
        (r,) = struct.unpack_from("<H", data, offset)
        result.height_m = round(r * 0.0254, 3) if (flags & BCM_FLAG_IMPERIAL) else r / 10.0
    result.compute_bmi()
    return result


@dataclass
class ScaleMeasurement:
    weight: Optional[WeightMeasurement] = None
    body_composition: Optional[BodyCompositionMeasurement] = None

    @property
    def is_valid(self) -> bool:
        return (
            (self.weight is not None and self.weight.is_valid)
            or (self.body_composition is not None and self.body_composition.is_valid)
        )

    @property
    def timestamp(self):
        if self.weight and self.weight.timestamp:
            return self.weight.timestamp
        if self.body_composition and self.body_composition.timestamp:
            return self.body_composition.timestamp
        return None

    @property
    def weight_kg(self) -> Optional[float]:
        if self.weight and self.weight.weight_kg is not None:
            return self.weight.weight_kg
        if self.body_composition and self.body_composition.weight_kg is not None:
            return self.body_composition.weight_kg
        return None

    @property
    def bmi(self) -> Optional[float]:
        if self.weight and self.weight.bmi is not None:
            return self.weight.bmi
        if self.body_composition and self.body_composition.bmi is not None:
            return self.body_composition.bmi
        return None
