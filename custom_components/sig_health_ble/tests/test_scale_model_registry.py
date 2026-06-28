"""Unit tests for the scale model registry and Beurer payload gate."""
from __future__ import annotations

import pytest

from custom_components.sig_health_ble.devices.scale.const import (
    SCALE_MODELS,
    ScaleConfig,
    WEIGHT_SCALE_SERVICE_UUID,
    _beurer_ready,
)
from tests.conftest import FakeServiceInfo


# ── ScaleConfig defaults ───────────────────────────────────────────────────────

class TestScaleConfig:
    def test_default_is_measurement_ready_always_true(self):
        config = ScaleConfig(bonding_required=False)
        si = FakeServiceInfo()
        assert config.is_measurement_ready(si) is True

    def test_bonding_required_stored(self):
        assert ScaleConfig(bonding_required=True).bonding_required is True
        assert ScaleConfig(bonding_required=False).bonding_required is False


# ── SCALE_MODELS registry ──────────────────────────────────────────────────────

class TestScaleModels:
    def test_bf105_not_bonding(self):
        assert SCALE_MODELS["BF105"].bonding_required is False

    def test_bf720_requires_bonding(self):
        assert SCALE_MODELS["BF720"].bonding_required is True

    def test_bf105_uses_beurer_gate(self):
        """BF105 should use _beurer_ready, not the permissive default."""
        config = SCALE_MODELS["BF105"]
        si_empty = FakeServiceInfo(
            service_data={WEIGHT_SCALE_SERVICE_UUID: b""}
        )
        si_ready = FakeServiceInfo(
            service_data={WEIGHT_SCALE_SERVICE_UUID: b"\x01"}
        )
        assert config.is_measurement_ready(si_empty) is False
        assert config.is_measurement_ready(si_ready) is True

    def test_bf720_uses_beurer_gate(self):
        config = SCALE_MODELS["BF720"]
        si_empty = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b""})
        si_ready = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b"\x01"})
        assert config.is_measurement_ready(si_empty) is False
        assert config.is_measurement_ready(si_ready) is True


# ── _beurer_ready gate ─────────────────────────────────────────────────────────

class TestBeurerReady:
    def test_empty_payload_not_ready(self):
        si = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b""})
        assert _beurer_ready(si) is False

    def test_null_byte_not_ready(self):
        si = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b"\x00"})
        assert _beurer_ready(si) is False

    def test_one_byte_ready(self):
        si = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b"\x01"})
        assert _beurer_ready(si) is True

    def test_missing_service_uuid_not_ready(self):
        si = FakeServiceInfo(service_data={})
        assert _beurer_ready(si) is False

    def test_non_null_multi_byte_ready(self):
        si = FakeServiceInfo(service_data={WEIGHT_SCALE_SERVICE_UUID: b"\x01\x02"})
        assert _beurer_ready(si) is True


# ── ScaleCoordinator bonding_required driven by model ─────────────────────────

class TestScaleCoordinatorBondingRequired:
    def _make_scale_coordinator(self, model: str):
        from unittest.mock import MagicMock
        from custom_components.sig_health_ble.devices.scale.coordinator import ScaleCoordinator
        hass = MagicMock()
        hass.data = {}
        return ScaleCoordinator(hass, "AA:BB:CC:DD:EE:FF", "Test Scale", model=model)

    def test_bf105_not_bonding_required(self):
        coord = self._make_scale_coordinator("BF105")
        assert coord.bonding_required is False

    def test_bf720_bonding_required(self):
        coord = self._make_scale_coordinator("BF720")
        assert coord.bonding_required is True

    def test_unknown_model_not_bonding(self):
        coord = self._make_scale_coordinator("UnknownModel")
        assert coord.bonding_required is False

    def test_empty_model_not_bonding(self):
        coord = self._make_scale_coordinator("")
        assert coord.bonding_required is False
