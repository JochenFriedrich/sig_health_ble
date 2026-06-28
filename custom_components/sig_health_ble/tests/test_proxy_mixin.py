"""Unit tests for BondedProxyMixin — proxy pinning and repair-issue logic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from bleak import BleakError

from custom_components.sig_health_ble.ble_utils import PairingRequiresManualSetup
from custom_components.sig_health_ble.proxy_mixin import BondedProxyMixin, _AUTH_FAILURE_THRESHOLD


# ── Test host class ────────────────────────────────────────────────────────────

class FakeCoordinator(BondedProxyMixin):
    """Minimal host that satisfies the mixin's attribute requirements."""

    def __init__(self, bonding_required: bool = True):
        self.hass = MagicMock()
        self.address = "AA:BB:CC:DD:EE:FF"
        self.device_name = "Test Device"
        self.entry_id = "test_entry_id"
        self.bonding_required = bonding_required
        self.bonded_proxy = None
        self.last_seen_proxy = None
        self.last_connected_proxy = None
        self._consecutive_auth_failures = 0


# ── proxy_track_seen ───────────────────────────────────────────────────────────

class TestProxyTrackSeen:
    def test_records_source(self):
        c = FakeCoordinator()
        c.proxy_track_seen("proxy_kitchen")
        assert c.last_seen_proxy == "proxy_kitchen"

    def test_ignores_none(self):
        c = FakeCoordinator()
        c.proxy_track_seen(None)
        assert c.last_seen_proxy is None

    def test_updates_on_each_call(self):
        c = FakeCoordinator()
        c.proxy_track_seen("proxy_a")
        c.proxy_track_seen("proxy_b")
        assert c.last_seen_proxy == "proxy_b"

    def test_no_op_when_bonding_not_required(self):
        """Track should still work even when bonding_required is False."""
        c = FakeCoordinator(bonding_required=False)
        c.proxy_track_seen("proxy_a")
        assert c.last_seen_proxy == "proxy_a"


# ── proxy_should_connect ───────────────────────────────────────────────────────

class TestProxyShouldConnect:
    def test_always_true_when_bonding_not_required(self):
        c = FakeCoordinator(bonding_required=False)
        c.bonded_proxy = "proxy_kitchen"
        # Even with a mismatched source, should return True when not bonding
        assert c.proxy_should_connect("proxy_other") is True

    def test_true_when_no_pin_no_previous(self):
        c = FakeCoordinator()
        assert c.proxy_should_connect("proxy_kitchen") is True

    def test_true_when_source_matches_pin(self):
        c = FakeCoordinator()
        c.bonded_proxy = "proxy_kitchen"
        assert c.proxy_should_connect("proxy_kitchen") is True

    def test_false_when_source_mismatches_pin(self):
        c = FakeCoordinator()
        c.bonded_proxy = "proxy_kitchen"
        assert c.proxy_should_connect("proxy_bedroom") is False

    def test_false_for_none_source_with_pin(self):
        c = FakeCoordinator()
        c.bonded_proxy = "proxy_kitchen"
        assert c.proxy_should_connect(None) is False

    def test_true_for_none_source_without_pin(self):
        c = FakeCoordinator()
        assert c.proxy_should_connect(None) is True

    def test_raises_repair_issue_on_proxy_switch(self):
        c = FakeCoordinator()
        c.last_connected_proxy = "proxy_kitchen"

        with patch(
            "custom_components.sig_health_ble.proxy_mixin.ir"
        ) as mock_ir:
            result = c.proxy_should_connect("proxy_bedroom")

        assert result is True  # no pin, so still connects
        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args
        assert call_kwargs[1]["translation_key"] == "proxy_switch_detected"

    def test_no_repair_issue_when_source_unchanged(self):
        c = FakeCoordinator()
        c.last_connected_proxy = "proxy_kitchen"

        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_should_connect("proxy_kitchen")

        mock_ir.async_create_issue.assert_not_called()

    def test_no_repair_issue_when_proxy_pinned(self):
        """If pinned to a different proxy, just drop the ad — don't raise a repair."""
        c = FakeCoordinator()
        c.bonded_proxy = "proxy_kitchen"
        c.last_connected_proxy = "proxy_kitchen"

        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            result = c.proxy_should_connect("proxy_bedroom")

        assert result is False
        mock_ir.async_create_issue.assert_not_called()


