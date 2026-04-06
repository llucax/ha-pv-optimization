from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ha_pv_optimization.controller import PowerControllerCore
from ha_pv_optimization.core import ControllerConfig as LegacyControllerConfig
from ha_pv_optimization.models import (
    ActuatorConfig,
    ActuatorInputs,
    ControllerConfig,
    ControllerInputs,
    MaintenanceStateSnapshot,
    ThermalPolicyConfig,
    ThermalState,
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
    assert result.target_limit_w == 170.0
    assert result.requested_target_w == 170.0
    assert result.primary_actuator.requested_limit_w == 170.0
    assert result.primary_actuator.target_limit_w == 150.0
    assert result.primary_actuator.applied_limit_w == 150.0
    assert result.effective_target_w == 150.0
    assert result.action == "write"


def test_visible_oversupply_guard_reduces_output_quickly() -> None:
    controller = _single_actuator_controller(
        min_write_interval_s=0.0,
        max_output_w=1000.0,
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=200.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=400.0,
                seconds_since_last_write=999.0,
            ),
            trim_actuator=ActuatorInputs(
                current_limit_w=400.0,
                actual_power_w=400.0,
                seconds_since_last_write=999.0,
            ),
            tw_consumption_fast_mean_w=400.0,
            tw_consumption_slow_q20_w=400.0,
            tw_consumption_pre_event_median_w=200.0,
        )
    )
    assert result.target_limit_w == 260.0
    assert result.action == "write"
    assert result.reason.startswith("oversupply_severe")


def test_soc_floor_forces_primary_output_to_zero() -> None:
    controller = _single_actuator_controller(
        consumption_ema_tau_s=1.0,
        min_write_interval_s=0.0,
        max_output_w=1000.0,
        thermal_policy=ThermalPolicyConfig(normal_min_soc_pct=25.0),
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
    assert result.requested_target_w == 200.0
    assert result.target_limit_w == 0.0
    assert result.action == "write"
    assert result.primary_allowed_max_output_w == 0.0
    assert result.primary_actuator.target_limit_w == 0.0
    assert result.effective_target_w == 0.0
    assert result.degraded_mode == "battery_limited"


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
            thermal_policy=ThermalPolicyConfig(normal_min_soc_pct=25.0),
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
    assert result.target_limit_w == 100.0
    assert result.primary_actuator.target_limit_w == 100.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.target_limit_w == 100.0


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
            thermal_policy=ThermalPolicyConfig(normal_min_soc_pct=25.0),
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
    assert result.primary_actuator.target_limit_w == 100.0
    assert result.primary_actuator.applied_limit_w == 300.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.action == "write"
    assert result.trim_actuator.target_limit_w == 100.0
    assert result.effective_target_w == 100.0
    assert result.degraded_mode == "battery_not_enforcing_target"


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
            thermal_policy=ThermalPolicyConfig(normal_min_soc_pct=25.0),
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=300.0,
            primary_actuator=None,
            trim_actuator=ActuatorInputs(
                current_limit_w=100.0,
                seconds_since_last_write=999.0,
            ),
        )
    )
    assert result.action == "write"
    assert result.primary_actuator.available is False
    assert result.target_limit_w == 200.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.target_limit_w == 200.0


def test_path_cap_is_clamped_by_battery_before_inverter_target() -> None:
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
                power_step_w=25.0,
                min_change_w=25.0,
                min_write_interval_s=0.0,
                max_increase_per_cycle_w=500.0,
                max_decrease_per_cycle_w=500.0,
                emergency_max_decrease_per_cycle_w=500.0,
            ),
            consumption_ema_tau_s=1.0,
            thermal_policy=ThermalPolicyConfig(normal_min_soc_pct=25.0),
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=155.0,
            soc_pct=22.0,
            discharge_limit_pct=20.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
            trim_actuator=ActuatorInputs(
                current_limit_w=230.0,
                seconds_since_last_write=999.0,
            ),
        )
    )

    assert result.requested_target_w == 0.0
    assert result.target_limit_w == 0.0
    assert result.primary_actuator.target_limit_w == 0.0
    assert result.trim_actuator is not None
    assert result.trim_actuator.target_limit_w == 0.0
    assert result.trim_actuator.reason == "below_min_supported_by_other"
    assert result.effective_target_w == 0.0
    assert result.degraded_mode == "inverter_not_enforcing_target"


def test_device_feed_forward_bias_is_added_to_requested_target() -> None:
    controller = _single_actuator_controller(
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
            device_feed_forward_w=120.0,
        )
    )

    assert result.requested_target_w == 200.0
    assert result.device_feed_forward_w == 120.0
    assert "device_feed_forward" in result.reason


