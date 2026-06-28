"""Config flow for SIG Health BLE integration.
Setup flow:
  Step 1: Choose device type (Scale / BPM / Glucose)
  Step 2: Pick from discovered BLE devices or enter MAC manually
  Step 3: Confirm
ReconfigureFlow (BPM + Glucose):
  Step 1: Select bonded proxy from discovered sources or enter manually
  Step 2: Optionally unpair the device from that proxy
  Step 3: Optionally trigger re-pairing via ble_proxy_pairing actions
Options flow (scale only): UDS consent + gating settings.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import (
    DOMAIN,
    CONF_DEVICE_TYPE,
    CONF_BONDED_PROXY,
    CONF_BONDED_PROXY_ENTRY_ID,
    DEVICE_TYPE_SCALE,
    DEVICE_TYPE_BPM,
    DEVICE_TYPE_GLUCOSE,
    CONF_TIME_WINDOW_ENABLED,
    CONF_TIME_WINDOW_MINUTES,
    CONF_MAX_HISTORY,
    _DEFAULT_TIME_WINDOW_ENABLED,
    _DEFAULT_TIME_WINDOW_MINUTES,
    _DEFAULT_MAX_HISTORY,
)
from .devices.bpm.const     import BP_SERVICE_UUID
from .devices.glucose.const import GLUCOSE_SERVICE_UUID
from .devices.scale.const   import (
    WEIGHT_SCALE_SERVICE_UUID, BODY_COMPOSITION_SERVICE_UUID,
    CONF_SCALE_MODEL,
    UCP_USER_INDEX_UNKNOWN, UCP_DEFAULT_CONSENT_CODE,
)
from .proxy_mixin import (
    find_esphome_entry_id,
    call_esphome_service,
)

_LOGGER = logging.getLogger(__name__)

# Options keys (scale)
CONF_UDS_USER_INDEX      = "uds_user_index"
CONF_UDS_CONSENT_CODE    = "uds_consent_code"
CONF_UDS_AUTO_REGISTER   = "uds_auto_register"
CONF_COOLDOWN_MINUTES    = "cooldown_minutes"
CONF_REQUIRE_CONNECTABLE = "require_connectable"

_DEFAULT_COOLDOWN = 30

_TRIGGER_UUIDS = {
    DEVICE_TYPE_BPM:     {BP_SERVICE_UUID},
    DEVICE_TYPE_GLUCOSE: {GLUCOSE_SERVICE_UUID},
    DEVICE_TYPE_SCALE:   {WEIGHT_SCALE_SERVICE_UUID, BODY_COMPOSITION_SERVICE_UUID},
}

_DEVICE_TYPE_LABELS = {
    DEVICE_TYPE_BPM:     "Blood Pressure Monitor",
    DEVICE_TYPE_GLUCOSE: "Glucose Meter",
    DEVICE_TYPE_SCALE:   "Weight Scale",
}

_NO_PROXY = "__none__"


class SigHealthBleConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._device_type: str | None = None
        self._discovered_devices: dict[str, str] = {}  # address → name
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    # ── Bluetooth auto-discovery ───────────────────────────────────────────────

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        uuids = set(discovery_info.service_uuids or [])
        if BP_SERVICE_UUID in uuids:
            self._device_type = DEVICE_TYPE_BPM
        elif GLUCOSE_SERVICE_UUID in uuids:
            self._device_type = DEVICE_TYPE_GLUCOSE
        elif uuids & {WEIGHT_SCALE_SERVICE_UUID, BODY_COMPOSITION_SERVICE_UUID}:
            self._device_type = DEVICE_TYPE_SCALE
        else:
            return self.async_abort(reason="not_supported")
        self.context["title_placeholders"] = {
            "name": discovery_info.name or discovery_info.address
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        info = self._discovery_info
        if user_input is not None:
            return self._create_entry(info.name or info.address, info.address)
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": info.name or "Unknown",
                "address": info.address,
                "device_type": _DEVICE_TYPE_LABELS.get(self._device_type, ""),
            },
        )

    # ── Manual setup ───────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._device_type = user_input[CONF_DEVICE_TYPE]
            return await self.async_step_select_device()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_TYPE): vol.In(_DEVICE_TYPE_LABELS),
            }),
        )

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._device_type is not None
        trigger_uuids = _TRIGGER_UUIDS[self._device_type]
        current_addresses = self._async_current_ids()
        for service_info in async_discovered_service_info(self.hass, connectable=True):
            address = service_info.address
            if address in current_addresses:
                continue
            if trigger_uuids & set(service_info.service_uuids or []):
                self._discovered_devices[address] = service_info.name or address
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address.upper(), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            name = self._discovered_devices.get(address, address)
            return self._create_entry(name, address)
        device_options = {
            addr: f"{name} ({addr})"
            for addr, name in self._discovered_devices.items()
        }
        schema = vol.Schema(
            {vol.Required(CONF_ADDRESS): vol.In(device_options)}
            if device_options
            else {vol.Required(CONF_ADDRESS): str}
        )
        return self.async_show_form(
            step_id="select_device",
            data_schema=schema,
            description_placeholders={"count": str(len(device_options))},
        )

    # ── Entry creation ─────────────────────────────────────────────────────────

    def _create_entry(self, title: str, address: str) -> ConfigFlowResult:
        return self.async_create_entry(
            title=title,
            data={
                CONF_ADDRESS: address,
                CONF_DEVICE_TYPE: self._device_type,
            },
        )

    # ── Reconfigure flow (BPM + Glucose: proxy pinning) ───────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        device_type = entry.data.get(CONF_DEVICE_TYPE) if entry else None
        if device_type not in (DEVICE_TYPE_BPM, DEVICE_TYPE_GLUCOSE):
            coordinator = self.hass.data.get(DOMAIN, {}).get(self.context["entry_id"])
            if not (device_type == DEVICE_TYPE_SCALE
                    and getattr(coordinator, "bonding_required", False)):
                return self.async_abort(reason="not_supported")
        return await self.async_step_select_proxy()

    async def async_step_select_proxy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick the bonded ESPHome proxy (or disable pinning)."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        address = entry.data[CONF_ADDRESS] if entry else ""
        known_sources = _collect_proxy_sources(self.hass, address)

        if user_input is not None:
            selected = user_input[CONF_BONDED_PROXY]
            new_data = dict(entry.data)
            if selected == _NO_PROXY:
                new_data.pop(CONF_BONDED_PROXY, None)
                new_data.pop(CONF_BONDED_PROXY_ENTRY_ID, None)
                esphome_entry_id = None
            else:
                esphome_entry_id = find_esphome_entry_id(self.hass, selected)
                new_data[CONF_BONDED_PROXY] = selected
                if esphome_entry_id:
                    new_data[CONF_BONDED_PROXY_ENTRY_ID] = esphome_entry_id
                else:
                    new_data.pop(CONF_BONDED_PROXY_ENTRY_ID, None)

            self.hass.config_entries.async_update_entry(entry, data=new_data)
            _apply_bonded_proxy_to_coordinator(
                self.hass, entry.entry_id, new_data.get(CONF_BONDED_PROXY)
            )

            if selected == _NO_PROXY:
                return self.async_abort(reason="reconfigure_successful")

            self.context["_selected_proxy"]    = selected
            self.context["_esphome_entry_id"]  = esphome_entry_id
            self.context["_device_address"]    = address
            return await self.async_step_unpair_proxy()

        # Build proxy selector
        proxy_options: dict[str, str] = {_NO_PROXY: "No pinning (allow any proxy)"}
        for src in known_sources:
            esphome_entry_id = find_esphome_entry_id(self.hass, src)
            if esphome_entry_id:
                esphome_entry = self.hass.config_entries.async_get_entry(esphome_entry_id)
                label = f"{esphome_entry.title} ({src})" if esphome_entry else src
            else:
                label = src
            proxy_options[src] = label

        current_proxy = entry.data.get(CONF_BONDED_PROXY, _NO_PROXY) if entry else _NO_PROXY
        return self.async_show_form(
            step_id="select_proxy",
            data_schema=vol.Schema({
                vol.Required(CONF_BONDED_PROXY, default=current_proxy): vol.In(proxy_options),
            }),
            description_placeholders={
                "address": address,
                "device_type": _DEVICE_TYPE_LABELS.get(
                    entry.data.get(CONF_DEVICE_TYPE, "") if entry else "", ""
                ),
            },
        )

    async def async_step_unpair_proxy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to unpair the device, clearing its bond/LTK on the proxy."""
        esphome_entry_id = self.context.get("_esphome_entry_id")
        device_address   = self.context.get("_device_address", "")
        proxy_source     = self.context.get("_selected_proxy", "")

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("do_unpair"):
                coordinator = self.hass.data.get(DOMAIN, {}).get(self.context["entry_id"])
                if coordinator is not None and hasattr(coordinator, "async_request_unpair"):
                    success, error_msg = await coordinator.async_request_unpair(esphome_entry_id)
                else:
                    success, error_msg = False, "Coordinator unavailable"
                if not success:
                    errors["base"] = "unpair_failed"
                    self.context["_unpair_error"] = error_msg
                else:
                    return await self.async_step_pair_proxy()
            else:
                return await self.async_step_pair_proxy()

        return self.async_show_form(
            step_id="unpair_proxy",
            data_schema=vol.Schema({
                vol.Required("do_unpair", default=False): bool,
            }),
            errors=errors,
            description_placeholders={
                "address": device_address,
                "proxy": proxy_source,
                "unpair_error": self.context.get("_unpair_error", ""),
            },
        )

    async def async_step_pair_proxy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pairing wizard: surface ble_proxy_pairing actions to the user."""
        esphome_entry_id = self.context.get("_esphome_entry_id")
        device_address   = self.context.get("_device_address", "")
        errors: dict[str, str] = {}

        if user_input is not None:
            method = user_input.get("pairing_method", "skip")

            # Always try to trigger encryption first
            await call_esphome_service(
                self.hass, esphome_entry_id,
                "request_encryption", {"mac_address": device_address},
            )
            await asyncio.sleep(2)

            if method == "numeric_comparison":
                success, error_msg = await call_esphome_service(
                    self.hass, esphome_entry_id,
                    "numeric_comparison_reply",
                    {"mac_address": device_address, "accept": True},
                )
                if not success:
                    errors["base"] = "pairing_action_failed"
                    self.context["_pair_error"] = error_msg
                else:
                    return self.async_abort(reason="reconfigure_successful")

            elif method == "passkey":
                passkey = user_input.get("passkey")
                if not passkey:
                    errors["passkey"] = "passkey_required"
                elif not passkey.isdigit():
                    errors["passkey"] = "passkey_not_numeric"
                else:
                    success, error_msg = await call_esphome_service(
                        self.hass, esphome_entry_id,
                        "passkey_reply",
                        {"mac_address": device_address, "passkey": int(passkey)},
                    )
                    if not success:
                        errors["base"] = "pairing_action_failed"
                        self.context["_pair_error"] = error_msg
                    else:
                        return self.async_abort(reason="reconfigure_successful")

            else:
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="pair_proxy",
            data_schema=vol.Schema({
                vol.Required("pairing_method", default="skip"): vol.In({
                    "skip": "Skip — pairing not needed or already done",
                    "numeric_comparison": "Accept numeric comparison (Just Works / passkey display)",
                    "passkey": "Enter a passkey shown on the device",
                }),
                vol.Optional("passkey"): vol.All(
                    str, vol.Length(min=1, max=6),
                ),
            }),
            errors=errors,
            description_placeholders={
                "address": device_address,
                "pair_error": self.context.get("_pair_error", ""),
            },
        )

    # ── Options flow routing ───────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        device_type = config_entry.data.get(CONF_DEVICE_TYPE)
        if device_type == DEVICE_TYPE_SCALE:
            return ScaleOptionsFlow()
        if device_type == DEVICE_TYPE_BPM:
            return BPMOptionsFlow()
        if device_type == DEVICE_TYPE_GLUCOSE:
            return GlucoseOptionsFlow()
        return NoOptionsFlow()


# ── Options flows ──────────────────────────────────────────────────────────────

class NoOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: Any = None) -> ConfigFlowResult:
        return self.async_abort(reason="no_options")


class ScaleOptionsFlow(OptionsFlow):
    """Options flow for scale: UDS consent + cooldown settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not (0 <= user_input[CONF_UDS_USER_INDEX] <= 255):
                errors[CONF_UDS_USER_INDEX] = "user_index_out_of_range"
            if not (0 <= user_input[CONF_UDS_CONSENT_CODE] <= 65535):
                errors[CONF_UDS_CONSENT_CODE] = "consent_code_out_of_range"
            if not (1 <= user_input[CONF_COOLDOWN_MINUTES] <= 1440):
                errors[CONF_COOLDOWN_MINUTES] = "cooldown_out_of_range"
            if not errors:
                _apply_options_to_coordinator(
                    self.hass, self.config_entry.entry_id, user_input
                )
                return self.async_create_entry(title="", data=user_input)
        schema = vol.Schema({
            vol.Required(
                CONF_UDS_USER_INDEX,
                default=self.config_entry.options.get(CONF_UDS_USER_INDEX, UCP_USER_INDEX_UNKNOWN),
            ): vol.All(int, vol.Range(min=0, max=255)),
            vol.Required(
                CONF_UDS_CONSENT_CODE,
                default=self.config_entry.options.get(CONF_UDS_CONSENT_CODE, UCP_DEFAULT_CONSENT_CODE),
            ): vol.All(int, vol.Range(min=0, max=65535)),
            vol.Required(
                CONF_UDS_AUTO_REGISTER,
                default=self.config_entry.options.get(CONF_UDS_AUTO_REGISTER, False),
            ): bool,
            vol.Required(
                CONF_COOLDOWN_MINUTES,
                default=self.config_entry.options.get(CONF_COOLDOWN_MINUTES, _DEFAULT_COOLDOWN),
            ): vol.All(int, vol.Range(min=1, max=1440)),
            vol.Required(
                CONF_REQUIRE_CONNECTABLE,
                default=self.config_entry.options.get(CONF_REQUIRE_CONNECTABLE, True),
            ): bool,
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)



def _measurement_options_schema(options: dict) -> vol.Schema:
    """Shared schema for BPM and glucose options."""
    return vol.Schema({
        vol.Required(
            CONF_TIME_WINDOW_ENABLED,
            default=options.get(CONF_TIME_WINDOW_ENABLED, _DEFAULT_TIME_WINDOW_ENABLED),
        ): bool,
        vol.Required(
            CONF_TIME_WINDOW_MINUTES,
            default=options.get(CONF_TIME_WINDOW_MINUTES, _DEFAULT_TIME_WINDOW_MINUTES),
        ): vol.All(int, vol.Range(min=1, max=60)),
        vol.Required(
            CONF_MAX_HISTORY,
            default=options.get(CONF_MAX_HISTORY, _DEFAULT_MAX_HISTORY),
        ): vol.All(int, vol.Range(min=1, max=500)),
    })


class BPMOptionsFlow(OptionsFlow):
    """Options flow for BPM: time window + history settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_measurement_options_schema(self.config_entry.options),
        )


class GlucoseOptionsFlow(OptionsFlow):
    """Options flow for glucose: time window + history settings."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_measurement_options_schema(self.config_entry.options),
        )


