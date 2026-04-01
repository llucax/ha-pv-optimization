from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import ActuatorConfig, ControllerConfig


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

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> BatterySensorsSiteConfig:
        return cls(
            soc_entity=_optional_str(mapping, "soc_entity"),
            temperature_entity=_optional_str(mapping, "temperature_entity"),
            discharge_limit_entity=_optional_str(mapping, "discharge_limit_entity"),
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

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any] | None) -> LoggingSiteConfig:
        if mapping is None:
            return cls()
        return cls(
            debug_entity_prefix=_optional_str(mapping, "debug_entity_prefix")
            or "sensor.ha_pv_optimization",
            control_cycle_log=_optional_str(mapping, "control_cycle_log"),
            control_cycle_log_level=_optional_str(mapping, "control_cycle_log_level"),
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
    availability: AvailabilitySiteConfig = field(default_factory=AvailabilitySiteConfig)
    logging: LoggingSiteConfig = field(default_factory=LoggingSiteConfig)
    devices: dict[str, Any] = field(default_factory=dict)

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
            availability=AvailabilitySiteConfig.from_mapping(
                _optional_mapping(mapping.get("availability"), context="availability")
            ),
            logging=LoggingSiteConfig.from_mapping(
                _optional_mapping(mapping.get("logging"), context="logging")
            ),
            devices=_mapping(mapping.get("devices", {}), context="devices"),
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
        "soc_stop_buffer_pct": site_config.battery_policy.soc_stop_buffer_pct,
        "soc_full_power_buffer_pct": (
            site_config.battery_policy.soc_full_power_buffer_pct
        ),
        "soc_min_derate_factor": site_config.battery_policy.soc_min_derate_factor,
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
    )


def _raise_missing(field_name: str) -> float:
    raise ValueError(f"Site config `{field_name}` is required")
