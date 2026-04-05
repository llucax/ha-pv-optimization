from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .device_models import DeviceModelConfig, DeviceModelKind
from .models import ActuatorConfig, ControllerConfig, ThermalPolicyConfig


def _mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _optional_mapping(value: Any, *, context: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return _mapping(value, context=context)


def _required_str(mapping: dict[str, Any], key: str, *, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing required string `{context}.{key}`")
    return value.strip()


def _optional_str(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{key}` must be a string when provided")
    text = value.strip()
    return text or None


def _optional_float(mapping: dict[str, Any], key: str) -> float | None:
    value = mapping.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{key}` must be numeric when provided") from exc


def _optional_bool(mapping: dict[str, Any], key: str) -> bool | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "1"}:
            return True
        if lowered in {"false", "no", "off", "0"}:
            return False
    raise ValueError(f"`{key}` must be boolean when provided")


def _with_default(value: Any, default: Any) -> Any:
    return default if value is None else value


@dataclass(frozen=True)
class ActuatorSiteConfig:
    power_control_entity: str
    actual_power_entity: str | None = None
    power_control_label: str | None = None
    power_control_service: str | None = None
    power_control_value_key: str | None = None
    min_output_w: float | None = None
    max_output_w: float | None = None
    power_step_w: float | None = None
    min_change_w: float | None = None
    min_write_interval_s: float | None = None
    max_increase_per_cycle_w: float | None = None
    max_decrease_per_cycle_w: float | None = None
    emergency_max_decrease_per_cycle_w: float | None = None

    @classmethod
    def from_mapping(
        cls, mapping: dict[str, Any], *, context: str
    ) -> ActuatorSiteConfig:
        return cls(
            power_control_entity=_required_str(
                mapping, "power_control_entity", context=context
            ),
            actual_power_entity=_optional_str(mapping, "actual_power_entity"),
            power_control_label=_optional_str(mapping, "power_control_label"),
            power_control_service=_optional_str(mapping, "power_control_service"),
            power_control_value_key=_optional_str(mapping, "power_control_value_key"),
            min_output_w=_optional_float(mapping, "min_output_w"),
            max_output_w=_optional_float(mapping, "max_output_w"),
            power_step_w=_optional_float(mapping, "power_step_w"),
            min_change_w=_optional_float(mapping, "min_change_w"),
            min_write_interval_s=_optional_float(mapping, "min_write_interval_s"),
            max_increase_per_cycle_w=_optional_float(
                mapping, "max_increase_per_cycle_w"
            ),
            max_decrease_per_cycle_w=_optional_float(
                mapping, "max_decrease_per_cycle_w"
            ),
            emergency_max_decrease_per_cycle_w=_optional_float(
                mapping,
                "emergency_max_decrease_per_cycle_w",
            ),
        )


@dataclass(frozen=True)
class ConsumptionSiteConfig:
    entity: str
    net_entity: str | None = None
    total_consumption_template: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> ConsumptionSiteConfig:
        return cls(
            entity=_required_str(mapping, "entity", context="consumption"),
            net_entity=_optional_str(mapping, "net_entity"),
            total_consumption_template=_optional_str(
                mapping, "total_consumption_template"
            ),
        )


@dataclass(frozen=True)
class BatterySensorsSiteConfig:
    soc_entity: str | None = None
    temperature_entity: str | None = None
    discharge_limit_entity: str | None = None
    charging_limit_entity: str | None = None
    heating_entity: str | None = None
    high_temp_alarm_entity: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> BatterySensorsSiteConfig:
        return cls(
            soc_entity=_optional_str(mapping, "soc_entity"),
            temperature_entity=_optional_str(mapping, "temperature_entity"),
            discharge_limit_entity=_optional_str(mapping, "discharge_limit_entity"),
            charging_limit_entity=_optional_str(mapping, "charging_limit_entity"),
            heating_entity=_optional_str(mapping, "heating_entity"),
            high_temp_alarm_entity=_optional_str(mapping, "high_temp_alarm_entity"),
        )


@dataclass(frozen=True)
class ControlSiteConfig:
    baseline_load_w: float = 0.0
    control_interval_s: float = 30.0
    consumption_ema_tau_s: float = 75.0
    net_ema_tau_s: float = 45.0
    deadband_w: float = 50.0
    zero_output_threshold_w: float = 25.0
    fast_export_threshold_w: float = -80.0
    import_correction_gain: float = 0.35
    export_correction_gain: float = 1.0
    net_export_negative: bool = True
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

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> ControlSiteConfig:
        if mapping is None:
            return cls()
        net_export_negative = _optional_bool(mapping, "net_export_negative")
        return cls(
            baseline_load_w=_with_default(
                _optional_float(mapping, "baseline_load_w"), 0.0
            ),
            control_interval_s=_with_default(
                _optional_float(mapping, "control_interval_s"), 30.0
            ),
            consumption_ema_tau_s=_with_default(
                _optional_float(mapping, "consumption_ema_tau_s"),
                75.0,
            ),
            net_ema_tau_s=_with_default(
                _optional_float(mapping, "net_ema_tau_s"), 45.0
            ),
            deadband_w=_with_default(_optional_float(mapping, "deadband_w"), 50.0),
            zero_output_threshold_w=_with_default(
                _optional_float(mapping, "zero_output_threshold_w"),
                25.0,
            ),
            fast_export_threshold_w=_with_default(
                _optional_float(mapping, "fast_export_threshold_w"),
                -80.0,
            ),
            import_correction_gain=_with_default(
                _optional_float(mapping, "import_correction_gain"),
                0.35,
            ),
            export_correction_gain=_with_default(
                _optional_float(mapping, "export_correction_gain"),
                1.0,
            ),
            net_export_negative=_with_default(net_export_negative, True),
            command_step_w=_with_default(
                _optional_float(mapping, "command_step_w"),
                10.0,
            ),
            command_lockout_s=_with_default(
                _optional_float(mapping, "command_lockout_s"),
                12.0,
            ),
            slow_up_deadband_w=_with_default(
                _optional_float(mapping, "slow_up_deadband_w"),
                80.0,
            ),
            slow_down_deadband_w=_with_default(
                _optional_float(mapping, "slow_down_deadband_w"),
                -40.0,
            ),
            minor_up_event_threshold_w=_with_default(
                _optional_float(mapping, "minor_up_event_threshold_w"),
                150.0,
            ),
            major_up_event_threshold_w=_with_default(
                _optional_float(mapping, "major_up_event_threshold_w"),
                400.0,
            ),
            down_event_threshold_w=_with_default(
                _optional_float(mapping, "down_event_threshold_w"),
                -150.0,
            ),
            minor_up_persistence_s=_with_default(
                _optional_float(mapping, "minor_up_persistence_s"),
                3.0,
            ),
            major_up_persistence_s=_with_default(
                _optional_float(mapping, "major_up_persistence_s"),
                2.0,
            ),
            down_event_persistence_s=_with_default(
                _optional_float(mapping, "down_event_persistence_s"),
                3.0,
            ),
            minor_up_multiplier=_with_default(
                _optional_float(mapping, "minor_up_multiplier"),
                0.75,
            ),
            major_up_multiplier=_with_default(
                _optional_float(mapping, "major_up_multiplier"),
                0.90,
            ),
            down_event_multiplier=_with_default(
                _optional_float(mapping, "down_event_multiplier"),
                0.90,
            ),
            slow_up_gain=_with_default(
                _optional_float(mapping, "slow_up_gain"),
                0.50,
            ),
            slow_up_max_step_w=_with_default(
                _optional_float(mapping, "slow_up_max_step_w"),
                100.0,
            ),
            slow_down_guard_w=_with_default(
                _optional_float(mapping, "slow_down_guard_w"),
                20.0,
            ),
            slow_down_max_step_w=_with_default(
                _optional_float(mapping, "slow_down_max_step_w"),
                300.0,
            ),
            visible_oversupply_one_sample_w=_with_default(
                _optional_float(mapping, "visible_oversupply_one_sample_w"),
                -120.0,
            ),
            visible_oversupply_two_sample_w=_with_default(
                _optional_float(mapping, "visible_oversupply_two_sample_w"),
                -60.0,
            ),
            visible_oversupply_max_cut_w=_with_default(
                _optional_float(mapping, "visible_oversupply_max_cut_w"),
                500.0,
            ),
        )


@dataclass(frozen=True)
class BatteryPolicySiteConfig:
    soc_stop_buffer_pct: float = 3.0
    soc_full_power_buffer_pct: float = 10.0
    soc_min_derate_factor: float = 0.25

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> BatteryPolicySiteConfig:
        if mapping is None:
            return cls()
        return cls(
            soc_stop_buffer_pct=_with_default(
                _optional_float(mapping, "soc_stop_buffer_pct"),
                3.0,
            ),
            soc_full_power_buffer_pct=_with_default(
                _optional_float(mapping, "soc_full_power_buffer_pct"),
                10.0,
            ),
            soc_min_derate_factor=_with_default(
                _optional_float(mapping, "soc_min_derate_factor"),
                0.25,
            ),
        )


@dataclass(frozen=True)
class AvailabilitySiteConfig:
    warning_grace_s: float = 900.0
    idle_output_threshold_w: float | None = None
    low_sun_elevation_deg: float | None = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> AvailabilitySiteConfig:
        if mapping is None:
            return cls()
        return cls(
            warning_grace_s=_with_default(
                _optional_float(mapping, "warning_grace_s"),
                900.0,
            ),
            idle_output_threshold_w=_optional_float(mapping, "idle_output_threshold_w"),
            low_sun_elevation_deg=_optional_float(mapping, "low_sun_elevation_deg"),
        )


@dataclass(frozen=True)
class LoggingSiteConfig:
    debug_entity_prefix: str = "sensor.ha_pv_optimization"
    control_cycle_log: str | None = None
    control_cycle_log_level: str | None = None
    thermal_log: str | None = None
    thermal_log_level: str | None = None

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> LoggingSiteConfig:
        if mapping is None:
            return cls()
        return cls(
            debug_entity_prefix=_optional_str(mapping, "debug_entity_prefix")
            or "sensor.ha_pv_optimization",
            control_cycle_log=_optional_str(mapping, "control_cycle_log"),
            control_cycle_log_level=_optional_str(mapping, "control_cycle_log_level"),
            thermal_log=_optional_str(mapping, "thermal_log"),
            thermal_log_level=_optional_str(mapping, "thermal_log_level"),
        )


@dataclass(frozen=True)
class DeviceModelSiteConfig:
    name: str
    kind: DeviceModelKind
    entity_id: str
    enabled: bool = True
    included_in_total_template: bool = False
    used_for_feed_forward: bool = True
    used_for_baseline_overlay: bool = False
    low_threshold_w: float | None = None
    high_threshold_w: float = 300.0
    enter_persistence_s: float = 2.0
    exit_persistence_s: float = 2.0
    ff_gain: float = 0.9
    ff_hold_s: float = 60.0
    reference_power_w: float | None = None

    @classmethod
    def from_mapping(
        cls,
        name: str,
        mapping: dict[str, Any],
    ) -> DeviceModelSiteConfig:
        kind_text = _required_str(mapping, "kind", context=f"devices.{name}")
        try:
            kind = DeviceModelKind(kind_text)
        except ValueError as exc:
            raise ValueError(f"Invalid devices.{name}.kind: {kind_text}") from exc
        enabled = _optional_bool(mapping, "enabled")
        included_in_total_template = _optional_bool(
            mapping,
            "included_in_total_template",
        )
        used_for_feed_forward = _optional_bool(mapping, "used_for_feed_forward")
        used_for_baseline_overlay = _optional_bool(
            mapping,
            "used_for_baseline_overlay",
        )
        return cls(
            name=name,
            kind=kind,
            entity_id=_required_str(mapping, "entity_id", context=f"devices.{name}"),
            enabled=True if enabled is None else enabled,
            included_in_total_template=False
            if included_in_total_template is None
            else included_in_total_template,
            used_for_feed_forward=True
            if used_for_feed_forward is None
            else used_for_feed_forward,
            used_for_baseline_overlay=False
            if used_for_baseline_overlay is None
            else used_for_baseline_overlay,
            low_threshold_w=_optional_float(mapping, "low_threshold_w"),
            high_threshold_w=_with_default(
                _optional_float(mapping, "high_threshold_w"),
                300.0,
            ),
            enter_persistence_s=_with_default(
                _optional_float(mapping, "enter_persistence_s"),
                2.0,
            ),
            exit_persistence_s=_with_default(
                _optional_float(mapping, "exit_persistence_s"),
                2.0,
            ),
            ff_gain=_with_default(_optional_float(mapping, "ff_gain"), 0.9),
            ff_hold_s=_with_default(_optional_float(mapping, "ff_hold_s"), 60.0),
            reference_power_w=_optional_float(mapping, "reference_power_w"),
        )

    def to_runtime_config(self) -> DeviceModelConfig:
        return DeviceModelConfig(
            name=self.name,
            kind=self.kind,
            entity_id=self.entity_id,
            enabled=self.enabled,
            included_in_total_template=self.included_in_total_template,
            used_for_feed_forward=self.used_for_feed_forward,
            used_for_baseline_overlay=self.used_for_baseline_overlay,
            low_threshold_w=self.low_threshold_w,
            high_threshold_w=self.high_threshold_w,
            enter_persistence_s=self.enter_persistence_s,
            exit_persistence_s=self.exit_persistence_s,
            ff_gain=self.ff_gain,
            ff_hold_s=self.ff_hold_s,
            reference_power_w=self.reference_power_w,
        )


@dataclass(frozen=True)
class ThermalSiteConfig:
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

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> ThermalSiteConfig:
        if mapping is None:
            return cls()
        return cls(
            normal_min_soc_pct=_with_default(
                _optional_float(mapping, "normal_min_soc_pct"), 15.0
            ),
            normal_max_soc_pct=_with_default(
                _optional_float(mapping, "normal_max_soc_pct"), 95.0
            ),
            normal_cap_limit_w=_with_default(
                _optional_float(mapping, "normal_cap_limit_w"), 800.0
            ),
            hot_enter_t30_c=_with_default(
                _optional_float(mapping, "hot_enter_t30_c"), 35.0
            ),
            hot_exit_t30_c=_with_default(
                _optional_float(mapping, "hot_exit_t30_c"), 33.0
            ),
            hot_exit_hold_s=_with_default(
                _optional_float(mapping, "hot_exit_hold_s"), 3600.0
            ),
            hot_min_soc_pct=_with_default(
                _optional_float(mapping, "hot_min_soc_pct"), 15.0
            ),
            hot_max_soc_pct=_with_default(
                _optional_float(mapping, "hot_max_soc_pct"), 90.0
            ),
            hot_cap_limit_w=_with_default(
                _optional_float(mapping, "hot_cap_limit_w"), 800.0
            ),
            very_hot_enter_t30_c=_with_default(
                _optional_float(mapping, "very_hot_enter_t30_c"), 40.0
            ),
            very_hot_enter_t5_c=_with_default(
                _optional_float(mapping, "very_hot_enter_t5_c"), 45.0
            ),
            very_hot_exit_t30_c=_with_default(
                _optional_float(mapping, "very_hot_exit_t30_c"), 38.0
            ),
            very_hot_exit_t5_c=_with_default(
                _optional_float(mapping, "very_hot_exit_t5_c"), 43.0
            ),
            very_hot_exit_hold_s=_with_default(
                _optional_float(mapping, "very_hot_exit_hold_s"), 3600.0
            ),
            very_hot_min_soc_pct=_with_default(
                _optional_float(mapping, "very_hot_min_soc_pct"), 20.0
            ),
            very_hot_max_soc_pct=_with_default(
                _optional_float(mapping, "very_hot_max_soc_pct"), 85.0
            ),
            very_hot_cap_limit_w=_with_default(
                _optional_float(mapping, "very_hot_cap_limit_w"), 400.0
            ),
        )


@dataclass(frozen=True)
class SiteConfig:
    consumption: ConsumptionSiteConfig
    battery: ActuatorSiteConfig
    battery_sensors: BatterySensorsSiteConfig = field(
        default_factory=BatterySensorsSiteConfig
    )
    inverter: ActuatorSiteConfig | None = None
    control: ControlSiteConfig = field(default_factory=ControlSiteConfig)
    battery_policy: BatteryPolicySiteConfig = field(
        default_factory=BatteryPolicySiteConfig
    )
    thermal: ThermalSiteConfig = field(default_factory=ThermalSiteConfig)
    availability: AvailabilitySiteConfig = field(default_factory=AvailabilitySiteConfig)
    logging: LoggingSiteConfig = field(default_factory=LoggingSiteConfig)
    devices: dict[str, DeviceModelSiteConfig] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> SiteConfig:
        return cls(
            consumption=ConsumptionSiteConfig.from_mapping(
                _mapping(mapping.get("consumption"), context="consumption")
            ),
            battery=ActuatorSiteConfig.from_mapping(
                _mapping(mapping.get("battery"), context="battery"),
                context="battery",
            ),
            battery_sensors=BatterySensorsSiteConfig.from_mapping(
                _mapping(mapping.get("battery_sensors", {}), context="battery_sensors")
            ),
            inverter=None
            if mapping.get("inverter") is None
            else ActuatorSiteConfig.from_mapping(
                _mapping(mapping.get("inverter"), context="inverter"),
                context="inverter",
            ),
            control=ControlSiteConfig.from_mapping(
                _optional_mapping(mapping.get("control"), context="control")
            ),
            battery_policy=BatteryPolicySiteConfig.from_mapping(
                _optional_mapping(
                    mapping.get("battery_policy"), context="battery_policy"
                )
            ),
            thermal=ThermalSiteConfig.from_mapping(
                _optional_mapping(mapping.get("thermal"), context="thermal")
            ),
            availability=AvailabilitySiteConfig.from_mapping(
                _optional_mapping(mapping.get("availability"), context="availability")
            ),
            logging=LoggingSiteConfig.from_mapping(
                _optional_mapping(mapping.get("logging"), context="logging")
            ),
            devices={
                name: DeviceModelSiteConfig.from_mapping(name, device_mapping)
                for name, device_mapping in _mapping(
                    mapping.get("devices", {}),
                    context="devices",
                ).items()
            },
        )


def load_site_config(path: Path) -> SiteConfig:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.exists():
        raise ValueError(f"Site config file not found: {path} (resolved={resolved})")
    with resolved.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Site config must be a mapping: {resolved}")
    try:
        return SiteConfig.from_mapping(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid site config {resolved}: {exc}") from exc


def site_config_to_appdaemon_args(site_config: SiteConfig) -> dict[str, Any]:
    args: dict[str, Any] = {
        "consumption_entity": site_config.consumption.entity,
        "net_consumption_entity": site_config.consumption.net_entity,
        "battery_power_control_entity": site_config.battery.power_control_entity,
        "battery_actual_power_entity": site_config.battery.actual_power_entity,
        "battery_power_control_label": site_config.battery.power_control_label,
        "battery_power_control_service": site_config.battery.power_control_service,
        "battery_power_control_value_key": site_config.battery.power_control_value_key,
        "battery_min_output_w": site_config.battery.min_output_w,
        "battery_max_output_w": site_config.battery.max_output_w,
        "battery_power_step_w": site_config.battery.power_step_w,
        "battery_min_change_w": site_config.battery.min_change_w,
        "battery_min_write_interval_s": site_config.battery.min_write_interval_s,
        "battery_max_increase_per_cycle_w": (
            site_config.battery.max_increase_per_cycle_w
        ),
        "battery_max_decrease_per_cycle_w": (
            site_config.battery.max_decrease_per_cycle_w
        ),
        "battery_emergency_max_decrease_per_cycle_w": (
            site_config.battery.emergency_max_decrease_per_cycle_w
        ),
        "battery_soc_entity": site_config.battery_sensors.soc_entity,
        "battery_temperature_entity": (site_config.battery_sensors.temperature_entity),
        "battery_discharge_limit_entity": (
            site_config.battery_sensors.discharge_limit_entity
        ),
        "battery_charging_limit_entity": (
            site_config.battery_sensors.charging_limit_entity
        ),
        "battery_heating_entity": site_config.battery_sensors.heating_entity,
        "battery_high_temp_alarm_entity": (
            site_config.battery_sensors.high_temp_alarm_entity
        ),
        "baseline_load_w": site_config.control.baseline_load_w,
        "control_interval_s": site_config.control.control_interval_s,
        "consumption_ema_tau_s": site_config.control.consumption_ema_tau_s,
        "net_ema_tau_s": site_config.control.net_ema_tau_s,
        "deadband_w": site_config.control.deadband_w,
        "zero_output_threshold_w": site_config.control.zero_output_threshold_w,
        "fast_export_threshold_w": site_config.control.fast_export_threshold_w,
        "import_correction_gain": site_config.control.import_correction_gain,
        "export_correction_gain": site_config.control.export_correction_gain,
        "net_export_negative": site_config.control.net_export_negative,
        "command_step_w": site_config.control.command_step_w,
        "command_lockout_s": site_config.control.command_lockout_s,
        "slow_up_deadband_w": site_config.control.slow_up_deadband_w,
        "slow_down_deadband_w": site_config.control.slow_down_deadband_w,
        "minor_up_event_threshold_w": site_config.control.minor_up_event_threshold_w,
        "major_up_event_threshold_w": site_config.control.major_up_event_threshold_w,
        "down_event_threshold_w": site_config.control.down_event_threshold_w,
        "minor_up_persistence_s": site_config.control.minor_up_persistence_s,
        "major_up_persistence_s": site_config.control.major_up_persistence_s,
        "down_event_persistence_s": site_config.control.down_event_persistence_s,
        "minor_up_multiplier": site_config.control.minor_up_multiplier,
        "major_up_multiplier": site_config.control.major_up_multiplier,
        "down_event_multiplier": site_config.control.down_event_multiplier,
        "slow_up_gain": site_config.control.slow_up_gain,
        "slow_up_max_step_w": site_config.control.slow_up_max_step_w,
        "slow_down_guard_w": site_config.control.slow_down_guard_w,
        "slow_down_max_step_w": site_config.control.slow_down_max_step_w,
        "visible_oversupply_one_sample_w": (
            site_config.control.visible_oversupply_one_sample_w
        ),
        "visible_oversupply_two_sample_w": (
            site_config.control.visible_oversupply_two_sample_w
        ),
        "visible_oversupply_max_cut_w": (
            site_config.control.visible_oversupply_max_cut_w
        ),
        "soc_stop_buffer_pct": site_config.battery_policy.soc_stop_buffer_pct,
        "soc_full_power_buffer_pct": (
            site_config.battery_policy.soc_full_power_buffer_pct
        ),
        "soc_min_derate_factor": site_config.battery_policy.soc_min_derate_factor,
        "thermal_normal_min_soc_pct": site_config.thermal.normal_min_soc_pct,
        "thermal_normal_max_soc_pct": site_config.thermal.normal_max_soc_pct,
        "thermal_normal_cap_limit_w": site_config.thermal.normal_cap_limit_w,
        "thermal_hot_enter_t30_c": site_config.thermal.hot_enter_t30_c,
        "thermal_hot_exit_t30_c": site_config.thermal.hot_exit_t30_c,
        "thermal_hot_exit_hold_s": site_config.thermal.hot_exit_hold_s,
        "thermal_hot_min_soc_pct": site_config.thermal.hot_min_soc_pct,
        "thermal_hot_max_soc_pct": site_config.thermal.hot_max_soc_pct,
        "thermal_hot_cap_limit_w": site_config.thermal.hot_cap_limit_w,
        "thermal_very_hot_enter_t30_c": site_config.thermal.very_hot_enter_t30_c,
        "thermal_very_hot_enter_t5_c": site_config.thermal.very_hot_enter_t5_c,
        "thermal_very_hot_exit_t30_c": site_config.thermal.very_hot_exit_t30_c,
        "thermal_very_hot_exit_t5_c": site_config.thermal.very_hot_exit_t5_c,
        "thermal_very_hot_exit_hold_s": site_config.thermal.very_hot_exit_hold_s,
        "thermal_very_hot_min_soc_pct": site_config.thermal.very_hot_min_soc_pct,
        "thermal_very_hot_max_soc_pct": site_config.thermal.very_hot_max_soc_pct,
        "thermal_very_hot_cap_limit_w": site_config.thermal.very_hot_cap_limit_w,
        "availability_warning_grace_s": site_config.availability.warning_grace_s,
        "availability_idle_output_threshold_w": (
            site_config.availability.idle_output_threshold_w
        ),
        "availability_low_sun_elevation_deg": (
            site_config.availability.low_sun_elevation_deg
        ),
        "debug_entity_prefix": site_config.logging.debug_entity_prefix,
        "control_cycle_log": site_config.logging.control_cycle_log,
        "control_cycle_log_level": site_config.logging.control_cycle_log_level,
        "thermal_log": site_config.logging.thermal_log,
        "thermal_log_level": site_config.logging.thermal_log_level,
    }

    if site_config.inverter is not None:
        args.update(
            {
                "inverter_power_control_entity": (
                    site_config.inverter.power_control_entity
                ),
                "inverter_actual_power_entity": (
                    site_config.inverter.actual_power_entity
                ),
                "inverter_power_control_label": (
                    site_config.inverter.power_control_label
                ),
                "inverter_power_control_service": (
                    site_config.inverter.power_control_service
                ),
                "inverter_power_control_value_key": (
                    site_config.inverter.power_control_value_key
                ),
                "inverter_min_output_w": site_config.inverter.min_output_w,
                "inverter_max_output_w": site_config.inverter.max_output_w,
                "inverter_power_step_w": site_config.inverter.power_step_w,
                "inverter_min_change_w": site_config.inverter.min_change_w,
                "inverter_min_write_interval_s": (
                    site_config.inverter.min_write_interval_s
                ),
                "inverter_max_increase_per_cycle_w": (
                    site_config.inverter.max_increase_per_cycle_w
                ),
                "inverter_max_decrease_per_cycle_w": (
                    site_config.inverter.max_decrease_per_cycle_w
                ),
                "inverter_emergency_max_decrease_per_cycle_w": (
                    site_config.inverter.emergency_max_decrease_per_cycle_w
                ),
            }
        )

    return {key: value for key, value in args.items() if value is not None}


def controller_config_from_site_config(
    site_config: SiteConfig,
    *,
    dry_run: bool = False,
) -> ControllerConfig:
    battery = site_config.battery
    if battery.max_output_w is None:
        raise ValueError("Site config battery.max_output_w is required for replay")
    inverter = site_config.inverter
    return ControllerConfig(
        primary_actuator=ActuatorConfig(
            label=battery.power_control_label or battery.power_control_entity,
            min_output_w=_with_default(battery.min_output_w, 0.0),
            max_output_w=battery.max_output_w,
            power_step_w=_with_default(battery.power_step_w, 50.0),
            min_change_w=_with_default(
                battery.min_change_w,
                _with_default(battery.power_step_w, 50.0),
            ),
            min_write_interval_s=_with_default(battery.min_write_interval_s, 60.0),
            max_increase_per_cycle_w=_with_default(
                battery.max_increase_per_cycle_w,
                150.0,
            ),
            max_decrease_per_cycle_w=_with_default(
                battery.max_decrease_per_cycle_w,
                300.0,
            ),
            emergency_max_decrease_per_cycle_w=_with_default(
                battery.emergency_max_decrease_per_cycle_w,
                500.0,
            ),
        ),
        trim_actuator=None
        if inverter is None
        else ActuatorConfig(
            label=inverter.power_control_label or inverter.power_control_entity,
            min_output_w=_with_default(inverter.min_output_w, 0.0),
            max_output_w=inverter.max_output_w
            if inverter.max_output_w is not None
            else (_raise_missing("inverter.max_output_w")),
            power_step_w=_with_default(inverter.power_step_w, 50.0),
            min_change_w=_with_default(
                inverter.min_change_w,
                _with_default(inverter.power_step_w, 50.0),
            ),
            min_write_interval_s=_with_default(inverter.min_write_interval_s, 60.0),
            max_increase_per_cycle_w=_with_default(
                inverter.max_increase_per_cycle_w,
                150.0,
            ),
            max_decrease_per_cycle_w=_with_default(
                inverter.max_decrease_per_cycle_w,
                300.0,
            ),
            emergency_max_decrease_per_cycle_w=_with_default(
                inverter.emergency_max_decrease_per_cycle_w,
                500.0,
            ),
        ),
        control_interval_s=site_config.control.control_interval_s,
        consumption_ema_tau_s=site_config.control.consumption_ema_tau_s,
        net_ema_tau_s=site_config.control.net_ema_tau_s,
        baseline_load_w=site_config.control.baseline_load_w,
        deadband_w=site_config.control.deadband_w,
        zero_output_threshold_w=site_config.control.zero_output_threshold_w,
        fast_export_threshold_w=site_config.control.fast_export_threshold_w,
        import_correction_gain=site_config.control.import_correction_gain,
        export_correction_gain=site_config.control.export_correction_gain,
        soc_stop_buffer_pct=site_config.battery_policy.soc_stop_buffer_pct,
        soc_full_power_buffer_pct=site_config.battery_policy.soc_full_power_buffer_pct,
        soc_min_derate_factor=site_config.battery_policy.soc_min_derate_factor,
        net_export_negative=site_config.control.net_export_negative,
        dry_run=dry_run,
        command_step_w=site_config.control.command_step_w,
        command_lockout_s=site_config.control.command_lockout_s,
        slow_up_deadband_w=site_config.control.slow_up_deadband_w,
        slow_down_deadband_w=site_config.control.slow_down_deadband_w,
        minor_up_event_threshold_w=site_config.control.minor_up_event_threshold_w,
        major_up_event_threshold_w=site_config.control.major_up_event_threshold_w,
        down_event_threshold_w=site_config.control.down_event_threshold_w,
        minor_up_persistence_s=site_config.control.minor_up_persistence_s,
        major_up_persistence_s=site_config.control.major_up_persistence_s,
        down_event_persistence_s=site_config.control.down_event_persistence_s,
        minor_up_multiplier=site_config.control.minor_up_multiplier,
        major_up_multiplier=site_config.control.major_up_multiplier,
        down_event_multiplier=site_config.control.down_event_multiplier,
        slow_up_gain=site_config.control.slow_up_gain,
        slow_up_max_step_w=site_config.control.slow_up_max_step_w,
        slow_down_guard_w=site_config.control.slow_down_guard_w,
        slow_down_max_step_w=site_config.control.slow_down_max_step_w,
        visible_oversupply_one_sample_w=site_config.control.visible_oversupply_one_sample_w,
        visible_oversupply_two_sample_w=site_config.control.visible_oversupply_two_sample_w,
        visible_oversupply_max_cut_w=site_config.control.visible_oversupply_max_cut_w,
        thermal_policy=ThermalPolicyConfig(
            normal_min_soc_pct=site_config.thermal.normal_min_soc_pct,
            normal_max_soc_pct=site_config.thermal.normal_max_soc_pct,
            normal_cap_limit_w=site_config.thermal.normal_cap_limit_w,
            hot_enter_t30_c=site_config.thermal.hot_enter_t30_c,
            hot_exit_t30_c=site_config.thermal.hot_exit_t30_c,
            hot_exit_hold_s=site_config.thermal.hot_exit_hold_s,
            hot_min_soc_pct=site_config.thermal.hot_min_soc_pct,
            hot_max_soc_pct=site_config.thermal.hot_max_soc_pct,
            hot_cap_limit_w=site_config.thermal.hot_cap_limit_w,
            very_hot_enter_t30_c=site_config.thermal.very_hot_enter_t30_c,
            very_hot_enter_t5_c=site_config.thermal.very_hot_enter_t5_c,
            very_hot_exit_t30_c=site_config.thermal.very_hot_exit_t30_c,
            very_hot_exit_t5_c=site_config.thermal.very_hot_exit_t5_c,
            very_hot_exit_hold_s=site_config.thermal.very_hot_exit_hold_s,
            very_hot_min_soc_pct=site_config.thermal.very_hot_min_soc_pct,
            very_hot_max_soc_pct=site_config.thermal.very_hot_max_soc_pct,
            very_hot_cap_limit_w=site_config.thermal.very_hot_cap_limit_w,
        ),
    )


def _raise_missing(field_name: str) -> float:
    raise ValueError(f"Site config `{field_name}` is required")
