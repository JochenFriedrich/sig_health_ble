"""Constants for the Blood Pressure Monitor device."""

# ── Bluetooth SIG standard UUIDs ──────────────────────────────────────────────
BP_SERVICE_UUID       = "00001810-0000-1000-8000-00805f9b34fb"
BP_MEASUREMENT_UUID   = "00002a35-0000-1000-8000-00805f9b34fb"
INTERMEDIATE_CUFF_UUID = "00002a36-0000-1000-8000-00805f9b34fb"
BP_FEATURE_UUID       = "00002a49-0000-1000-8000-00805f9b34fb"
CCCD_UUID             = "00002902-0000-1000-8000-00805f9b34fb"

# ── Measurement flag bits (octet 0 of 0x2A35) ─────────────────────────────────
FLAG_UNIT_KPA           = 0x01
FLAG_TIMESTAMP          = 0x02
FLAG_PULSE_RATE         = 0x04
FLAG_USER_ID            = 0x08
FLAG_MEASUREMENT_STATUS = 0x10

# ── Unit labels ───────────────────────────────────────────────────────────────
UNIT_MMHG = "mmHg"
UNIT_KPA  = "kPa"

# ── Timing ────────────────────────────────────────────────────────────────────
NOTIFICATION_TIMEOUT           = 20.0
IDLE_AFTER_LAST_RECORD_TIMEOUT = 3.0
