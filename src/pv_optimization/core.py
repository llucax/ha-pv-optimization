from __future__ import annotations

import math
from dataclasses import dataclass


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _quantize(value: float, step: float) -> float:
    if step <= 0:
        return value
    if value >= 0:
        return math.floor((value / step) + 0.5) * step
    return math.ceil((value / step) - 0.5) * step


def _ema(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return previous + alpha * (current - previous)


def _tau_to_alpha(interval_s: float, tau_s: float) -> float:
    if tau_s <= 0:
        return 1.0
    return 1.0 - math.exp(-interval_s / tau_s)


@dataclass
class ControllerConfig:
    control_interval_s: float = 30.0
    consumption_ema_tau_s: float = 75.0
    net_ema_tau_s: float = 45.0
    baseline_load_w: float = 0.0
    deadband_w: float = 50.0
    zero_output_threshold_w: float = 25.0
    fast_export_threshold_w: float = -80.0
    import_correction_gain: float = 0.35
    export_correction_gain: float = 1.0
    min_output_w: float = 0.0
    max_output_w: float = 0.0
    power_step_w: float = 50.0
    min_change_w: float = 50.0
    min_write_interval_s: float = 60.0
    max_increase_per_cycle_w: float = 150.0
    max_decrease_per_cycle_w: float = 300.0
    emergency_max_decrease_per_cycle_w: float = 500.0
    soc_stop_buffer_pct: float = 3.0
    soc_full_power_buffer_pct: float = 10.0
    soc_min_derate_factor: float = 0.25
    net_export_negative: bool = True
    dry_run: bool = False


@dataclass
class ControllerInputs:
    consumption_w: float
    current_limit_w: float
    net_consumption_w: float | None = None
    actual_power_w: float | None = None
    soc_pct: float | None = None
    discharge_limit_pct: float | None = None
    seconds_since_last_write: float | None = None


@dataclass
class ControllerResult:
    action: str
    target_limit_w: float
    effective_consumption_w: float
    smoothed_consumption_w: float
    raw_net_consumption_w: float | None
    smoothed_net_consumption_w: float | None
    net_correction_w: float
    allowed_max_output_w: float
    export_fast: bool
    reason: str
    current_limit_w: float


class PowerControllerCore:
    def __init__(self, config: ControllerConfig) -> None:
        self.config = config
        self.smoothed_consumption_w: float | None = None
        self.smoothed_net_consumption_w: float | None = None

    def step(self, inputs: ControllerInputs) -> ControllerResult:
        effective_consumption_w = max(
            0.0, inputs.consumption_w + self.config.baseline_load_w
        )

        consumption_alpha = _tau_to_alpha(
            self.config.control_interval_s,
            self.config.consumption_ema_tau_s,
        )
        self.smoothed_consumption_w = _ema(
            self.smoothed_consumption_w,
            effective_consumption_w,
            consumption_alpha,
        )

        raw_net_w = inputs.net_consumption_w
        if raw_net_w is not None:
            if not self.config.net_export_negative:
                raw_net_w = -raw_net_w
            net_alpha = _tau_to_alpha(
                self.config.control_interval_s,
                self.config.net_ema_tau_s,
            )
            self.smoothed_net_consumption_w = _ema(
                self.smoothed_net_consumption_w,
                raw_net_w,
                net_alpha,
            )

        target_w = self.smoothed_consumption_w
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

        target_w += net_correction_w

        if effective_consumption_w <= self.config.zero_output_threshold_w and (
            raw_net_w is None or abs(raw_net_w) <= self.config.deadband_w
        ):
            target_w = 0.0
            reason_parts.append("low_demand_zero")

        allowed_max_output_w = self.config.max_output_w
        if inputs.soc_pct is not None and inputs.discharge_limit_pct is not None:
            reserve_stop = inputs.discharge_limit_pct + self.config.soc_stop_buffer_pct
            reserve_full = (
                inputs.discharge_limit_pct + self.config.soc_full_power_buffer_pct
            )
            if inputs.soc_pct <= reserve_stop:
                allowed_max_output_w = 0.0
                reason_parts.append("soc_stop")
            elif inputs.soc_pct < reserve_full:
                span = max(0.1, reserve_full - reserve_stop)
                ratio = (inputs.soc_pct - reserve_stop) / span
                derate = self.config.soc_min_derate_factor + (
                    (1.0 - self.config.soc_min_derate_factor) * ratio
                )
                allowed_max_output_w = min(
                    allowed_max_output_w,
                    self.config.max_output_w * derate,
                )
                reason_parts.append("soc_derate")

        target_w = _clamp(target_w, self.config.min_output_w, allowed_max_output_w)

        delta_w = target_w - inputs.current_limit_w
        if delta_w > self.config.max_increase_per_cycle_w:
            target_w = inputs.current_limit_w + self.config.max_increase_per_cycle_w
            reason_parts.append("slew_up")
        elif delta_w < 0:
            limit_w = (
                self.config.emergency_max_decrease_per_cycle_w
                if export_fast
                else self.config.max_decrease_per_cycle_w
            )
            if abs(delta_w) > limit_w:
                target_w = inputs.current_limit_w - limit_w
                reason_parts.append("slew_down")

        target_w = _clamp(target_w, self.config.min_output_w, allowed_max_output_w)
        target_w = _quantize(target_w, self.config.power_step_w)

        if abs(target_w) < self.config.zero_output_threshold_w:
            target_w = 0.0

        action = "skip"
        if abs(target_w - inputs.current_limit_w) < self.config.min_change_w:
            reason_parts.append("delta_below_min")
        elif (
            inputs.seconds_since_last_write is not None
            and inputs.seconds_since_last_write < self.config.min_write_interval_s
            and not export_fast
        ):
            reason_parts.append("min_write_interval")
        else:
            action = "write"
            reason_parts.append("write")

        if self.config.dry_run and action == "write":
            action = "dry_run"
            reason_parts.append("dry_run")

        if not reason_parts:
            reason_parts.append("steady")

        return ControllerResult(
            action=action,
            target_limit_w=target_w,
            effective_consumption_w=effective_consumption_w,
            smoothed_consumption_w=self.smoothed_consumption_w,
            raw_net_consumption_w=raw_net_w,
            smoothed_net_consumption_w=self.smoothed_net_consumption_w,
            net_correction_w=net_correction_w,
            allowed_max_output_w=allowed_max_output_w,
            export_fast=export_fast,
            reason=",".join(reason_parts),
            current_limit_w=inputs.current_limit_w,
        )
