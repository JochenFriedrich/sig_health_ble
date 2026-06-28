"""Shared bonded-proxy pinning and repair-issue logic for all coordinator types.
Used by both NotifyCoordinator (BPM, Glucose) and AdvNotifyCoordinator (Scale).
Activated only when bonding_required is True — non-bonding devices (BF105) get
zero overhead.

Proxy pinning
─────────────
If bonded_proxy is set, any advertisement from a different source is dropped
before a connection attempt.  This prevents a roaming proxy from connecting to
a device whose LTK is stored only on the pinned proxy's ESP32 flash, which
causes the device to rotate its LTK and silently break the existing bond.

Repair issues
─────────────
Two situations surface a HA repair notification:
  proxy_switch_detected
    Advertisement source changed from the last successfully connected proxy
    with no pinning configured.  Classic precursor to field LTK rotation.
  manual_pairing_required
    pair() failed in a way consistent with ESP_GAP_BLE_PASSKEY_REQ_EVT not
    being surfaced (stock bluetooth_proxy limitation), or consecutive auth
    errors exceeded the threshold.  User is directed to the Reconfigure flow
    for unpair + re-pair wizard.
"""
from __future__ import annotations

import logging
import re
from typing import Any, TYPE_CHECKING

from bleak import BleakError
from homeassistant.helpers import issue_registry as ir

from .ble_utils import is_auth_error, unpair_device, PairingRequiresManualSetup
from .const import DOMAIN, ESPHOME_UNPAIR_ACTION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_AUTH_FAILURE_THRESHOLD = 2


# ── ESPHome entry resolution ───────────────────────────────────────────────────

def find_esphome_entry_id(hass: Any, source_mac: str) -> str | None:
    """Find the ESPHome config entry ID for a Bluetooth proxy adapter MAC.

    Tries two strategies, both of which fail gracefully:

    Strategy 1 (preferred): use bluetooth.async_scanner_by_source() to get
    the scanner registered for this adapter MAC, read its name, then match
    the name against ESPHome config entry titles.

    Strategy 2 (fallback): walk ESPHome runtime data looking for a stored
    Bluetooth adapter MAC — the attribute path varies by HA version.

    Returns None if no match is found; native unpair still works without it
    because async_request_unpair() uses client.unpair() directly.
    """
    source_upper = source_mac.upper()
    _LOGGER.debug("Resolving ESPHome entry for adapter MAC %s", source_mac)

    # Strategy 1: Bluetooth scanner registry
    try:
        from homeassistant.components import bluetooth
        if fn := getattr(bluetooth, "async_scanner_by_source", None):
            if scanner := fn(hass, source_upper):
                scanner_name = getattr(scanner, "name", "") or ""
                if scanner_name:
                    entry_id = _match_esphome_entry_by_scanner_name(hass, scanner_name)
                    if entry_id:
                        _LOGGER.debug(
                            "Resolved %s → scanner %r → entry %s",
                            source_mac, scanner_name, entry_id,
                        )
                        return entry_id
    except Exception:  # noqa: BLE001
        pass

    # Strategy 2: ESPHome runtime data
    try:
        for entry_id, runtime_data in hass.data.get("esphome", {}).items():
            if isinstance(entry_id, str) and _runtime_data_has_bt_mac(runtime_data, source_upper):
                _LOGGER.debug(
                    "Resolved %s → ESPHome entry %s via runtime data", source_mac, entry_id
                )
                return entry_id
    except Exception:  # noqa: BLE001
        pass

    _LOGGER.debug(
        "Could not resolve adapter MAC %s to an ESPHome config entry "
        "(native unpair will still work without it)",
        source_mac,
    )
    return None


def _match_esphome_entry_by_scanner_name(hass: Any, scanner_name: str) -> str | None:
    """Match a Bluetooth scanner name to an ESPHome config entry title."""
    name_lower = scanner_name.lower()
    best: tuple[int, str] | None = None
    try:
        for entry in hass.config_entries.async_entries("esphome"):
            title = (entry.title or "").lower().strip()
            if title and name_lower.startswith(title):
                if best is None or len(title) > best[0]:
                    best = (len(title), entry.entry_id)
    except Exception:  # noqa: BLE001
        pass
    return best[1] if best else None


def _runtime_data_has_bt_mac(runtime_data: Any, mac_upper: str) -> bool:
    """Check whether an ESPHome runtime_data object holds a given BT adapter MAC."""
    candidates = [
        getattr(runtime_data, "bluetooth_mac_address", None),
        getattr(getattr(runtime_data, "entry_data", None), "bluetooth_mac_address", None),
        getattr(getattr(runtime_data, "data", None), "bluetooth_mac_address", None),
    ]
    return any(c and c.upper() == mac_upper for c in candidates)


