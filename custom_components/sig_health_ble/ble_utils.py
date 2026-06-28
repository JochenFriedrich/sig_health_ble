"""Shared BLE pairing/bonding logic for SIG Health BLE coordinators."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakError

_LOGGER = logging.getLogger(__name__)


class PairingRequiresManualSetup(Exception):
    """Raised when pairing failed in a way that strongly suggests the device
    needs passkey/numeric-comparison confirmation, which stock bluetooth_proxy
    cannot surface (it doesn't handle ESP_GAP_BLE_PASSKEY_REQ_EVT).

    The only fix is the documented manual procedure: reflash the proxy with
    ble_client + io_capability: keyboard_display, pair once, reflash back to
    bluetooth_proxy. The coordinator raises a repair issue when this occurs.
    """


def is_auth_error(exc: BleakError) -> bool:
    """Return True if the BleakError indicates an authentication/encryption failure."""
    msg = str(exc).lower()
    _LOGGER.debug("is_auth_error: %s", msg)
    return (
        "insufficient authentication" in msg
        or "insufficient encryption" in msg
        or "error=5" in msg
        or "error=8" in msg
        or "error=15" in msg
        or "error=19" in msg
        or "esp_gatt_conn_terminate_peer_user" in msg
    )


def _looks_like_passkey_stuck(exc: BaseException) -> bool:
    """Heuristic: timeout or specific GATT errors during pair() on a stock
    bluetooth_proxy almost always mean the device is waiting for a passkey
    or numeric comparison that never arrives, since the proxy can't raise
    ESP_GAP_BLE_PASSKEY_REQ_EVT to Home Assistant.
    """
    if isinstance(exc, asyncio.TimeoutError):
        return True
    msg = str(exc).lower()
    return "error=5" in msg or "error=8" in msg or "timed out" in msg


async def ensure_paired(client: Any, address: str, pair_timeout: float) -> None:
    """Attempt to pair/bond with the device; handle proxies and failures gracefully.

    On BlueZ (Linux / HAOS):
      - If already bonded, pair() returns almost instantly.
      - If not bonded, BlueZ performs the SMP exchange and stores the LTK.

    On ESPHome Bluetooth Proxies (bleak-esphome, newer firmware):
      - pair()/unpair() are implemented and forwarded to the ESP32.
      - BUT: bluetooth_proxy does not handle ESP_GAP_BLE_PASSKEY_REQ_EVT, so
        any device requiring passkey entry or numeric comparison will hang
        or fail here even though pair() itself is "supported". This function
        cannot distinguish "no pairing needed" from "stuck waiting for a
        passkey nobody can answer" — it raises PairingRequiresManualSetup
        when the failure signature matches the latter so the coordinator can
        surface a repair flow instead of silently retrying forever.
    """
    try:
        _LOGGER.debug("[%s] Calling client.pair() …", address)
        await asyncio.wait_for(client.pair(), timeout=pair_timeout)
        _LOGGER.info("[%s] Paired/bonded successfully (or already bonded)", address)
    except NotImplementedError:
        _LOGGER.debug(
            "[%s] pair() not supported on this backend. "
            "Continuing without explicit pairing.",
            address,
        )
    except asyncio.TimeoutError as exc:
        _LOGGER.warning(
            "[%s] Pairing timed out after %ds. This usually means the device "
            "is waiting for a passkey or numeric comparison that stock "
            "bluetooth_proxy cannot surface. A manual re-pair via ble_client "
            "mode is likely required.",
            address, pair_timeout,
        )
        raise PairingRequiresManualSetup(str(exc)) from exc
    except BleakError as exc:
        if "already" in str(exc).lower() or "paired" in str(exc).lower():
            _LOGGER.debug("[%s] Device reports already paired: %s", address, exc)
        elif _looks_like_passkey_stuck(exc):
            _LOGGER.warning(
                "[%s] pair() failed in a way consistent with a stuck passkey "
                "request (%s). A manual re-pair via ble_client mode is "
                "likely required.",
                address, exc,
            )
            raise PairingRequiresManualSetup(str(exc)) from exc
        else:
            _LOGGER.warning(
                "[%s] pair() failed: %s. "
                "If you see GATT error=5 next, run: "
                "bluetoothctl; agent on; pair %s",
                address, exc, address,
            )


async def unpair_device(client: Any, address: str) -> tuple[bool, str]:
    """Attempt to clear the bond/LTK for this device via bleak's unpair().

    ESPHome's bluetooth_proxy component handles BLUETOOTH_DEVICE_REQUEST_TYPE_UNPAIR
    by calling esp_ble_remove_bond_device() on the ESP32 — i.e. unpairing is a
    native proxy capability and does NOT require a custom YAML lambda action.

    Whether this is reachable via bleak's client.unpair() depends on the
    Home Assistant esphome integration's bluetooth client implementation
    exposing it. This function tries that path first; if unsupported, the
    caller should fall back to a custom ESPHome API action.

    Returns (success, error_message).
    """
    try:
        if not hasattr(client, "unpair"):
            return False, "unpair() not implemented on this BLE backend"
        await client.unpair()
        _LOGGER.info("[%s] Unpaired successfully (LTK cleared)", address)
        return True, ""
    except NotImplementedError:
        return False, "unpair() not supported on this backend (ESPHome proxy version too old?)"
    except BleakError as exc:
        _LOGGER.warning("[%s] unpair() failed: %s", address, exc)
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("[%s] unpair() raised unexpected error: %s", address, exc)
        return False, str(exc)
