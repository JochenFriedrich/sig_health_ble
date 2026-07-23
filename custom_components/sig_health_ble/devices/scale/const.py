"""Constants and model registry for Weight Scale devices."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Any

# ── Bluetooth SIG service UUIDs ───────────────────────────────────────────────
WEIGHT_SCALE_SERVICE_UUID         = "0000181d-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION_SERVICE_UUID     = "0000181b-0000-1000-8000-00805f9b34fb"
USER_DATA_SERVICE_UUID            = "0000181c-0000-1000-8000-00805f9b34fb"

# ── Characteristic UUIDs ──────────────────────────────────────────────────────
WEIGHT_MEASUREMENT_UUID           = "00002a9d-0000-1000-8000-00805f9b34fb"
WEIGHT_SCALE_FEATURE_UUID         = "00002a9e-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION_MEASUREMENT_UUID = "00002a9c-0000-1000-8000-00805f9b34fb"
BODY_COMPOSITION_FEATURE_UUID     = "00002a9b-0000-1000-8000-00805f9b34fb"

# ── User Data Service ─────────────────────────────────────────────────────────
USER_INDEX_UUID         = "00002a9a-0000-1000-8000-00805f9b34fb"
USER_CONTROL_POINT_UUID = "00002a9f-0000-1000-8000-00805f9b34fb"

# ── UCP Op Codes ──────────────────────────────────────────────────────────────
UCP_OP_REGISTER_NEW_USER = 0x01
UCP_OP_CONSENT           = 0x02
UCP_OP_DELETE_USER_DATA  = 0x03
UCP_OP_RESPONSE          = 0x20
UCP_RESPONSE_SUCCESS     = 0x01
UCP_USER_INDEX_UNKNOWN   = 0xFF
UCP_DEFAULT_CONSENT_CODE = 0x0000

# ── Weight Measurement (0x2A9D) flag bits ─────────────────────────────────────
WM_FLAG_IMPERIAL    = 0x0001
WM_FLAG_TIMESTAMP   = 0x0002
WM_FLAG_USER_ID     = 0x0004
WM_FLAG_BMI_HEIGHT  = 0x0008

# ── Body Composition Measurement (0x2A9C) flag bits ──────────────────────────
BCM_FLAG_IMPERIAL          = 0x0001
BCM_FLAG_TIMESTAMP         = 0x0002
BCM_FLAG_USER_ID           = 0x0004
BCM_FLAG_BASAL_METABOLISM  = 0x0008
BCM_FLAG_MUSCLE_PERCENTAGE = 0x0010
BCM_FLAG_MUSCLE_MASS       = 0x0020
BCM_FLAG_FAT_FREE_MASS     = 0x0040
BCM_FLAG_SOFT_LEAN_MASS    = 0x0080
BCM_FLAG_BODY_WATER_MASS   = 0x0100
BCM_FLAG_IMPEDANCE         = 0x0200
BCM_FLAG_WEIGHT            = 0x0400
BCM_FLAG_HEIGHT            = 0x0800

# ── Resolution constants ──────────────────────────────────────────────────────
WM_WEIGHT_SI_RES  = 200.0
WM_WEIGHT_IMP_RES = 100.0
WM_BMI_RES        = 10.0
WM_HEIGHT_SI_RES  = 1000.0
WM_HEIGHT_IMP_RES = 10.0

# ── Unit strings ───────────────────────────────────────────────────────────────
UNIT_KG   = "kg"
UNIT_LB   = "lb"
UNIT_M    = "m"
UNIT_INCH = "in"
UNIT_KJ   = "kJ"
UNIT_OHM  = "Ω"

# ── Timing ────────────────────────────────────────────────────────────────────
PAIR_TIMEOUT                   = 30.0
FIRST_INDICATION_TIMEOUT       = 60.0
IDLE_AFTER_LAST_RECORD_TIMEOUT = 30.0
UCP_WRITE_TIMEOUT              = 5.0
UCP_RESPONSE_TIMEOUT           = 10.0


# ── Model registry ─────────────────────────────────────────────────────────────

@dataclass
class ScaleConfig:
    """Per-model configuration for a weight scale."""
    bonding_required: bool
    # Called on each advertisement to decide whether to connect.
    # Default: always connect (non-Beurer devices or unknown models).
    is_measurement_ready: Callable[[Any], bool] = field(
        default=lambda _: True, repr=False
    )


def _beurer_ready(service_info: Any) -> bool:
    """Gate for Beurer scales: connect only when service_data payload is non-empty."""
    sd = service_info.service_data
    return (
        WEIGHT_SCALE_SERVICE_UUID in sd
        and sd[WEIGHT_SCALE_SERVICE_UUID] not in (b'', b'\x00')
    )


SCALE_MODELS: dict[str, ScaleConfig] = {
    "BF105": ScaleConfig(bonding_required=True, is_measurement_ready=_beurer_ready),
    "BF720": ScaleConfig(bonding_required=True,  is_measurement_ready=_beurer_ready),
    # Add further models here; non-Beurer devices can use the default lambda
}

# Config entry key for storing the chosen model
CONF_SCALE_MODEL = "scale_model"
