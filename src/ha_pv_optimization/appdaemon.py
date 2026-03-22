from __future__ import annotations

import datetime as dt
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .core import (
    ControllerConfig,
    ControllerInputs,
    ControllerResult,
    PowerControllerCore,
)

try:
    from appdaemon.plugins.hass.hassapi import (
        Hass as BaseHass,  # type: ignore[import-not-found]
    )
except ImportError:  # pragma: no cover

    class BaseHass:  # type: ignore[no-redef]
        args: dict[str, Any]

        def log(self, message: str, level: str = "INFO") -> None:
            return None

        def run_every(self, callback: Any, start: Any, interval: Any) -> None:
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


def _default_power_control_service(entity_id: str) -> str | None:
    domain = entity_id.split(".", 1)[0]
    if domain in {"number", "input_number"}:
        return f"{domain}/set_value"
    return None


@dataclass(frozen=True)
class EntityConfig:
    consumption_entity: str
    power_control_entity: str
    net_consumption_entity: str | None
    actual_power_entity: str | None
    battery_soc_entity: str | None
    battery_discharge_limit_entity: str | None
    power_control_service: str
    power_control_value_key: str
    power_control_label: str
    debug_entity_prefix: str


class HaPvOptimization(BaseHass):  # type: ignore[misc]
    def initialize(self) -> None:
        self.entities = self._build_entity_config()
        self.config = self._build_controller_config()
        self.controller = PowerControllerCore(self.config)
        self.last_write_monotonic: float | None = None
        self.last_write_iso: str | None = None

        self.log(
            "Initialized ha-pv-optimization controller"
            f" (consumption={self.entities.consumption_entity},"
            f" power_control={self.entities.power_control_entity},"
            f" service={self.entities.power_control_service},"
            f" dry_run={self.config.dry_run})"
        )

        start = dt.datetime.now() + dt.timedelta(seconds=1)
        self.run_every(self._control_tick, start, self.config.control_interval_s)

    def _build_entity_config(self) -> EntityConfig:
        consumption_entity = self._require_entity("consumption_entity")
        power_control_entity = self._require_entity("power_control_entity")
        power_control_service = _as_non_empty_str(
            self.args.get("power_control_service")
        )
        if power_control_service is None:
            power_control_service = _default_power_control_service(power_control_entity)
        if power_control_service is None:
            raise ValueError(
                "Set `power_control_service` when `power_control_entity` "
                "is not a `number.*` or `input_number.*` entity."
            )

        return EntityConfig(
            consumption_entity=consumption_entity,
            power_control_entity=power_control_entity,
            net_consumption_entity=_as_non_empty_str(
                self.args.get("net_consumption_entity")
            ),
            actual_power_entity=_as_non_empty_str(self.args.get("actual_power_entity")),
            battery_soc_entity=_as_non_empty_str(self.args.get("battery_soc_entity")),
            battery_discharge_limit_entity=_as_non_empty_str(
                self.args.get("battery_discharge_limit_entity")
            ),
            power_control_service=power_control_service,
            power_control_value_key=_as_non_empty_str(
                self.args.get("power_control_value_key")
            )
            or "value",
            power_control_label=_as_non_empty_str(self.args.get("power_control_label"))
            or power_control_entity,
            debug_entity_prefix=_as_non_empty_str(self.args.get("debug_entity_prefix"))
            or "sensor.ha_pv_optimization",
        )

    def _build_controller_config(self) -> ControllerConfig:
        actuator_attributes = self._read_entity_attributes(
            self.entities.power_control_entity
        )
        inferred_min_output_w = _as_float(actuator_attributes.get("min"))
        inferred_max_output_w = _as_float(actuator_attributes.get("max"))
        inferred_step_w = _as_float(actuator_attributes.get("step"))

        min_output_w = self._get_float(
            "min_output_w",
            0.0 if inferred_min_output_w is None else inferred_min_output_w,
        )
        max_output_w = _as_float(self.args.get("max_output_w"))
        if max_output_w is None:
            max_output_w = inferred_max_output_w
        if max_output_w is None:
            raise ValueError(
                "Set `max_output_w` or use a power-control entity "
                "that exposes a numeric `max` attribute."
            )

        power_step_w = self._get_float(
            "power_step_w",
            50.0 if inferred_step_w is None else inferred_step_w,
        )
        min_change_w = self._get_float("min_change_w", power_step_w)

        if max_output_w < min_output_w:
            raise ValueError(
                "`max_output_w` must be greater than or equal to `min_output_w`."
            )

        return ControllerConfig(
            control_interval_s=self._get_float("control_interval_s", 30.0),
            consumption_ema_tau_s=self._get_float("consumption_ema_tau_s", 75.0),
            net_ema_tau_s=self._get_float("net_ema_tau_s", 45.0),
            baseline_load_w=self._get_float("baseline_load_w", 0.0),
            deadband_w=self._get_float("deadband_w", 50.0),
            zero_output_threshold_w=self._get_float("zero_output_threshold_w", 25.0),
            fast_export_threshold_w=self._get_float("fast_export_threshold_w", -80.0),
            import_correction_gain=self._get_float("import_correction_gain", 0.35),
            export_correction_gain=self._get_float("export_correction_gain", 1.0),
            min_output_w=min_output_w,
            max_output_w=max_output_w,
            power_step_w=power_step_w,
            min_change_w=min_change_w,
            min_write_interval_s=self._get_float("min_write_interval_s", 60.0),
            max_increase_per_cycle_w=self._get_float("max_increase_per_cycle_w", 150.0),
            max_decrease_per_cycle_w=self._get_float("max_decrease_per_cycle_w", 300.0),
            emergency_max_decrease_per_cycle_w=self._get_float(
                "emergency_max_decrease_per_cycle_w",
                500.0,
            ),
            soc_stop_buffer_pct=self._get_float("soc_stop_buffer_pct", 3.0),
            soc_full_power_buffer_pct=self._get_float(
                "soc_full_power_buffer_pct", 10.0
            ),
            soc_min_derate_factor=self._get_float("soc_min_derate_factor", 0.25),
            net_export_negative=_as_bool(self.args.get("net_export_negative"), True),
            dry_run=_as_bool(self.args.get("dry_run"), True),
        )

    def _require_entity(self, key: str) -> str:
        value = _as_non_empty_str(self.args.get(key))
        if value is None:
            raise ValueError(f"Missing required AppDaemon argument: `{key}`")
        return value

    def _get_float(self, key: str, default: float) -> float:
        value = _as_float(self.args.get(key))
        return default if value is None else value

    def _control_tick(self, kwargs: dict[str, Any]) -> None:
        consumption_w = self._read_entity_float(self.entities.consumption_entity)
        current_limit_w = self._read_entity_float(self.entities.power_control_entity)

        if consumption_w is None or current_limit_w is None:
            self._publish_status(
                state="blocked",
                reason="missing_required_entity",
                raw_consumption_w=consumption_w,
                current_limit_w=current_limit_w,
            )
            self.log(
                "Missing required controller entity state"
                f" (consumption={self.entities.consumption_entity}:{consumption_w},"
                f" power_control={self.entities.power_control_entity}:"
                f"{current_limit_w})",
                level="WARNING",
            )
            return

        now_monotonic = time.monotonic()
        seconds_since_last_write = None
        if self.last_write_monotonic is not None:
            seconds_since_last_write = now_monotonic - self.last_write_monotonic

        inputs = ControllerInputs(
            consumption_w=consumption_w,
            current_limit_w=current_limit_w,
            net_consumption_w=self._read_entity_float(
                self.entities.net_consumption_entity
            ),
            actual_power_w=self._read_entity_float(self.entities.actual_power_entity),
            soc_pct=self._read_entity_float(self.entities.battery_soc_entity),
            discharge_limit_pct=self._read_entity_float(
                self.entities.battery_discharge_limit_entity
            ),
            seconds_since_last_write=seconds_since_last_write,
        )
        result = self.controller.step(inputs)

        if result.action == "write":
            self.call_service(
                self.entities.power_control_service,
                entity_id=self.entities.power_control_entity,
                **{self.entities.power_control_value_key: int(result.target_limit_w)},
            )
            self.last_write_monotonic = now_monotonic
            self.last_write_iso = dt.datetime.now(dt.UTC).isoformat()
            self.log(
                "Updated power control entity"
                f" entity={self.entities.power_control_entity}"
                f" service={self.entities.power_control_service}"
                f" target={int(result.target_limit_w)}W"
                f" current={int(result.current_limit_w)}W"
                f" reason={result.reason}"
            )
        elif result.action == "dry_run":
            self.log(
                "Dry-run power control update"
                f" entity={self.entities.power_control_entity}"
                f" service={self.entities.power_control_service}"
                f" target={int(result.target_limit_w)}W"
                f" current={int(result.current_limit_w)}W"
                f" reason={result.reason}"
            )

        self.log(
            "Control cycle"
            f" action={result.action}"
            f" target={int(result.target_limit_w)}W"
            f" consumption={result.effective_consumption_w:.1f}W"
            f" smoothed={result.smoothed_consumption_w:.1f}W"
            f" net={result.raw_net_consumption_w}"
            f" reason={result.reason}",
            level="DEBUG",
        )

        self._publish_result(result, inputs)

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

    def _publish_result(
        self, result: ControllerResult, inputs: ControllerInputs
    ) -> None:
        state = "running"
        if self.config.dry_run:
            state = "dry_run"
        if result.action == "skip" and result.reason.startswith("missing"):
            state = "blocked"

        attributes = {
            "consumption_entity": self.entities.consumption_entity,
            "net_consumption_entity": self.entities.net_consumption_entity,
            "power_control_entity": self.entities.power_control_entity,
            "power_control_service": self.entities.power_control_service,
            "power_control_value_key": self.entities.power_control_value_key,
            "power_control_label": self.entities.power_control_label,
            "actual_power_entity": self.entities.actual_power_entity,
            "battery_soc_entity": self.entities.battery_soc_entity,
            "battery_discharge_limit_entity": (
                self.entities.battery_discharge_limit_entity
            ),
            "action": result.action,
            "reason": result.reason,
            "current_power_control_w": round(result.current_limit_w, 1),
            "target_power_control_w": round(result.target_limit_w, 1),
            "raw_consumption_w": round(inputs.consumption_w, 1),
            "effective_consumption_w": round(result.effective_consumption_w, 1),
            "smoothed_consumption_w": round(result.smoothed_consumption_w, 1),
            "raw_net_consumption_w": None
            if result.raw_net_consumption_w is None
            else round(result.raw_net_consumption_w, 1),
            "smoothed_net_consumption_w": None
            if result.smoothed_net_consumption_w is None
            else round(result.smoothed_net_consumption_w, 1),
            "net_correction_w": round(result.net_correction_w, 1),
            "actual_power_w": None
            if inputs.actual_power_w is None
            else round(inputs.actual_power_w, 1),
            "battery_soc_pct": None
            if inputs.soc_pct is None
            else round(inputs.soc_pct, 1),
            "battery_discharge_limit_pct": None
            if inputs.discharge_limit_pct is None
            else round(inputs.discharge_limit_pct, 1),
            "allowed_max_output_w": round(result.allowed_max_output_w, 1),
            "baseline_load_w": round(self.config.baseline_load_w, 1),
            "seconds_since_last_write": None
            if inputs.seconds_since_last_write is None
            else round(inputs.seconds_since_last_write, 1),
            "last_write_utc": self.last_write_iso,
            "export_fast": result.export_fast,
            "dry_run": self.config.dry_run,
        }

        self.set_state(self._debug_entity("status"), state=state, attributes=attributes)
        self.set_state(
            self._debug_entity("target_limit"),
            state=int(result.target_limit_w),
            attributes={"unit_of_measurement": "W"},
        )
        self.set_state(
            self._debug_entity("smoothed_consumption"),
            state=round(result.smoothed_consumption_w, 1),
            attributes={"unit_of_measurement": "W"},
        )
        if result.smoothed_net_consumption_w is not None:
            self.set_state(
                self._debug_entity("smoothed_net"),
                state=round(result.smoothed_net_consumption_w, 1),
                attributes={"unit_of_measurement": "W"},
            )

    def _publish_status(self, state: str, reason: str, **attributes: Any) -> None:
        payload = {"reason": reason, **attributes}
        self.set_state(self._debug_entity("status"), state=state, attributes=payload)
