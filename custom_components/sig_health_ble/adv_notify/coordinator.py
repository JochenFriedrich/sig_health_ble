"""Base coordinator for advertisement-triggered + connection devices (scales).

Scale flow:
  1. Device advertises continuously
  2. Advertisement payload signals measurement ready (device-specific gate)
  3. Integration connects, performs optional UDS consent, reads GATT indications
  4. Post-read cooldown prevents reconnecting on every beacon

Bonded-proxy pinning and repair-issue logic lives in BondedProxyMixin and is
activated only when bonding_required is True (e.g. BF720, not BF105).

Subclasses supply:
  - bonding_required: bool            (from ScaleConfig, set in ScaleCoordinator)
  - is_measurement_ready(service_info) → bool  (the payload gate)
  - _do_session(client)               (GATT subscribe/drain/parse)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

from homeassistant.components.bluetooth import async_clear_advertisement_history
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..ble_utils import ensure_paired, PairingRequiresManualSetup
from ..const import PAIR_TIMEOUT
from ..proxy_mixin import BondedProxyMixin

_LOGGER = logging.getLogger(__name__)
_POLL_INTERVAL = timedelta(minutes=2)

COOLDOWN_AFTER_MEASUREMENT = timedelta(minutes=30)
COOLDOWN_AFTER_FAILURE     = timedelta(minutes=2)


class AdvNotifyCoordinator(BondedProxyMixin, DataUpdateCoordinator):
    """Coordinator for scales: watch advertisements, gate on payload, then connect."""

    bonding_required: bool = False  # overridden by ScaleCoordinator from ScaleConfig

    def __init__(
        self, hass: HomeAssistant, address: str, name: str, entry_id: str = ""
    ) -> None:
        DataUpdateCoordinator.__init__(
            self, hass, _LOGGER, name=name, update_interval=_POLL_INTERVAL
        )
        self.address = address
        self.device_name = name
        self.entry_id = entry_id
        self._connecting = False
        self._last_successful_read: datetime | None = None
        self._last_failed_attempt: datetime | None = None

        # BondedProxyMixin fields
        self.bonded_proxy = None
        self.last_seen_proxy = None
        self.last_connected_proxy = None
        self._consecutive_auth_failures = 0

        # Tunable via options flow
        self.require_connectable: bool = True
        self.cooldown_after_measurement: timedelta = COOLDOWN_AFTER_MEASUREMENT

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_advertisement(self, service_info: Any) -> None:
        source = getattr(service_info, "source", None)
        self.proxy_track_seen(source)
        if not self.proxy_should_connect(service_info.source):
            return

        now = datetime.now()

        # Guard 1: post-read cooldown
        if self._last_successful_read is not None:
            elapsed = now - self._last_successful_read
            if elapsed < self.cooldown_after_measurement:
                remaining = int((self.cooldown_after_measurement - elapsed).total_seconds() // 60)
                _LOGGER.debug("[%s] Post-read cooldown (%dm remaining)", self.address, remaining)
                return

        # Guard 2: post-failure cooldown
        if self._last_failed_attempt is not None:
            if (now - self._last_failed_attempt) < COOLDOWN_AFTER_FAILURE:
                _LOGGER.debug("[%s] Post-failure cooldown", self.address)
                return

        # Guard 3: connectable flag
        if self.require_connectable and not service_info.connectable:
            _LOGGER.debug("[%s] Not connectable – skipping", self.address)
            return

        # Guard 4: device-specific payload gate
        if not self.is_measurement_ready(service_info):
            _LOGGER.debug("[%s] Payload indicates no measurement ready – skipping", self.address)
            return

        # Guard 5: bonded proxy pinning (no-op when bonding_required is False)
        if not self.proxy_should_connect(source):
            return

        if self._connecting:
            _LOGGER.debug("[%s] Already connecting – skipping", self.address)
            return

        _LOGGER.info("[%s] Advertisement passed all guards – connecting", self.address)
        self.hass.async_create_task(self._connect_and_read(service_info))

    def is_measurement_ready(self, service_info: Any) -> bool:
        """Override to gate on advertisement payload. Default: always ready."""
        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _connect_and_read(self, service_info: Any) -> None:
        self._connecting = True
        source = getattr(service_info, "source", None)
        success = False
        try:
            await self._do_connect_and_read(service_info)
            success = True
            self.proxy_on_success(source)
        except PairingRequiresManualSetup as err:
            _LOGGER.warning("[%s] Session failed: %s", self.address, err)
            self.proxy_on_error(err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Session failed: %s", self.address, err)
            self.proxy_on_error(err)
        finally:
            self._connecting = False
            if success:
                self._last_successful_read = datetime.now()
                _LOGGER.debug(
                    "[%s] Cooldown active for %dm",
                    self.address,
                    int(self.cooldown_after_measurement.total_seconds() // 60),
                )
            else:
                self._last_failed_attempt = datetime.now()
            try:
                async_clear_advertisement_history(self.hass, self.address)
            except Exception:  # noqa: BLE001
                pass

    async def _do_connect_and_read(self, service_info: Any) -> None:
        def _disconnected_callback(_client: Any) -> None:
            _LOGGER.debug("[%s] Device disconnected", self.address)
            self._on_disconnected()

        _LOGGER.info("[%s] Connecting via establish_connection …", self.address)
        client = await establish_connection(
            BleakClientWithServiceCache,
            service_info.device,
            self.device_name,
            disconnected_callback=_disconnected_callback,
            max_attempts=3,
        )
        try:
            _LOGGER.info("[%s] Connected – pairing …", self.address)
            await ensure_paired(client, self.address, PAIR_TIMEOUT)
            await self._do_session(client)
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def _on_disconnected(self) -> None:
        """Called when device disconnects. Override to signal done_event."""

    async def _do_session(self, client: Any) -> None:
        """Override to perform GATT subscribe/drain/parse."""
        raise NotImplementedError

    # ── DataUpdateCoordinator override ────────────────────────────────────────

    async def _async_update_data(self) -> Any:
        return getattr(self, "_last_measurement", None)
