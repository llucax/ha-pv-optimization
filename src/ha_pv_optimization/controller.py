from __future__ import annotations

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
from .signals import clamp, quantize_down


class PowerControllerCore:
    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self.cap_cmd_w: float | None = None
        self.lockout_remaining_s = 0.0
        self.minor_up_elapsed_s = 0.0
        self.major_up_elapsed_s = 0.0
        self.down_elapsed_s = 0.0
        self.moderate_oversupply_streak = 0
        self.smoothed_consumption_w: float | None = None
        self.smoothed_net_consumption_w: float | None = None
        self.thermal_state = ThermalState.NORMAL
        self.thermal_clear_elapsed_s = 0.0

    def step(self, inputs: ControllerInputs) -> ControllerResult:
        visible_load_w = max(0.0, inputs.consumption_w + self.config.baseline_load_w)
        device_feed_forward_w = max(0.0, inputs.device_feed_forward_w)
        estimated_load_fast_w = self._with_baseline(
            inputs.tw_consumption_fast_mean_w,
            fallback=visible_load_w,
            include_feed_forward_w=device_feed_forward_w,
        )
        estimated_load_slow_w = self._with_baseline(
            inputs.tw_consumption_slow_q20_w,
            fallback=visible_load_w,
            include_feed_forward_w=device_feed_forward_w,
        )
        visible_load_pre_event_median_w = self._with_baseline(
            inputs.tw_consumption_pre_event_median_w,
            fallback=visible_load_w,
            include_feed_forward_w=0.0,
        )

        self.smoothed_consumption_w = estimated_load_fast_w
        self.smoothed_net_consumption_w = inputs.tw_net_fast_mean_w

        thermal_state = self._update_thermal_state(inputs)
        desired_min_soc_pct, desired_max_soc_pct, battery_cap_limit_w = (
            self._thermal_limits(thermal_state)
        )

        battery_allowed_max_output_w = self._allowed_battery_output_w(
            inputs,
            battery_cap_limit_w=battery_cap_limit_w,
            desired_min_soc_pct=desired_min_soc_pct,
        )
        inverter_allowed_max_output_w = self._allowed_inverter_output_w(inputs)
        allowed_path_cap_w = self._allowed_path_cap_w(
            inputs=inputs,
            battery_allowed_max_output_w=battery_allowed_max_output_w,
            inverter_allowed_max_output_w=inverter_allowed_max_output_w,
        )

        observed_path_cap_w = self._observed_path_cap_w(inputs)
        if self.cap_cmd_w is None:
            self.cap_cmd_w = observed_path_cap_w

        self.lockout_remaining_s = max(
            0.0,
            self.lockout_remaining_s - self.config.control_interval_s,
        )

        delta_load_w = visible_load_w - visible_load_pre_event_median_w
        self._update_event_persistence(delta_load_w)

        requested_target_w = self.cap_cmd_w
        fast_error_w = estimated_load_fast_w - self.cap_cmd_w
        slow_error_w = estimated_load_slow_w - self.cap_cmd_w
        visible_margin_w = self._visible_margin_w(inputs, visible_load_w)

        reason_parts: list[str] = []
        if device_feed_forward_w > 0:
            reason_parts.append("device_feed_forward")

        requested_target_w, event_reason = self._fast_event_target(
            requested_target_w=requested_target_w,
            delta_load_w=delta_load_w,
        )
        if event_reason is not None:
            reason_parts.append(event_reason)
            self.lockout_remaining_s = self.config.command_lockout_s
            self._reset_event_persistence()
        elif self.lockout_remaining_s <= 0.0:
            requested_target_w, trim_reason = self._slow_trim_target(
                requested_target_w=requested_target_w,
                fast_error_w=fast_error_w,
                slow_error_w=slow_error_w,
            )
            if trim_reason is not None:
                reason_parts.append(trim_reason)

        requested_target_w, oversupply_reason = self._oversupply_target(
            requested_target_w=requested_target_w,
            visible_margin_w=visible_margin_w,
        )
        if oversupply_reason is not None:
            reason_parts.append(oversupply_reason)

        requested_target_w = clamp(
            quantize_down(requested_target_w, self.config.command_step_w),
            0.0,
            max(0.0, max(allowed_path_cap_w, observed_path_cap_w, self.cap_cmd_w)),
        )
        self.cap_cmd_w = requested_target_w

        if visible_load_w <= self.config.zero_output_threshold_w:
            requested_target_w = 0.0
            self.cap_cmd_w = 0.0
            reason_parts.append("low_demand_zero")

        desired_path_cap_w = clamp(requested_target_w, 0.0, allowed_path_cap_w)

        battery_result = self._build_actuator_result(
            config=self.config.battery_actuator,
            inputs=inputs.battery_actuator,
            desired_target_w=desired_path_cap_w,
            allowed_max_output_w=battery_allowed_max_output_w,
            other_actuator_available=inputs.inverter_actuator is not None,
            export_fast=False,
        )
        inverter_result = None
        if self.config.inverter_actuator is not None:
            inverter_result = self._build_actuator_result(
                config=self.config.inverter_actuator,
                inputs=inputs.inverter_actuator,
                desired_target_w=desired_path_cap_w,
                allowed_max_output_w=inverter_allowed_max_output_w,
                other_actuator_available=inputs.battery_actuator is not None,
                export_fast=False,
            )

        action = self._combined_action(battery_result, inverter_result)
        reason_parts.extend(
            self._actuator_reason_parts(battery_result, inverter_result)
        )
        if not reason_parts:
            reason_parts.append("steady")

        effective_target_w = self._effective_path_limit_w(
            battery_result, inverter_result
        )
        degraded_reasons = self._degraded_reasons(
            requested_target_w=requested_target_w,
            battery_result=battery_result,
            inverter_result=inverter_result,
            inverter_expected=self.config.inverter_actuator is not None,
        )
        degraded_mode = "nominal"
        if degraded_reasons:
            degraded_mode = ",".join(degraded_reasons)

        return ControllerResult(
            action=action,
            target_limit_w=desired_path_cap_w,
            requested_target_w=requested_target_w,
            desired_path_cap_w=desired_path_cap_w,
            cap_cmd_w=self.cap_cmd_w,
            effective_target_w=effective_target_w,
            degraded_mode=degraded_mode,
            degraded_reasons=degraded_reasons,
            thermal_state=thermal_state,
            desired_min_soc_pct=desired_min_soc_pct,
            desired_max_soc_pct=desired_max_soc_pct,
            battery_cap_limit_w=battery_cap_limit_w,
            device_feed_forward_w=device_feed_forward_w,
            estimated_load_fast_w=estimated_load_fast_w,
            estimated_load_slow_w=estimated_load_slow_w,
            visible_load_pre_event_median_w=visible_load_pre_event_median_w,
            fast_error_w=fast_error_w,
            slow_error_w=slow_error_w,
            visible_margin_w=visible_margin_w,
            effective_consumption_w=visible_load_w,
            smoothed_consumption_w=estimated_load_fast_w,
            raw_net_consumption_w=inputs.net_consumption_w,
            smoothed_net_consumption_w=inputs.tw_net_fast_mean_w,
            net_correction_w=0.0,
            allowed_max_output_w=allowed_path_cap_w,
            primary_allowed_max_output_w=battery_allowed_max_output_w,
            trim_allowed_max_output_w=inverter_allowed_max_output_w,
            export_fast=False,
            reason=",".join(reason_parts),
            current_limit_w=observed_path_cap_w,
            primary_actuator=battery_result,
            trim_actuator=inverter_result,
        )

    def _with_baseline(
        self,
        value: float | None,
        *,
        fallback: float,
        include_feed_forward_w: float,
    ) -> float:
        if value is None:
            return fallback + include_feed_forward_w
        return max(0.0, value + self.config.baseline_load_w + include_feed_forward_w)

    def _observed_path_cap_w(self, inputs: ControllerInputs) -> float:
        current_limits = [
            actuator.current_limit_w
            for actuator in (inputs.battery_actuator, inputs.inverter_actuator)
            if actuator is not None
        ]
        if not current_limits:
            return 0.0
        return min(current_limits)

    def _update_event_persistence(self, delta_load_w: float) -> None:
        interval_s = self.config.control_interval_s
        if delta_load_w >= self.config.minor_up_event_threshold_w:
            self.minor_up_elapsed_s += interval_s
        else:
            self.minor_up_elapsed_s = 0.0

        if delta_load_w >= self.config.major_up_event_threshold_w:
            self.major_up_elapsed_s += interval_s
        else:
            self.major_up_elapsed_s = 0.0

        if delta_load_w <= self.config.down_event_threshold_w:
            self.down_elapsed_s += interval_s
        else:
            self.down_elapsed_s = 0.0

    def _reset_event_persistence(self) -> None:
        self.minor_up_elapsed_s = 0.0
        self.major_up_elapsed_s = 0.0
        self.down_elapsed_s = 0.0

    def _fast_event_target(
        self,
        *,
        requested_target_w: float,
        delta_load_w: float,
    ) -> tuple[float, str | None]:
        if self.major_up_elapsed_s >= self.config.major_up_persistence_s:
            jump_w = self.config.major_up_multiplier * delta_load_w
            return requested_target_w + jump_w, "major_up_event"
        if self.minor_up_elapsed_s >= self.config.minor_up_persistence_s:
            jump_w = self.config.minor_up_multiplier * delta_load_w
            return requested_target_w + jump_w, "minor_up_event"
        if self.down_elapsed_s >= self.config.down_event_persistence_s:
            drop_w = self.config.down_event_multiplier * abs(delta_load_w)
            return max(0.0, requested_target_w - drop_w), "down_event"
        return requested_target_w, None

    def _slow_trim_target(
        self,
        *,
        requested_target_w: float,
        fast_error_w: float,
        slow_error_w: float,
    ) -> tuple[float, str | None]:
        if slow_error_w > self.config.slow_up_deadband_w:
            delta_up_w = clamp(
                self.config.slow_up_gain * slow_error_w,
                self.config.command_step_w,
                self.config.slow_up_max_step_w,
            )
            return requested_target_w + delta_up_w, "slow_up_trim"
        if fast_error_w < self.config.slow_down_deadband_w:
            delta_down_w = clamp(
                abs(fast_error_w) + self.config.slow_down_guard_w,
                self.config.command_step_w,
                self.config.slow_down_max_step_w,
            )
            return max(0.0, requested_target_w - delta_down_w), "slow_down_trim"
        return requested_target_w, None

    def _visible_margin_w(
        self,
        inputs: ControllerInputs,
        visible_load_w: float,
    ) -> float | None:
        inverter_actual_power_w = None
        if inputs.inverter_actuator is not None:
            inverter_actual_power_w = inputs.inverter_actuator.actual_power_w
        if inverter_actual_power_w is None:
            return None
        return visible_load_w - inverter_actual_power_w

    def _oversupply_target(
        self,
        *,
        requested_target_w: float,
        visible_margin_w: float | None,
    ) -> tuple[float, str | None]:
        if visible_margin_w is None:
            self.moderate_oversupply_streak = 0
            return requested_target_w, None

        if visible_margin_w < self.config.visible_oversupply_two_sample_w:
            self.moderate_oversupply_streak += 1
        else:
            self.moderate_oversupply_streak = 0

        if visible_margin_w < self.config.visible_oversupply_one_sample_w:
            cut_w = min(
                max(0.0, abs(visible_margin_w) - 60.0),
                self.config.visible_oversupply_max_cut_w,
            )
            return max(0.0, requested_target_w - cut_w), "oversupply_severe"

        if self.moderate_oversupply_streak >= 2:
            cut_w = min(abs(visible_margin_w), 300.0)
            return max(0.0, requested_target_w - cut_w), "oversupply_moderate"

        return requested_target_w, None

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

    def _allowed_battery_output_w(
        self,
        inputs: ControllerInputs,
        *,
        battery_cap_limit_w: float,
        desired_min_soc_pct: float,
    ) -> float:
        if inputs.battery_actuator is None:
            return 0.0

        allowed_max_output_w = min(
            self.config.battery_actuator.max_output_w,
            battery_cap_limit_w,
        )
        if inputs.soc_pct is None:
            return allowed_max_output_w
        if inputs.soc_pct <= desired_min_soc_pct:
            return 0.0
        return allowed_max_output_w

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

    def _representative_current_limit(self, inputs: ControllerInputs) -> float:
        return self._observed_path_cap_w(inputs)

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

    def _degraded_reasons(
        self,
        *,
        requested_target_w: float,
        battery_result: ActuatorResult,
        inverter_result: ActuatorResult | None,
        inverter_expected: bool,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not battery_result.available:
            reasons.append("battery_unavailable")
        if inverter_expected and inverter_result is None:
            reasons.append("inverter_unavailable")
        elif inverter_result is not None and not inverter_result.available:
            reasons.append("inverter_unavailable")

        if (
            battery_result.available
            and battery_result.applied_limit_w is not None
            and battery_result.applied_limit_w != battery_result.target_limit_w
        ):
            reasons.append("battery_not_enforcing_target")
        if (
            inverter_result is not None
            and inverter_result.available
            and inverter_result.applied_limit_w is not None
            and inverter_result.applied_limit_w != inverter_result.target_limit_w
        ):
            reasons.append("inverter_not_enforcing_target")

        if (
            battery_result.available
            and battery_result.allowed_max_output_w < requested_target_w
        ):
            reasons.append("battery_limited")
        if (
            inverter_result is not None
            and inverter_result.available
            and inverter_result.allowed_max_output_w < requested_target_w
        ):
            reasons.append("inverter_limited")

        return tuple(dict.fromkeys(reasons))

    def _update_thermal_state(self, inputs: ControllerInputs) -> ThermalState:
        policy = self.config.thermal_policy
        interval_s = self.config.control_interval_s
        requested_state = self.thermal_state

        if self._very_hot_triggered(inputs, policy):
            self.thermal_state = ThermalState.VERY_HOT
            self.thermal_clear_elapsed_s = 0.0
            return self.thermal_state

        if self.thermal_state == ThermalState.VERY_HOT:
            if self._very_hot_clear(inputs, policy):
                self.thermal_clear_elapsed_s += interval_s
                if self.thermal_clear_elapsed_s >= policy.very_hot_exit_hold_s:
                    requested_state = (
                        ThermalState.HOT
                        if self._hot_triggered(inputs, policy)
                        else ThermalState.NORMAL
                    )
            else:
                self.thermal_clear_elapsed_s = 0.0
            self.thermal_state = requested_state
            return self.thermal_state

        if self._hot_triggered(inputs, policy):
            self.thermal_state = ThermalState.HOT
            self.thermal_clear_elapsed_s = 0.0
            return self.thermal_state

        if self.thermal_state == ThermalState.HOT:
            if self._hot_clear(inputs, policy):
                self.thermal_clear_elapsed_s += interval_s
                if self.thermal_clear_elapsed_s >= policy.hot_exit_hold_s:
                    self.thermal_state = ThermalState.NORMAL
            else:
                self.thermal_clear_elapsed_s = 0.0

        return self.thermal_state

    def _very_hot_triggered(
        self,
        inputs: ControllerInputs,
        policy: ThermalPolicyConfig,
    ) -> bool:
        return bool(
            inputs.battery_high_temp_alarm_active
            or (
                inputs.battery_temp_t30_c is not None
                and inputs.battery_temp_t30_c >= policy.very_hot_enter_t30_c
            )
            or (
                inputs.battery_temp_t5_c is not None
                and inputs.battery_temp_t5_c >= policy.very_hot_enter_t5_c
            )
        )

    def _very_hot_clear(
        self,
        inputs: ControllerInputs,
        policy: ThermalPolicyConfig,
    ) -> bool:
        if inputs.battery_high_temp_alarm_active:
            return False
        return bool(
            inputs.battery_temp_t30_c is not None
            and inputs.battery_temp_t30_c < policy.very_hot_exit_t30_c
            and inputs.battery_temp_t5_c is not None
            and inputs.battery_temp_t5_c < policy.very_hot_exit_t5_c
        )

    def _hot_triggered(
        self,
        inputs: ControllerInputs,
        policy: ThermalPolicyConfig,
    ) -> bool:
        return bool(
            inputs.battery_temp_t30_c is not None
            and inputs.battery_temp_t30_c >= policy.hot_enter_t30_c
        )

    def _hot_clear(
        self,
        inputs: ControllerInputs,
        policy: ThermalPolicyConfig,
    ) -> bool:
        return bool(
            inputs.battery_temp_t30_c is not None
            and inputs.battery_temp_t30_c < policy.hot_exit_t30_c
        )

    def _thermal_limits(
        self,
        state: ThermalState,
    ) -> tuple[float, float, float]:
        policy = self.config.thermal_policy
        if state == ThermalState.HOT:
            return (
                policy.hot_min_soc_pct,
                policy.hot_max_soc_pct,
                policy.hot_cap_limit_w,
            )
        if state == ThermalState.VERY_HOT:
            return (
                policy.very_hot_min_soc_pct,
                policy.very_hot_max_soc_pct,
                policy.very_hot_cap_limit_w,
            )
        return (
            policy.normal_min_soc_pct,
            policy.normal_max_soc_pct,
            policy.normal_cap_limit_w,
        )
