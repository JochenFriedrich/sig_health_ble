"""Coordinator for Blood Pressure Monitor devices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakError

from homeassistant.core import HomeAssistant

from ...ble_utils import is_auth_error
from ...notify.coordinator import NotifyCoordinator
from .const import (
    BP_SERVICE_UUID, BP_MEASUREMENT_UUID, INTERMEDIATE_CUFF_UUID,
    NOTIFICATION_TIMEOUT, IDLE_AFTER_LAST_RECORD_TIMEOUT,
)
from .parser import BloodPressureMeasurement, parse_blood_pressure_measurement

_LOGGER = logging.getLogger(__name__)


class BPMCoordinator(NotifyCoordinator):
    """Coordinator for a single BPM device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str, entry_id: str = "") -> None:
        super().__init__(hass, address, name, entry_id=entry_id)
        self._last_measurement: BloodPressureMeasurement | None = None
        self._done_event: asyncio.Event = asyncio.Event()

    def _on_disconnected(self) -> None:
        self._done_event.set()

    async def _do_session(self, client: Any) -> None:
        received: list[BloodPressureMeasurement] = []
        first_record_event = asyncio.Event()
        self._done_event = asyncio.Event()
        idle_handle: list[asyncio.TimerHandle | None] = [None]

        def _reschedule_idle() -> None:
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            idle_handle[0] = asyncio.get_event_loop().call_later(
                IDLE_AFTER_LAST_RECORD_TIMEOUT, self._done_event.set
            )

        def _notification_handler(sender: Any, data: bytearray) -> None:
            _LOGGER.debug("[%s] BP indication data=%s", self.address, data.hex())
            _reschedule_idle()
            try:
                parsed = parse_blood_pressure_measurement(bytes(data))
                if parsed.is_valid:
                    received.append(parsed)
                    first_record_event.set()
            except ValueError as exc:
                _LOGGER.warning("[%s] Parse error: %s", self.address, exc)

        def _intermediate_handler(sender: Any, data: bytearray) -> None:
            _reschedule_idle()

        handles = self._resolve_characteristics(client)

        try:
            await client.start_notify(handles["measurement"], _notification_handler)
        except BleakError as exc:
            if is_auth_error(exc):
                raise BleakError(
                    f"[{self.address}] Auth error – "
                    f"try: bluetoothctl remove {self.address} then re-pair. {exc}"
                ) from exc
            raise

        if handles["intermediate"] is not None:
            try:
                await client.start_notify(handles["intermediate"], _intermediate_handler)
            except BleakError:
                _LOGGER.debug("[%s] Intermediate Cuff Pressure not available", self.address)

        try:
            await asyncio.wait_for(first_record_event.wait(), timeout=NOTIFICATION_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning("[%s] No BP record within %ds", self.address, NOTIFICATION_TIMEOUT)
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            return

        await self._done_event.wait()
        if idle_handle[0] is not None:
            idle_handle[0].cancel()

        _LOGGER.info("[%s] Transfer complete – %d record(s)", self.address, len(received))

        try:
            await client.stop_notify(handles["measurement"])
        except BleakError:
            pass

        if not received:
            return

        with_ts = [m for m in received if m.timestamp is not None]
        latest = max(with_ts, key=lambda m: m.timestamp) if with_ts else received[-1]

        _LOGGER.info(
            "[%s] ✓ Publishing: sys=%s dia=%s %s pulse=%s ts=%s",
            self.address, latest.systolic, latest.diastolic,
            latest.unit, latest.pulse_rate, latest.timestamp,
        )
        self._last_measurement = latest
        self.async_set_updated_data(latest)

    def _resolve_characteristics(self, client: Any) -> dict[str, int | None]:
        def _n(u: str) -> str:
            return str(u).lower()

        bp_svc = _n(BP_SERVICE_UUID)
        meas   = _n(BP_MEASUREMENT_UUID)
        inter  = _n(INTERMEDIATE_CUFF_UUID)
        handles: dict[str, int | None] = {"measurement": None, "intermediate": None}

        for svc in client.services:
            if _n(svc.uuid) != bp_svc:
                continue
            for char in svc.characteristics:
                u = _n(char.uuid)
                if u == meas:
                    handles["measurement"] = char.handle
                elif u == inter:
                    handles["intermediate"] = char.handle

        if handles["measurement"] is None:
            for svc in client.services:
                for char in svc.characteristics:
                    u = _n(char.uuid)
                    if u == meas and handles["measurement"] is None:
                        handles["measurement"] = char.handle
                    elif u == inter and handles["intermediate"] is None:
                        handles["intermediate"] = char.handle

        if handles["measurement"] is None:
            raise BleakError(f"[{self.address}] BP Measurement (0x2A35) not found")
        return handles
