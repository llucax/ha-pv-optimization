from __future__ import annotations

from pathlib import Path
from typing import Any

import ha_pv_optimization.appdaemon as appdaemon_module
from ha_pv_optimization.appdaemon import HaPvOptimization


class FakeHaPvOptimization(HaPvOptimization):
    def __init__(self, args: dict[str, Any], state_map: dict[str, Any]) -> None:
        self.args = args
        self.state_map = state_map
        self.logs: list[tuple[str, str, dict[str, Any]]] = []
        self.state_updates: list[tuple[str, Any, dict[str, Any]]] = []
        self.service_calls: list[tuple[str, dict[str, Any]]] = []
        self.state_listeners: list[tuple[Any, dict[str, Any]]] = []

    def log(self, message: str, level: str = "INFO", **kwargs: Any) -> None:
        self.logs.append((level, message, kwargs))

    def run_every(self, callback: Any, start: Any, interval: Any) -> None:
        return None

    def listen_state(self, callback: Any, **kwargs: Any) -> None:
        self.state_listeners.append((callback, kwargs))

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
        self.service_calls.append((service, kwargs))

    def set_state(self, entity_id: str, state: Any, attributes: dict[str, Any]) -> None:
        self.state_updates.append((entity_id, state, attributes))


def _warning_messages(app: FakeHaPvOptimization) -> list[str]:
    return [message for level, message, _ in app.logs if level == "WARNING"]


def _info_messages(app: FakeHaPvOptimization) -> list[str]:
    return [message for level, message, _ in app.logs if level == "INFO"]


def _messages_for_log(
    app: FakeHaPvOptimization,
    *,
    log_name: str,
) -> list[str]:
    return [message for _, message, kwargs in app.logs if kwargs.get("log") == log_name]


def _heartbeat_messages(app: FakeHaPvOptimization) -> list[str]:
    return [
        message for message in _info_messages(app) if "Control heartbeat" in message
    ]


def _latest_status_update(
    app: FakeHaPvOptimization,
) -> tuple[str, Any, dict[str, Any]]:
    return next(
        update
        for update in reversed(app.state_updates)
        if update[0].endswith("_status")
    )


def test_primary_missing_is_not_blocking_when_trim_available(monkeypatch: Any) -> None:
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: 0.0)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.battery_limit",
            "trim_power_control_entity": "number.inverter_limit",
            "trim_power_step_w": 10,
            "trim_min_change_w": 10,
            "trim_min_write_interval_s": 0,
            "trim_max_increase_per_cycle_w": 500,
            "trim_max_decrease_per_cycle_w": 500,
            "trim_emergency_max_decrease_per_cycle_w": 500,
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "180",
            "number.battery_limit": "unavailable",
            "number.inverter_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 10},
            },
        },
    )

    app.initialize()
    app._control_tick({})

    assert _warning_messages(app) == []
    status_update = _latest_status_update(app)
    assert status_update[1] == "dry_run"
    assert status_update[2]["primary_power_control_available"] is False
    assert status_update[2]["trim_power_control_available"] is True
    assert status_update[2]["available_actuators"] == ["number.inverter_limit"]
    assert status_update[2]["trim_target_power_control_w"] == 180.0


def test_all_actuators_missing_is_expected_at_battery_reserve(monkeypatch: Any) -> None:
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: 0.0)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.battery_limit",
            "actual_power_entity": "sensor.battery_output",
            "trim_power_control_entity": "number.inverter_limit",
            "trim_actual_power_entity": "sensor.inverter_output",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "availability_warning_grace_s": 30,
            "max_output_w": 800,
            "trim_max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "123",
            "number.battery_limit": "unavailable",
            "number.inverter_limit": "unavailable",
            "sensor.battery_output": "0",
            "sensor.inverter_output": "0",
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
            "sun.sun": {"state": "above_horizon", "attributes": {"elevation": 30}},
        },
    )

    app.initialize()
    app._control_tick({})

    assert _warning_messages(app) == []
    assert any("battery_reserve" in message for message in _info_messages(app))
    status_update = _latest_status_update(app)
    assert status_update[1] == "blocked"
    assert status_update[2]["availability_state"] == "expected_missing"
    assert status_update[2]["expected_missing_reason"] == "battery_reserve"


