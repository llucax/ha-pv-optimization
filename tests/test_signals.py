from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ha_pv_optimization.signals import TimeWeightedSeries


def test_time_weighted_series_mean_median_and_quantile() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    series = TimeWeightedSeries(max_history_s=300)
    series.update(start, 100.0)
    series.update(start + timedelta(seconds=10), 200.0)
    series.update(start + timedelta(seconds=30), 50.0)

    now = start + timedelta(seconds=40)

    assert series.mean(40.0, now) == 137.5
    assert series.quantile(40.0, 0.2, now) == 50.0
    assert series.median(40.0, now) == 100.0


def test_time_weighted_series_prunes_history_but_keeps_window_anchor() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    series = TimeWeightedSeries(max_history_s=30)
    series.update(start, 100.0)
    series.update(start + timedelta(seconds=10), 200.0)
    series.update(start + timedelta(seconds=50), 300.0)

    assert series.sample_count == 2
    now = start + timedelta(seconds=60)
    assert series.mean(20.0, now) == 250.0


def test_time_weighted_series_requires_monotonic_timestamps() -> None:
    start = datetime(2026, 3, 28, 6, 0, tzinfo=UTC)
    series = TimeWeightedSeries(max_history_s=60)
    series.update(start, 100.0)

    with pytest.raises(ValueError, match="monotonic"):
        series.update(start - timedelta(seconds=1), 90.0)
