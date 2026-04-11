from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ha_pv_optimization.appdaemon as appdaemon_module
from ha_pv_optimization.appdaemon import HaPvOptimization
from ha_pv_optimization.storage import RuntimeStateStore


class FakeHaPvOptimization(HaPvOptimization):
    def __init__(
        self,
        args: dict[str, Any],
        state_map: dict[str, Any],
        *,
        history_map: dict[str, list[dict[str, Any]]] | Exception | None = None,
    ) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ha-pvopt-test-"))
        effective_args = dict(args)
        effective_args.setdefault(
            "persistence_dir",
            str(self.temp_dir / "var"),
        )
        self.args = effective_args
        self.state_map = state_map
        self.history_map = history_map
        self.history_requests: list[dict[str, Any]] = []
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

    def get_history(self, **kwargs: Any) -> Any:
        self.history_requests.append(kwargs)
        if isinstance(self.history_map, Exception):
            raise self.history_map
        if self.history_map is None:
            return None

        entity_id = kwargs.get("entity_id")
        entity_ids = [entity_id] if isinstance(entity_id, str) else list(entity_id)
        return [list(self.history_map.get(item, [])) for item in entity_ids]


class _FixedDateTime(datetime):
    current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        current = cls.current
        if tz is None:
            return current.replace(tzinfo=None)
        return current.astimezone(tz)


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


def _rail_service_calls(
    app: FakeHaPvOptimization,
) -> list[tuple[str, dict[str, Any]]]:
    return [
        call
        for call in app.service_calls
        if call[1].get("entity_id")
        in {"number.discharge_limit", "number.charging_limit"}
    ]


def _latest_status_update(
    app: FakeHaPvOptimization,
) -> tuple[str, Any, dict[str, Any]]:
    return next(
        update
        for update in reversed(app.state_updates)
        if update[0].endswith("_status")
    )


def _history_rows_from_samples(samples: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "state": str(sample.value),
            "last_changed": sample.timestamp,
        }
        for sample in samples
    ]


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
    assert status_update[2]["trim_target_power_control_w"] == 100.0


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
        ("number/set_value", {"entity_id": "number.battery_limit", "value": 100}),
        ("number/set_value", {"entity_id": "number.inverter_limit", "value": 100}),
    ]
    status_update = _latest_status_update(app)
    assert status_update[2]["target_power_control_w"] == 100.0
    assert status_update[2]["primary_target_power_control_w"] == 100.0
    assert status_update[2]["trim_target_power_control_w"] == 100.0


def test_debug_target_entities_publish_zero_as_string() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_soc_entity": "sensor.battery_soc",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_normal_min_soc_pct": 25,
            "inverter_power_control_entity": "number.inverter_limit",
            "inverter_min_output_w": 30,
            "inverter_power_step_w": 10,
            "inverter_min_change_w": 10,
            "inverter_min_write_interval_s": 0,
            "inverter_max_increase_per_cycle_w": 500,
            "inverter_max_decrease_per_cycle_w": 500,
            "inverter_emergency_max_decrease_per_cycle_w": 500,
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
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 999,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_normal_min_soc_pct": 25,
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
        },
    )

    app.initialize()
    app._control_tick({})

    assert app.service_calls == [
        ("number/set_value", {"entity_id": "number.inverter_limit", "value": 30})
    ]
    status_update = _latest_status_update(app)
    assert status_update[2]["requested_target_power_control_w"] == 0.0
    assert status_update[2]["target_power_control_w"] == 0.0
    assert status_update[2]["effective_target_power_control_w"] == 0.0
    assert status_update[2]["battery_requested_power_control_w"] == 0.0
    assert status_update[2]["battery_translated_power_control_w"] == 0.0
    assert status_update[2]["battery_applied_power_control_w"] == 0.0
    assert status_update[2]["inverter_requested_power_control_w"] == 0.0
    assert status_update[2]["inverter_translated_power_control_w"] == 30.0
    assert status_update[2]["inverter_applied_power_control_w"] == 30.0


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
    assert "requested=70W" in heartbeat_messages[-1]

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
        kwargs["entity_id"]
        for _, kwargs in app.state_listeners
        if "entity_id" in kwargs
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