# ── ESPHome service calls ──────────────────────────────────────────────────────

async def call_esphome_service(
    hass: Any,
    esphome_entry_id: str | None,
    action_name: str,
    service_data: dict[str, Any],
) -> tuple[bool, str]:
    """Call a custom ESPHome API action by name.

    Returns (success, error_message). The action must be present in the
    user's ESPHome proxy YAML config under ``api: actions:``.
    """
    _LOGGER.debug("Calling ESPHome action %s on entry %s", action_name, esphome_entry_id)
    if esphome_entry_id is None:
        return False, "No ESPHome config entry found for this proxy"
    try:
        esphome_entry = hass.config_entries.async_get_entry(esphome_entry_id)
        if esphome_entry is None:
            return False, "ESPHome config entry not found"
        slug = re.sub(r"[^a-z0-9]+", "_", esphome_entry.title.lower()).strip("_")
        service_name = f"{slug}_{action_name}"
        if not hass.services.has_service("esphome", service_name):
            return False, (
                f"Action 'esphome.{service_name}' not found. "
                f"Add the {action_name} action to your ESPHome proxy config."
            )
        await hass.services.async_call("esphome", service_name, service_data, blocking=True)
        _LOGGER.info("Called esphome.%s with %s", service_name, service_data)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("ESPHome service call failed: %s", exc)
        return False, str(exc)


# ── Mixin ─────────────────────────────────────────────────────────────────────

