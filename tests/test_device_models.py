from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ha_pv_optimization.device_models import (
    DeviceFeedForwardEngine,
    DeviceModelConfig,
    DeviceModelKind,
    DeviceRunState,
)


def test_burst_device_emits_temporary_bias_after_enter_persistence() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    engine = DeviceFeedForwardEngine.from_configs(
        {
            "microwave": DeviceModelConfig(
                name="microwave",
                kind=DeviceModelKind.BURST_HIGH_POWER,
                entity_id="sensor.outlet_microwave_power",
                high_threshold_w=300.0,
                enter_persistence_s=2.0,
                exit_persistence_s=2.0,
                ff_gain=0.95,
                ff_hold_s=60.0,
            )
        }
    )

    engine.update_sample("microwave", start, 0.0)
    total_bias_w, contributions = engine.contribution_snapshot(start)
    assert total_bias_w == 0.0
    assert contributions[0].state == DeviceRunState.OFF

    engine.update_sample("microwave", start + timedelta(seconds=1), 1400.0)
    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=2)
    )
    assert total_bias_w == 0.0
    assert contributions[0].state == DeviceRunState.OFF

    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=3)
    )
    assert round(total_bias_w, 1) == 1330.0
    assert contributions[0].state == DeviceRunState.HIGH
    assert contributions[0].active is True

    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=70)
    )
    assert total_bias_w == 0.0
    assert contributions[0].state == DeviceRunState.HIGH


def test_cyclic_heater_only_biases_high_state() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    engine = DeviceFeedForwardEngine.from_configs(
        {
            "oven": DeviceModelConfig(
                name="oven",
                kind=DeviceModelKind.CYCLIC_HEATER,
                entity_id="sensor.outlet_oven_power",
                low_threshold_w=20.0,
                high_threshold_w=500.0,
                enter_persistence_s=2.0,
                exit_persistence_s=2.0,
                ff_gain=0.9,
                ff_hold_s=120.0,
            )
        }
    )

    engine.update_sample("oven", start, 60.0)
    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=5)
    )
    assert total_bias_w == 0.0
    assert contributions[0].state == DeviceRunState.LOW

    engine.update_sample("oven", start + timedelta(seconds=10), 1900.0)
    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=13)
    )
    assert round(total_bias_w, 1) == 1710.0
    assert contributions[0].state == DeviceRunState.HIGH

    engine.update_sample("oven", start + timedelta(seconds=20), 50.0)
    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=23)
    )
    assert total_bias_w == 0.0
    assert contributions[0].state == DeviceRunState.LOW