def test_site_config_devices_produce_feed_forward_status(tmp_path: Path) -> None:
    site_config_path = tmp_path / "site.yaml"
    site_config_path.write_text(
        "consumption:\n"
        "  entity: sensor.site_load\n"
        "battery:\n"
        "  power_control_entity: number.site_battery_limit\n"
        "  max_output_w: 800\n"
        "  power_step_w: 50\n"
        "  min_change_w: 50\n"
        "  min_write_interval_s: 0\n"
        "inverter:\n"
        "  power_control_entity: number.site_inverter_limit\n"
        "  max_output_w: 800\n"
        "  min_output_w: 30\n"
        "  power_step_w: 25\n"
        "  min_change_w: 25\n"
        "  min_write_interval_s: 0\n"
        "devices:\n"
        "  microwave:\n"
        "    kind: burst_high_power\n"
        "    entity_id: sensor.outlet_microwave_power\n"
        "    high_threshold_w: 300\n"
        "    enter_persistence_s: 0\n"
        "    exit_persistence_s: 2\n"
        "    ff_gain: 0.95\n"
        "    ff_hold_s: 90\n",
        encoding="utf-8",
    )
    app = FakeHaPvOptimization(
        args={
            "site_config_path": str(site_config_path),
            "dry_run": True,
        },
        state_map={
            "sensor.site_load": "200",
            "sensor.outlet_microwave_power": "1400",
            "number.site_battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.site_inverter_limit": {
                "state": "0",
                "attributes": {"min": 30, "max": 800, "step": 25},
            },
        },
    )

    app.initialize()
    listener_entities = sorted(
        kwargs["entity_id"]
        for _, kwargs in app.state_listeners
        if "entity_id" in kwargs
    )
    assert "sensor.outlet_microwave_power" in listener_entities

    app._on_device_state_change(
        "sensor.outlet_microwave_power",
        "state",
        "0",
        "1400",
        {"device_name": "microwave"},
    )
    app._control_tick({})

    status_update = _latest_status_update(app)
    assert status_update[2]["device_feed_forward_w"] > 0.0
    assert "microwave" in status_update[2]["active_device_feed_forward"]


def test_status_reports_command_mismatch_after_grace(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])
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
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    now["value"] = 31.0
    app.state_map["number.battery_limit"] = {
        "state": "0",
        "attributes": {"min": 0, "max": 800, "step": 50},
    }
    app._control_tick({})

    status_update = _latest_status_update(app)
    assert (
        status_update[2]["battery_command_mismatch_reason"]
        == "probable_rejected_command"
    )
    assert status_update[2]["battery_command_mismatch_w"] == -100.0
    assert "battery_probable_rejected_command" in status_update[2]["degraded_reasons"]


def test_status_reports_external_override_after_command_grace(monkeypatch: Any) -> None:
    now = {"value": 0.0}
    monkeypatch.setattr(appdaemon_module.time, "monotonic", lambda: now["value"])
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
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    now["value"] = 31.0
    app.state_map["number.battery_limit"] = {
        "state": "300",
        "attributes": {"min": 0, "max": 800, "step": 50},
    }
    app._control_tick({})

    status_update = _latest_status_update(app)
    assert (
        status_update[2]["battery_command_mismatch_reason"]
        == "probable_external_override"
    )
    assert status_update[2]["battery_command_mismatch_w"] == 200.0
    assert "battery_probable_external_override" in status_update[2]["degraded_reasons"]


def test_thermal_policy_writes_soc_rails() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_max_output_w": 800,
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "thermal_hot_min_soc_pct": 15,
            "thermal_hot_max_soc_pct": 90,
            "thermal_hot_cap_limit_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "36",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "10",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "95",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})

    assert (
        "number/set_value",
        {"entity_id": "number.discharge_limit", "value": 15},
    ) in app.service_calls
    assert (
        "number/set_value",
        {"entity_id": "number.charging_limit", "value": 90},
    ) in app.service_calls
    status_update = _latest_status_update(app)
    assert status_update[2]["thermal_state"] == "HOT"
    assert status_update[2]["thermal_reason"] == "t30_threshold"
    assert status_update[2]["desired_min_soc_pct"] == 15.0
    assert status_update[2]["desired_max_soc_pct"] == 90.0
    assert status_update[2]["battery_min_soc_action"] == "write"
    assert status_update[2]["battery_max_soc_action"] == "write"


