from __future__ import annotations

import datetime as dt
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_site_config, site_config_to_appdaemon_args
from .controller import PowerControllerCore
from .device_models import (
    DeviceContribution,
    DeviceFeedForwardEngine,
    empty_feed_forward_engine,
)
from .models import (
    ActuatorConfig,
    ActuatorInputs,
    ActuatorResult,
    ControllerConfig,
    ControllerInputs,
    ControllerResult,
    ThermalPolicyConfig,
    ThermalState,
)
from .signals import TimeWeightedSeries

try:
    from appdaemon.plugins.hass.hassapi import (
        Hass as BaseHass,  # type: ignore[import-not-found]
    )
except ImportError:  # pragma: no cover

    class BaseHass:  # type: ignore[no-redef]
        args: dict[str, Any]

        def log(self, message: str, level: str = "INFO", **kwargs: Any) -> None:
            return None

        def run_every(self, callback: Any, start: Any, interval: Any) -> None:
            return None

        def listen_state(self, callback: Any, **kwargs: Any) -> None:
            return None

        def get_state(self, entity_id: str, attribute: str | None = None) -> Any:
            return None

        def call_service(self, service: str, **kwargs: Any) -> None:
            return None

        def set_state(
            self, entity_id: str, state: Any, attributes: dict[str, Any]
        ) -> None:
            return None


