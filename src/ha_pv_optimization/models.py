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
    soc_pct: float | None = None
    discharge_limit_pct: float | None = None
    charging_limit_pct: float | None = None
    battery_temp_t5_c: float | None = None
    battery_temp_t30_c: float | None = None
    battery_heating_active: bool = False
    battery_high_temp_alarm_active: bool = False

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
    desired_target_w: float
    effective_target_w: float | None
    degraded_mode: str
    degraded_reasons: tuple[str, ...]
    thermal_state: ThermalState
    desired_min_soc_pct: float
    desired_max_soc_pct: float
    battery_cap_limit_w: float
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