def test_soc_rail_writes_are_deduplicated_until_retry_window() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_max_output_w": 800,
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "thermal_hot_min_soc_pct": 15,
            "thermal_hot_max_soc_pct": 90,
            "thermal_hot_cap_limit_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "36",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "10",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "100",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    first_calls = list(_rail_service_calls(app))
    app._control_tick({})

    assert _rail_service_calls(app) == first_calls
    status_update = _latest_status_update(app)
    assert status_update[2]["battery_min_soc_action"] == "pending"
    assert status_update[2]["battery_max_soc_action"] == "pending"


def test_soc_rail_drift_is_reapplied_immediately() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_max_output_w": 800,
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "thermal_hot_min_soc_pct": 15,
            "thermal_hot_max_soc_pct": 90,
            "thermal_hot_cap_limit_w": 800,
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "36",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "10",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "100",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    app.state_map["number.discharge_limit"] = {
        "state": "15",
        "attributes": {"min": 0, "max": 30, "step": 1},
    }
    app.state_map["number.charging_limit"] = {
        "state": "90",
        "attributes": {"min": 70, "max": 100, "step": 1},
    }
    app._control_tick({})
    calls_after_alignment = len(_rail_service_calls(app))

    app.state_map["number.discharge_limit"] = {
        "state": "10",
        "attributes": {"min": 0, "max": 30, "step": 1},
    }
    app._control_tick({})

    assert len(_rail_service_calls(app)) == calls_after_alignment + 1
    assert _rail_service_calls(app)[-1] == (
        "number/set_value",
        {"entity_id": "number.discharge_limit", "value": 15},
    )


def test_thermal_heartbeat_can_use_dedicated_logger() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "thermal_log": "thermal_log",
            "thermal_log_level": "INFO",
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()
    app._thermal_heartbeat_tick({})

    thermal_messages = _messages_for_log(app, log_name="thermal_log")
    assert any("Thermal heartbeat" in message for message in thermal_messages)


def test_maintenance_state_is_persisted(tmp_path: Path) -> None:
    db_path = tmp_path / "var" / "maintenance.sqlite3"
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_max_output_w": 800,
            "persistence_dir": str(db_path),
            "maintenance_full_charge_threshold_pct": 99,
            "maintenance_full_charge_hold_s": 1800,
            "maintenance_max_age_days": 30,
            "maintenance_start_min_t30_c": 10,
            "maintenance_start_max_t30_c": 35,
            "maintenance_max_soc_pct": 100,
            "maintenance_path_cap_w": 0,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "20",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "15",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "95",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})

    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_max_output_w": 800,
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "20",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "15",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "95",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    reloaded_app.initialize()
    assert reloaded_app.controller.maintenance_active is True


def test_signal_histories_are_restored_on_restart(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_power_control_entity": "number.battery_limit",
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "100",
            "sensor.battery_temp": "10",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()

    app.state_map["sensor.battery_temp"] = "20"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 15, tzinfo=UTC)
    app._record_signal_sample(
        history_key="battery_temperature",
        entity_id="sensor.battery_temp",
        timestamp=_FixedDateTime.current,
    )

    app.state_map["sensor.load"] = "200"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 29, 50, tzinfo=UTC)
    app._record_signal_sample(
        history_key="consumption",
        entity_id="sensor.load",
        timestamp=_FixedDateTime.current,
    )

    app.state_map["sensor.load"] = "400"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 29, 55, tzinfo=UTC)
    app._record_signal_sample(
        history_key="consumption",
        entity_id="sensor.load",
        timestamp=_FixedDateTime.current,
    )

    restart_at = datetime(2026, 4, 10, 12, 30, tzinfo=UTC)
    expected_metrics = app._time_weighted_metrics(restart_at)
    history_map = {
        "sensor.load": _history_rows_from_samples(
            app.signal_histories["consumption"].samples()
        ),
        "sensor.battery_temp": _history_rows_from_samples(
            app.signal_histories["battery_temperature"].samples()
        ),
    }

    _FixedDateTime.current = restart_at
    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_power_control_entity": "number.battery_limit",
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "400",
            "sensor.battery_temp": "20",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
        history_map=history_map,
    )

    reloaded_app.initialize()
    restored_metrics = reloaded_app._time_weighted_metrics(restart_at)

    assert restored_metrics == expected_metrics


