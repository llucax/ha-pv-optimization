from __future__ import annotations

from .models import (
    ActuatorConfig,
    ActuatorInputs,
    ActuatorResult,
    ControllerConfig,
    ControllerInputs,
    ControllerResult,
)
from .signals import clamp, ema, quantize_down, tau_to_alpha


class PowerControllerCore:
    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self.smoothed_consumption_w: float | None = None
        self.smoothed_net_consumption_w: float | None = None

    def step(self, inputs: ControllerInputs) -> ControllerResult:
        effective_consumption_w = max(
            0.0, inputs.consumption_w + self.config.baseline_load_w
        )

        consumption_alpha = tau_to_alpha(
            self.config.control_interval_s,
            self.config.consumption_ema_tau_s,
        )
        self.smoothed_consumption_w = ema(
            self.smoothed_consumption_w,
            effective_consumption_w,
            consumption_alpha,
        )

        raw_net_w = inputs.net_consumption_w
        if raw_net_w is not None:
            if not self.config.net_export_negative:
                raw_net_w = -raw_net_w
            net_alpha = tau_to_alpha(
                self.config.control_interval_s,
                self.config.net_ema_tau_s,
            )
            self.smoothed_net_consumption_w = ema(
                self.smoothed_net_consumption_w,
                raw_net_w,
                net_alpha,
            )

        requested_target_w = self.smoothed_consumption_w
        net_correction_w = 0.0
        export_fast = False
        reason_parts: list[str] = []

        if raw_net_w is not None:
            if raw_net_w <= self.config.fast_export_threshold_w:
                net_correction_w = raw_net_w
                export_fast = True
                reason_parts.append("fast_export")
            else:
                net_signal_w = self.smoothed_net_consumption_w
                if (
                    net_signal_w is not None
                    and abs(net_signal_w) >= self.config.deadband_w
                ):
                    gain = (
                        self.config.export_correction_gain
                        if net_signal_w < 0
                        else self.config.import_correction_gain
                    )
                    net_correction_w = gain * net_signal_w
                    reason_parts.append("net_correction")

        requested_target_w += net_correction_w

        if effective_consumption_w <= self.config.zero_output_threshold_w and (
            raw_net_w is None or abs(raw_net_w) <= self.config.deadband_w
        ):
            requested_target_w = 0.0
            reason_parts.append("low_demand_zero")

        battery_allowed_max_output_w = self._allowed_battery_output_w(inputs)
        inverter_allowed_max_output_w = self._allowed_inverter_output_w(inputs)
        allowed_path_cap_w = self._allowed_path_cap_w(
            inputs=inputs,
            battery_allowed_max_output_w=battery_allowed_max_output_w,
            inverter_allowed_max_output_w=inverter_allowed_max_output_w,
        )
        desired_target_w = clamp(requested_target_w, 0.0, allowed_path_cap_w)

        battery_result = self._build_actuator_result(
            config=self.config.battery_actuator,
            inputs=inputs.battery_actuator,
            desired_target_w=desired_target_w,
            allowed_max_output_w=battery_allowed_max_output_w,
            other_actuator_available=inputs.inverter_actuator is not None,
            export_fast=export_fast,
        )
        inverter_result = None
        if self.config.inverter_actuator is not None:
            inverter_result = self._build_actuator_result(
                config=self.config.inverter_actuator,
                inputs=inputs.inverter_actuator,
                desired_target_w=desired_target_w,
                allowed_max_output_w=inverter_allowed_max_output_w,
                other_actuator_available=inputs.battery_actuator is not None,
                export_fast=export_fast,
            )

        action = self._combined_action(battery_result, inverter_result)
        reason_parts.extend(
            self._actuator_reason_parts(battery_result, inverter_result)
        )
        if not reason_parts:
            reason_parts.append("steady")

        representative_current_w = self._representative_current_limit(inputs)
        effective_target_w = self._effective_path_limit_w(
            battery_result, inverter_result
        )

        return ControllerResult(
            action=action,
            target_limit_w=desired_target_w,
            requested_target_w=requested_target_w,
            desired_target_w=desired_target_w,
            effective_target_w=effective_target_w,
            effective_consumption_w=effective_consumption_w,
            smoothed_consumption_w=self.smoothed_consumption_w,
            raw_net_consumption_w=raw_net_w,
            smoothed_net_consumption_w=self.smoothed_net_consumption_w,
            net_correction_w=net_correction_w,
            allowed_max_output_w=allowed_path_cap_w,
            primary_allowed_max_output_w=battery_allowed_max_output_w,
            trim_allowed_max_output_w=inverter_allowed_max_output_w,
            export_fast=export_fast,
            reason=",".join(reason_parts),
            current_limit_w=representative_current_w,
            primary_actuator=battery_result,
            trim_actuator=inverter_result,
        )

    def _allowed_path_cap_w(
        self,
        inputs: ControllerInputs,
        battery_allowed_max_output_w: float,
        inverter_allowed_max_output_w: float,
    ) -> float:
        allowed_caps: list[float] = []
        if inputs.battery_actuator is not None:
            allowed_caps.append(battery_allowed_max_output_w)
        if (
            inputs.inverter_actuator is not None
            and self.config.inverter_actuator is not None
        ):
            allowed_caps.append(inverter_allowed_max_output_w)
        if allowed_caps:
            return min(allowed_caps)
        if self.config.inverter_actuator is not None:
            return min(
                self.config.battery_actuator.max_output_w,
                self.config.inverter_actuator.max_output_w,
            )
        return self.config.battery_actuator.max_output_w

    def _allowed_battery_output_w(self, inputs: ControllerInputs) -> float:
        if inputs.battery_actuator is None:
            return 0.0

        allowed_max_output_w = self.config.battery_actuator.max_output_w
        if inputs.soc_pct is None or inputs.discharge_limit_pct is None:
            return allowed_max_output_w

        reserve_stop = inputs.discharge_limit_pct + self.config.soc_stop_buffer_pct
        reserve_full = (
            inputs.discharge_limit_pct + self.config.soc_full_power_buffer_pct
        )
        if inputs.soc_pct <= reserve_stop:
            return 0.0
        if inputs.soc_pct >= reserve_full:
            return allowed_max_output_w

        span = max(0.1, reserve_full - reserve_stop)
        ratio = (inputs.soc_pct - reserve_stop) / span
        derate = self.config.soc_min_derate_factor + (
            (1.0 - self.config.soc_min_derate_factor) * ratio
        )
        return min(
            allowed_max_output_w, self.config.battery_actuator.max_output_w * derate
        )

    def _allowed_inverter_output_w(self, inputs: ControllerInputs) -> float:
        if self.config.inverter_actuator is None or inputs.inverter_actuator is None:
            return 0.0
        return self.config.inverter_actuator.max_output_w

    def _build_actuator_result(
        self,
        config: ActuatorConfig,
        inputs: ActuatorInputs | None,
        desired_target_w: float,
        allowed_max_output_w: float,
        other_actuator_available: bool,
        export_fast: bool,
    ) -> ActuatorResult:
        if inputs is None:
            return ActuatorResult(
                label=config.label,
                available=False,
                action="unavailable",
                reason="unavailable",
                current_limit_w=None,
                requested_limit_w=desired_target_w,
                translated_limit_w=0.0,
                target_limit_w=0.0,
                applied_limit_w=None,
                actual_power_w=None,
                allowed_max_output_w=allowed_max_output_w,
            )

        current_limit_w = inputs.current_limit_w
        translated_limit_w = self._translated_target_w(
            config=config,
            current_limit_w=current_limit_w,
            desired_target_w=desired_target_w,
            allowed_max_output_w=allowed_max_output_w,
            export_fast=export_fast,
        )

        if other_actuator_available and desired_target_w < config.min_output_w:
            return ActuatorResult(
                label=config.label,
                available=True,
                action="skip",
                reason="below_min_supported_by_other",
                current_limit_w=current_limit_w,
                requested_limit_w=desired_target_w,
                translated_limit_w=0.0,
                target_limit_w=0.0,
                applied_limit_w=current_limit_w,
                actual_power_w=inputs.actual_power_w,
                allowed_max_output_w=allowed_max_output_w,
            )

        delta_w = abs(translated_limit_w - current_limit_w)
        if delta_w < config.min_change_w:
            return ActuatorResult(
                label=config.label,
                available=True,
                action="skip",
                reason="delta_below_min",
                current_limit_w=current_limit_w,
                requested_limit_w=desired_target_w,
                translated_limit_w=translated_limit_w,
                target_limit_w=translated_limit_w,
                applied_limit_w=current_limit_w,
                actual_power_w=inputs.actual_power_w,
                allowed_max_output_w=allowed_max_output_w,
            )

        if (
            inputs.seconds_since_last_write is not None
            and inputs.seconds_since_last_write < config.min_write_interval_s
            and not export_fast
        ):
            return ActuatorResult(
                label=config.label,
                available=True,
                action="skip",
                reason="min_write_interval",
                current_limit_w=current_limit_w,
                requested_limit_w=desired_target_w,
                translated_limit_w=translated_limit_w,
                target_limit_w=translated_limit_w,
                applied_limit_w=current_limit_w,
                actual_power_w=inputs.actual_power_w,
                allowed_max_output_w=allowed_max_output_w,
            )

        action = "dry_run" if self.config.dry_run else "write"
        return ActuatorResult(
            label=config.label,
            available=True,
            action=action,
            reason=action,
            current_limit_w=current_limit_w,
            requested_limit_w=desired_target_w,
            translated_limit_w=translated_limit_w,
            target_limit_w=translated_limit_w,
            applied_limit_w=translated_limit_w,
            actual_power_w=inputs.actual_power_w,
            allowed_max_output_w=allowed_max_output_w,
        )

    def _translated_target_w(
        self,
        config: ActuatorConfig,
        current_limit_w: float,
        desired_target_w: float,
        allowed_max_output_w: float,
        export_fast: bool,
    ) -> float:
        lower_bound_w = max(0.0, config.min_output_w)
        upper_bound_w = min(config.max_output_w, allowed_max_output_w)

        target_limit_w = clamp(desired_target_w, lower_bound_w, upper_bound_w)
        delta_w = target_limit_w - current_limit_w
        if delta_w > config.max_increase_per_cycle_w:
            target_limit_w = current_limit_w + config.max_increase_per_cycle_w
        elif delta_w < 0:
            limit_w = (
                config.emergency_max_decrease_per_cycle_w
                if export_fast
                else config.max_decrease_per_cycle_w
            )
            if abs(delta_w) > limit_w:
                target_limit_w = current_limit_w - limit_w

        target_limit_w = clamp(target_limit_w, lower_bound_w, upper_bound_w)
        target_limit_w = quantize_down(
            target_limit_w,
            config.power_step_w,
            offset=config.min_output_w,
        )
        return clamp(target_limit_w, lower_bound_w, upper_bound_w)

    def _effective_path_limit_w(
        self,
        battery_result: ActuatorResult,
        inverter_result: ActuatorResult | None,
    ) -> float | None:
        applied_limits = [
            result.applied_limit_w
            for result in (battery_result, inverter_result)
            if result is not None and result.applied_limit_w is not None
        ]
        if not applied_limits:
            return None
        return min(applied_limits)

    def _representative_current_limit(self, inputs: ControllerInputs) -> float:
        current_limits = [
            actuator.current_limit_w
            for actuator in (inputs.battery_actuator, inputs.inverter_actuator)
            if actuator is not None
        ]
        if current_limits:
            return min(current_limits)
        return 0.0

    def _combined_action(
        self,
        battery_result: ActuatorResult,
        inverter_result: ActuatorResult | None,
    ) -> str:
        results = [battery_result]
        if inverter_result is not None:
            results.append(inverter_result)

        if any(result.action == "write" for result in results):
            return "write"
        if any(result.action == "dry_run" for result in results):
            return "dry_run"
        return "skip"

    def _actuator_reason_parts(
        self,
        battery_result: ActuatorResult,
        inverter_result: ActuatorResult | None,
    ) -> list[str]:
        parts: list[str] = []
        parts.append(f"battery_{battery_result.reason}")
        if inverter_result is not None:
            parts.append(f"inverter_{inverter_result.reason}")
        return parts
