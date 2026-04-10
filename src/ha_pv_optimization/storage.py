from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import MaintenanceStateSnapshot
from .signals import TimedValue


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

    def load_signal_histories(self) -> dict[str, tuple[TimedValue, ...]]:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            rows = connection.execute(
                """
                SELECT history_key, recorded_at, value
                FROM signal_history_samples
                ORDER BY history_key, recorded_at
                """
            ).fetchall()

        histories: dict[str, list[TimedValue]] = {}
        for history_key, recorded_at, value in rows:
            histories.setdefault(str(history_key), []).append(
                TimedValue(
                    timestamp=datetime.fromisoformat(recorded_at).astimezone(UTC),
                    value=float(value),
                )
            )
        return {
            history_key: tuple(samples) for history_key, samples in histories.items()
        }

    def save_signal_sample(
        self,
        history_key: str,
        timestamp: datetime,
        value: float,
        *,
        max_history_s: float,
    ) -> None:
        if max_history_s <= 0:
            raise ValueError("`max_history_s` must be positive")

        self._ensure_parent_dir()
        timestamp_utc = timestamp.astimezone(UTC)
        recorded_at = timestamp_utc.isoformat()
        cutoff_at = (timestamp_utc - timedelta(seconds=max_history_s)).isoformat()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO signal_history_samples (history_key, recorded_at, value)
                VALUES (?, ?, ?)
                ON CONFLICT(history_key, recorded_at) DO UPDATE SET
                    value = excluded.value
                """,
                (history_key, recorded_at, value),
            )
            anchor_row = connection.execute(
                """
                SELECT MAX(recorded_at)
                FROM signal_history_samples
                WHERE history_key = ?
                  AND recorded_at <= ?
                """,
                (history_key, cutoff_at),
            ).fetchone()
            anchor_recorded_at = anchor_row[0]
            if anchor_recorded_at is not None:
                connection.execute(
                    """
                    DELETE FROM signal_history_samples
                    WHERE history_key = ?
                      AND recorded_at < ?
                    """,
                    (history_key, anchor_recorded_at),
                )
            connection.commit()

    def clear_signal_history(self, history_key: str) -> None:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            connection.execute(
                "DELETE FROM signal_history_samples WHERE history_key = ?",
                (history_key,),
            )
            connection.commit()

    def load_runtime_snapshot(self) -> tuple[datetime, dict[str, Any]] | None:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT saved_at, payload
                FROM control_runtime_state
                WHERE id = 1
                """
            ).fetchone()

        if row is None:
            return None

        return (
            datetime.fromisoformat(row[0]).astimezone(UTC),
            json.loads(row[1]),
        )

    def save_runtime_snapshot(
        self,
        *,
        saved_at: datetime,
        payload: dict[str, Any],
    ) -> None:
        self._ensure_parent_dir()
        with sqlite3.connect(self.path) as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                INSERT INTO control_runtime_state (id, saved_at, payload)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    saved_at = excluded.saved_at,
                    payload = excluded.payload
                """,
                (
                    saved_at.astimezone(UTC).isoformat(),
                    json.dumps(payload, sort_keys=True),
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_history_samples (
                history_key TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (history_key, recorded_at)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS control_runtime_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                saved_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
