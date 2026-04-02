from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ThermalState(StrEnum):
    NORMAL = "NORMAL"
    HOT = "HOT"
    VERY_HOT = "VERY_HOT"


@dataclass(frozen=True)
class ThermalPolicyConfig:
    normal_min_soc_pct: float = 15.0
    normal_max_soc_pct: float = 95.0
    normal_cap_limit_w: float = 800.0
    hot_enter_t30_c: float = 35.0
    hot_exit_t30_c: float = 33.0
    hot_exit_hold_s: float = 3600.0
    hot_min_soc_pct: float = 15.0
    hot_max_soc_pct: float = 90.0
    hot_cap_limit_w: float = 800.0
    very_hot_enter_t30_c: float = 40.0
    very_hot_enter_t5_c: float = 45.0
    very_hot_exit_t30_c: float = 38.0
    very_hot_exit_t5_c: float = 43.0
    very_hot_exit_hold_s: float = 3600.0
    very_hot_min_soc_pct: float = 20.0
    very_hot_max_soc_pct: float = 85.0
    very_hot_cap_limit_w: float = 400.0


@dataclass(frozen=True)
class ActuatorConfig:
    label: str
    min_output_w: float = 0.0
    max_output_w: float = 0.0
    power_step_w: float = 50.0
    min_change_w: float = 50.0
    min_write_interval_s: float = 60.0
    max_increase_per_cycle_w: float = 150.0
    max_decrease_per_cycle_w: float = 300.0
    emergency_max_decrease_per_cycle_w: float = 500.0


@dataclass
class ControllerConfig:
    primary_actuator: ActuatorConfig
    trim_actuator: ActuatorConfig | None = None
    control_interval_s: float = 30.0
    consumption_ema_tau_s: float = 75.0
    net_ema_tau_s: float = 45.0
    baseline_load_w: float = 0.0
    deadband_w: float = 50.0
    zero_output_threshold_w: float = 25.0
    fast_export_threshold_w: float = -80.0
    import_correction_gain: float = 0.35
    export_correction_gain: float = 1.0
    soc_stop_buffer_pct: float = 3.0
    soc_full_power_buffer_pct: float = 10.0
    soc_min_derate_factor: float = 0.25
    net_export_negative: bool = True
    dry_run: bool = False
    thermal_policy: ThermalPolicyConfig = field(default_factory=ThermalPolicyConfig)
    command_step_w: float = 10.0
    command_lockout_s: float = 12.0
    slow_up_deadband_w: float = 80.0
    slow_down_deadband_w: float = -40.0
    minor_up_event_threshold_w: float = 150.0
    major_up_event_threshold_w: float = 400.0
    down_event_threshold_w: float = -150.0
    minor_up_persistence_s: float = 3.0
    major_up_persistence_s: float = 2.0
    down_event_persistence_s: float = 3.0
    minor_up_multiplier: float = 0.75
    major_up_multiplier: float = 0.90
    down_event_multiplier: float = 0.90
    slow_up_gain: float = 0.50
    slow_up_max_step_w: float = 100.0
    slow_down_guard_w: float = 20.0
    slow_down_max_step_w: float = 300.0
    visible_oversupply_one_sample_w: float = -120.0
    visible_oversupply_two_sample_w: float = -60.0
    visible_oversupply_max_cut_w: float = 500.0

    @property
    def battery_actuator(self) -> ActuatorConfig:
        return self.primary_actuator

    @property
    def inverter_actuator(self) -> ActuatorConfig | None:
        return self.trim_actuator


@dataclass
class ActuatorInputs:
    current_limit_w: float
    actual_power_w: float | None = None
    seconds_since_last_write: float | None = None
    last_command_target_w: float | None = None
    command_mismatch_reason: str | None = None
    command_mismatch_w: float | None = None


@dataclass
class ControllerInputs:
    consumption_w: float
    primary_actuator: ActuatorInputs | None
    trim_actuator: ActuatorInputs | None = None
    net_consumption_w: float | None = None
    tw_consumption_fast_mean_w: float | None = None
    tw_consumption_slow_q20_w: float | None = None
    tw_consumption_pre_event_median_w: float | None = None
    tw_net_fast_mean_w: float | None = None
    tw_net_slow_q20_w: float | None = None
    soc_pct: float | None = None
    discharge_limit_pct: float | None = None
    charging_limit_pct: float | None = None
    battery_temp_t5_c: float | None = None
    battery_temp_t30_c: float | None = None
    battery_heating_active: bool = False
    battery_high_temp_alarm_active: bool = False
    device_feed_forward_w: float = 0.0

    @property
    def battery_actuator(self) -> ActuatorInputs | None:
        return self.primary_actuator

    @property
    def inverter_actuator(self) -> ActuatorInputs | None:
        return self.trim_actuator


@dataclass
class ActuatorResult:
    label: str
    available: bool
    action: str
    reason: str
    current_limit_w: float | None
    requested_limit_w: float
    translated_limit_w: float
    target_limit_w: float
    applied_limit_w: float | None
    actual_power_w: float | None
    allowed_max_output_w: float


@dataclass
class ControllerResult:
    action: str
    target_limit_w: float
    requested_target_w: float
    desired_path_cap_w: float
    cap_cmd_w: float
    effective_target_w: float | None
    degraded_mode: str
    degraded_reasons: tuple[str, ...]
    thermal_state: ThermalState
    thermal_reason: str
    desired_min_soc_pct: float
    desired_max_soc_pct: float
    battery_cap_limit_w: float
    device_feed_forward_w: float
    estimated_load_fast_w: float
    estimated_load_slow_w: float
    visible_load_pre_event_median_w: float
    fast_error_w: float
    slow_error_w: float
    visible_margin_w: float | None
    effective_consumption_w: float
    smoothed_consumption_w: float
    raw_net_consumption_w: float | None
    smoothed_net_consumption_w: float | None
    net_correction_w: float
    allowed_max_output_w: float
    primary_allowed_max_output_w: float
    trim_allowed_max_output_w: float
    export_fast: bool
    reason: str
    current_limit_w: float
    primary_actuator: ActuatorResult
    trim_actuator: ActuatorResult | None

    @property
    def battery_actuator(self) -> ActuatorResult:
        return self.primary_actuator

    @property
    def inverter_actuator(self) -> ActuatorResult | None:
        return self.trim_actuator

    @property
    def battery_allowed_max_output_w(self) -> float:
        return self.primary_allowed_max_output_w

    @property
    def inverter_allowed_max_output_w(self) -> float:
        return self.trim_allowed_max_output_w

    @property
    def desired_target_w(self) -> float:
        return self.desired_path_cap_w