def test_hot_thermal_state_caps_output_and_soc_targets() -> None:
    controller = _single_actuator_controller(
        consumption_ema_tau_s=1.0,
        min_write_interval_s=0.0,
        max_output_w=1000.0,
        thermal_policy=ThermalPolicyConfig(
            hot_enter_t30_c=35.0,
            hot_exit_t30_c=33.0,
            hot_exit_hold_s=60.0,
            hot_min_soc_pct=15.0,
            hot_max_soc_pct=90.0,
            hot_cap_limit_w=800.0,
            very_hot_enter_t30_c=40.0,
            very_hot_enter_t5_c=45.0,
            very_hot_exit_t30_c=38.0,
            very_hot_exit_t5_c=43.0,
            very_hot_exit_hold_s=60.0,
            very_hot_min_soc_pct=20.0,
            very_hot_max_soc_pct=85.0,
            very_hot_cap_limit_w=400.0,
        ),
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=600.0,
            soc_pct=80.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
            battery_temp_t30_c=36.0,
            battery_temp_t5_c=30.0,
        )
    )

    assert result.thermal_state == ThermalState.HOT
    assert result.desired_min_soc_pct == 15.0
    assert result.desired_max_soc_pct == 90.0
    assert result.battery_cap_limit_w == 800.0


def test_very_hot_state_limits_battery_output_and_recovers_with_hysteresis() -> None:
    controller = _single_actuator_controller(
        consumption_ema_tau_s=1.0,
        control_interval_s=30.0,
        min_write_interval_s=0.0,
        max_output_w=1000.0,
        thermal_policy=ThermalPolicyConfig(
            hot_enter_t30_c=35.0,
            hot_exit_t30_c=33.0,
            hot_exit_hold_s=60.0,
            hot_min_soc_pct=15.0,
            hot_max_soc_pct=90.0,
            hot_cap_limit_w=800.0,
            very_hot_enter_t30_c=40.0,
            very_hot_enter_t5_c=45.0,
            very_hot_exit_t30_c=38.0,
            very_hot_exit_t5_c=43.0,
            very_hot_exit_hold_s=60.0,
            very_hot_min_soc_pct=20.0,
            very_hot_max_soc_pct=85.0,
            very_hot_cap_limit_w=400.0,
        ),
    )
    hot_result = controller.step(
        ControllerInputs(
            consumption_w=700.0,
            soc_pct=80.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
            battery_temp_t30_c=41.0,
            battery_temp_t5_c=46.0,
        )
    )
    assert hot_result.thermal_state == ThermalState.VERY_HOT
    assert hot_result.battery_cap_limit_w == 400.0
    assert hot_result.primary_allowed_max_output_w == 400.0

    recover_step_1 = controller.step(
        ControllerInputs(
            consumption_w=700.0,
            soc_pct=80.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=400.0,
                seconds_since_last_write=999.0,
            ),
            battery_temp_t30_c=37.0,
            battery_temp_t5_c=42.0,
        )
    )
    assert recover_step_1.thermal_state == ThermalState.VERY_HOT

    recover_step_2 = controller.step(
        ControllerInputs(
            consumption_w=700.0,
            soc_pct=80.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=400.0,
                seconds_since_last_write=999.0,
            ),
            battery_temp_t30_c=37.0,
            battery_temp_t5_c=42.0,
        )
    )
    assert recover_step_2.thermal_state == ThermalState.HOT


def test_maintenance_starts_when_overdue_and_conditions_are_ok() -> None:
    controller = _single_actuator_controller(
        control_interval_s=30.0,
        min_write_interval_s=0.0,
    )
    now = datetime(2026, 4, 4, 12, 0, tzinfo=UTC)

    result = controller.step(
        ControllerInputs(
            timestamp=now,
            consumption_w=300.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=200.0,
                seconds_since_last_write=999.0,
            ),
            soc_pct=80.0,
            battery_temp_t30_c=20.0,
            battery_temp_t5_c=20.0,
        )
    )

    assert result.maintenance_active is True
    assert result.maintenance_due is True
    assert result.maintenance_reason == "started"
    assert result.desired_max_soc_pct == 100.0
    assert result.target_limit_w == 0.0


def test_maintenance_completes_after_full_charge_hold() -> None:
    controller = _single_actuator_controller(control_interval_s=60.0)
    start = datetime(2026, 4, 4, 12, 0, tzinfo=UTC)
    controller.load_maintenance_state(
        MaintenanceStateSnapshot(
            maintenance_active=True,
            full_charge_elapsed_s=1740.0,
            last_full_charge_at=None,
        )
    )

    result = controller.step(
        ControllerInputs(
            timestamp=start,
            consumption_w=0.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=0.0,
                seconds_since_last_write=999.0,
            ),
            soc_pct=99.5,
            battery_temp_t30_c=20.0,
            battery_temp_t5_c=20.0,
        )
    )

    assert result.maintenance_active is False
    assert result.maintenance_due is False
    assert result.maintenance_reason == "completed"
    assert result.last_full_charge_at == start


def test_maintenance_waits_for_allowed_thermal_window() -> None:
    controller = _single_actuator_controller(control_interval_s=30.0)
    now = datetime(2026, 4, 4, 12, 0, tzinfo=UTC)

    result = controller.step(
        ControllerInputs(
            timestamp=now,
            consumption_w=200.0,
            primary_actuator=ActuatorInputs(
                current_limit_w=100.0,
                seconds_since_last_write=999.0,
            ),
            soc_pct=80.0,
            battery_temp_t30_c=5.0,
            battery_temp_t5_c=5.0,
        )
    )

    assert result.maintenance_active is False
    assert result.maintenance_due is True
    assert result.maintenance_reason == "waiting_conditions"