def test_all_actuators_missing_warns_after_expected_window(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.battery_limit",
            "actual_power_entity": "sensor.battery_output",
            "trim_power_control_entity": "number.inverter_limit",
            "trim_actual_power_entity": "sensor.inverter_output",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "availability_warning_grace_s": 30,
            "max_output_w": 800,
            "trim_max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "123",
            "number.battery_limit": "unavailable",
            "number.inverter_limit": "unavailable",
            "sensor.battery_output": "0",
            "sensor.inverter_output": "0",
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
    status_update = _latest_status_update(app)
    assert status_update[2]["availability_state"] == "warning_grace"

    now["value"] = 91.0
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
            "power_control_entity": "number.battery_limit",
            "max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "unavailable",
            "number.battery_limit": {"state": "400", "attributes": {"max": 800}},
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


def test_live_mode_writes_primary_and_trim_targets() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "power_control_entity": "number.battery_limit",
            "power_step_w": 50,
            "min_change_w": 50,
            "min_write_interval_s": 0,
            "max_increase_per_cycle_w": 500,
            "max_decrease_per_cycle_w": 500,
            "emergency_max_decrease_per_cycle_w": 500,
            "trim_power_control_entity": "number.inverter_limit",
            "trim_power_step_w": 10,
            "trim_min_change_w": 10,
            "trim_min_write_interval_s": 0,
            "trim_max_increase_per_cycle_w": 500,
            "trim_max_decrease_per_cycle_w": 500,
            "trim_emergency_max_decrease_per_cycle_w": 500,
            "max_output_w": 800,
            "trim_max_output_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "350",
            "number.battery_limit": {
                "state": "250",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.inverter_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 10},
            },
        },
    )

    app.initialize()
    app._control_tick({})

    assert app.service_calls == [
        ("number/set_value", {"entity_id": "number.battery_limit", "value": 350}),
        ("number/set_value", {"entity_id": "number.inverter_limit", "value": 350}),
    ]
    status_update = _latest_status_update(app)
    assert status_update[2]["target_power_control_w"] == 350.0
    assert status_update[2]["primary_target_power_control_w"] == 350.0
    assert status_update[2]["trim_target_power_control_w"] == 350.0


def test_debug_target_entities_publish_zero_as_string() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "inverter_power_control_entity": "number.inverter_limit",
            "inverter_min_output_w": 30,
            "inverter_power_step_w": 10,
            "inverter_min_change_w": 10,
            "inverter_min_write_interval_s": 0,
            "inverter_max_increase_per_cycle_w": 500,
            "inverter_max_decrease_per_cycle_w": 500,
            "inverter_emergency_max_decrease_per_cycle_w": 500,
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "battery_max_output_w": 800,
            "inverter_max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "128",
            "number.battery_limit": {
                "state": "800",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.inverter_limit": "unavailable",
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
        },
    )

    app.initialize()
    app._control_tick({})

    primary_target = next(
        update
        for update in app.state_updates
        if update[0].endswith("_primary_target_limit")
    )
    trim_target = next(
        update
        for update in app.state_updates
        if update[0].endswith("_trim_target_limit")
    )
    assert primary_target[1] == "0"
    assert trim_target[1] == "0"


def test_status_reports_requested_translated_and_applied_targets() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 999,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "inverter_power_control_entity": "number.inverter_limit",
            "inverter_power_step_w": 25,
            "inverter_min_change_w": 25,
            "inverter_min_write_interval_s": 0,
            "inverter_max_increase_per_cycle_w": 500,
            "inverter_max_decrease_per_cycle_w": 500,
            "inverter_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "inverter_max_output_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "155",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.inverter_limit": {
                "state": "230",
                "attributes": {"min": 30, "max": 800, "step": 25},
            },
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
        },
    )

    app.initialize()
    app._control_tick({})

    assert app.service_calls == []
    status_update = _latest_status_update(app)
    assert status_update[2]["requested_target_power_control_w"] == 155.0
    assert status_update[2]["target_power_control_w"] == 0.0
    assert status_update[2]["effective_target_power_control_w"] == 0.0
    assert status_update[2]["battery_requested_power_control_w"] == 0.0
    assert status_update[2]["battery_translated_power_control_w"] == 0.0
    assert status_update[2]["battery_applied_power_control_w"] == 0.0
    assert status_update[2]["inverter_requested_power_control_w"] == 0.0
    assert status_update[2]["inverter_translated_power_control_w"] == 0.0
    assert status_update[2]["inverter_applied_power_control_w"] == 230.0


