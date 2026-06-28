"""Unit tests for NotifyCoordinator (BPM + Glucose base class)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from bleak import BleakError

from custom_components.sig_health_ble.ble_utils import PairingRequiresManualSetup
from tests.conftest import FakeServiceInfo


# ── Concrete subclass for testing ──────────────────────────────────────────────

def _make_coordinator(hass=None, session_coro=None, entry_id="entry_abc"):
    """Build a NotifyCoordinator subclass with a controllable _do_session."""
    from custom_components.sig_health_ble.notify.coordinator import NotifyCoordinator

    class TestCoordinator(NotifyCoordinator):
        async def _do_session(self, client):
            if session_coro is not None:
                await session_coro(client)

    if hass is None:
        hass = MagicMock()
        hass.data = {}

    coord = TestCoordinator(hass, "AA:BB:CC:DD:EE:FF", "Test Device", entry_id=entry_id)
    coord.hass.async_create_task = lambda coro: asyncio.ensure_future(coro)
    return coord


# ── handle_advertisement — source tracking ─────────────────────────────────────

class TestHandleAdvertisement:
    def test_tracks_last_seen_proxy(self):
        coord = _make_coordinator()
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock):
            coord.handle_advertisement(si)
        assert coord.last_seen_proxy == "proxy_kitchen"

    def test_tracks_seen_even_when_filtered_by_pin(self):
        coord = _make_coordinator()
        coord.bonded_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_bedroom")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        assert coord.last_seen_proxy == "proxy_bedroom"
        mock_conn.assert_not_called()

    def test_schedules_connection_when_source_matches_pin(self):
        coord = _make_coordinator()
        coord.bonded_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once_with(si)

    def test_skips_when_already_connecting(self):
        coord = _make_coordinator()
        coord._connecting = True
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_schedules_connection_when_no_pin(self):
        coord = _make_coordinator()
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()


# ── _connect_and_read — success path ──────────────────────────────────────────

class TestConnectAndReadSuccess:
    @pytest.mark.asyncio
    async def test_updates_last_connected_on_success(self):
        coord = _make_coordinator()
        si = FakeServiceInfo(source="proxy_kitchen")

        async def _ok_session(client):
            pass

        with patch.object(coord, "_do_connect_and_read", new_callable=AsyncMock):
            await coord._connect_and_read(si)

        assert coord.last_connected_proxy == "proxy_kitchen"
        assert coord._consecutive_auth_failures == 0
        assert coord._connecting is False

    @pytest.mark.asyncio
    async def test_clears_connecting_flag_on_success(self):
        coord = _make_coordinator()
        si = FakeServiceInfo()
        with patch.object(coord, "_do_connect_and_read", new_callable=AsyncMock):
            await coord._connect_and_read(si)
        assert coord._connecting is False

    @pytest.mark.asyncio
    async def test_clears_connecting_flag_on_failure(self):
        coord = _make_coordinator()
        si = FakeServiceInfo()
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=BleakError("fail"),
        ):
            await coord._connect_and_read(si)
        assert coord._connecting is False


# ── _connect_and_read — error handling ────────────────────────────────────────

class TestConnectAndReadErrors:
    @pytest.mark.asyncio
    async def test_pairing_requires_manual_fires_repair(self):
        coord = _make_coordinator()
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=PairingRequiresManualSetup("timeout"),
        ), patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            await coord._connect_and_read(si)

        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "manual_pairing_required"
        )

    @pytest.mark.asyncio
    async def test_auth_error_increments_counter(self):
        coord = _make_coordinator()
        si = FakeServiceInfo()
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=BleakError("Insufficient Authentication"),
        ), patch("custom_components.sig_health_ble.proxy_mixin.ir"):
            await coord._connect_and_read(si)

        assert coord._consecutive_auth_failures == 1

    @pytest.mark.asyncio
    async def test_success_resets_auth_failure_counter(self):
        coord = _make_coordinator()
        coord._consecutive_auth_failures = 2
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_do_connect_and_read", new_callable=AsyncMock):
            await coord._connect_and_read(si)
        assert coord._consecutive_auth_failures == 0

    @pytest.mark.asyncio
    async def test_success_clears_repair_issues(self):
        coord = _make_coordinator()
        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_do_connect_and_read", new_callable=AsyncMock), \
             patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            await coord._connect_and_read(si)
        assert mock_ir.async_delete_issue.call_count == 2


# ── Proxy switch repair issue ──────────────────────────────────────────────────

class TestProxySwitchRepairIssue:
    def test_proxy_switch_fires_repair_when_unpinned(self):
        coord = _make_coordinator()
        coord.last_connected_proxy = "proxy_kitchen"

        si = FakeServiceInfo(source="proxy_bedroom")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock), \
             patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            coord.handle_advertisement(si)

        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "proxy_switch_detected"
        )

    def test_no_repair_when_source_unchanged(self):
        coord = _make_coordinator()
        coord.last_connected_proxy = "proxy_kitchen"

        si = FakeServiceInfo(source="proxy_kitchen")
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock), \
             patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            coord.handle_advertisement(si)

        mock_ir.async_create_issue.assert_not_called()
