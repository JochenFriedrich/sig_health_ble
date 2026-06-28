"""Read Device Information Service (0x180A) characteristics via GATT.

Reads Model Number String (0x2A24) and Manufacturer Name String (0x2A29)
from a connected BleakClient.  Both are optional — missing characteristics
return None gracefully.
"""
from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

DEVICE_INFORMATION_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID               = "00002a24-0000-1000-8000-00805f9b34fb"
MANUFACTURER_NAME_UUID          = "00002a29-0000-1000-8000-00805f9b34fb"


async def read_device_info(client: Any, address: str) -> tuple[str | None, str | None]:
    """Return (model_number, manufacturer_name) from the Device Information Service.

    Both values may be None if the device does not expose them.
    """
    model        = await _read_char(client, address, MODEL_NUMBER_UUID,    "Model Number")
    manufacturer = await _read_char(client, address, MANUFACTURER_NAME_UUID, "Manufacturer Name")
    return model, manufacturer


async def _read_char(
    client: Any, address: str, uuid: str, label: str
) -> str | None:
    """Read a single UTF-8 string characteristic; return None on any failure."""
    uuid_lower = uuid.lower()
    handle = None

    for svc in client.services:
        for char in svc.characteristics:
            if str(char.uuid).lower() == uuid_lower:
                handle = char.handle
                break
        if handle is not None:
            break

    if handle is None:
        _LOGGER.debug("[%s] %s characteristic not found", address, label)
        return None

    try:
        from bleak import BleakError
        data = await client.read_gatt_char(handle)
        value = bytes(data).decode("utf-8", errors="replace").strip("\x00").strip()
        _LOGGER.debug("[%s] %s = %r", address, label, value)
        return value or None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug("[%s] Could not read %s: %s", address, label, exc)
        return None