def test_skip_cycles_emit_startup_and_periodic_heartbeat(monkeypatch: Any) -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_discharge_limit_entity": "number.battery_reserve",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 999,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "inverter_power_control_entity": "number.inverter_limit",
            "inverter_power_step_w": 25,
            "inverter_min_change_w": 25,
            "inverter_min_write_interval_s": 999,
            "inverter_max_increase_per_cycle_w": 500,
            "inverter_max_decrease_per_cycle_w": 500,
            "inverter_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "inverter_max_output_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "155",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.inverter_limit": {
                "state": "230",
                "attributes": {"min": 30, "max": 800, "step": 25},
            },
            "sensor.battery_soc": "22",
            "number.battery_reserve": "20",
        },
    )

    app.initialize()
    heartbeat_messages = _heartbeat_messages(app)
    assert len(heartbeat_messages) == 1
    assert "state=initialized" in heartbeat_messages[0]

    app._control_tick({})
    app._heartbeat_tick({})
    heartbeat_messages = _heartbeat_messages(app)
    assert len(heartbeat_messages) == 2
    assert "requested=155W" in heartbeat_messages[-1]

    app._heartbeat_tick({})
    assert len(_heartbeat_messages(app)) == 3


def test_control_cycle_can_use_dedicated_user_log() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "dry_run": True,
            "control_cycle_log": "cycle_log",
            "control_cycle_log_level": "INFO",
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()
    app._control_tick({})

    cycle_messages = _messages_for_log(app, log_name="cycle_log")
    assert len(cycle_messages) == 1
    assert "Control cycle" in cycle_messages[0]
    assert "battery=" in cycle_messages[0]
    assert "inverter=" in cycle_messages[0]
    assert "battery_allowed=" in cycle_messages[0]


def test_appdaemon_loads_site_config_file(tmp_path: Path) -> None:
    site_config_path = tmp_path / "site.yaml"
    site_config_path.write_text(
        "consumption:\n"
        "  entity: sensor.site_load\n"
        "battery:\n"
        "  power_control_entity: number.site_battery_limit\n"
        "  max_output_w: 800\n"
        "inverter:\n"
        "  power_control_entity: number.site_inverter_limit\n"
        "  max_output_w: 800\n",
        encoding="utf-8",
    )
    app = FakeHaPvOptimization(
        args={
            "module": "ha_pv_optimization_app",
            "class": "HaPvOptimization",
            "site_config_path": str(site_config_path),
            "dry_run": True,
        },
        state_map={
            "sensor.site_load": "200",
            "number.site_battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.site_inverter_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 25},
            },
        },
    )

    app.initialize()

    assert app.entities.consumption_entity == "sensor.site_load"
    assert (
        app.entities.primary_actuator.power_control_entity
        == "number.site_battery_limit"
    )
    assert app.entities.trim_actuator is not None
    assert (
        app.entities.trim_actuator.power_control_entity == "number.site_inverter_limit"
    )


def test_time_weighted_metrics_are_published_and_listeners_registered() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "net_consumption_entity": "sensor.net",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_power_control_entity": "number.battery_limit",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "sensor.net": "-20",
            "sensor.battery_temp": "30",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()

    listener_entities = sorted(
        kwargs["entity"] for _, kwargs in app.state_listeners if "entity" in kwargs
    )
    assert listener_entities == [
        "sensor.battery_temp",
        "sensor.load",
        "sensor.net",
    ]

    app._control_tick({})
    status_update = _latest_status_update(app)
    assert status_update[2]["tw_consumption_fast_mean_w"] == 200.0
    assert status_update[2]["tw_consumption_slow_q20_w"] == 200.0
    assert status_update[2]["tw_consumption_pre_event_median_w"] == 200.0
    assert status_update[2]["tw_net_fast_mean_w"] == -20.0
    assert status_update[2]["tw_net_slow_q20_w"] == -20.0
    assert status_update[2]["battery_temperature_t5_c"] == 30.0
    assert status_update[2]["battery_temperature_t30_c"] == 30.0
