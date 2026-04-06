from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import MaintenanceStateSnapshot


class RuntimeStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load_maintenance_state(self) -> MaintenanceStateSnapshot:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT maintenance_active, full_charge_elapsed_s, last_full_charge_at
                FROM maintenance_state
                WHERE id = 1
                """
            ).fetchone()

        if row is None:
            return MaintenanceStateSnapshot(
                maintenance_active=False,
                full_charge_elapsed_s=0.0,
                last_full_charge_at=None,
            )

        last_full_charge_at = None
        if row[2] is not None:
            last_full_charge_at = datetime.fromisoformat(row[2]).astimezone(UTC)

        return MaintenanceStateSnapshot(
            maintenance_active=bool(row[0]),
            full_charge_elapsed_s=float(row[1]),
            last_full_charge_at=last_full_charge_at,
        )

    def save_maintenance_state(self, snapshot: MaintenanceStateSnapshot) -> None:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO maintenance_state (
                    id,
                    maintenance_active,
                    full_charge_elapsed_s,
                    last_full_charge_at
                ) VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    maintenance_active = excluded.maintenance_active,
                    full_charge_elapsed_s = excluded.full_charge_elapsed_s,
                    last_full_charge_at = excluded.last_full_charge_at
                """,
                (
                    int(snapshot.maintenance_active),
                    snapshot.full_charge_elapsed_s,
                    None
                    if snapshot.last_full_charge_at is None
                    else snapshot.last_full_charge_at.astimezone(UTC).isoformat(),
                ),
            )
            connection.commit()

    def _ensure_parent_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS maintenance_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                maintenance_active INTEGER NOT NULL,
                full_charge_elapsed_s REAL NOT NULL,
                last_full_charge_at TEXT
            )
            """
        )
