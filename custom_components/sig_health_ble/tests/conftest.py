"""Shared pytest fixtures for sig_health_ble tests.

Run all tests with:  pytest tests/ -v
Run one file with:   pytest tests/test_parser_bpm.py -v
"""
from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest


# ── Fake BLE service info ──────────────────────────────────────────────────────

@dataclass
class FakeServiceInfo:
    """Minimal BluetoothServiceInfoBleak stand-in."""
    address: str = "AA:BB:CC:DD:EE:FF"
    name: str = "Test Device"
    source: str = "esphome_proxy_kitchen"
    connectable: bool = True
    service_uuids: list[str] = field(default_factory=list)
    service_data: dict[str, bytes] = field(default_factory=dict)
    device: Any = None

    def __post_init__(self):
        if self.device is None:
            self.device = MagicMock()
            self.device.address = self.address


@pytest.fixture
def fake_service_info():
    return FakeServiceInfo()


# ── Fake GATT characteristic / service tree ────────────────────────────────────

@dataclass
class FakeChar:
    uuid: str
    handle: int
    properties: list[str] = field(default_factory=lambda: ["notify", "indicate"])


@dataclass
class FakeService:
    uuid: str
    characteristics: list[FakeChar] = field(default_factory=list)


def make_char(uuid: str, handle: int, properties: list[str] | None = None) -> FakeChar:
    return FakeChar(uuid=uuid, handle=handle,
                    properties=properties or ["notify", "indicate"])


# ── Fake BleakClient ───────────────────────────────────────────────────────────

class FakeBleakClient:
    """Minimal async BleakClient stand-in for coordinator tests."""

    def __init__(self, services: list[FakeService] | None = None):
        self.services = services or []
        self._notify_handlers: dict[int, Any] = {}
        self._written: list[tuple[int, bytes]] = []
        self._paired = False
        self._disconnected_callback = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def connect(self, **kwargs):
        pass

    async def disconnect(self):
        if self._disconnected_callback:
            self._disconnected_callback(self)

    async def pair(self):
        self._paired = True

    async def unpair(self):
        self._paired = False

    async def start_notify(self, handle: int, callback):
        self._notify_handlers[handle] = callback

    async def stop_notify(self, handle: int):
        self._notify_handlers.pop(handle, None)

    async def write_gatt_char(self, handle: int, data: bytes, response: bool = False):
        self._written.append((handle, data))

    async def read_gatt_char(self, handle: int) -> bytes:
        return b""

    def fire_notify(self, handle: int, data: bytes):
        """Helper: simulate the device sending a notification."""
        if handle in self._notify_handlers:
            self._notify_handlers[handle](handle, bytearray(data))


@pytest.fixture
def fake_client():
    return FakeBleakClient()


# ── Minimal HomeAssistant stub ─────────────────────────────────────────────────

class FakeIssueRegistry:
    def __init__(self):
        self.issues: dict[str, Any] = {}

    def async_create_issue(self, hass, domain, issue_id, **kwargs):
        self.issues[issue_id] = kwargs

    def async_delete_issue(self, hass, domain, issue_id):
        self.issues.pop(issue_id, None)


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.data = {}
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def fake_issue_registry():
    return FakeIssueRegistry()