# ── Module-level helpers ───────────────────────────────────────────────────────

def _collect_proxy_sources(hass: Any, address: str) -> list[str]:
    """Return unique service_info.source values seen for this BLE address."""
    sources: set[str] = set()
    try:
        for si in async_discovered_service_info(hass, connectable=True):
            if si.address.upper() == address.upper():
                src = getattr(si, "source", None)
                if src:
                    sources.add(src)
    except Exception:  # noqa: BLE001
        pass
    return sorted(sources)


def _apply_bonded_proxy_to_coordinator(
    hass: Any, entry_id: str, bonded_proxy: str | None
) -> None:
    """Push updated bonded_proxy into the live coordinator."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is not None:
        coordinator.bonded_proxy = bonded_proxy
        _LOGGER.debug("[%s] Bonded proxy set to: %s", entry_id, bonded_proxy)


def _apply_options_to_coordinator(hass: Any, entry_id: str, options: dict) -> None:
    """Push updated scale options into a live ScaleCoordinator."""
    from datetime import timedelta
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        return
    coordinator.uds_user_index      = options.get(CONF_UDS_USER_INDEX,      UCP_USER_INDEX_UNKNOWN)
    coordinator.uds_consent_code    = options.get(CONF_UDS_CONSENT_CODE,    UCP_DEFAULT_CONSENT_CODE)
    coordinator.uds_auto_register   = options.get(CONF_UDS_AUTO_REGISTER,   False)
    coordinator.require_connectable = options.get(CONF_REQUIRE_CONNECTABLE, True)
    coordinator.cooldown_after_measurement = timedelta(
        minutes=options.get(CONF_COOLDOWN_MINUTES, _DEFAULT_COOLDOWN)
    )
