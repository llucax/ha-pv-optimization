from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ha_pv_optimization.models import MaintenanceStateSnapshot
from ha_pv_optimization.storage import RuntimeStateStore


def test_runtime_state_store_round_trips_maintenance_snapshot(tmp_path: Path) -> None:
    state_dir = tmp_path / "var"
    store = RuntimeStateStore(state_dir)
    snapshot = MaintenanceStateSnapshot(
        maintenance_active=True,
        full_charge_elapsed_s=123.0,
        last_full_charge_at=datetime(2026, 4, 3, 12, 0, tzinfo=UTC),
    )

    store.save_maintenance_state(snapshot)
    loaded = store.load_maintenance_state()

    assert loaded == snapshot


def test_runtime_state_store_round_trips_runtime_snapshot(tmp_path: Path) -> None:
    state_dir = tmp_path / "var"
    store = RuntimeStateStore(state_dir)
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

    store.save_runtime_snapshot(saved_at=saved_at, snapshot=snapshot)
    loaded = store.load_runtime_snapshot()
    written = json.loads((state_dir / "control_runtime_state.json").read_text())

    assert loaded == (saved_at, snapshot)
    assert written["saved_at"] == saved_at.isoformat()
    assert written["controller"] == snapshot["controller"]
    assert written["actuators"] == snapshot["actuators"]
    assert "payload" not in written


def test_wrapped_runtime_snapshot_is_ignored(tmp_path: Path) -> None:
    warnings: list[str] = []
    state_dir = tmp_path / "var"
    state_dir.mkdir(parents=True)
    (state_dir / "control_runtime_state.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "saved_at": datetime(2026, 4, 3, 12, 0, tzinfo=UTC).isoformat(),
                "payload": {"controller": {"cap_cmd_w": 150.0}},
            }
        ),
        encoding="utf-8",
    )

    store = RuntimeStateStore(state_dir, on_warning=warnings.append)

    assert store.load_runtime_snapshot() is None
    assert warnings


def test_malformed_maintenance_state_falls_back_to_defaults(tmp_path: Path) -> None:
    warnings: list[str] = []
    state_dir = tmp_path / "var"
    state_dir.mkdir(parents=True)
    (state_dir / "maintenance_state.json").write_text("{oops", encoding="utf-8")

    store = RuntimeStateStore(state_dir, on_warning=warnings.append)

    loaded = store.load_maintenance_state()

    assert loaded == MaintenanceStateSnapshot(
        maintenance_active=False,
        full_charge_elapsed_s=0.0,
        last_full_charge_at=None,
    )
    assert warnings


def test_malformed_runtime_snapshot_is_ignored(tmp_path: Path) -> None:
    warnings: list[str] = []
    state_dir = tmp_path / "var"
    state_dir.mkdir(parents=True)
    (state_dir / "control_runtime_state.json").write_text(
        '{"saved_at":"nope","payload":[]}',
        encoding="utf-8",
    )

    store = RuntimeStateStore(state_dir, on_warning=warnings.append)

    assert store.load_runtime_snapshot() is None
    assert warnings
