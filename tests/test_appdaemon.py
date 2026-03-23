from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import ha_pv_optimization.appdaemon as appdaemon_module  # noqa: E402
from ha_pv_optimization.appdaemon import HaPvOptimization  # noqa: E402


class FakeHaPvOptimization(HaPvOptimization):
    def __init__(self, args: dict[str, Any], state_map: dict[str, Any]) -> None:
        self.args = args
        self.state_map = state_map
        self.logs: list[tuple[str, str]] = []
        self.state_updates: list[tuple[str, Any, dict[str, Any]]] = []

    def log(self, message: str, level: str = "INFO") -> None:
        self.logs.append((level, message))

    def run_every(self, callback: Any, start: Any, interval: Any) -> None:
        return None

    def get_state(self, entity_id: str, attribute: str | None = None) -> Any:
        value = self.state_map.get(entity_id)
        if attribute == "all":
            if isinstance(value, dict):
                return value
            if value is None:
                return None
            return {"state": value, "attributes": {}}
        if isinstance(value, dict):
            return value.get("state")
        return value

    def call_service(self, service: str, **kwargs: Any) -> None:
        return None

    def set_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> None:
        self.state_updates.append((entity_id, state, attributes))


def _warning_messages(app: FakeHaPvOptimization) -> list[str]:
    return [message for level, message in app.logs if level == "WARNING"]


def _info_messages(app: FakeHaPvOptimization) -> list[str]:
    return [message for level, message in app.logs if level == "INFO"]


def test_power_control_missing_is_expected_at_battery_reserve(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])

    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.limit",
            "actual_power_entity": "sensor.output_power",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "123",
            "number.limit": "unavailable",
            "sensor.output_power": "0",
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
            "sun.sun": {"state": "above_horizon", "attributes": {"elevation": 30}},
        },
    )

    app.initialize()
    app._control_tick({})

    assert _warning_messages(app) == []
    assert any(
        "currently expected" in message and "battery_reserve" in message
        for message in _info_messages(app)
    )

    status_update = app.state_updates[-1]
    assert status_update[1] == "blocked"
    assert status_update[2]["availability_state"] == "expected_missing"
    assert status_update[2]["expected_missing_reason"] == "battery_reserve"
    assert status_update[2]["warning_active"] is False


def test_expected_missing_warns_after_conditions_clear_and_grace_expires(
    monkeypatch: Any,
) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])

    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.limit",
            "actual_power_entity": "sensor.output_power",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "123",
            "number.limit": "unavailable",
            "sensor.output_power": "50",
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
            "sun.sun": {"state": "above_horizon", "attributes": {"elevation": 30}},
        },
    )

    app.initialize()
    app._control_tick({})

    now["value"] = 60.0
    app.state_map["sensor.battery_soc"] = "35"
    app._control_tick({})

    assert _warning_messages(app) == []
    assert any(
        "expected condition cleared" in message for message in _info_messages(app)
    )
    status_update = app.state_updates[-1]
    assert status_update[2]["availability_state"] == "warning_grace"
    assert status_update[2]["expected_missing_reason"] is None

    now["value"] = appdaemon_module._MISSING_REQUIRED_WARNING_GRACE_S + 61.0
    app._control_tick({})

    warning_messages = _warning_messages(app)
    assert len(warning_messages) == 1
    assert "warning grace period" in warning_messages[0]
    status_update = app.state_updates[-1]
    assert status_update[2]["availability_state"] == "warning_active"
    assert status_update[2]["warning_active"] is True

    now["value"] += 30.0
    app.state_map["number.limit"] = "800"
    app._control_tick({})

    assert any("state recovered" in message for message in _info_messages(app))


def test_power_control_missing_is_expected_while_sun_is_down(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])

    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.limit",
            "actual_power_entity": "sensor.output_power",
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "123",
            "number.limit": "unavailable",
            "sensor.output_power": "0",
            "sun.sun": {"state": "below_horizon", "attributes": {"elevation": -15}},
        },
    )

    app.initialize()
    app._control_tick({})

    assert _warning_messages(app) == []
    status_update = app.state_updates[-1]
    assert status_update[2]["expected_missing_reason"] == "sun_down"

    now["value"] = 60.0
    app.state_map["sun.sun"] = {
        "state": "above_horizon",
        "attributes": {"elevation": 20},
    }
    app._control_tick({})
    assert app.state_updates[-1][2]["availability_state"] == "warning_grace"

    now["value"] = appdaemon_module._MISSING_REQUIRED_WARNING_GRACE_S + 61.0
    app._control_tick({})
    warning_messages = _warning_messages(app)
    assert len(warning_messages) == 1
    assert "warning grace period" in warning_messages[0]


def test_consumption_missing_warns_once_until_recovery(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])

    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.limit",
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "unavailable",
            "number.limit": "800",
        },
    )

    app.initialize()
    app._control_tick({})
    now["value"] = 60.0
    app._control_tick({})

    warning_messages = _warning_messages(app)
    assert len(warning_messages) == 1
    assert "missing=consumption" in warning_messages[0]

    app.state_map["sensor.load"] = "125"
    app._control_tick({})

    assert any("state recovered" in message for message in _info_messages(app))
