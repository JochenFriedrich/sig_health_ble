"""Base coordinator for advertisement-triggered notify devices (BPM, Glucose).

These devices:
  1. Advertise briefly when a measurement is ready
  2. Require a BLE connection to retrieve data via GATT notify/indicate
  3. May require bonding for encrypted characteristics
  4. Disconnect themselves after streaming all records

Bonded-proxy pinning and repair-issue logic lives in BondedProxyMixin.
Subclasses implement _do_session(client) for device-specific GATT logic.
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
_POLL_INTERVAL = timedelta(hours=24)
_COOLDOWN_AFTER_FAILURE = timedelta(minutes=2)

class NotifyCoordinator(BondedProxyMixin, DataUpdateCoordinator):
    """Coordinator for BPM and Glucose: connect on advertisement, drain via notify.

    BPM and Glucose always require bonding, so bonding_required is hardcoded
    True here.
    """

    bonding_required: bool = True

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
        self.bonded_proxy = None
        self.last_seen_proxy = None
        self.last_connected_proxy = None
        self._consecutive_auth_failures = 0
        self._last_failed_attempt: datetime | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_advertisement(self, service_info: Any) -> None:
        source = getattr(service_info, "source", None)
        self.proxy_track_seen(source)
        if not self.proxy_should_connect(service_info.source):
            return

        if self._last_failed_attempt is not None:
            elapsed = datetime.now() - self._last_failed_attempt
            if elapsed < _COOLDOWN_AFTER_FAILURE:
                remaining = int((_COOLDOWN_AFTER_FAILURE - elapsed).total_seconds())
                _LOGGER.debug(
                    "[%s] Post-failure cooldown (%ds remaining) – skipping",
                    self.address, remaining,
                )
                return

        if not self.proxy_should_connect(source):
            return

        if self._connecting:
            _LOGGER.debug("[%s] Already connecting – skipping", self.address)
            return

        _LOGGER.debug("[%s] Advertisement received – scheduling connection", self.address)
        self.hass.async_create_task(self._connect_and_read(service_info))

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _connect_and_read(self, service_info: Any) -> None:
        self._connecting = True
        source = getattr(service_info, "source", None)
        try:
            await self._do_connect_and_read(service_info)
            self.proxy_on_success(source)
            self._last_failed_attempt = None        # ← clear on success
        except PairingRequiresManualSetup as err:
            _LOGGER.warning("[%s] Session failed: %s", self.address, err)
            self._last_failed_attempt = datetime.now()   # ← set on failure
            self.proxy_on_error(err)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("[%s] Session failed: %s", self.address, err)
            self._last_failed_attempt = datetime.now()   # ← set on failure
            self.proxy_on_error(err)
        finally:
            self._connecting = False
            try:
                async_clear_advertisement_history(self.hass, self.address)
            except Exception:  # noqa: BLE001
                pass

    async def _do_connect_and_read(self, service_info: Any) -> None:
        def _disconnected_callback(_client: Any) -> None:
            _LOGGER.debug("[%s] Device disconnected", self.address)
            self._on_disconnected()

        _LOGGER.info("[%s] Connecting …", self.address)
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
        """Override in subclasses to perform GATT subscribe/drain/parse."""
        raise NotImplementedError

    # ── DataUpdateCoordinator override ────────────────────────────────────────

    async def _async_update_data(self) -> Any:
        return getattr(self, "_last_measurement", None)
