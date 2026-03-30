from __future__ import annotations

import math


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def quantize_down(value: float, step: float, offset: float = 0.0) -> float:
    if step <= 0:
        return value
    return offset + math.floor((value - offset) / step) * step


def quantize(value: float, step: float, offset: float = 0.0) -> float:
    return quantize_down(value, step, offset)


def ema(previous: float | None, current: float, alpha: float) -> float:
    if previous is None:
        return current
    return previous + alpha * (current - previous)


def tau_to_alpha(interval_s: float, tau_s: float) -> float:
    if tau_s <= 0:
        return 1.0
    return 1.0 - math.exp(-interval_s / tau_s)
