"""Unit tests for ble_utils.py — ensure_paired and unpair_device."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError

from custom_components.sig_health_ble.ble_utils import (
    ensure_paired,
    unpair_device,
    is_auth_error,
    PairingRequiresManualSetup,
)


# ── is_auth_error ──────────────────────────────────────────────────────────────

class TestIsAuthError:
    def test_insufficient_authentication(self):
        assert is_auth_error(BleakError("Insufficient Authentication"))

    def test_insufficient_encryption(self):
        assert is_auth_error(BleakError("Insufficient Encryption for this link"))

    def test_error_5(self):
        assert is_auth_error(BleakError("GATT error=5 on handle 0x001a"))

    def test_error_8(self):
        assert is_auth_error(BleakError("error=8"))

    def test_error_15(self):
        assert is_auth_error(BleakError("error=15 (0x0F)"))

    def test_generic_error_not_auth(self):
        assert not is_auth_error(BleakError("Connection failed"))

    def test_gatt_error_133_not_auth(self):
        assert not is_auth_error(BleakError("GATT error=133"))


# ── ensure_paired ──────────────────────────────────────────────────────────────

class TestEnsurePaired:
    @pytest.mark.asyncio
    async def test_success_logs_info(self):
        client = MagicMock()
        client.pair = AsyncMock(return_value=None)
        # Should complete without raising
        await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=5.0)
        client.pair.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_implemented_silently_continues(self):
        client = MagicMock()
        client.pair = AsyncMock(side_effect=NotImplementedError)
        # Must not raise
        await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=5.0)

    @pytest.mark.asyncio
    async def test_timeout_raises_pairing_requires_manual_setup(self):
        client = MagicMock()

        async def _slow_pair():
            await asyncio.sleep(100)

        client.pair = _slow_pair
        with pytest.raises(PairingRequiresManualSetup):
            await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=0.01)

    @pytest.mark.asyncio
    async def test_already_paired_bleak_error_silently_continues(self):
        client = MagicMock()
        client.pair = AsyncMock(side_effect=BleakError("Already paired"))
        await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=5.0)

    @pytest.mark.asyncio
    async def test_auth_error_raises_pairing_requires_manual_setup(self):
        """error=5 / error=8 during pair() → stuck passkey heuristic → raises."""
        client = MagicMock()
        client.pair = AsyncMock(side_effect=BleakError("GATT error=5"))
        with pytest.raises(PairingRequiresManualSetup):
            await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=5.0)

    @pytest.mark.asyncio
    async def test_generic_bleak_error_does_not_raise(self):
        """A non-auth BleakError from pair() logs a warning but does not raise."""
        client = MagicMock()
        client.pair = AsyncMock(side_effect=BleakError("Random connection error"))
        # Should complete without raising PairingRequiresManualSetup
        await ensure_paired(client, "AA:BB:CC:DD:EE:FF", pair_timeout=5.0)


# ── unpair_device ──────────────────────────────────────────────────────────────

class TestUnpairDevice:
    @pytest.mark.asyncio
    async def test_success(self):
        client = MagicMock()
        client.unpair = AsyncMock(return_value=None)
        success, msg = await unpair_device(client, "AA:BB:CC:DD:EE:FF")
        assert success is True
        assert msg == ""
        client.unpair.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_implemented_returns_false(self):
        client = MagicMock()
        client.unpair = AsyncMock(side_effect=NotImplementedError)
        success, msg = await unpair_device(client, "AA:BB:CC:DD:EE:FF")
        assert success is False
        assert "not supported" in msg.lower()

    @pytest.mark.asyncio
    async def test_missing_unpair_method_returns_false(self):
        client = MagicMock(spec=[])  # no unpair attribute
        success, msg = await unpair_device(client, "AA:BB:CC:DD:EE:FF")
        assert success is False
        assert "not implemented" in msg.lower()

    @pytest.mark.asyncio
    async def test_bleak_error_returns_false(self):
        client = MagicMock()
        client.unpair = AsyncMock(side_effect=BleakError("Failed to remove bond"))
        success, msg = await unpair_device(client, "AA:BB:CC:DD:EE:FF")
        assert success is False
        assert "Failed to remove bond" in msg
