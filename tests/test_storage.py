from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ha_pv_optimization.models import MaintenanceStateSnapshot
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