def _as_float(value: Any) -> float | None:
    if value in (None, "", "unknown", "unavailable", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_non_empty_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        text = _as_non_empty_str(value)
        if text is not None:
            return text
    return None


def _format_duration(duration_s: float) -> str:
    total_seconds = max(0, int(round(duration_s)))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _sensor_state(value: float | int) -> str:
    if isinstance(value, int):
        return str(value)
    if float(value).is_integer():
        return str(int(value))
    return str(value)


def _normalized_log_level(value: Any, default: str = "DEBUG") -> str:
    text = _as_non_empty_str(value)
    if text is None:
        return default
    normalized = text.upper()
    if normalized in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return normalized
    return default


_DEFAULT_AVAILABILITY_WARNING_GRACE_S = 15 * 60.0
_DEFAULT_AVAILABILITY_IDLE_OUTPUT_THRESHOLD_W = 20.0
_DEFAULT_AVAILABILITY_LOW_SUN_ELEVATION_DEG = 10.0
_CONTROL_HEARTBEAT_INTERVAL_S = 5 * 60.0
_THERMAL_HEARTBEAT_INTERVAL_S = 15 * 60.0
_COMMAND_MISMATCH_GRACE_S = 30.0
_SOC_RAIL_RETRY_INTERVAL_S = 60.0
_SIGNAL_HISTORY_WINDOW_S = 2 * 60 * 60.0
_TW_FAST_WINDOW_S = 3.0
_TW_SLOW_WINDOW_S = 20.0
_TW_PRE_EVENT_WINDOW_S = 10.0
_TW_BATTERY_TEMP_SHORT_WINDOW_S = 5 * 60.0
_TW_BATTERY_TEMP_LONG_WINDOW_S = 30 * 60.0


def _default_power_control_service(entity_id: str) -> str | None:
    domain = entity_id.split(".", 1)[0]
    if domain in {"number", "input_number"}:
        return f"{domain}/set_value"
    return None


@dataclass(frozen=True)
class ActuatorEntityConfig:
    slot: str
    power_control_entity: str
    power_control_service: str
    power_control_value_key: str
    power_control_label: str
    actual_power_entity: str | None


@dataclass(frozen=True)
class EntityConfig:
    consumption_entity: str
    net_consumption_entity: str | None
    battery_temperature_entity: str | None
    battery_soc_entity: str | None
    battery_discharge_limit_entity: str | None
    battery_charging_limit_entity: str | None
    battery_heating_entity: str | None
    battery_high_temp_alarm_entity: str | None
    primary_actuator: ActuatorEntityConfig
    trim_actuator: ActuatorEntityConfig | None
    debug_entity_prefix: str


@dataclass(frozen=True)
class AvailabilityConfig:
    warning_grace_s: float
    idle_output_threshold_w: float
    low_sun_elevation_deg: float


@dataclass(frozen=True)
class LoggingConfig:
    control_cycle_log: str | None
    control_cycle_log_level: str
    thermal_log: str | None
    thermal_log_level: str


@dataclass(frozen=True)
class TimeWeightedMetrics:
    consumption_fast_mean_w: float | None
    consumption_slow_q20_w: float | None
    consumption_pre_event_median_w: float | None
    net_fast_mean_w: float | None
    net_slow_q20_w: float | None
    battery_temp_t5_c: float | None
    battery_temp_t30_c: float | None


class HaPvOptimization(BaseHass):  # type: ignore[misc]
    def initialize(self) -> None:
        self.site_config = None
        self.args = self._load_effective_args(dict(self.args))
        self.entities = self._build_entity_config()
        self.config = self._build_controller_config()
        self.availability = self._build_availability_config()
        self.logging = self._build_logging_config()
        self.device_feed_forward = self._build_device_feed_forward_engine()
        self.controller = PowerControllerCore(self.config)
        self.signal_histories = self._build_signal_histories()
        self.last_write_monotonic: dict[str, float | None] = {
            "battery": None,
            "inverter": None,
        }
        self.last_write_iso: dict[str, str | None] = {
            "battery": None,
            "inverter": None,
        }
        self.last_command_target_w: dict[str, float | None] = {
            "battery": None,
            "inverter": None,
        }
        self.last_command_observed_w: dict[str, float | None] = {
            "battery": None,
            "inverter": None,
        }
        self.last_soc_rail_target_pct: dict[str, int | None] = {
            "min_soc": None,
            "max_soc": None,
        }
        self.last_soc_rail_write_monotonic: dict[str, float | None] = {
            "min_soc": None,
            "max_soc": None,
        }
        self.last_soc_rail_observed_pct: dict[str, int | None] = {
            "min_soc": None,
            "max_soc": None,
        }
        self.last_reported_thermal_state: ThermalState | None = None
        self.last_control_summary = "state=initialized no-control-cycle-yet"
        self.last_thermal_summary = "state=initialized no-thermal-cycle-yet"
        self.missing_required_entities: tuple[str, ...] | None = None
        self.missing_required_since_monotonic: float | None = None
        self.missing_required_since_iso: str | None = None
        self.missing_required_expected_reason: str | None = None
        self.missing_required_unexpected_since_monotonic: float | None = None
        self.missing_required_unexpected_since_iso: str | None = None
        self.missing_required_warning_active = False

        inverter_label = None
        if self.entities.trim_actuator is not None:
            inverter_label = self.entities.trim_actuator.power_control_label

        self.log(
            "Initialized ha-pv-optimization controller"
            f" (consumption={self.entities.consumption_entity},"
            f" battery={self.entities.primary_actuator.power_control_label},"
            f" inverter={inverter_label},"
            f" dry_run={self.config.dry_run})"
        )
        self.log(f"Control heartbeat {self.last_control_summary}")
        self._emit_thermal_log(
            f"Thermal heartbeat {self.last_thermal_summary}",
            level="INFO",
            force_main=True,
        )

        self._seed_signal_histories()
        self._register_signal_listeners()
        self._register_device_listeners()

        start = dt.datetime.now() + dt.timedelta(seconds=1)
        self.run_every(self._control_tick, start, self.config.control_interval_s)
        heartbeat_start = start + dt.timedelta(seconds=5)
        self.run_every(
            self._heartbeat_tick,
            heartbeat_start,
            _CONTROL_HEARTBEAT_INTERVAL_S,
        )
        thermal_heartbeat_start = start + dt.timedelta(seconds=10)
        self.run_every(
            self._thermal_heartbeat_tick,
            thermal_heartbeat_start,
            _THERMAL_HEARTBEAT_INTERVAL_S,
        )

    def _build_entity_config(self) -> EntityConfig:
        battery_actuator = self._build_actuator_entity_config(
            prefix="",
            alias_prefix="battery_",
            slot="battery",
            required=True,
        )
        assert battery_actuator is not None

        return EntityConfig(
            consumption_entity=self._require_entity("consumption_entity"),
            net_consumption_entity=_as_non_empty_str(
                self.args.get("net_consumption_entity")
            ),
            battery_temperature_entity=_as_non_empty_str(
                self.args.get("battery_temperature_entity")
            ),
            battery_soc_entity=_as_non_empty_str(self.args.get("battery_soc_entity")),
            battery_discharge_limit_entity=_as_non_empty_str(
                self.args.get("battery_discharge_limit_entity")
            ),
            battery_charging_limit_entity=_as_non_empty_str(
                self.args.get("battery_charging_limit_entity")
            ),
            battery_heating_entity=_as_non_empty_str(
                self.args.get("battery_heating_entity")
            ),
            battery_high_temp_alarm_entity=_as_non_empty_str(
                self.args.get("battery_high_temp_alarm_entity")
            ),
            primary_actuator=battery_actuator,
            trim_actuator=self._build_actuator_entity_config(
                prefix="trim_",
                alias_prefix="inverter_",
                slot="inverter",
                required=False,
            ),
            debug_entity_prefix=_as_non_empty_str(self.args.get("debug_entity_prefix"))
            or "sensor.ha_pv_optimization",
        )

    def _load_effective_args(self, args: dict[str, Any]) -> dict[str, Any]:
        site_config_path = _as_non_empty_str(args.get("site_config_path"))
        if site_config_path is None:
            return args

        site_config = load_site_config(Path(site_config_path))
        self.site_config = site_config
        effective_args = site_config_to_appdaemon_args(site_config)
        effective_args.update(args)
        return effective_args

    def _build_actuator_entity_config(
        self,
        prefix: str,
        alias_prefix: str,
        slot: str,
        required: bool,
    ) -> ActuatorEntityConfig | None:
        entity_key = f"{prefix}power_control_entity"
        alias_entity_key = f"{alias_prefix}power_control_entity"
        power_control_entity = _first_non_empty_str(
            self.args.get(alias_entity_key),
            self.args.get(entity_key),
        )
        if power_control_entity is None:
            if required:
                raise ValueError(
                    f"Missing required AppDaemon argument: `{alias_entity_key}`"
                    f" (or legacy `{entity_key}`)."
                )
            return None

        service_key = f"{prefix}power_control_service"
        alias_service_key = f"{alias_prefix}power_control_service"
        power_control_service = _first_non_empty_str(
            self.args.get(alias_service_key),
            self.args.get(service_key),
        )
        if power_control_service is None:
            power_control_service = _default_power_control_service(power_control_entity)
        if power_control_service is None:
            raise ValueError(
                f"Set `{alias_service_key}` (or legacy `{service_key}`) when "
                f"`{alias_entity_key}` is not a `number.*` or `input_number.*` "
                "entity."
            )

        return ActuatorEntityConfig(
            slot=slot,
            power_control_entity=power_control_entity,
            power_control_service=power_control_service,
            power_control_value_key=_first_non_empty_str(
                self.args.get(f"{alias_prefix}power_control_value_key"),
                self.args.get(f"{prefix}power_control_value_key"),
            )
            or "value",
            power_control_label=_first_non_empty_str(
                self.args.get(f"{alias_prefix}power_control_label"),
                self.args.get(f"{prefix}power_control_label"),
            )
            or power_control_entity,
            actual_power_entity=_first_non_empty_str(
                self.args.get(f"{alias_prefix}actual_power_entity"),
                self.args.get(f"{prefix}actual_power_entity"),
            ),
        )

    def _build_controller_config(self) -> ControllerConfig:
        inverter_actuator = None
        if self.entities.trim_actuator is not None:
            inverter_actuator = self._build_actuator_config(
                entity_config=self.entities.trim_actuator,
                prefix="trim_",
                alias_prefix="inverter_",
            )

        return ControllerConfig(
            primary_actuator=self._build_actuator_config(
                entity_config=self.entities.primary_actuator,
                prefix="",
                alias_prefix="battery_",
            ),
            trim_actuator=inverter_actuator,
            control_interval_s=self._get_float("control_interval_s", 30.0),
            consumption_ema_tau_s=self._get_float("consumption_ema_tau_s", 75.0),
            net_ema_tau_s=self._get_float("net_ema_tau_s", 45.0),
            baseline_load_w=self._get_float("baseline_load_w", 0.0),
            deadband_w=self._get_float("deadband_w", 50.0),
            zero_output_threshold_w=self._get_float("zero_output_threshold_w", 25.0),
            fast_export_threshold_w=self._get_float("fast_export_threshold_w", -80.0),
            import_correction_gain=self._get_float("import_correction_gain", 0.35),
            export_correction_gain=self._get_float("export_correction_gain", 1.0),
            soc_stop_buffer_pct=self._get_float("soc_stop_buffer_pct", 3.0),
            soc_full_power_buffer_pct=self._get_float(
                "soc_full_power_buffer_pct", 10.0
            ),
            soc_min_derate_factor=self._get_float("soc_min_derate_factor", 0.25),
            net_export_negative=_as_bool(self.args.get("net_export_negative"), True),
            dry_run=_as_bool(self.args.get("dry_run"), True),
            command_step_w=self._get_float("command_step_w", 10.0),
            command_lockout_s=self._get_float("command_lockout_s", 12.0),
            slow_up_deadband_w=self._get_float("slow_up_deadband_w", 80.0),
            slow_down_deadband_w=self._get_float("slow_down_deadband_w", -40.0),
            minor_up_event_threshold_w=self._get_float(
                "minor_up_event_threshold_w",
                150.0,
            ),
            major_up_event_threshold_w=self._get_float(
                "major_up_event_threshold_w",
                400.0,
            ),
            down_event_threshold_w=self._get_float("down_event_threshold_w", -150.0),
            minor_up_persistence_s=self._get_float("minor_up_persistence_s", 3.0),
            major_up_persistence_s=self._get_float("major_up_persistence_s", 2.0),
            down_event_persistence_s=self._get_float(
                "down_event_persistence_s",
                3.0,
            ),
            minor_up_multiplier=self._get_float("minor_up_multiplier", 0.75),
            major_up_multiplier=self._get_float("major_up_multiplier", 0.90),
            down_event_multiplier=self._get_float("down_event_multiplier", 0.90),
            slow_up_gain=self._get_float("slow_up_gain", 0.50),
            slow_up_max_step_w=self._get_float("slow_up_max_step_w", 100.0),
            slow_down_guard_w=self._get_float("slow_down_guard_w", 20.0),
            slow_down_max_step_w=self._get_float("slow_down_max_step_w", 300.0),
            visible_oversupply_one_sample_w=self._get_float(
                "visible_oversupply_one_sample_w",
                -120.0,
            ),
            visible_oversupply_two_sample_w=self._get_float(
                "visible_oversupply_two_sample_w",
                -60.0,
            ),
            visible_oversupply_max_cut_w=self._get_float(
                "visible_oversupply_max_cut_w",
                500.0,
            ),
            thermal_policy=ThermalPolicyConfig(
                normal_min_soc_pct=self._get_float("thermal_normal_min_soc_pct", 15.0),
                normal_max_soc_pct=self._get_float("thermal_normal_max_soc_pct", 95.0),
                normal_cap_limit_w=self._get_float("thermal_normal_cap_limit_w", 800.0),
                hot_enter_t30_c=self._get_float("thermal_hot_enter_t30_c", 35.0),
                hot_exit_t30_c=self._get_float("thermal_hot_exit_t30_c", 33.0),
                hot_exit_hold_s=self._get_float("thermal_hot_exit_hold_s", 3600.0),
                hot_min_soc_pct=self._get_float("thermal_hot_min_soc_pct", 15.0),
                hot_max_soc_pct=self._get_float("thermal_hot_max_soc_pct", 90.0),
                hot_cap_limit_w=self._get_float("thermal_hot_cap_limit_w", 800.0),
                very_hot_enter_t30_c=self._get_float(
                    "thermal_very_hot_enter_t30_c",
                    40.0,
                ),
                very_hot_enter_t5_c=self._get_float(
                    "thermal_very_hot_enter_t5_c",
                    45.0,
                ),
                very_hot_exit_t30_c=self._get_float(
                    "thermal_very_hot_exit_t30_c",
                    38.0,
                ),
                very_hot_exit_t5_c=self._get_float(
                    "thermal_very_hot_exit_t5_c",
                    43.0,
                ),
                very_hot_exit_hold_s=self._get_float(
                    "thermal_very_hot_exit_hold_s",
                    3600.0,
                ),
                very_hot_min_soc_pct=self._get_float(
                    "thermal_very_hot_min_soc_pct",
                    20.0,
                ),
                very_hot_max_soc_pct=self._get_float(
                    "thermal_very_hot_max_soc_pct",
                    85.0,
                ),
                very_hot_cap_limit_w=self._get_float(
                    "thermal_very_hot_cap_limit_w",
                    400.0,
                ),
            ),
        )

    def _build_actuator_config(
        self,
        entity_config: ActuatorEntityConfig,
        prefix: str,
        alias_prefix: str,
    ) -> ActuatorConfig:
        actuator_attributes = self._read_entity_attributes(
            entity_config.power_control_entity
        )
        inferred_min_output_w = _as_float(actuator_attributes.get("min"))
        inferred_max_output_w = _as_float(actuator_attributes.get("max"))
        inferred_step_w = _as_float(actuator_attributes.get("step"))

        alias_min_output_w = _as_float(self.args.get(f"{alias_prefix}min_output_w"))
        legacy_min_output_w = _as_float(self.args.get(f"{prefix}min_output_w"))
        min_output_w = (
            alias_min_output_w
            if alias_min_output_w is not None
            else legacy_min_output_w
            if legacy_min_output_w is not None
            else 0.0
            if inferred_min_output_w is None
            else inferred_min_output_w
        )

        max_output_w = _as_float(self.args.get(f"{alias_prefix}max_output_w"))
        if max_output_w is None:
            max_output_w = _as_float(self.args.get(f"{prefix}max_output_w"))
        if max_output_w is None:
            max_output_w = inferred_max_output_w
        if max_output_w is None:
            raise ValueError(
                f"Set `{alias_prefix}max_output_w` (or legacy `{prefix}max_output_w`)"
                " or use a power-control entity that exposes a numeric `max`"
                " attribute."
            )

        power_step_w = _as_float(self.args.get(f"{alias_prefix}power_step_w"))
        if power_step_w is None:
            power_step_w = _as_float(self.args.get(f"{prefix}power_step_w"))
        if power_step_w is None:
            power_step_w = 50.0 if inferred_step_w is None else inferred_step_w

        min_change_w = _as_float(self.args.get(f"{alias_prefix}min_change_w"))
        if min_change_w is None:
            min_change_w = _as_float(self.args.get(f"{prefix}min_change_w"))
        if min_change_w is None:
            min_change_w = power_step_w

        min_write_interval_s = _as_float(
            self.args.get(f"{alias_prefix}min_write_interval_s")
        )
        if min_write_interval_s is None:
            min_write_interval_s = _as_float(
                self.args.get(f"{prefix}min_write_interval_s")
            )
        if min_write_interval_s is None:
            min_write_interval_s = 60.0

        max_increase_per_cycle_w = _as_float(
            self.args.get(f"{alias_prefix}max_increase_per_cycle_w")
        )
        if max_increase_per_cycle_w is None:
            max_increase_per_cycle_w = _as_float(
                self.args.get(f"{prefix}max_increase_per_cycle_w")
            )
        if max_increase_per_cycle_w is None:
            max_increase_per_cycle_w = 150.0

        max_decrease_per_cycle_w = _as_float(
            self.args.get(f"{alias_prefix}max_decrease_per_cycle_w")
        )
        if max_decrease_per_cycle_w is None:
            max_decrease_per_cycle_w = _as_float(
                self.args.get(f"{prefix}max_decrease_per_cycle_w")
            )
        if max_decrease_per_cycle_w is None:
            max_decrease_per_cycle_w = 300.0

        emergency_max_decrease_per_cycle_w = _as_float(
            self.args.get(f"{alias_prefix}emergency_max_decrease_per_cycle_w")
        )
        if emergency_max_decrease_per_cycle_w is None:
            emergency_max_decrease_per_cycle_w = _as_float(
                self.args.get(f"{prefix}emergency_max_decrease_per_cycle_w")
            )
        if emergency_max_decrease_per_cycle_w is None:
            emergency_max_decrease_per_cycle_w = 500.0

        if max_output_w < min_output_w:
            raise ValueError(
                f"`{alias_prefix}max_output_w` must be greater than or equal to "
                f"`{alias_prefix}min_output_w`."
            )

        return ActuatorConfig(
            label=entity_config.power_control_label,
            min_output_w=min_output_w,
            max_output_w=max_output_w,
            power_step_w=power_step_w,
            min_change_w=min_change_w,
            min_write_interval_s=min_write_interval_s,
            max_increase_per_cycle_w=max_increase_per_cycle_w,
            max_decrease_per_cycle_w=max_decrease_per_cycle_w,
            emergency_max_decrease_per_cycle_w=emergency_max_decrease_per_cycle_w,
        )

    def _build_availability_config(self) -> AvailabilityConfig:
        warning_grace_s = self._get_float(
            "availability_warning_grace_s",
            _DEFAULT_AVAILABILITY_WARNING_GRACE_S,
        )
        idle_output_threshold_w = self._get_float(
            "availability_idle_output_threshold_w",
            _DEFAULT_AVAILABILITY_IDLE_OUTPUT_THRESHOLD_W,
        )
        low_sun_elevation_deg = self._get_float(
            "availability_low_sun_elevation_deg",
            _DEFAULT_AVAILABILITY_LOW_SUN_ELEVATION_DEG,
        )

        if warning_grace_s < 0:
            raise ValueError("`availability_warning_grace_s` must be non-negative.")
        if idle_output_threshold_w < 0:
            raise ValueError(
                "`availability_idle_output_threshold_w` must be non-negative."
            )

        return AvailabilityConfig(
            warning_grace_s=warning_grace_s,
            idle_output_threshold_w=idle_output_threshold_w,
            low_sun_elevation_deg=low_sun_elevation_deg,
        )

    def _build_logging_config(self) -> LoggingConfig:
        return LoggingConfig(
            control_cycle_log=_as_non_empty_str(self.args.get("control_cycle_log")),
            control_cycle_log_level=_normalized_log_level(
                self.args.get("control_cycle_log_level"),
                default="DEBUG",
            ),
            thermal_log=_as_non_empty_str(self.args.get("thermal_log")),
            thermal_log_level=_normalized_log_level(
                self.args.get("thermal_log_level"),
                default="DEBUG",
            ),
        )

    def _build_signal_histories(self) -> dict[str, TimeWeightedSeries]:
        return {
            "consumption": TimeWeightedSeries(_SIGNAL_HISTORY_WINDOW_S),
            "net": TimeWeightedSeries(_SIGNAL_HISTORY_WINDOW_S),
            "battery_temperature": TimeWeightedSeries(_SIGNAL_HISTORY_WINDOW_S),
        }

    def _build_device_feed_forward_engine(self) -> DeviceFeedForwardEngine:
        if self.site_config is None:
            return empty_feed_forward_engine()
        return DeviceFeedForwardEngine.from_configs(
            {
                name: device.to_runtime_config()
                for name, device in self.site_config.devices.items()
            }
        )

    def _seed_signal_histories(self) -> None:
        timestamp = dt.datetime.now(dt.UTC)
        self._record_signal_sample(
            history_key="consumption",
            entity_id=self.entities.consumption_entity,
            timestamp=timestamp,
        )
        self._record_signal_sample(
            history_key="net",
            entity_id=self.entities.net_consumption_entity,
            timestamp=timestamp,
        )
        self._record_signal_sample(
            history_key="battery_temperature",
            entity_id=self.entities.battery_temperature_entity,
            timestamp=timestamp,
        )

    def _register_signal_listeners(self) -> None:
        self._register_signal_listener(
            entity_id=self.entities.consumption_entity,
            history_key="consumption",
        )
        self._register_signal_listener(
            entity_id=self.entities.net_consumption_entity,
            history_key="net",
        )
        self._register_signal_listener(
            entity_id=self.entities.battery_temperature_entity,
            history_key="battery_temperature",
        )

    def _register_signal_listener(
        self,
        *,
        entity_id: str | None,
        history_key: str,
    ) -> None:
        if entity_id is None:
            return
        self.listen_state(
            self._on_signal_state_change,
            entity_id=entity_id,
            history_key=history_key,
        )

    def _register_device_listeners(self) -> None:
        for name, runtime in self.device_feed_forward.runtimes.items():
            self.listen_state(
                self._on_device_state_change,
                entity_id=runtime.config.entity_id,
                device_name=name,
            )

    def _on_signal_state_change(
        self,
        entity: str,
        attribute: str,
        old: Any,
        new: Any,
        kwargs: dict[str, Any],
    ) -> None:
        history_key = str(kwargs["history_key"])
        value = _as_float(new)
        if value is None:
            return
        self.signal_histories[history_key].update(dt.datetime.now(dt.UTC), value)

    def _on_device_state_change(
        self,
        entity: str,
        attribute: str,
        old: Any,
        new: Any,
        kwargs: dict[str, Any],
    ) -> None:
        value = _as_float(new)
        if value is None:
            return
        self.device_feed_forward.update_sample(
            str(kwargs["device_name"]),
            dt.datetime.now(dt.UTC),
            value,
        )

    def _record_signal_sample(
        self,
        *,
        history_key: str,
        entity_id: str | None,
        timestamp: dt.datetime,
    ) -> None:
        if entity_id is None:
            return
        value = self._read_entity_float(entity_id)
        if value is None:
            return
        self.signal_histories[history_key].update(timestamp, value)

    def _record_device_samples(self, timestamp: dt.datetime) -> None:
        for name, runtime in self.device_feed_forward.runtimes.items():
            value = self._read_entity_float(runtime.config.entity_id)
            if value is None:
                continue
            self.device_feed_forward.update_sample(name, timestamp, value)

    def _time_weighted_metrics(self, now: dt.datetime) -> TimeWeightedMetrics:
        consumption_history = self.signal_histories["consumption"]
        net_history = self.signal_histories["net"]
        battery_temp_history = self.signal_histories["battery_temperature"]
        return TimeWeightedMetrics(
            consumption_fast_mean_w=consumption_history.mean(_TW_FAST_WINDOW_S, now),
            consumption_slow_q20_w=consumption_history.quantile(
                _TW_SLOW_WINDOW_S,
                q=0.2,
                now=now,
            ),
            consumption_pre_event_median_w=consumption_history.median(
                _TW_PRE_EVENT_WINDOW_S,
                now=now,
            ),
            net_fast_mean_w=net_history.mean(_TW_FAST_WINDOW_S, now),
            net_slow_q20_w=net_history.quantile(_TW_SLOW_WINDOW_S, q=0.2, now=now),
            battery_temp_t5_c=battery_temp_history.mean(
                _TW_BATTERY_TEMP_SHORT_WINDOW_S,
                now,
            ),
            battery_temp_t30_c=battery_temp_history.mean(
                _TW_BATTERY_TEMP_LONG_WINDOW_S,
                now,
            ),
        )

    def _emit_log(
        self,
        message: str,
        *,
        level: str = "INFO",
        log_name: str | None = None,
    ) -> None:
        if log_name is None:
            self.log(message, level=level)
            return
        self.log(message, level=level, log=log_name)

    def _emit_thermal_log(
        self,
        message: str,
        *,
        level: str = "DEBUG",
        force_main: bool = False,
    ) -> None:
        if force_main or self.logging.thermal_log is None:
            self.log(message, level=level)
            return
        self.log(message, level=level, log=self.logging.thermal_log)

    def _require_entity(self, key: str) -> str:
        value = _as_non_empty_str(self.args.get(key))
        if value is None:
            raise ValueError(f"Missing required AppDaemon argument: `{key}`")
        return value

    def _get_float(self, key: str, default: float) -> float:
        value = _as_float(self.args.get(key))
        return default if value is None else value

    def _control_tick(self, kwargs: dict[str, Any]) -> None:
        now = dt.datetime.now(dt.UTC)
        self._record_signal_sample(
            history_key="consumption",
            entity_id=self.entities.consumption_entity,
            timestamp=now,
        )
        self._record_signal_sample(
            history_key="net",
            entity_id=self.entities.net_consumption_entity,
            timestamp=now,
        )
        self._record_signal_sample(
            history_key="battery_temperature",
            entity_id=self.entities.battery_temperature_entity,
            timestamp=now,
        )
        self._record_device_samples(now)

        consumption_w = self._read_entity_float(self.entities.consumption_entity)
        primary_actual_power_w = self._read_entity_float(
            self.entities.primary_actuator.actual_power_entity
        )
        trim_actual_power_w = self._read_trim_actual_power()
        primary_inputs = self._read_actuator_inputs(
            entity_config=self.entities.primary_actuator,
            actual_power_w=primary_actual_power_w,
            last_write_monotonic=self.last_write_monotonic["battery"],
            last_command_target_w=self.last_command_target_w["battery"],
            last_command_observed_w=self.last_command_observed_w["battery"],
        )
        trim_inputs = self._read_trim_inputs(trim_actual_power_w)
        soc_pct = self._read_entity_float(self.entities.battery_soc_entity)
        discharge_limit_pct = self._read_entity_float(
            self.entities.battery_discharge_limit_entity
        )
        charging_limit_pct = self._read_entity_float(
            self.entities.battery_charging_limit_entity
        )
        battery_heating_active = self._read_entity_bool(
            self.entities.battery_heating_entity
        )
        battery_high_temp_alarm_active = self._read_entity_bool(
            self.entities.battery_high_temp_alarm_entity
        )
        tw_metrics = self._time_weighted_metrics(now)

        if self._handle_missing_required_state(
            consumption_w=consumption_w,
            primary_inputs=primary_inputs,
            trim_inputs=trim_inputs,
            primary_actual_power_w=primary_actual_power_w,
            trim_actual_power_w=trim_actual_power_w,
            soc_pct=soc_pct,
            discharge_limit_pct=discharge_limit_pct,
        ):
            return

        assert consumption_w is not None

        device_feed_forward_w, device_contributions = (
            self.device_feed_forward.contribution_snapshot(now)
        )

        inputs = ControllerInputs(
            consumption_w=consumption_w,
            primary_actuator=primary_inputs,
            trim_actuator=trim_inputs,
            net_consumption_w=self._read_entity_float(
                self.entities.net_consumption_entity
            ),
            tw_consumption_fast_mean_w=tw_metrics.consumption_fast_mean_w,
            tw_consumption_slow_q20_w=tw_metrics.consumption_slow_q20_w,
            tw_consumption_pre_event_median_w=tw_metrics.consumption_pre_event_median_w,
            tw_net_fast_mean_w=tw_metrics.net_fast_mean_w,
            tw_net_slow_q20_w=tw_metrics.net_slow_q20_w,
            soc_pct=soc_pct,
            discharge_limit_pct=discharge_limit_pct,
            charging_limit_pct=charging_limit_pct,
            battery_temp_t5_c=tw_metrics.battery_temp_t5_c,
            battery_temp_t30_c=tw_metrics.battery_temp_t30_c,
            battery_heating_active=battery_heating_active,
            battery_high_temp_alarm_active=battery_high_temp_alarm_active,
            device_feed_forward_w=device_feed_forward_w,
        )
        result = self.controller.step(inputs)
        degraded_mode, degraded_reasons = self._effective_degraded_state(
            result=result,
            battery_inputs=primary_inputs,
            inverter_inputs=trim_inputs,
        )
        min_soc_action, max_soc_action = self._apply_soc_rail_targets(
            result=result,
            current_discharge_limit_pct=discharge_limit_pct,
            current_charging_limit_pct=charging_limit_pct,
            thermal_state=result.thermal_state,
        )

        if result.thermal_state != self.last_reported_thermal_state:
            self._emit_thermal_log(
                "Thermal state changed"
                f" state={result.thermal_state}"
                f" reason={result.thermal_reason}"
                f" t5={tw_metrics.battery_temp_t5_c}"
                f" t30={tw_metrics.battery_temp_t30_c}"
                f" heating={inputs.battery_heating_active}"
                f" high_temp_alarm={inputs.battery_high_temp_alarm_active}"
                f" desired_min_soc={int(result.desired_min_soc_pct)}%"
                f" desired_max_soc={int(result.desired_max_soc_pct)}%"
                f" battery_cap_limit={int(result.battery_cap_limit_w)}W",
                level="INFO",
                force_main=True,
            )
            self.last_reported_thermal_state = result.thermal_state

        self.last_thermal_summary = (
            f"state={result.thermal_state}"
            f" reason={result.thermal_reason}"
            f" t5={tw_metrics.battery_temp_t5_c}"
            f" t30={tw_metrics.battery_temp_t30_c}"
            f" heating={inputs.battery_heating_active}"
            f" high_temp_alarm={inputs.battery_high_temp_alarm_active}"
            f" desired_min_soc={int(result.desired_min_soc_pct)}%"
            f" desired_max_soc={int(result.desired_max_soc_pct)}%"
            f" battery_cap_limit={int(result.battery_cap_limit_w)}W"
            f" min_soc_action={min_soc_action}"
            f" max_soc_action={max_soc_action}"
        )

        self._apply_actuator_result(
            entity_config=self.entities.primary_actuator,
            actuator_result=result.primary_actuator,
        )
        if self.entities.trim_actuator is not None and result.trim_actuator is not None:
            self._apply_actuator_result(
                entity_config=self.entities.trim_actuator,
                actuator_result=result.trim_actuator,
            )

        if result.action in {"write", "dry_run"}:
            action_label = "Dry-run" if result.action == "dry_run" else "Updated"
            summary = self._control_summary(result, degraded_mode=degraded_mode)
            self.log(f"{action_label} control targets {summary}")
        self.last_control_summary = self._control_summary(
            result,
            degraded_mode=degraded_mode,
        )

        self._emit_log(
            "Control cycle"
            f" action={result.action}"
            f" consumption={result.effective_consumption_w:.1f}W"
            f" smoothed={result.smoothed_consumption_w:.1f}W"
            f" net={result.raw_net_consumption_w}"
            f" {self._control_summary(result, degraded_mode=degraded_mode)}",
            level=self.logging.control_cycle_log_level,
            log_name=self.logging.control_cycle_log,
        )

        self._publish_result(
            result,
            inputs,
            tw_metrics,
            degraded_mode=degraded_mode,
            degraded_reasons=degraded_reasons,
            current_discharge_limit_pct=discharge_limit_pct,
            current_charging_limit_pct=charging_limit_pct,
            min_soc_action=min_soc_action,
            max_soc_action=max_soc_action,
            device_contributions=device_contributions,
        )

    def _heartbeat_tick(self, kwargs: dict[str, Any]) -> None:
        self.log(f"Control heartbeat {self.last_control_summary}")

    def _thermal_heartbeat_tick(self, kwargs: dict[str, Any]) -> None:
        if self.logging.thermal_log is None:
            return
        self._emit_thermal_log(
            f"Thermal heartbeat {self.last_thermal_summary}",
            level=self.logging.thermal_log_level,
        )

    def _control_summary(
        self,
        result: ControllerResult,
        *,
        degraded_mode: str,
    ) -> str:
        effective_text = "unknown"
        if result.effective_target_w is not None:
            effective_text = f"{int(result.effective_target_w)}W"
        return (
            f"requested={int(result.requested_target_w)}W"
            f" planned={int(result.target_limit_w)}W"
            f" cap_cmd={int(result.cap_cmd_w)}W"
            f" effective={effective_text}"
            f" ff={int(result.device_feed_forward_w)}W"
            f" l_fast={int(result.estimated_load_fast_w)}W"
            f" l_slow={int(result.estimated_load_slow_w)}W"
            f" l_pre={int(result.visible_load_pre_event_median_w)}W"
            f" e_fast={int(result.fast_error_w)}W"
            f" e_slow={int(result.slow_error_w)}W"
            f" visible_margin={result.visible_margin_w}"
            f" battery_allowed={int(result.battery_allowed_max_output_w)}W"
            f" inverter_allowed={int(result.inverter_allowed_max_output_w)}W"
            f" thermal={result.thermal_state}"
            f" current={int(result.current_limit_w)}W"
            f" degraded={degraded_mode}"
            f" battery={self._format_actuator_summary(result.primary_actuator)}"
            f" inverter={self._format_trim_summary(result.trim_actuator)}"
            f" reason={result.reason}"
        )

    def _effective_degraded_state(
        self,
        *,
        result: ControllerResult,
        battery_inputs: ActuatorInputs | None,
        inverter_inputs: ActuatorInputs | None,
    ) -> tuple[str, tuple[str, ...]]:
        reasons = list(result.degraded_reasons)
        for prefix, inputs in (
            ("battery", battery_inputs),
            ("inverter", inverter_inputs),
        ):
            if inputs is None or inputs.command_mismatch_reason is None:
                continue
            reasons.append(f"{prefix}_{inputs.command_mismatch_reason}")

        if not reasons:
            return "nominal", ()
        unique_reasons = tuple(dict.fromkeys(reasons))
        return ",".join(unique_reasons), unique_reasons

    def _read_actuator_inputs(
        self,
        entity_config: ActuatorEntityConfig,
        actual_power_w: float | None,
        last_write_monotonic: float | None,
        last_command_target_w: float | None,
        last_command_observed_w: float | None,
    ) -> ActuatorInputs | None:
        current_limit_w = self._read_entity_float(entity_config.power_control_entity)
        if current_limit_w is None:
            return None

        seconds_since_last_write = None
        if last_write_monotonic is not None:
            seconds_since_last_write = time.monotonic() - last_write_monotonic

        command_mismatch_reason = None
        command_mismatch_w = None
        if (
            last_command_target_w is not None
            and seconds_since_last_write is not None
            and seconds_since_last_write >= _COMMAND_MISMATCH_GRACE_S
        ):
            mismatch_w = current_limit_w - last_command_target_w
            if abs(mismatch_w) >= 1.0:
                command_mismatch_w = mismatch_w
                if (
                    last_command_observed_w is not None
                    and abs(current_limit_w - last_command_observed_w) < 1.0
                ):
                    command_mismatch_reason = "probable_rejected_command"
                else:
                    command_mismatch_reason = "probable_external_override"

        return ActuatorInputs(
            current_limit_w=current_limit_w,
            actual_power_w=actual_power_w,
            seconds_since_last_write=seconds_since_last_write,
            last_command_target_w=last_command_target_w,
            command_mismatch_reason=command_mismatch_reason,
            command_mismatch_w=command_mismatch_w,
        )

    def _read_trim_actual_power(self) -> float | None:
        if self.entities.trim_actuator is None:
            return None
        return self._read_entity_float(self.entities.trim_actuator.actual_power_entity)

    def _read_trim_inputs(
        self, trim_actual_power_w: float | None
    ) -> ActuatorInputs | None:
        if self.entities.trim_actuator is None:
            return None
        return self._read_actuator_inputs(
            entity_config=self.entities.trim_actuator,
            actual_power_w=trim_actual_power_w,
            last_write_monotonic=self.last_write_monotonic["inverter"],
            last_command_target_w=self.last_command_target_w["inverter"],
            last_command_observed_w=self.last_command_observed_w["inverter"],
        )

    def _read_entity_bool(self, entity_id: str | None) -> bool:
        if entity_id is None:
            return False
        value = self.get_state(entity_id)
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        lowered = str(value).strip().lower()
        return lowered in {"on", "true", "yes", "1", "problem"}

    def _apply_soc_rail_targets(
        self,
        *,
        result: ControllerResult,
        current_discharge_limit_pct: float | None,
        current_charging_limit_pct: float | None,
        thermal_state: ThermalState,
    ) -> tuple[str, str]:
        min_soc_action = self._apply_soc_rail_target(
            entity_id=self.entities.battery_discharge_limit_entity,
            desired_pct=result.desired_min_soc_pct,
            current_pct=current_discharge_limit_pct,
            label="min_soc",
            thermal_state=thermal_state,
        )
        max_soc_action = self._apply_soc_rail_target(
            entity_id=self.entities.battery_charging_limit_entity,
            desired_pct=result.desired_max_soc_pct,
            current_pct=current_charging_limit_pct,
            label="max_soc",
            thermal_state=thermal_state,
        )
        return min_soc_action, max_soc_action

    def _apply_soc_rail_target(
        self,
        *,
        entity_id: str | None,
        desired_pct: float,
        current_pct: float | None,
        label: str,
        thermal_state: ThermalState,
    ) -> str:
        if entity_id is None:
            return "unconfigured"

        desired_value = int(round(desired_pct))
        current_value = None if current_pct is None else int(round(current_pct))
        if current_value == desired_value:
            self.last_soc_rail_target_pct[label] = desired_value
            self.last_soc_rail_observed_pct[label] = current_value
            return "aligned"

        now_monotonic = time.monotonic()
        last_target = self.last_soc_rail_target_pct[label]
        last_write_monotonic = self.last_soc_rail_write_monotonic[label]
        last_observed = self.last_soc_rail_observed_pct[label]

        service = _default_power_control_service(entity_id)
        if service is None:
            return "unsupported"

        if self.config.dry_run:
            return "dry_run"

        write_reason = "target_changed"
        if last_target == desired_value:
            if current_value != last_observed and current_value is not None:
                write_reason = "reconcile_drift"
            elif (
                last_write_monotonic is not None
                and now_monotonic - last_write_monotonic < _SOC_RAIL_RETRY_INTERVAL_S
            ):
                self.last_soc_rail_observed_pct[label] = current_value
                return "pending"
            else:
                write_reason = "retry"

        self.call_service(service, entity_id=entity_id, value=desired_value)
        self.last_soc_rail_target_pct[label] = desired_value
        self.last_soc_rail_write_monotonic[label] = now_monotonic
        self.last_soc_rail_observed_pct[label] = current_value
        self._emit_thermal_log(
            f"Updated {label} rail"
            f" entity={entity_id}"
            f" target={desired_value}%"
            f" current={current_value}%"
            f" thermal={thermal_state}"
            f" write_reason={write_reason}",
            level="INFO",
            force_main=True,
        )
        return "write"

    def _apply_actuator_result(
        self,
        entity_config: ActuatorEntityConfig,
        actuator_result: ActuatorResult,
    ) -> None:
        if actuator_result.action != "write":
            return

        self.call_service(
            entity_config.power_control_service,
            entity_id=entity_config.power_control_entity,
            **{
                entity_config.power_control_value_key: int(
                    actuator_result.target_limit_w
                )
            },
        )
        now_monotonic = time.monotonic()
        now_iso = dt.datetime.now(dt.UTC).isoformat()
        self.last_command_observed_w[entity_config.slot] = (
            actuator_result.current_limit_w
        )
        self.last_write_monotonic[entity_config.slot] = now_monotonic
        self.last_write_iso[entity_config.slot] = now_iso
        self.last_command_target_w[entity_config.slot] = actuator_result.target_limit_w

    def _handle_missing_required_state(
        self,
        consumption_w: float | None,
        primary_inputs: ActuatorInputs | None,
        trim_inputs: ActuatorInputs | None,
        primary_actual_power_w: float | None,
        trim_actual_power_w: float | None,
        soc_pct: float | None,
        discharge_limit_pct: float | None,
    ) -> bool:
        missing_entities: list[str] = []
        if consumption_w is None:
            missing_entities.append("consumption")

        available_actuators = self._available_actuator_labels(
            primary_inputs, trim_inputs
        )
        if not available_actuators:
            missing_entities.append("battery_power_control")
            if self.entities.trim_actuator is not None:
                missing_entities.append("inverter_power_control")

        if not missing_entities:
            self._log_required_entity_recovery()
            return False

        expected_reason = None
        sun_state: str | None = None
        sun_elevation_deg: float | None = None
        if "consumption" not in missing_entities and not available_actuators:
            sun_state, sun_elevation_deg = self._read_sun_status()
            expected_reason = self._expected_missing_reason(
                primary_actual_power_w=primary_actual_power_w,
                trim_actual_power_w=trim_actual_power_w,
                soc_pct=soc_pct,
                discharge_limit_pct=discharge_limit_pct,
                sun_state=sun_state,
                sun_elevation_deg=sun_elevation_deg,
            )

        now_monotonic = time.monotonic()
        now_iso = dt.datetime.now(dt.UTC).isoformat()
        missing_key = tuple(missing_entities)
        if self.missing_required_entities != missing_key:
            self._start_missing_required_episode(
                missing_key=missing_key,
                expected_reason=expected_reason,
                now_monotonic=now_monotonic,
                now_iso=now_iso,
                consumption_w=consumption_w,
                primary_inputs=primary_inputs,
                trim_inputs=trim_inputs,
            )
        else:
            self._update_missing_required_episode(
                expected_reason=expected_reason,
                now_monotonic=now_monotonic,
                now_iso=now_iso,
            )

        self._publish_status(
            state="blocked",
            reason="missing_required_entity",
            missing_entities=missing_entities,
            available_actuators=available_actuators,
            availability_state=self._missing_required_availability_state(),
            expected_missing_reason=self.missing_required_expected_reason,
            warning_active=self.missing_required_warning_active,
            missing_since_utc=self.missing_required_since_iso,
            unexpected_missing_since_utc=self.missing_required_unexpected_since_iso,
            warning_grace_s=self.availability.warning_grace_s,
            primary_power_control_available=primary_inputs is not None,
            trim_power_control_available=trim_inputs is not None,
            battery_power_control_available=primary_inputs is not None,
            inverter_power_control_available=trim_inputs is not None,
            raw_consumption_w=consumption_w,
            primary_actual_power_w=primary_actual_power_w,
            trim_actual_power_w=trim_actual_power_w,
            battery_actual_power_w=primary_actual_power_w,
            inverter_actual_power_w=trim_actual_power_w,
            battery_soc_pct=soc_pct,
            battery_discharge_limit_pct=discharge_limit_pct,
            sun_state=sun_state,
            sun_elevation_deg=sun_elevation_deg,
        )
        expected_reason = (
            self.missing_required_expected_reason or "missing_required_entity"
        )
        available_actuators_text = ",".join(available_actuators) or "none"
        self.last_control_summary = (
            "state=blocked"
            f" missing={','.join(missing_entities)}"
            f" availability={self._missing_required_availability_state()}"
            f" reason={expected_reason}"
            f" available_actuators={available_actuators_text}"
        )

        return True

    def _available_actuator_labels(
        self,
        primary_inputs: ActuatorInputs | None,
        trim_inputs: ActuatorInputs | None,
    ) -> list[str]:
        labels: list[str] = []
        if primary_inputs is not None:
            labels.append(self.entities.primary_actuator.power_control_label)
        if trim_inputs is not None and self.entities.trim_actuator is not None:
            labels.append(self.entities.trim_actuator.power_control_label)
        return labels

    def _start_missing_required_episode(
        self,
        missing_key: tuple[str, ...],
        expected_reason: str | None,
        now_monotonic: float,
        now_iso: str,
        consumption_w: float | None,
        primary_inputs: ActuatorInputs | None,
        trim_inputs: ActuatorInputs | None,
    ) -> None:
        self.missing_required_entities = missing_key
        self.missing_required_since_monotonic = now_monotonic
        self.missing_required_since_iso = now_iso
        self.missing_required_expected_reason = expected_reason

        if expected_reason is None:
            self.missing_required_unexpected_since_monotonic = now_monotonic
            self.missing_required_unexpected_since_iso = now_iso
            self.missing_required_warning_active = True
            trim_entity = None
            if self.entities.trim_actuator is not None:
                trim_entity = self.entities.trim_actuator.power_control_entity
            self.log(
                "Missing required controller entity state"
                f" (missing={','.join(missing_key)},"
                f" consumption={self.entities.consumption_entity}:{consumption_w},"
                f" battery={self.entities.primary_actuator.power_control_entity}:"
                f"{None if primary_inputs is None else primary_inputs.current_limit_w},"
                f" inverter={trim_entity}:"
                f"{None if trim_inputs is None else trim_inputs.current_limit_w})",
                level="WARNING",
            )
            return

        self.missing_required_unexpected_since_monotonic = None
        self.missing_required_unexpected_since_iso = None
        self.missing_required_warning_active = False
        self.log(
            "Required controller entity missing but currently expected"
            f" (entities={','.join(missing_key)},"
            f" reason={expected_reason})"
        )

    def _update_missing_required_episode(
        self,
        expected_reason: str | None,
        now_monotonic: float,
        now_iso: str,
    ) -> None:
        previous_reason = self.missing_required_expected_reason
        if expected_reason != previous_reason:
            self.missing_required_expected_reason = expected_reason
            if expected_reason is not None:
                self.missing_required_unexpected_since_monotonic = None
                self.missing_required_unexpected_since_iso = None
                self.missing_required_warning_active = False
                self.log(
                    "Required controller entity missing is now expected"
                    f" (entities={','.join(self.missing_required_entities or ())},"
                    f" reason={expected_reason})"
                )
                return

            self.missing_required_unexpected_since_monotonic = now_monotonic
            self.missing_required_unexpected_since_iso = now_iso
            self.missing_required_warning_active = False
            self.log(
                "Required controller entity still missing"
                " after expected condition cleared"
                f" (entities={','.join(self.missing_required_entities or ())},"
                f" previous_reason={previous_reason},"
                f" warning_in={_format_duration(self.availability.warning_grace_s)})"
            )
            return

        if expected_reason is not None or self.missing_required_warning_active:
            return

        if self.missing_required_unexpected_since_monotonic is None:
            self.missing_required_unexpected_since_monotonic = now_monotonic
            self.missing_required_unexpected_since_iso = now_iso
            return

        if (
            now_monotonic - self.missing_required_unexpected_since_monotonic
            < self.availability.warning_grace_s
        ):
            return

        self.missing_required_warning_active = True
        self.log(
            "Required controller entity still missing after warning grace period"
            f" (entities={','.join(self.missing_required_entities or ())},"
            f" grace={_format_duration(self.availability.warning_grace_s)})",
            level="WARNING",
        )

    def _expected_missing_reason(
        self,
        primary_actual_power_w: float | None,
        trim_actual_power_w: float | None,
        soc_pct: float | None,
        discharge_limit_pct: float | None,
        sun_state: str | None,
        sun_elevation_deg: float | None,
    ) -> str | None:
        if (
            soc_pct is not None
            and discharge_limit_pct is not None
            and soc_pct <= discharge_limit_pct + self.config.soc_stop_buffer_pct
        ):
            return "battery_reserve"

        known_actual_power_w = [
            value
            for value in (primary_actual_power_w, trim_actual_power_w)
            if value is not None
        ]
        if (
            not known_actual_power_w
            or sum(known_actual_power_w) > self.availability.idle_output_threshold_w
        ):
            return None

        if sun_state == "below_horizon":
            return "sun_down"

        if (
            sun_elevation_deg is not None
            and sun_elevation_deg < self.availability.low_sun_elevation_deg
        ):
            return "low_sun"

        return None

    def _read_sun_status(self) -> tuple[str | None, float | None]:
        sun_state = _as_non_empty_str(self.get_state("sun.sun"))
        sun_attributes = self._read_entity_attributes("sun.sun")
        sun_elevation_deg = _as_float(sun_attributes.get("elevation"))
        return sun_state, sun_elevation_deg

    def _missing_required_availability_state(self) -> str:
        if self.missing_required_expected_reason is not None:
            return "expected_missing"
        if self.missing_required_warning_active:
            return "warning_active"
        return "warning_grace"

    def _log_required_entity_recovery(self) -> None:
        if self.missing_required_entities is None:
            return

        duration_text = "unknown duration"
        if self.missing_required_since_monotonic is not None:
            duration_s = time.monotonic() - self.missing_required_since_monotonic
            duration_text = _format_duration(duration_s)

        self.log(
            "Required controller entity state recovered"
            f" after {duration_text}"
            f" (entities={','.join(self.missing_required_entities)},"
            f" warning_active={self.missing_required_warning_active},"
            f" last_expected_reason={self.missing_required_expected_reason})"
        )
        self.missing_required_entities = None
        self.missing_required_since_monotonic = None
        self.missing_required_since_iso = None
        self.missing_required_expected_reason = None
        self.missing_required_unexpected_since_monotonic = None
        self.missing_required_unexpected_since_iso = None
        self.missing_required_warning_active = False

    def _format_actuator_summary(self, actuator_result: ActuatorResult) -> str:
        current_text = "None"
        if actuator_result.current_limit_w is not None:
            current_text = f"{int(actuator_result.current_limit_w)}W"
        applied_text = "None"
        if actuator_result.applied_limit_w is not None:
            applied_text = f"{int(actuator_result.applied_limit_w)}W"
        return (
            f"{actuator_result.label}:"
            f"allowed={int(actuator_result.allowed_max_output_w)}W:"
            f"requested={int(actuator_result.requested_limit_w)}W:"
            f"translated={int(actuator_result.translated_limit_w)}W:"
            f"applied={applied_text}:"
            f"action={actuator_result.action}:"
            f"reason={actuator_result.reason}:"
            f"current={current_text}"
        )

    def _format_trim_summary(self, actuator_result: ActuatorResult | None) -> str:
        if actuator_result is None:
            return "None"
        return self._format_actuator_summary(actuator_result)

    def _read_entity_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        return _as_float(self.get_state(entity_id))

    def _read_entity_attributes(self, entity_id: str) -> dict[str, Any]:
        payload = self.get_state(entity_id, attribute="all")
        if isinstance(payload, Mapping):
            attributes = payload.get("attributes")
            if isinstance(attributes, Mapping):
                return dict(attributes)
        return {}

    def _debug_entity(self, suffix: str) -> str:
        return f"{self.entities.debug_entity_prefix}_{suffix}"

    def _most_recent_last_write_iso(self) -> str | None:
        timestamps = [
            timestamp
            for timestamp in self.last_write_iso.values()
            if timestamp is not None
        ]
        if not timestamps:
            return None
        return max(timestamps)

    def _publish_result(
        self,
        result: ControllerResult,
        inputs: ControllerInputs,
        tw_metrics: TimeWeightedMetrics,
        *,
        degraded_mode: str,
        degraded_reasons: tuple[str, ...],
        current_discharge_limit_pct: float | None,
        current_charging_limit_pct: float | None,
        min_soc_action: str,
        max_soc_action: str,
        device_contributions: tuple[DeviceContribution, ...],
    ) -> None:
        state = "running"
        if self.config.dry_run:
            state = "dry_run"

        battery_inputs = inputs.primary_actuator
        inverter_inputs = inputs.trim_actuator
        trim_result = result.trim_actuator
        trim_entity = self.entities.trim_actuator
        total_actual_power_w = None
        actual_values = [
            value
            for value in (
                result.primary_actuator.actual_power_w,
                None if trim_result is None else trim_result.actual_power_w,
            )
            if value is not None
        ]
        if actual_values:
            total_actual_power_w = sum(actual_values)

        attributes = {
            "consumption_entity": self.entities.consumption_entity,
            "net_consumption_entity": self.entities.net_consumption_entity,
            "power_control_entity": (
                self.entities.primary_actuator.power_control_entity
            ),
            "battery_power_control_entity": (
                self.entities.primary_actuator.power_control_entity
            ),
            "power_control_service": (
                self.entities.primary_actuator.power_control_service
            ),
            "battery_power_control_service": (
                self.entities.primary_actuator.power_control_service
            ),
            "power_control_value_key": (
                self.entities.primary_actuator.power_control_value_key
            ),
            "battery_power_control_value_key": (
                self.entities.primary_actuator.power_control_value_key
            ),
            "power_control_label": self.entities.primary_actuator.power_control_label,
            "battery_power_control_label": (
                self.entities.primary_actuator.power_control_label
            ),
            "actual_power_entity": self.entities.primary_actuator.actual_power_entity,
            "battery_actual_power_entity": (
                self.entities.primary_actuator.actual_power_entity
            ),
            "trim_power_control_entity": None
            if trim_entity is None
            else trim_entity.power_control_entity,
            "inverter_power_control_entity": None
            if trim_entity is None
            else trim_entity.power_control_entity,
            "trim_power_control_service": None
            if trim_entity is None
            else trim_entity.power_control_service,
            "inverter_power_control_service": None
            if trim_entity is None
            else trim_entity.power_control_service,
            "trim_power_control_value_key": None
            if trim_entity is None
            else trim_entity.power_control_value_key,
            "inverter_power_control_value_key": None
            if trim_entity is None
            else trim_entity.power_control_value_key,
            "trim_power_control_label": None
            if trim_entity is None
            else trim_entity.power_control_label,
            "inverter_power_control_label": None
            if trim_entity is None
            else trim_entity.power_control_label,
            "trim_actual_power_entity": None
            if trim_entity is None
            else trim_entity.actual_power_entity,
            "inverter_actual_power_entity": None
            if trim_entity is None
            else trim_entity.actual_power_entity,
            "battery_temperature_entity": self.entities.battery_temperature_entity,
            "battery_soc_entity": self.entities.battery_soc_entity,
            "battery_discharge_limit_entity": (
                self.entities.battery_discharge_limit_entity
            ),
            "battery_charging_limit_entity": (
                self.entities.battery_charging_limit_entity
            ),
            "battery_heating_entity": self.entities.battery_heating_entity,
            "battery_high_temp_alarm_entity": (
                self.entities.battery_high_temp_alarm_entity
            ),
            "action": result.action,
            "reason": result.reason,
            "device_feed_forward_w": round(result.device_feed_forward_w, 1),
            "active_device_feed_forward": [
                contribution.name
                for contribution in device_contributions
                if contribution.active
            ],
            "device_contributions": {
                contribution.name: {
                    "entity_id": contribution.entity_id,
                    "kind": contribution.kind,
                    "state": contribution.state,
                    "power_w": round(contribution.power_w, 1),
                    "bias_w": round(contribution.bias_w, 1),
                    "confidence": round(contribution.confidence, 2),
                    "active": contribution.active,
                }
                for contribution in device_contributions
            },
            "degraded_mode": degraded_mode,
            "degraded_reasons": list(degraded_reasons),
            "thermal_state": result.thermal_state,
            "thermal_reason": result.thermal_reason,
            "desired_min_soc_pct": round(result.desired_min_soc_pct, 1),
            "desired_max_soc_pct": round(result.desired_max_soc_pct, 1),
            "battery_cap_limit_w": round(result.battery_cap_limit_w, 1),
            "available_actuators": self._available_actuator_labels(
                inputs.primary_actuator,
                inputs.trim_actuator,
            ),
            "primary_power_control_available": result.primary_actuator.available,
            "battery_power_control_available": result.primary_actuator.available,
            "trim_power_control_available": False
            if trim_result is None
            else trim_result.available,
            "inverter_power_control_available": False
            if trim_result is None
            else trim_result.available,
            "current_power_control_w": round(result.current_limit_w, 1),
            "target_power_control_w": round(result.target_limit_w, 1),
            "requested_target_power_control_w": round(result.requested_target_w, 1),
            "desired_target_w": round(result.desired_target_w, 1),
            "cap_cmd_w": round(result.cap_cmd_w, 1),
            "effective_target_power_control_w": None
            if result.effective_target_w is None
            else round(result.effective_target_w, 1),
            "estimated_load_fast_w": round(result.estimated_load_fast_w, 1),
            "estimated_load_slow_w": round(result.estimated_load_slow_w, 1),
            "visible_load_pre_event_median_w": round(
                result.visible_load_pre_event_median_w,
                1,
            ),
            "fast_error_w": round(result.fast_error_w, 1),
            "slow_error_w": round(result.slow_error_w, 1),
            "visible_margin_w": None
            if result.visible_margin_w is None
            else round(result.visible_margin_w, 1),
            "primary_current_power_control_w": None
            if result.primary_actuator.current_limit_w is None
            else round(result.primary_actuator.current_limit_w, 1),
            "battery_current_power_control_w": None
            if result.primary_actuator.current_limit_w is None
            else round(result.primary_actuator.current_limit_w, 1),
            "primary_requested_power_control_w": round(
                result.primary_actuator.requested_limit_w, 1
            ),
            "battery_requested_power_control_w": round(
                result.primary_actuator.requested_limit_w, 1
            ),
            "primary_target_power_control_w": round(
                result.primary_actuator.target_limit_w, 1
            ),
            "battery_target_power_control_w": round(
                result.primary_actuator.target_limit_w, 1
            ),
            "primary_applied_power_control_w": None
            if result.primary_actuator.applied_limit_w is None
            else round(result.primary_actuator.applied_limit_w, 1),
            "battery_applied_power_control_w": None
            if result.primary_actuator.applied_limit_w is None
            else round(result.primary_actuator.applied_limit_w, 1),
            "primary_action": result.primary_actuator.action,
            "battery_action": result.primary_actuator.action,
            "primary_reason": result.primary_actuator.reason,
            "battery_reason": result.primary_actuator.reason,
            "battery_command_mismatch_reason": None
            if battery_inputs is None
            else battery_inputs.command_mismatch_reason,
            "battery_command_mismatch_w": None
            if battery_inputs is None or battery_inputs.command_mismatch_w is None
            else round(battery_inputs.command_mismatch_w, 1),
            "primary_translated_power_control_w": round(
                result.primary_actuator.translated_limit_w, 1
            ),
            "battery_translated_power_control_w": round(
                result.primary_actuator.translated_limit_w, 1
            ),
            "trim_current_power_control_w": None
            if trim_result is None or trim_result.current_limit_w is None
            else round(trim_result.current_limit_w, 1),
            "inverter_current_power_control_w": None
            if trim_result is None or trim_result.current_limit_w is None
            else round(trim_result.current_limit_w, 1),
            "trim_requested_power_control_w": None
            if trim_result is None
            else round(trim_result.requested_limit_w, 1),
            "inverter_requested_power_control_w": None
            if trim_result is None
            else round(trim_result.requested_limit_w, 1),
            "trim_target_power_control_w": None
            if trim_result is None
            else round(trim_result.target_limit_w, 1),
            "inverter_target_power_control_w": None
            if trim_result is None
            else round(trim_result.target_limit_w, 1),
            "trim_applied_power_control_w": None
            if trim_result is None or trim_result.applied_limit_w is None
            else round(trim_result.applied_limit_w, 1),
            "inverter_applied_power_control_w": None
            if trim_result is None or trim_result.applied_limit_w is None
            else round(trim_result.applied_limit_w, 1),
            "trim_action": None if trim_result is None else trim_result.action,
            "inverter_action": None if trim_result is None else trim_result.action,
            "trim_reason": None if trim_result is None else trim_result.reason,
            "inverter_reason": None if trim_result is None else trim_result.reason,
            "inverter_command_mismatch_reason": None
            if inverter_inputs is None
            else inverter_inputs.command_mismatch_reason,
            "inverter_command_mismatch_w": None
            if inverter_inputs is None or inverter_inputs.command_mismatch_w is None
            else round(inverter_inputs.command_mismatch_w, 1),
            "trim_translated_power_control_w": None
            if trim_result is None
            else round(trim_result.translated_limit_w, 1),
            "inverter_translated_power_control_w": None
            if trim_result is None
            else round(trim_result.translated_limit_w, 1),
            "raw_consumption_w": round(inputs.consumption_w, 1),
            "effective_consumption_w": round(result.effective_consumption_w, 1),
            "smoothed_consumption_w": round(result.smoothed_consumption_w, 1),
            "tw_consumption_fast_mean_w": None
            if tw_metrics.consumption_fast_mean_w is None
            else round(tw_metrics.consumption_fast_mean_w, 1),
            "tw_consumption_slow_q20_w": None
            if tw_metrics.consumption_slow_q20_w is None
            else round(tw_metrics.consumption_slow_q20_w, 1),
            "tw_consumption_pre_event_median_w": None
            if tw_metrics.consumption_pre_event_median_w is None
            else round(tw_metrics.consumption_pre_event_median_w, 1),
            "raw_net_consumption_w": None
            if result.raw_net_consumption_w is None
            else round(result.raw_net_consumption_w, 1),
            "smoothed_net_consumption_w": None
            if result.smoothed_net_consumption_w is None
            else round(result.smoothed_net_consumption_w, 1),
            "tw_net_fast_mean_w": None
            if tw_metrics.net_fast_mean_w is None
            else round(tw_metrics.net_fast_mean_w, 1),
            "tw_net_slow_q20_w": None
            if tw_metrics.net_slow_q20_w is None
            else round(tw_metrics.net_slow_q20_w, 1),
            "net_correction_w": round(result.net_correction_w, 1),
            "actual_power_w": None
            if total_actual_power_w is None
            else round(total_actual_power_w, 1),
            "primary_actual_power_w": None
            if result.primary_actuator.actual_power_w is None
            else round(result.primary_actuator.actual_power_w, 1),
            "battery_actual_power_w": None
            if result.primary_actuator.actual_power_w is None
            else round(result.primary_actuator.actual_power_w, 1),
            "trim_actual_power_w": None
            if trim_result is None or trim_result.actual_power_w is None
            else round(trim_result.actual_power_w, 1),
            "inverter_actual_power_w": None
            if trim_result is None or trim_result.actual_power_w is None
            else round(trim_result.actual_power_w, 1),
            "battery_soc_pct": None
            if inputs.soc_pct is None
            else round(inputs.soc_pct, 1),
            "battery_temperature_t5_c": None
            if tw_metrics.battery_temp_t5_c is None
            else round(tw_metrics.battery_temp_t5_c, 1),
            "battery_temperature_t30_c": None
            if tw_metrics.battery_temp_t30_c is None
            else round(tw_metrics.battery_temp_t30_c, 1),
            "battery_heating_active": inputs.battery_heating_active,
            "battery_high_temp_alarm_active": inputs.battery_high_temp_alarm_active,
            "battery_discharge_limit_pct": None
            if current_discharge_limit_pct is None
            else round(current_discharge_limit_pct, 1),
            "battery_charging_limit_pct": None
            if current_charging_limit_pct is None
            else round(current_charging_limit_pct, 1),
            "battery_min_soc_action": min_soc_action,
            "battery_max_soc_action": max_soc_action,
            "allowed_max_output_w": round(result.allowed_max_output_w, 1),
            "primary_allowed_max_output_w": round(
                result.primary_allowed_max_output_w, 1
            ),
            "battery_allowed_max_output_w": round(
                result.primary_allowed_max_output_w, 1
            ),
            "trim_allowed_max_output_w": round(result.trim_allowed_max_output_w, 1),
            "inverter_allowed_max_output_w": round(result.trim_allowed_max_output_w, 1),
            "availability_warning_grace_s": round(self.availability.warning_grace_s, 1),
            "availability_idle_output_threshold_w": round(
                self.availability.idle_output_threshold_w, 1
            ),
            "availability_low_sun_elevation_deg": round(
                self.availability.low_sun_elevation_deg, 1
            ),
            "baseline_load_w": round(self.config.baseline_load_w, 1),
            "primary_seconds_since_last_write": None
            if inputs.primary_actuator is None
            or inputs.primary_actuator.seconds_since_last_write is None
            else round(inputs.primary_actuator.seconds_since_last_write, 1),
            "trim_seconds_since_last_write": None
            if inputs.trim_actuator is None
            or inputs.trim_actuator.seconds_since_last_write is None
            else round(inputs.trim_actuator.seconds_since_last_write, 1),
            "last_write_utc": self._most_recent_last_write_iso(),
            "primary_last_write_utc": self.last_write_iso["battery"],
            "trim_last_write_utc": self.last_write_iso["inverter"],
            "battery_last_write_utc": self.last_write_iso["battery"],
            "inverter_last_write_utc": self.last_write_iso["inverter"],
            "export_fast": result.export_fast,
            "dry_run": self.config.dry_run,
        }

        self.set_state(self._debug_entity("status"), state=state, attributes=attributes)
        self.set_state(
            self._debug_entity("target_limit"),
            state=_sensor_state(int(result.target_limit_w)),
            attributes={"unit_of_measurement": "W"},
        )
        self.set_state(
            self._debug_entity("primary_target_limit"),
            state=_sensor_state(int(result.primary_actuator.target_limit_w)),
            attributes={"unit_of_measurement": "W"},
        )
        if trim_result is not None:
            self.set_state(
                self._debug_entity("trim_target_limit"),
                state=_sensor_state(int(trim_result.target_limit_w)),
                attributes={"unit_of_measurement": "W"},
            )
        self.set_state(
            self._debug_entity("smoothed_consumption"),
            state=_sensor_state(round(result.smoothed_consumption_w, 1)),
            attributes={"unit_of_measurement": "W"},
        )
        if tw_metrics.consumption_fast_mean_w is not None:
            self.set_state(
                self._debug_entity("tw_consumption_fast_mean"),
                state=_sensor_state(round(tw_metrics.consumption_fast_mean_w, 1)),
                attributes={"unit_of_measurement": "W"},
            )
        if tw_metrics.consumption_slow_q20_w is not None:
            self.set_state(
                self._debug_entity("tw_consumption_slow_q20"),
                state=_sensor_state(round(tw_metrics.consumption_slow_q20_w, 1)),
                attributes={"unit_of_measurement": "W"},
            )
        if tw_metrics.consumption_pre_event_median_w is not None:
            self.set_state(
                self._debug_entity("tw_consumption_pre_event_median"),
                state=_sensor_state(
                    round(tw_metrics.consumption_pre_event_median_w, 1)
                ),
                attributes={"unit_of_measurement": "W"},
            )
        if result.smoothed_net_consumption_w is not None:
            self.set_state(
                self._debug_entity("smoothed_net"),
                state=_sensor_state(round(result.smoothed_net_consumption_w, 1)),
                attributes={"unit_of_measurement": "W"},
            )
        if tw_metrics.net_fast_mean_w is not None:
            self.set_state(
                self._debug_entity("tw_net_fast_mean"),
                state=_sensor_state(round(tw_metrics.net_fast_mean_w, 1)),
                attributes={"unit_of_measurement": "W"},
            )
        if tw_metrics.net_slow_q20_w is not None:
            self.set_state(
                self._debug_entity("tw_net_slow_q20"),
                state=_sensor_state(round(tw_metrics.net_slow_q20_w, 1)),
                attributes={"unit_of_measurement": "W"},
            )
        if tw_metrics.battery_temp_t5_c is not None:
            self.set_state(
                self._debug_entity("battery_temp_t5"),
                state=_sensor_state(round(tw_metrics.battery_temp_t5_c, 1)),
                attributes={"unit_of_measurement": "°C"},
            )
        if tw_metrics.battery_temp_t30_c is not None:
            self.set_state(
                self._debug_entity("battery_temp_t30"),
                state=_sensor_state(round(tw_metrics.battery_temp_t30_c, 1)),
                attributes={"unit_of_measurement": "°C"},
            )

    def _publish_status(self, state: str, reason: str, **attributes: Any) -> None:
        payload = {"reason": reason, **attributes}
        self.set_state(self._debug_entity("status"), state=state, attributes=payload)