def test_stale_signal_histories_are_discarded_per_history(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_power_control_entity": "number.battery_limit",
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "100",
            "sensor.battery_temp": "10",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()

    app.state_map["sensor.load"] = "200"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 5, tzinfo=UTC)
    app._record_signal_sample(
        history_key="consumption",
        entity_id="sensor.load",
        timestamp=_FixedDateTime.current,
    )

    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 40, tzinfo=UTC)
    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_power_control_entity": "number.battery_limit",
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "300",
            "sensor.battery_temp": "10",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
        history_map={
            "sensor.load": _history_rows_from_samples(
                app.signal_histories["consumption"].samples()
            ),
            "sensor.battery_temp": [
                {
                    "state": "10",
                    "last_changed": datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
                }
            ],
        },
    )

    reloaded_app.initialize()

    assert reloaded_app.signal_histories["consumption"].sample_count == 1
    assert reloaded_app.signal_histories["battery_temperature"].sample_count == 2


def test_actuator_min_write_interval_is_preserved_across_restart(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 60,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "persistence_dir": str(db_path),
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    assert app.service_calls == [
        ("number/set_value", {"entity_id": "number.battery_limit", "value": 100})
    ]

    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 30, tzinfo=UTC)
    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 60,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "battery_max_output_w": 800,
            "persistence_dir": str(db_path),
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
    )

    reloaded_app.initialize()
    reloaded_app._control_tick({})

    assert reloaded_app.service_calls == []
    status_update = _latest_status_update(reloaded_app)
    assert status_update[2]["battery_action"] == "skip"
    assert status_update[2]["battery_reason"] == "min_write_interval"


def test_soc_rail_retry_window_is_preserved_across_restart(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_max_output_w": 800,
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "thermal_hot_min_soc_pct": 15,
            "thermal_hot_max_soc_pct": 90,
            "thermal_hot_cap_limit_w": 800,
            "persistence_dir": str(db_path),
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "36",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "10",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "100",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    assert len(_rail_service_calls(app)) == 2

    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 30, tzinfo=UTC)
    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_max_output_w": 800,
            "battery_power_step_w": 50,
            "battery_min_change_w": 50,
            "battery_min_write_interval_s": 0,
            "battery_max_increase_per_cycle_w": 500,
            "battery_max_decrease_per_cycle_w": 500,
            "battery_emergency_max_decrease_per_cycle_w": 500,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "thermal_hot_min_soc_pct": 15,
            "thermal_hot_max_soc_pct": 90,
            "thermal_hot_cap_limit_w": 800,
            "persistence_dir": str(db_path),
            "dry_run": False,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "36",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "10",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "100",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    reloaded_app.initialize()
    reloaded_app._control_tick({})

    assert _rail_service_calls(reloaded_app) == []
    status_update = _latest_status_update(reloaded_app)
    assert status_update[2]["battery_min_soc_action"] == "pending"
    assert status_update[2]["battery_max_soc_action"] == "pending"


def test_thermal_clear_hold_is_preserved_across_restart(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    store = RuntimeStateStore(db_path)
    store.save_runtime_snapshot(
        saved_at=datetime(2026, 4, 10, 12, 0, 30, tzinfo=UTC),
        snapshot={
            "controller": {
                "thermal_state": "HOT",
                "thermal_clear_elapsed_s": 30.0,
            }
        },
    )

    _FixedDateTime.current = datetime(2026, 4, 10, 12, 1, tzinfo=UTC)
    reloaded_app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_max_output_w": 800,
            "thermal_hot_enter_t30_c": 35,
            "thermal_hot_exit_t30_c": 33,
            "thermal_hot_exit_hold_s": 60,
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "32",
            "number.battery_limit": {
                "state": "100",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
        },
        history_map={
            "sensor.battery_temp": [
                {
                    "state": "32",
                    "last_changed": datetime(2026, 4, 10, 11, 31, tzinfo=UTC),
                },
                {
                    "state": "32",
                    "last_changed": datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
                },
            ]
        },
    )

    reloaded_app.initialize()
    reloaded_app._control_tick({})

    status_update = _latest_status_update(reloaded_app)
    assert status_update[2]["thermal_state"] == "NORMAL"
    assert status_update[2]["thermal_reason"] == "normal"


