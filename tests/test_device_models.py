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


def test_session_baseline_emits_transition_bias_but_no_overlay_when_in_total() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    engine = DeviceFeedForwardEngine.from_configs(
        {
            "desk": DeviceModelConfig(
                name="desk",
                kind=DeviceModelKind.SESSION_BASELINE,
                entity_id="sensor.outlet_desk_power",
                included_in_total_template=True,
                used_for_feed_forward=True,
                used_for_baseline_overlay=True,
                high_threshold_w=30.0,
                enter_persistence_s=0.0,
                ff_gain=0.25,
                ff_hold_s=120.0,
                reference_power_w=80.0,
            )
        }
    )

    engine.update_sample("desk", start, 60.0)
    total_bias_w, contributions = engine.contribution_snapshot(start)

    assert total_bias_w == 20.0
    assert contributions[0].transition_bias_w == 20.0
    assert contributions[0].baseline_overlay_w == 0.0
    assert contributions[0].state == DeviceRunState.HIGH


def test_constant_baseline_emits_no_overlay_when_in_total() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    engine = DeviceFeedForwardEngine.from_configs(
        {
            "router": DeviceModelConfig(
                name="router",
                kind=DeviceModelKind.CONSTANT_BASELINE,
                entity_id="sensor.outlet_router_power",
                included_in_total_template=True,
                used_for_feed_forward=False,
                used_for_baseline_overlay=True,
                low_threshold_w=1.0,
                ff_gain=1.0,
                reference_power_w=15.0,
            )
        }
    )

    engine.update_sample("router", start, 15.0)
    total_bias_w, contributions = engine.contribution_snapshot(
        start + timedelta(seconds=10)
    )

    assert total_bias_w == 0.0
    assert contributions[0].baseline_overlay_w == 0.0
    assert contributions[0].state == DeviceRunState.LOW


def test_thermostatic_compressor_uses_reference_power_transition_bias() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    engine = DeviceFeedForwardEngine.from_configs(
        {
            "fridge": DeviceModelConfig(
                name="fridge",
                kind=DeviceModelKind.THERMOSTATIC_COMPRESSOR,
                entity_id="sensor.outlet_fridge_power",
                included_in_total_template=True,
                high_threshold_w=50.0,
                enter_persistence_s=0.0,
                exit_persistence_s=5.0,
                ff_gain=0.25,
                ff_hold_s=60.0,
                reference_power_w=100.0,
            )
        }
    )

    engine.update_sample("fridge", start, 95.0)
    total_bias_w, contributions = engine.contribution_snapshot(start)

    assert total_bias_w == 25.0
    assert contributions[0].transition_bias_w == 25.0
    assert contributions[0].state == DeviceRunState.HIGH
