from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pv_optimization.core import (  # noqa: E402
    ControllerConfig,
    ControllerInputs,
    PowerControllerCore,
)


def test_baseline_load_is_added_to_consumption() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            baseline_load_w=40.0,
            consumption_ema_tau_s=1.0,
            min_write_interval_s=0.0,
            max_output_w=1000.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=200.0,
            current_limit_w=100.0,
            seconds_since_last_write=999.0,
        )
    )
    assert result.target_limit_w == 250.0
    assert result.action == "write"


def test_fast_export_reduces_output_quickly() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            consumption_ema_tau_s=1.0,
            net_ema_tau_s=1.0,
            min_write_interval_s=999.0,
            max_output_w=1000.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=350.0,
            current_limit_w=400.0,
            net_consumption_w=-150.0,
            seconds_since_last_write=10.0,
        )
    )
    assert result.target_limit_w == 200.0
    assert result.action == "write"
    assert result.export_fast is True


def test_soc_floor_forces_zero_output() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            consumption_ema_tau_s=1.0,
            min_write_interval_s=0.0,
            max_output_w=1000.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=400.0,
            current_limit_w=200.0,
            soc_pct=22.0,
            discharge_limit_pct=20.0,
            seconds_since_last_write=999.0,
        )
    )
    assert result.target_limit_w == 0.0
    assert result.action == "write"
    assert "soc_stop" in result.reason


def test_missing_optional_inputs_still_allows_control() -> None:
    controller = PowerControllerCore(
        ControllerConfig(
            consumption_ema_tau_s=1.0,
            min_write_interval_s=0.0,
            max_output_w=500.0,
        )
    )
    result = controller.step(
        ControllerInputs(
            consumption_w=180.0,
            current_limit_w=0.0,
            seconds_since_last_write=999.0,
        )
    )
    assert result.action == "write"
    assert result.target_limit_w == 150.0
