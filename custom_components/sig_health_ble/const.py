"""Constants for the SIG Health BLE integration."""

DOMAIN = "sig_health_ble"

# ── Device type keys ──────────────────────────────────────────────────────────
DEVICE_TYPE_SCALE   = "scale"
DEVICE_TYPE_BPM     = "bpm"
DEVICE_TYPE_GLUCOSE = "glucose"

# ── Config entry keys ─────────────────────────────────────────────────────────
CONF_DEVICE_TYPE  = "device_type"
CONF_DEVICE_MODEL = "device_model"

# ── Bonded proxy pinning ──────────────────────────────────────────────────────
CONF_BONDED_PROXY          = "bonded_proxy"
CONF_BONDED_PROXY_ENTRY_ID = "bonded_proxy_entry_id"
ESPHOME_UNPAIR_ACTION      = "remove_bond"

# ── Timing (shared defaults) ──────────────────────────────────────────────────
PAIR_TIMEOUT                   = 30.0
CONNECT_TIMEOUT                = 15.0
NOTIFICATION_TIMEOUT           = 20.0
IDLE_AFTER_LAST_RECORD_TIMEOUT = 3.0

# ── Options keys (shared between BPM and glucose options flows) ───────────────
CONF_TIME_WINDOW_ENABLED = "time_window_enabled"
CONF_TIME_WINDOW_MINUTES = "time_window_minutes"
CONF_MAX_HISTORY         = "max_history_entries"

_DEFAULT_TIME_WINDOW_ENABLED = False
_DEFAULT_TIME_WINDOW_MINUTES = 5
_DEFAULT_MAX_HISTORY         = 20
