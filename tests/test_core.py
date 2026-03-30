from __future__ import annotations

from typing import Any

from ha_pv_optimization.controller import PowerControllerCore
from ha_pv_optimization.core import ControllerConfig as LegacyControllerConfig
from ha_pv_optimization.models import (
    ActuatorConfig,
    ActuatorInputs,
    ControllerConfig,
    ControllerInputs,
)


def _single_actuator_controller(**kwargs: Any) -> PowerControllerCore:
    primary_config = ActuatorConfig(
        label="battery",
        max_output_w=float(kwargs.pop("max_output_w", 1000.0)),
        min_write_interval_s=float(kwargs.pop("min_write_interval_s", 60.0)),
        max_increase_per_cycle_w=float(kwargs.pop("max_increase_per_cycle_w", 150.0)),
        max_decrease_per_cycle_w=float(kwargs.pop("max_decrease_per_cycle_w", 300.0)),
        emergency_max_decrease_per_cycle_w=float(
            kwargs.pop("emergency_max_decrease_per_cycle_w", 500.0)
        ),
        min_output_w=float(kwargs.pop("min_output_w", 0.0)),
        power_step_w=float(kwargs.pop("power_step_w", 50.0)),
        min_change_w=float(kwargs.pop("min_change_w", 50.0)),
    )
    return PowerControllerCore(
        ControllerConfig(
            primary_actuator=primary_config,
            **kwargs,
        )
    )


def test_legacy_core_exports_match_models_module() -> None:
    assert LegacyControllerConfig is ControllerConfig


def test_battery_and_inverter_alias_properties_match_legacy_fields() -> None:
    inverter_config = ActuatorConfig(label="inverter", max_output_w=800.0)
    controller_config = ControllerConfig(
        primary_actuator=ActuatorConfig(label="battery", max_output_w=800.0),
        trim_actuator=inverter_config,
    )
    controller_inputs = ControllerInputs(
        consumption_w=120.0,
        primary_actuator=ActuatorInputs(current_limit_w=100.0),
        trim_actuator=ActuatorInputs(current_limit_w=80.0),
    )

    assert controller_config.battery_actuator is controller_config.primary_actuator
    assert controller_config.inverter_actuator is inverter_config
    assert controller_inputs.battery_actuator is controller_inputs.primary_actuator
    assert controller_inputs.inverter_actuator is controller_inputs.trim_actuator


def test_baseline_load_is_added_to_consumption() -> None:
    controller = _single_actuator_controller(
        baseline_load_w=40.0,
        consumption_ema_tau_s=1.0,
        min_write_interval_s=0.0,
        max_output_w=1000.0,
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=200.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=100.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.target_limit_w == 240.0
    assert result.primary_actuator.target_limit_w == 250.0
    assert result.action == "write"


def test_fast_export_reduces_output_quickly() -> None:
    controller = _single_actuator_controller(
        consumption_ema_tau_s=1.0,
        net_ema_tau_s=1.0,
        min_write_interval_s=999.0,
        max_output_w=1000.0,
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=350.0,
            net_consumption_w=-150.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=400.0,
                seconds_since_last_write=10.0,
            ),
        )
    )
    assert result.target_limit_w == 200.0
    assert result.action == "write"
    assert result.export_fast is True


def test_soc_floor_forces_primary_output_to_zero() -> None:
    controller = _single_actuator_controller(
        consumption_ema_tau_s=1.0,
        min_write_interval_s=0.0,
        max_output_w=1000.0,
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=400.0,
            soc_pct=22.0,
            discharge_limit_pct=20.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=200.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.target_limit_w == 400.0
    assert result.action == "write"
    assert result.primary_allowed_max_output_w == 0.0
    assert result.primary_actuator.target_limit_w == 0.0


def test_trim_actuator_absorbs_residual_after_primary_quantization() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            primary_actuator=ActuatorConfig(
                label="battery",
                max_output_w=800.0,
                power_step_w=50.0,
                min_change_w=50.0,
                min_write_interval_s=0.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            trim_actuator=ActuatorConfig(
                label="inverter",
                min_output_w=30.0,
                max_output_w=800.0,
                power_step_w=10.0,
                min_change_w=10.0,
                min_write_interval_s=0.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            consumption_ema_tau_s=1.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=350.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=300.0,
                seconds_since_last_write=999.0,
            ),
            trim_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.action == "write"
    assert result.target_limit_w == 350.0
    assert result.primary_actuator.target_limit_w == 350.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.target_limit_w == 350.0


def test_trim_actuator_handles_change_when_primary_write_interval_blocks() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            primary_actuator=ActuatorConfig(
                label="battery",
                max_output_w=800.0,
                power_step_w=50.0,
                min_change_w=50.0,
                min_write_interval_s=999.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            trim_actuator=ActuatorConfig(
                label="inverter",
                max_output_w=800.0,
                power_step_w=10.0,
                min_change_w=10.0,
                min_write_interval_s=0.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            consumption_ema_tau_s=1.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=350.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=300.0,
                seconds_since_last_write=10.0,
            ),
            trim_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.primary_actuator.action == "skip"
    assert result.primary_actuator.target_limit_w == 300.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.action == "write"
    assert result.trim_actuator.target_limit_w == 350.0


def test_trim_actuator_can_run_alone_when_primary_is_unavailable() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            primary_actuator=ActuatorConfig(
                label="battery",
                max_output_w=800.0,
                min_write_interval_s=0.0,
            ),
            trim_actuator=ActuatorConfig(
                label="inverter",
                max_output_w=800.0,
                power_step_w=10.0,
                min_change_w=10.0,
                min_write_interval_s=0.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            consumption_ema_tau_s=1.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=180.0,
            primary_actuator=None,
            trim_actuator=ActuatorInputs(
                current_limit_w=100.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.action == "write"
    assert result.primary_actuator.available is False
    assert result.target_limit_w == 180.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.target_limit_w == 180.0