# ── proxy_on_success ───────────────────────────────────────────────────────────

class TestProxyOnSuccess:
    def test_updates_last_connected(self):
        c = FakeCoordinator()
        c.proxy_on_success("proxy_kitchen")
        assert c.last_connected_proxy == "proxy_kitchen"

    def test_resets_auth_failure_counter(self):
        c = FakeCoordinator()
        c._consecutive_auth_failures = 3
        c.proxy_on_success("proxy_kitchen")
        assert c._consecutive_auth_failures == 0

    def test_clears_both_repair_issues(self):
        c = FakeCoordinator()
        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_on_success("proxy_kitchen")
        assert mock_ir.async_delete_issue.call_count == 2

    def test_no_op_when_bonding_not_required(self):
        c = FakeCoordinator(bonding_required=False)
        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_on_success("proxy_kitchen")
        mock_ir.async_delete_issue.assert_not_called()
        # last_connected not updated when bonding not required
        assert c.last_connected_proxy is None


# ── proxy_on_error ─────────────────────────────────────────────────────────────

class TestProxyOnError:
    def test_pairing_requires_manual_setup_raises_issue_immediately(self):
        c = FakeCoordinator()
        err = PairingRequiresManualSetup("Timed out waiting for passkey")
        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_on_error(err)
        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "manual_pairing_required"
        )

    def test_auth_error_increments_counter(self):
        c = FakeCoordinator()
        err = BleakError("Insufficient Authentication")
        with patch("custom_components.sig_health_ble.proxy_mixin.ir"):
            c.proxy_on_error(err)
        assert c._consecutive_auth_failures == 1

    def test_auth_error_at_threshold_raises_issue(self):
        c = FakeCoordinator()
        c._consecutive_auth_failures = _AUTH_FAILURE_THRESHOLD - 1
        err = BleakError("Insufficient Authentication")
        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_on_error(err)
        mock_ir.async_create_issue.assert_called_once()
        assert (
            mock_ir.async_create_issue.call_args[1]["translation_key"]
            == "manual_pairing_required"
        )

    def test_non_auth_error_resets_counter(self):
        c = FakeCoordinator()
        c._consecutive_auth_failures = 2
        with patch("custom_components.sig_health_ble.proxy_mixin.ir"):
            c.proxy_on_error(Exception("Random timeout"))
        assert c._consecutive_auth_failures == 0

    def test_no_op_when_bonding_not_required(self):
        c = FakeCoordinator(bonding_required=False)
        err = PairingRequiresManualSetup("stuck")
        with patch("custom_components.sig_health_ble.proxy_mixin.ir") as mock_ir:
            c.proxy_on_error(err)
        mock_ir.async_create_issue.assert_not_called()

    def test_auth_string_in_generic_exception_increments_counter(self):
        c = FakeCoordinator()
        with patch("custom_components.sig_health_ble.proxy_mixin.ir"):
            c.proxy_on_error(Exception("auth failure somewhere"))
        assert c._consecutive_auth_failures == 1


# ── _proxy_issue_id ────────────────────────────────────────────────────────────

class TestProxyIssueId:
    def test_uses_entry_id(self):
        c = FakeCoordinator()
        assert c._proxy_issue_id("manual_pairing_required") == (
            "test_entry_id_manual_pairing_required"
        )

    def test_falls_back_to_address_when_no_entry_id(self):
        c = FakeCoordinator()
        c.entry_id = ""
        assert c._proxy_issue_id("proxy_switch_detected") == (
            "AA:BB:CC:DD:EE:FF_proxy_switch_detected"
        )