class BondedProxyMixin:
    """Mixin providing bonded-proxy pinning and repair-issue logic.

    The host class must supply:
      self.hass           : HomeAssistant
      self.address        : str
      self.device_name    : str
      self.entry_id       : str
      self.bonding_required: bool   (False → whole mixin is a no-op)
    """

    bonded_proxy: str | None = None
    last_seen_proxy: str | None = None
    last_connected_proxy: str | None = None
    bonding_required: bool = False
    _consecutive_auth_failures: int = 0

    # ── Advertisement source handling ─────────────────────────────────────────

    def proxy_track_seen(self, source: str | None) -> None:
        """Record the advertisement source; always called regardless of bonding."""
        if source:
            self.last_seen_proxy = source

    def _is_connectable_source(self, source: str | None) -> bool:
        """Return False if the source scanner is not currently online and connectable."""
        if source is None:
            return True
        try:
            from homeassistant.components.bluetooth import async_scanner_by_source
            scanner = async_scanner_by_source(self.hass, source)
            if scanner is None:
                # Scanner not currently registered — likely not reconnected yet after restart
                _LOGGER.debug(
                    "[%s] Source %s not currently registered, deferring connection",
                    self.address, source,
                )
                return False
            return getattr(scanner, "connectable", True)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _schedule_connectable_retry(self) -> None:
        """Poll until the source scanner is registered, then trigger a connection."""
        import asyncio
        hass: HomeAssistant = self.hass  # type: ignore[attr-defined]

        if getattr(self, "_connectable_retry_task", None) is not None:
            return  # already scheduled

        async def _wait_and_retry() -> None:
            try:
                for _ in range(60):  # up to 5 minutes
                    await asyncio.sleep(5)
                    from homeassistant.components.bluetooth import (
                        async_scanner_by_source,
                        async_last_service_info,
                    )
                    source = self.last_seen_proxy
                    if source and async_scanner_by_source(hass, source):
                        _LOGGER.debug(
                            "[%s] Source %s now registered — retrying connection",
                            self.address, source,
                        )
                        # Re-deliver the last known service_info to trigger connection
                        service_info = async_last_service_info(
                            hass, self.address, connectable=True  # type: ignore[attr-defined]
                        )
                        if service_info is not None:
                            self.handle_advertisement(service_info)
                        return
                    _LOGGER.debug(
                    "[%s] Source %s still not registered, retrying in 5s",
                        self.address, source,
                    )
            finally:
                self._connectable_retry_task = None

        self._connectable_retry_task = hass.async_create_task(_wait_and_retry())

    def proxy_should_connect(self, source: str | None) -> bool:
        """Return False if the source is pinned-out or triggers a repair issue."""
        _LOGGER.debug("[%s] proxy_should_connect: source=%s", self.address, source)
        if not self._is_connectable_source(source):
            _LOGGER.debug(
                "[%s] Skipping connection — source %s is passive-only",
                self.address, source,
            )
            self._schedule_connectable_retry()
            return False
        if not self.bonding_required:
            return True
        if (
            self.bonded_proxy is None
            and self.last_connected_proxy is not None
            and source is not None
            and source != self.last_connected_proxy
        ):
            _LOGGER.warning(
                "[%s] Advertisement source changed (%s → %s) with no proxy pinned. "
                "Connecting via the new proxy may invalidate the existing LTK.",
                self.address, self.last_connected_proxy, source,  # type: ignore[attr-defined]
            )
            self._raise_repair_issue(
                "proxy_switch_detected",
                {"previous_proxy": self.last_connected_proxy, "new_proxy": source or "unknown"},
            )
        if self.bonded_proxy is not None and source != self.bonded_proxy:
            _LOGGER.debug(
                "[%s] Ignoring advertisement from %s (bonded proxy: %s)",
                self.address, source, self.bonded_proxy,  # type: ignore[attr-defined]
            )
            return False
        return True

    def proxy_on_success(self, source: str | None) -> None:
        """Call after a successful session to update tracking and clear issues."""
        if not self.bonding_required:
            return
        if source:
            self.last_connected_proxy = source
        self._consecutive_auth_failures = 0
        self._clear_repair_issues()

    def proxy_on_error(self, err: BaseException) -> None:
        """Call on a failed session to update auth-failure counter and raise issues."""
        if not self.bonding_required:
            return
        if isinstance(err, PairingRequiresManualSetup):
            self._raise_repair_issue("manual_pairing_required", {"reason": str(err)})
            return
        if isinstance(err, BleakError) and is_auth_error(err):
            self._consecutive_auth_failures += 1
        elif "auth" in str(err).lower() or "encrypt" in str(err).lower():
            self._consecutive_auth_failures += 1
        else:
            self._consecutive_auth_failures = 0
        if self._consecutive_auth_failures >= _AUTH_FAILURE_THRESHOLD:
            self._raise_repair_issue(
                "manual_pairing_required",
                {"reason": f"{self._consecutive_auth_failures} consecutive auth failures"},
            )

    # ── Repair issues ─────────────────────────────────────────────────────────

    def _proxy_issue_id(self, kind: str) -> str:
        entry_id = getattr(self, "entry_id", None) or self.address  # type: ignore[attr-defined]
        return f"{entry_id}_{kind}"

    def _raise_repair_issue(self, translation_key: str, placeholders: dict) -> None:
        ir.async_create_issue(
            self.hass,  # type: ignore[attr-defined]
            DOMAIN,
            self._proxy_issue_id(translation_key),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=translation_key,
            translation_placeholders={
                "device_name": self.device_name,  # type: ignore[attr-defined]
                "address": self.address,           # type: ignore[attr-defined]
                **{k: str(v) for k, v in placeholders.items()},
            },
            learn_more_url=(
                "https://github.com/JochenFriedrich/sig_health_ble"
                "#repairing-a-stuck-bond"
            ),
        )

    def _clear_repair_issues(self) -> None:
        """Delete all proxy-related repair issues for this entry."""
        hass: HomeAssistant = self.hass  # type: ignore[attr-defined]
        ir.async_delete_issue(hass, DOMAIN, self._proxy_issue_id("manual_pairing_required"))
        ir.async_delete_issue(hass, DOMAIN, self._proxy_issue_id("proxy_switch_detected"))

    # ── Unpair ────────────────────────────────────────────────────────────────

    async def async_request_unpair(
        self, esphome_entry_id: str | None = None
    ) -> tuple[bool, str]:
        """Connect to the device and attempt to clear its bond/LTK.

        Tries native client.unpair() first (maps to BLUETOOTH_DEVICE_REQUEST_TYPE_UNPAIR
        on ESPHome proxies → esp_ble_remove_bond_device()). Falls back to the custom
        ``remove_bond`` ESPHome API action from ble_proxy_pairing if the native path
        is unsupported.
        """
        from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
        from homeassistant.components.bluetooth import async_ble_device_from_address

        hass: HomeAssistant = self.hass  # type: ignore[attr-defined]
        address: str = self.address      # type: ignore[attr-defined]
        name: str = self.device_name     # type: ignore[attr-defined]

        device = async_ble_device_from_address(hass, address, connectable=True)
        if device is None:
            return False, "Device not currently visible/connectable — make sure it is advertising"

        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device, name, max_attempts=2,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"Could not connect: {exc}"

        try:
            success, error_msg = await unpair_device(client, address)
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

        if success:
            self._clear_repair_issues()
            return True, ""

        # Native unpair failed — try the ble_proxy_pairing ESPHome action
        _LOGGER.debug("Native unpair failed (%s) — trying ESPHome remove_bond action", error_msg)
        if esphome_entry_id is None:
            esphome_entry_id = find_esphome_entry_id(hass, self.bonded_proxy or "")
        fallback_ok, fallback_err = await call_esphome_service(
            hass, esphome_entry_id, ESPHOME_UNPAIR_ACTION, {"mac_address": address}
        )
        if fallback_ok:
            self._clear_repair_issues()
        return fallback_ok, fallback_err if not fallback_ok else ""