def test_device_feed_forward_state_is_preserved_across_restart(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(appdaemon_module.dt, "datetime", _FixedDateTime)
    db_path = tmp_path / "var" / "runtime.sqlite3"
    site_config_path = tmp_path / "site.yaml"
    site_config_path.write_text(
        "consumption:\n"
        "  entity: sensor.site_load\n"
        "battery:\n"
        "  power_control_entity: number.site_battery_limit\n"
        "  max_output_w: 800\n"
        "inverter:\n"
        "  power_control_entity: number.site_inverter_limit\n"
        "  max_output_w: 800\n"
        "devices:\n"
        "  microwave:\n"
        "    kind: burst_high_power\n"
        "    entity_id: sensor.outlet_microwave_power\n"
        "    high_threshold_w: 300\n"
        "    enter_persistence_s: 2\n"
        "    exit_persistence_s: 2\n"
        "    ff_gain: 0.95\n"
        "    ff_hold_s: 90\n",
        encoding="utf-8",
    )
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
    app = FakeHaPvOptimization(
        args={
            "site_config_path": str(site_config_path),
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.site_load": "200",
            "sensor.outlet_microwave_power": "1400",
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
    app._control_tick({})
    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 3, tzinfo=UTC)
    app._control_tick({})
    status_update = _latest_status_update(app)
    assert status_update[2]["device_feed_forward_w"] > 0.0

    _FixedDateTime.current = datetime(2026, 4, 10, 12, 0, 4, tzinfo=UTC)
    reloaded_app = FakeHaPvOptimization(
        args={
            "site_config_path": str(site_config_path),
            "persistence_dir": str(db_path),
            "dry_run": True,
        },
        state_map={
            "sensor.site_load": "200",
            "sensor.outlet_microwave_power": "1400",
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

    reloaded_app.initialize()
    reloaded_app._control_tick({})

    status_update = _latest_status_update(reloaded_app)
    assert status_update[2]["device_feed_forward_w"] > 0.0
    assert "microwave" in status_update[2]["active_device_feed_forward"]


def test_maintenance_status_fields_are_published() -> None:
    app = FakeHaPvOptimization(
        args={
            "consumption_entity": "sensor.load",
            "battery_power_control_entity": "number.battery_limit",
            "battery_temperature_entity": "sensor.battery_temp",
            "battery_charging_limit_entity": "number.charging_limit",
            "battery_discharge_limit_entity": "number.discharge_limit",
            "battery_max_output_w": 800,
            "maintenance_full_charge_threshold_pct": 99,
            "maintenance_full_charge_hold_s": 1800,
            "maintenance_max_age_days": 30,
            "maintenance_start_min_t30_c": 10,
            "maintenance_start_max_t30_c": 35,
            "maintenance_max_soc_pct": 100,
            "maintenance_path_cap_w": 0,
            "dry_run": True,
        },
        state_map={
            "sensor.load": "200",
            "sensor.battery_temp": "20",
            "number.battery_limit": {
                "state": "0",
                "attributes": {"min": 0, "max": 800, "step": 50},
            },
            "number.discharge_limit": {
                "state": "15",
                "attributes": {"min": 0, "max": 30, "step": 1},
            },
            "number.charging_limit": {
                "state": "95",
                "attributes": {"min": 70, "max": 100, "step": 1},
            },
        },
    )

    app.initialize()
    app._control_tick({})
    status_update = _latest_status_update(app)
    assert status_update[2]["maintenance_active"] is True
    assert status_update[2]["maintenance_due"] is True
    assert status_update[2]["maintenance_reason"] == "started"
