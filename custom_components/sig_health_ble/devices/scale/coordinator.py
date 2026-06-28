"""Coordinator for Weight Scale devices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ...ble_utils import is_auth_error
from ...ble_device_info import read_device_info
from ...adv_notify.coordinator import AdvNotifyCoordinator
from .const import (
    WEIGHT_SCALE_SERVICE_UUID, BODY_COMPOSITION_SERVICE_UUID,
    WEIGHT_MEASUREMENT_UUID, BODY_COMPOSITION_MEASUREMENT_UUID,
    USER_DATA_SERVICE_UUID, USER_CONTROL_POINT_UUID,
    UCP_OP_CONSENT, UCP_OP_REGISTER_NEW_USER, UCP_OP_RESPONSE,
    UCP_RESPONSE_SUCCESS, UCP_USER_INDEX_UNKNOWN, UCP_DEFAULT_CONSENT_CODE,
    UCP_WRITE_TIMEOUT, UCP_RESPONSE_TIMEOUT,
    FIRST_INDICATION_TIMEOUT, IDLE_AFTER_LAST_RECORD_TIMEOUT,
    ScaleConfig, SCALE_MODELS, CONF_SCALE_MODEL,
)
from .parser import (
    ScaleMeasurement, WeightMeasurement, BodyCompositionMeasurement,
    parse_weight_measurement, parse_body_composition_measurement,
)

_LOGGER = logging.getLogger(__name__)


class ScaleCoordinator(AdvNotifyCoordinator):
    """Coordinator for a single weight scale."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        model: str,
        config_entry: ConfigEntry | None = None,
        entry_id: str = "",
    ) -> None:
        super().__init__(hass, address, name, entry_id=entry_id)
        self._model = model
        self._config: ScaleConfig = SCALE_MODELS.get(model, ScaleConfig(bonding_required=False))
        self._config_entry = config_entry
        self._device_info_read = bool(model)
        self._last_measurement: ScaleMeasurement | None = None
        self._done_event: asyncio.Event = asyncio.Event()

        # Activate proxy pinning only for bonding models (e.g. BF720, not BF105)
        self.bonding_required = self._config.bonding_required

        # UDS consent settings (configurable via options flow)
        self.uds_user_index: int     = UCP_USER_INDEX_UNKNOWN
        self.uds_consent_code: int   = UCP_DEFAULT_CONSENT_CODE
        self.uds_auto_register: bool = False

    # ── Advertisement payload gate ─────────────────────────────────────────────

    def is_measurement_ready(self, service_info: Any) -> bool:
        return self._config.is_measurement_ready(service_info)

    # ── Disconnect signal ──────────────────────────────────────────────────────

    def _on_disconnected(self) -> None:
        self._done_event.set()

    # ── GATT session ──────────────────────────────────────────────────────────

    async def _do_session(self, client: Any) -> None:
        # ── Step 0: read Device Information Service on first connection ────────
        if not self._device_info_read:
            await self._read_and_apply_device_info(client)

        weight_records: list[WeightMeasurement] = []
        bcm_records:    list[BodyCompositionMeasurement] = []
        first_indication_event = asyncio.Event()
        self._done_event = asyncio.Event()
        idle_handle: list[asyncio.TimerHandle | None] = [None]

        def _reschedule_idle() -> None:
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            idle_handle[0] = asyncio.get_event_loop().call_later(
                IDLE_AFTER_LAST_RECORD_TIMEOUT, self._done_event.set
            )

        def _weight_handler(sender: Any, data: bytearray) -> None:
            _LOGGER.debug("[%s] Weight indication data=%s", self.address, data.hex())
            _reschedule_idle()
            try:
                m = parse_weight_measurement(bytes(data))
                if m.is_valid:
                    weight_records.append(m)
                    first_indication_event.set()
            except ValueError as exc:
                _LOGGER.warning("[%s] Weight parse error: %s", self.address, exc)

        def _bcm_handler(sender: Any, data: bytearray) -> None:
            _LOGGER.debug("[%s] BCM indication data=%s", self.address, data.hex())
            _reschedule_idle()
            try:
                m = parse_body_composition_measurement(bytes(data))
                if m.is_valid:
                    bcm_records.append(m)
                    first_indication_event.set()
            except ValueError as exc:
                _LOGGER.warning("[%s] BCM parse error: %s", self.address, exc)

        handles = self._resolve_characteristics(client)

        if handles.get("weight") is None:
            raise BleakError(f"[{self.address}] Weight Measurement (0x2A9D) not found")

        try:
            await client.start_notify(handles["weight"], _weight_handler)
        except BleakError as exc:
            if is_auth_error(exc):
                raise BleakError(
                    f"[{self.address}] Auth error – "
                    f"try: bluetoothctl remove {self.address} then re-pair. {exc}"
                ) from exc
            raise

        bcm_available = False
        if handles.get("bcm") is not None:
            try:
                await client.start_notify(handles["bcm"], _bcm_handler)
                bcm_available = True
            except BleakError as exc:
                if self._done_event.is_set() or weight_records or bcm_records:
                    _LOGGER.debug("[%s] BCM subscribe failed after data received (expected): %s",
                                  self.address, exc)
                else:
                    _LOGGER.warning("[%s] BCM subscribe failed: %s", self.address, exc)

        # UDS consent (skip if no User Data Service)
        if self._has_uds(client):
            await self._ensure_consent(client)

        # Phase 1 — wait for first indication
        if not self._done_event.is_set() and not first_indication_event.is_set():
            try:
                await asyncio.wait_for(
                    first_indication_event.wait(), timeout=FIRST_INDICATION_TIMEOUT
                )
            except asyncio.TimeoutError:
                _LOGGER.warning("[%s] No indications within %ds",
                                self.address, FIRST_INDICATION_TIMEOUT)
                if idle_handle[0] is not None:
                    idle_handle[0].cancel()
                raise BleakError(
                    f"[{self.address}] No indications within {FIRST_INDICATION_TIMEOUT}s"
                )
        elif self._done_event.is_set() and not weight_records and not bcm_records:
            _LOGGER.info("[%s] Device disconnected with no data", self.address)
            return
        else:
            _LOGGER.debug("[%s] Data already received – fast-path to drain", self.address)

        # Phase 2 — drain
        if not self._done_event.is_set():
            await self._done_event.wait()
        if idle_handle[0] is not None:
            idle_handle[0].cancel()

        _LOGGER.info("[%s] Transfer complete – %d weight, %d BCM record(s)",
                     self.address, len(weight_records), len(bcm_records))

        for h in [handles.get("weight"), handles.get("bcm") if bcm_available else None]:
            if h is not None:
                try:
                    await client.stop_notify(h)
                except BleakError:
                    pass

        if not weight_records and not bcm_records:
            return

        def _latest(records):
            if not records:
                return None
            with_ts = [r for r in records if r.timestamp is not None]
            return max(with_ts, key=lambda r: r.timestamp) if with_ts else records[-1]

        result = ScaleMeasurement(
            weight=_latest(weight_records),
            body_composition=_latest(bcm_records),
        )
        _LOGGER.info(
            "[%s] ✓ Publishing: %.3f kg bmi=%s fat=%s%%",
            self.address, result.weight_kg or 0, result.bmi,
            result.body_composition.body_fat_percent if result.body_composition else "N/A",
        )
        self._last_measurement = result
        self.async_set_updated_data(result)

    # ── Device Information Service ─────────────────────────────────────────────

    async def _read_and_apply_device_info(self, client: Any) -> None:
        """Read 0x2A24 (model) and 0x2A29 (manufacturer) from the device.

        On success:
          - Updates self._model and self._config
          - Persists the model to the config entry so the select_model step
            is skipped on future HA restarts
          - Marks _device_info_read so this only runs once
        """
        try:
            model, manufacturer = await read_device_info(client, self.address)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("[%s] Device info read failed: %s", self.address, exc)
            self._device_info_read = True
            return

        if model:
            model = model.strip()
            _LOGGER.info("[%s] Device model from GATT: %r", self.address, model)
            self._model = model
            self._config = SCALE_MODELS.get(model, ScaleConfig(bonding_required=False))
            # Update bonding_required so proxy pinning activates for e.g. BF720
            self.bonding_required = self._config.bonding_required
            if model not in SCALE_MODELS:
                _LOGGER.info(
                    "[%s] Model %r not in SCALE_MODELS registry — "
                    "using generic config (no bonding, default gate)",
                    self.address, model,
                )

            # Persist to config entry so HA knows the model after restart
            if self._config_entry is not None:
                new_data = dict(self._config_entry.data)
                new_data[CONF_SCALE_MODEL] = model
                if manufacturer:
                    new_data["manufacturer"] = manufacturer.strip()
                self.hass.config_entries.async_update_entry(
                    self._config_entry, data=new_data
                )
                _LOGGER.debug("[%s] Config entry updated with model=%r", self.address, model)
        else:
            _LOGGER.debug("[%s] Model Number characteristic absent or empty", self.address)

        self._device_info_read = True

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _resolve_characteristics(self, client: Any) -> dict[str, int | None]:
        def _n(u: str) -> str:
            return str(u).lower()

        ws_svc   = _n(WEIGHT_SCALE_SERVICE_UUID)
        bc_svc   = _n(BODY_COMPOSITION_SERVICE_UUID)
        wm_uuid  = _n(WEIGHT_MEASUREMENT_UUID)
        bcm_uuid = _n(BODY_COMPOSITION_MEASUREMENT_UUID)
        handles: dict[str, int | None] = {"weight": None, "bcm": None}

        for svc in client.services:
            su = _n(svc.uuid)
            for char in svc.characteristics:
                cu = _n(char.uuid)
                if cu == wm_uuid  and su == ws_svc and handles["weight"] is None:
                    handles["weight"] = char.handle
                elif cu == bcm_uuid and su == bc_svc and handles["bcm"] is None:
                    handles["bcm"] = char.handle

        if handles["weight"] is None or handles["bcm"] is None:
            for svc in client.services:
                for char in svc.characteristics:
                    cu = _n(char.uuid)
                    if cu == wm_uuid  and handles["weight"] is None: handles["weight"] = char.handle
                    elif cu == bcm_uuid and handles["bcm"] is None:  handles["bcm"]    = char.handle

        return handles

    def _has_uds(self, client: Any) -> bool:
        uds = USER_DATA_SERVICE_UUID.lower()
        return any(str(svc.uuid).lower() == uds for svc in client.services)

    async def _ensure_consent(self, client: Any) -> None:
        """Run UDS consent handshake if the scale has a User Data Service."""
        try:
            ucp_handle = None
            for svc in client.services:
                for char in svc.characteristics:
                    if str(char.uuid).lower() == USER_CONTROL_POINT_UUID.lower():
                        ucp_handle = char.handle
            if ucp_handle is None:
                return

            ucp_response: list[bytes] = []
            ucp_event = asyncio.Event()

            def _ucp_handler(sender: Any, data: bytearray) -> None:
                ucp_response.append(bytes(data))
                ucp_event.set()

            await client.start_notify(ucp_handle, _ucp_handler)

            if self.uds_user_index == UCP_USER_INDEX_UNKNOWN and self.uds_auto_register:
                cmd = bytes([UCP_OP_REGISTER_NEW_USER,
                             self.uds_consent_code & 0xFF,
                             (self.uds_consent_code >> 8) & 0xFF])
            else:
                idx = self.uds_user_index if self.uds_user_index != UCP_USER_INDEX_UNKNOWN else 0
                cmd = bytes([UCP_OP_CONSENT, idx,
                             self.uds_consent_code & 0xFF,
                             (self.uds_consent_code >> 8) & 0xFF])

            await asyncio.wait_for(
                client.write_gatt_char(ucp_handle, cmd, response=True),
                timeout=UCP_WRITE_TIMEOUT,
            )
            try:
                await asyncio.wait_for(ucp_event.wait(), timeout=UCP_RESPONSE_TIMEOUT)
            except asyncio.TimeoutError:
                _LOGGER.warning("[%s] UCP response timed out", self.address)
                return

            if ucp_response and ucp_response[0][0] == UCP_OP_RESPONSE:
                if ucp_response[0][2] == UCP_RESPONSE_SUCCESS:
                    _LOGGER.info("[%s] UDS consent granted", self.address)
                else:
                    _LOGGER.warning("[%s] UDS consent refused: code=0x%02x",
                                    self.address, ucp_response[0][2])
            await client.stop_notify(ucp_handle)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("[%s] UDS consent error (continuing): %s", self.address, exc)

    # ── DataUpdateCoordinator override ────────────────────────────────────────

    async def _async_update_data(self) -> ScaleMeasurement | None:
        return self._last_measurement
