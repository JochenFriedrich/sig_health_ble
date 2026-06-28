"""Coordinator for Glucose Meter devices."""
from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from bleak import BleakError

from homeassistant.core import HomeAssistant

from ...ble_utils import is_auth_error
from ...notify.coordinator import NotifyCoordinator
from .const import (
    GLUCOSE_SERVICE_UUID, GLUCOSE_MEASUREMENT_UUID, GLUCOSE_CONTEXT_UUID, RACP_UUID,
    RACP_OP_REPORT_STORED_RECORDS, RACP_OPERATOR_ALL,
    RACP_RESPONSE_SUCCESS, RACP_RESPONSE_NO_RECORDS,
    RACP_WRITE_TIMEOUT, FIRST_RECORD_TIMEOUT, RACP_RESPONSE_TIMEOUT,
    IDLE_AFTER_LAST_RECORD_TIMEOUT,
)
from .parser import (
    GlucoseMeasurement, GlucoseMeasurementContext,
    parse_glucose_measurement, parse_glucose_context, parse_racp_response,
)

_LOGGER = logging.getLogger(__name__)
_RACP_REPORT_ALL = bytes([RACP_OP_REPORT_STORED_RECORDS, RACP_OPERATOR_ALL])


class GlucoseCoordinator(NotifyCoordinator):
    """Coordinator for a single glucose meter device."""

    def __init__(self, hass: HomeAssistant, address: str, name: str, entry_id: str = "") -> None:
        super().__init__(hass, address, name, entry_id=entry_id)
        self._last_measurement: GlucoseMeasurement | None = None
        self._racp_done_event: asyncio.Event = asyncio.Event()

    def _on_disconnected(self) -> None:
        self._racp_done_event.set()

    async def _do_session(self, client: Any) -> None:
        received_measurements: dict[int, GlucoseMeasurement] = {}
        received_contexts:     dict[int, GlucoseMeasurementContext] = {}
        first_record_event = asyncio.Event()
        self._racp_done_event = asyncio.Event()
        idle_handle: list[asyncio.TimerHandle | None] = [None]
        racp_result: list[int] = [RACP_RESPONSE_SUCCESS]

        def _reschedule_idle() -> None:
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            idle_handle[0] = asyncio.get_event_loop().call_later(
                IDLE_AFTER_LAST_RECORD_TIMEOUT, self._racp_done_event.set
            )

        def _measurement_handler(sender: Any, data: bytearray) -> None:
            _reschedule_idle()
            try:
                m = parse_glucose_measurement(bytes(data))
                received_measurements[m.sequence_number] = m
                first_record_event.set()
            except ValueError as exc:
                _LOGGER.warning("[%s] Parse error: %s", self.address, exc)

        def _context_handler(sender: Any, data: bytearray) -> None:
            _reschedule_idle()
            try:
                ctx = parse_glucose_context(bytes(data))
                received_contexts[ctx.sequence_number] = ctx
            except ValueError as exc:
                _LOGGER.warning("[%s] Context parse error: %s", self.address, exc)

        def _racp_handler(sender: Any, data: bytearray) -> None:
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            try:
                _, _, response_code = parse_racp_response(bytes(data))
                racp_result[0] = response_code
            except ValueError as exc:
                _LOGGER.warning("[%s] RACP parse error: %s", self.address, exc)
            finally:
                self._racp_done_event.set()

        handles = self._resolve_characteristics(client)

        try:
            await client.start_notify(handles["measurement"], _measurement_handler)
        except BleakError as exc:
            if is_auth_error(exc):
                raise BleakError(
                    f"[{self.address}] Auth error – "
                    f"try: bluetoothctl remove {self.address} then re-pair. {exc}"
                ) from exc
            raise

        context_available = False
        if handles.get("context") is not None:
            try:
                await client.start_notify(handles["context"], _context_handler)
                context_available = True
            except BleakError:
                _LOGGER.debug("[%s] Context not available", self.address)

        await client.start_notify(handles["racp"], _racp_handler)

        _LOGGER.info("[%s] Writing RACP: Report All Stored Records …", self.address)
        await asyncio.wait_for(
            client.write_gatt_char(handles["racp"], _RACP_REPORT_ALL, response=True),
            timeout=RACP_WRITE_TIMEOUT,
        )

        # Phase 1 — wait for first record or RACP done
        first_or_done = asyncio.ensure_future(asyncio.wait(
            {asyncio.ensure_future(first_record_event.wait()),
             asyncio.ensure_future(self._racp_done_event.wait())},
            return_when=asyncio.FIRST_COMPLETED,
        ))
        try:
            await asyncio.wait_for(first_or_done, timeout=FIRST_RECORD_TIMEOUT)
        except asyncio.TimeoutError:
            _LOGGER.warning("[%s] No records within %ds", self.address, FIRST_RECORD_TIMEOUT)
            if idle_handle[0] is not None:
                idle_handle[0].cancel()
            return

        # Phase 2 — drain until RACP signals done
        if not self._racp_done_event.is_set():
            try:
                await asyncio.wait_for(
                    self._racp_done_event.wait(), timeout=RACP_RESPONSE_TIMEOUT
                )
            except asyncio.TimeoutError:
                _LOGGER.warning("[%s] RACP response not received within %ds",
                                self.address, RACP_RESPONSE_TIMEOUT)

        if idle_handle[0] is not None:
            idle_handle[0].cancel()

        if racp_result[0] == RACP_RESPONSE_NO_RECORDS:
            _LOGGER.info("[%s] Device reports no stored records", self.address)
            return

        _LOGGER.info("[%s] Transfer complete – %d record(s), %d context(s)",
                     self.address, len(received_measurements), len(received_contexts))

        stop_handles = [handles["measurement"], handles["racp"]]
        if context_available and handles.get("context"):
            stop_handles.append(handles["context"])
        for h in stop_handles:
            try:
                await client.stop_notify(h)
            except BleakError:
                pass

        for seq, ctx in received_contexts.items():
            if seq in received_measurements:
                received_measurements[seq].context = ctx

        if not received_measurements:
            return

        measurements = list(received_measurements.values())
        with_ts = [m for m in measurements if m.timestamp is not None]
        latest = (
            max(with_ts, key=lambda m: m.timestamp)
            if with_ts
            else max(measurements, key=lambda m: m.sequence_number)
        )
        _LOGGER.info(
            "[%s] ✓ Publishing latest of %d: seq#%d %.2f mmol/L ts=%s",
            self.address, len(measurements),
            latest.sequence_number, latest.glucose_mmol_l or 0, latest.timestamp,
        )
        self._last_measurement = latest
        self.async_set_updated_data(latest)

    def _resolve_characteristics(self, client: Any) -> dict[str, int | None]:
        def _n(u: str) -> str:
            return str(u).lower()

        gl_svc    = _n(GLUCOSE_SERVICE_UUID)
        meas_uuid = _n(GLUCOSE_MEASUREMENT_UUID)
        ctx_uuid  = _n(GLUCOSE_CONTEXT_UUID)
        racp_uuid = _n(RACP_UUID)
        handles: dict[str, int | None] = {"measurement": None, "context": None, "racp": None}

        for svc in client.services:
            if _n(svc.uuid) != gl_svc:
                continue
            for char in svc.characteristics:
                u = _n(char.uuid)
                if u == meas_uuid:   handles["measurement"] = char.handle
                elif u == ctx_uuid:  handles["context"]     = char.handle
                elif u == racp_uuid: handles["racp"]        = char.handle

        if None in (handles["measurement"], handles["racp"]):
            for svc in client.services:
                for char in svc.characteristics:
                    u = _n(char.uuid)
                    if u == meas_uuid   and handles["measurement"] is None: handles["measurement"] = char.handle
                    elif u == ctx_uuid  and handles["context"]     is None: handles["context"]     = char.handle
                    elif u == racp_uuid and handles["racp"]        is None: handles["racp"]        = char.handle

        missing = [k for k in ("measurement", "racp") if handles[k] is None]
        if missing:
            raise BleakError(f"[{self.address}] Required characteristics not found: {missing}")
        return handles
