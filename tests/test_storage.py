from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ha_pv_optimization.models import MaintenanceStateSnapshot
from ha_pv_optimization.signals import TimedValue
from ha_pv_optimization.storage import RuntimeStateStore


def test_runtime_state_store_round_trips_maintenance_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "var" / "state.sqlite3"
    store = RuntimeStateStore(db_path)
    snapshot = MaintenanceStateSnapshot(
        maintenance_active=True,
        full_charge_elapsed_s=123.0,
        last_full_charge_at=datetime(2026, 4, 3, 12, 0, tzinfo=UTC),
    )

    store.save_maintenance_state(snapshot)
    loaded = store.load_maintenance_state()

    assert loaded == snapshot


def test_runtime_state_store_round_trips_signal_histories(tmp_path: Path) -> None:
    db_path = tmp_path / "var" / "state.sqlite3"
    store = RuntimeStateStore(db_path)
    start = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)

    store.save_signal_sample(
        "consumption",
        start,
        120.0,
        max_history_s=3600.0,
    )
    store.save_signal_sample(
        "consumption",
        start + timedelta(seconds=30),
        240.0,
        max_history_s=3600.0,
    )
    store.save_signal_sample(
        "battery_temperature",
        start + timedelta(minutes=5),
        21.5,
        max_history_s=7200.0,
    )

    loaded = store.load_signal_histories()

    assert loaded == {
        "battery_temperature": (TimedValue(start + timedelta(minutes=5), 21.5),),
        "consumption": (
            TimedValue(start, 120.0),
            TimedValue(start + timedelta(seconds=30), 240.0),
        ),
    }


def test_runtime_state_store_round_trips_runtime_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "var" / "state.sqlite3"
    store = RuntimeStateStore(db_path)
    saved_at = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)
    snapshot = {
        "controller": {
            "cap_cmd_w": 150.0,
            "thermal_state": "HOT",
        },
        "actuators": {
            "battery": {
                "last_write_at": saved_at.isoformat(),
                "last_command_target_w": 150.0,
                "last_command_observed_w": 100.0,
            }
        },
    }

    store.save_runtime_snapshot(saved_at=saved_at, payload=snapshot)
    loaded = store.load_runtime_snapshot()

    assert loaded == (saved_at, snapshot)
