from datetime import datetime
from homeassistant.core import callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from ...const import CONF_TIME_WINDOW_ENABLED, _DEFAULT_TIME_WINDOW_ENABLED, CONF_TIME_WINDOW_MINUTES, _DEFAULT_TIME_WINDOW_MINUTES, DOMAIN

def _timestamp_ok(
    device_ts: datetime | None,
    received_at: datetime,
    window_enabled: bool,
    window_minutes: int,
) -> tuple[bool, str]:
    """Return (ok, reason_if_not_ok)."""
    if not window_enabled or device_ts is None:
        return True, ""
    delta = abs((received_at - device_ts).total_seconds()) / 60
    if delta > window_minutes:
        h, m = divmod(int(delta), 60)
        desc = f"{h}h {m}min off" if h else f"{m}min off"
        return False, f"timestamp {desc}"
    return True, ""

def _glucose_validity(
    m: Any,
    received_at: datetime,
    window_enabled: bool,
    window_minutes: int,
) -> tuple[bool, str]:
    """Return (valid, problem_description) for a GlucoseMeasurement."""
    # Status flags
    if m.status_raw is not None and m.status_raw != 0:
        summary = m.status_summary or f"flags 0x{m.status_raw:04x}"
        return False, summary
    # measurement_valid=False with no status bits set (shouldn't happen, but guard)
    if m.measurement_valid is False:
        return False, "invalid measurement"
    # Timestamp window
    ts_ok, ts_reason = _timestamp_ok(m.timestamp, received_at, window_enabled, window_minutes)
    if not ts_ok:
        return False, ts_reason
    return True, ""

class GlucoseHistorySensor(CoordinatorEntity, SensorEntity):
    """History sensor — appends every measurement, valid or not."""

    _attr_icon = "mdi:history"
    _attr_state_class = None

    def __init__(self, coordinator: Any, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_glucose_history"
        self._attr_name = f"{entry.title} History"
        self._history: list[dict] = []
        self._attr_native_value = 0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.device_name,
            manufacturer="Bluetooth SIG",
            model="Glucose Meter (0x1808)",
        )


    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        

    @property
    def _opts(self) -> dict:
        return self._entry.options

    @property
    def extra_state_attributes(self) -> dict:
        received_at = getattr(
            self.coordinator, "last_received_at", datetime.now().astimezone()
        )
        window_enabled = self._opts.get(CONF_TIME_WINDOW_ENABLED, _DEFAULT_TIME_WINDOW_ENABLED)
        window_minutes = self._opts.get(CONF_TIME_WINDOW_MINUTES, _DEFAULT_TIME_WINDOW_MINUTES)

        entries = []
        for m in self._history:
            valid, problem = _bpm_validity(m, received_at, window_enabled, window_minutes)
            entries.append({
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "sequence_number": seq,
                "glucose":         round(float(m.glucose_mg_dl), 1) if m.glucose_mg_dl is not None else None,
                "glucose_mmol_l":  round(float(m.glucose_mmol_l), 1) if m.glucose_mmol_l is not None else None,
                "sample_type":     m.sample_type if m.sample_type is not None else None,
                "sample_location": m.sample_location if m.sample_location is not None else None,
                "valid":     valid,
                "status":    "OK" if valid else problem,
            })

        return {"measurements": entries}

    @callback
    def _handle_coordinator_update(self) -> None:
        m = self.coordinator.data
        if m is None:
            return
        self._history = getattr(m, "_history", [])
        self._attr_native_value = len(self._history)
        self.async_write_ha_state()

