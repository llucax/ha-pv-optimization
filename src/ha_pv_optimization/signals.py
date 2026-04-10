from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TimedValue:
    timestamp: datetime
    value: float


class TimeWeightedSeries:
    def __init__(self, max_history_s: float) -> None:
        if max_history_s <= 0:
            raise ValueError("`max_history_s` must be positive")
        self.max_history_s = max_history_s
        self._samples: deque[TimedValue] = deque()

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def latest_timestamp(self) -> datetime | None:
        if not self._samples:
            return None
        return self._samples[-1].timestamp

    def samples(self) -> tuple[TimedValue, ...]:
        return tuple(self._samples)

    def load_samples(self, samples: tuple[TimedValue, ...]) -> None:
        restored_samples: deque[TimedValue] = deque()
        for sample in samples:
            if restored_samples and sample.timestamp < restored_samples[-1].timestamp:
                raise ValueError("TimeWeightedSeries samples must be monotonic")
            if restored_samples and sample.timestamp == restored_samples[-1].timestamp:
                restored_samples[-1] = sample
            else:
                restored_samples.append(sample)
        self._samples = restored_samples
        if self._samples:
            self._prune(reference_time=self._samples[-1].timestamp)

    def update(self, timestamp: datetime, value: float) -> None:
        if self._samples and timestamp < self._samples[-1].timestamp:
            raise ValueError("TimeWeightedSeries samples must be monotonic")
        sample = TimedValue(timestamp=timestamp, value=value)
        if self._samples and timestamp == self._samples[-1].timestamp:
            self._samples[-1] = sample
        else:
            self._samples.append(sample)
        self._prune(reference_time=timestamp)

    def latest_value(self) -> float | None:
        if not self._samples:
            return None
        return self._samples[-1].value

    def mean(self, window_s: float, now: datetime) -> float | None:
        segments = self._window_segments(window_s=window_s, now=now)
        if not segments:
            return None
        weighted_sum = sum(value * duration_s for value, duration_s in segments)
        total_duration_s = sum(duration_s for _, duration_s in segments)
        if total_duration_s <= 0:
            return None
        return weighted_sum / total_duration_s

    def quantile(self, window_s: float, q: float, now: datetime) -> float | None:
        if not 0.0 <= q <= 1.0:
            raise ValueError("quantile q must be between 0 and 1")
        segments = self._window_segments(window_s=window_s, now=now)
        if not segments:
            return None
        weighted_values = sorted(segments, key=lambda item: item[0])
        total_duration_s = sum(duration_s for _, duration_s in weighted_values)
        if total_duration_s <= 0:
            return None
        threshold_s = q * total_duration_s
        accumulated_s = 0.0
        for value, duration_s in weighted_values:
            accumulated_s += duration_s
            if accumulated_s >= threshold_s:
                return value
        return weighted_values[-1][0]

    def median(self, window_s: float, now: datetime) -> float | None:
        return self.quantile(window_s=window_s, q=0.5, now=now)

    def _window_segments(
        self,
        *,
        window_s: float,
        now: datetime,
    ) -> list[tuple[float, float]]:
        if window_s <= 0 or not self._samples:
            return []

        start = now - timedelta(seconds=window_s)
        samples = list(self._samples)
        current_value: float | None = None
        current_start = start
        for sample in samples:
            if sample.timestamp <= start:
                current_value = sample.value
                continue
            if current_value is None:
                current_value = sample.value
            break

        if current_value is None:
            return []

        segments: list[tuple[float, float]] = []
        for sample in samples:
            if sample.timestamp <= start:
                continue
            if sample.timestamp > now:
                break
            duration_s = (sample.timestamp - current_start).total_seconds()
            if duration_s > 0:
                segments.append((current_value, duration_s))
            current_value = sample.value
            current_start = sample.timestamp

        final_duration_s = (now - current_start).total_seconds()
        if final_duration_s > 0:
            segments.append((current_value, final_duration_s))
        return segments

    def _prune(self, *, reference_time: datetime) -> None:
        cutoff = reference_time - timedelta(seconds=self.max_history_s)
        while len(self._samples) >= 2 and self._samples[1].timestamp <= cutoff:
            self._samples.popleft()


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
