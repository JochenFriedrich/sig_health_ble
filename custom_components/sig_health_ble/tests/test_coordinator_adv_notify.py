"""Unit tests for AdvNotifyCoordinator (Scale base class)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError

from custom_components.sig_health_ble.ble_utils import PairingRequiresManualSetup
from custom_components.sig_health_ble.adv_notify.coordinator import (
    AdvNotifyCoordinator,
    COOLDOWN_AFTER_MEASUREMENT,
    COOLDOWN_AFTER_FAILURE,
)
from tests.conftest import FakeServiceInfo


# ── Test subclass ──────────────────────────────────────────────────────────────

def _make_coordinator(
    bonding_required: bool = False,
    measurement_ready: bool = True,
    session_raises=None,
    entry_id: str = "entry_scale",
):
    hass = MagicMock()
    hass.data = {}
    hass.async_create_task = lambda coro: asyncio.ensure_future(coro)

    class TestScaleCoordinator(AdvNotifyCoordinator):
        def is_measurement_ready(self, service_info):
            return measurement_ready

        async def _do_session(self, client):
            if session_raises is not None:
                raise session_raises
            self._last_measurement = object()  # sentinel

    coord = TestScaleCoordinator(hass, "AA:BB:CC:DD:EE:FF", "Test Scale", entry_id=entry_id)
    coord.bonding_required = bonding_required
    return coord


# ── Advertisement guards ───────────────────────────────────────────────────────

class TestAdvertisementGuards:
    def test_payload_gate_blocks_connection(self):
        coord = _make_coordinator(measurement_ready=False)
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_payload_gate_allows_connection(self):
        coord = _make_coordinator(measurement_ready=True)
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()

    def test_not_connectable_blocks_when_require_connectable(self):
        coord = _make_coordinator()
        coord.require_connectable = True
        si = FakeServiceInfo(connectable=False)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_not_connectable_allowed_when_flag_disabled(self):
        coord = _make_coordinator()
        coord.require_connectable = False
        si = FakeServiceInfo(connectable=False)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()

    def test_already_connecting_skips(self):
        coord = _make_coordinator()
        coord._connecting = True
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()


# ── Post-read cooldown ─────────────────────────────────────────────────────────

class TestPostReadCooldown:
    def test_blocks_during_cooldown(self):
        coord = _make_coordinator()
        coord._last_successful_read = datetime.now()  # just finished a read
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_allows_after_cooldown_expires(self):
        coord = _make_coordinator()
        coord._last_successful_read = datetime.now() - COOLDOWN_AFTER_MEASUREMENT - timedelta(seconds=1)
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()

    def test_configurable_cooldown_respected(self):
        coord = _make_coordinator()
        coord.cooldown_after_measurement = timedelta(minutes=60)
        coord._last_successful_read = datetime.now() - timedelta(minutes=45)
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()


# ── Post-failure cooldown ──────────────────────────────────────────────────────

class TestPostFailureCooldown:
    def test_blocks_during_failure_cooldown(self):
        coord = _make_coordinator()
        coord._last_failed_attempt = datetime.now()
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_allows_after_failure_cooldown_expires(self):
        coord = _make_coordinator()
        coord._last_failed_attempt = datetime.now() - COOLDOWN_AFTER_FAILURE - timedelta(seconds=1)
        si = FakeServiceInfo(connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()


# ── _connect_and_read state management ────────────────────────────────────────

class TestConnectAndReadState:
    @pytest.mark.asyncio
    async def test_sets_last_successful_read_on_success(self):
        coord = _make_coordinator()
        si = FakeServiceInfo()
        with patch.object(coord, "_do_connect_and_read", new_callable=AsyncMock):
            await coord._connect_and_read(si)
        assert coord._last_successful_read is not None
        assert coord._last_failed_attempt is None

    @pytest.mark.asyncio
    async def test_sets_last_failed_attempt_on_failure(self):
        coord = _make_coordinator()
        si = FakeServiceInfo()
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=BleakError("failed"),
        ):
            await coord._connect_and_read(si)
        assert coord._last_failed_attempt is not None
        assert coord._last_successful_read is None

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
            side_effect=Exception("boom"),
        ):
            await coord._connect_and_read(si)
        assert coord._connecting is False


# ── Bonded proxy pinning (bonding_required=True) ───────────────────────────────

class TestBondedProxyPinning:
    def test_proxy_source_tracked_always(self):
        coord = _make_coordinator(bonding_required=True)
        coord.bonded_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_bedroom", connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock):
            coord.handle_advertisement(si)
        assert coord.last_seen_proxy == "proxy_bedroom"

    def test_mismatched_proxy_blocks_connection_when_bonding_required(self):
        coord = _make_coordinator(bonding_required=True)
        coord.bonded_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_bedroom", connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_not_called()

    def test_matching_proxy_allows_connection_when_bonding_required(self):
        coord = _make_coordinator(bonding_required=True)
        coord.bonded_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_kitchen", connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock) as mock_conn:
            coord.handle_advertisement(si)
        mock_conn.assert_called_once()

    def test_proxy_switch_fires_repair_when_bonding_required_and_unpinned(self):
        coord = _make_coordinator(bonding_required=True)
        coord.last_connected_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_bedroom", connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock), \
             patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            coord.handle_advertisement(si)
        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "proxy_switch_detected"
        )

    def test_proxy_switch_ignored_when_bonding_not_required(self):
        coord = _make_coordinator(bonding_required=False)
        coord.last_connected_proxy = "proxy_kitchen"
        si = FakeServiceInfo(source="proxy_bedroom", connectable=True)
        with patch.object(coord, "_connect_and_read", new_callable=AsyncMock), \
             patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            coord.handle_advertisement(si)
        mock_ir.async_create_issue.assert_not_called()


# ── PairingRequiresManualSetup error handling ──────────────────────────────────

class TestPairingRequiresManualSetup:
    @pytest.mark.asyncio
    async def test_fires_repair_issue(self):
        coord = _make_coordinator(bonding_required=True)
        si = FakeServiceInfo()
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=PairingRequiresManualSetup("timeout during pair()"),
        ), patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            await coord._connect_and_read(si)

        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "manual_pairing_required"
        )

    @pytest.mark.asyncio
    async def test_does_not_fire_repair_when_bonding_not_required(self):
        coord = _make_coordinator(bonding_required=False)
        si = FakeServiceInfo()
        with patch.object(
            coord, "_do_connect_and_read",
            new_callable=AsyncMock,
            side_effect=PairingRequiresManualSetup("timeout"),
        ), patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            await coord._connect_and_read(si)
        mock_ir.async_create_issue.assert_not_called()
