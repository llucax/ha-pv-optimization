from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import MaintenanceStateSnapshot


class RuntimeStateStore:
    def __init__(
        self,
        dir_path: Path,
        *,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self.dir_path = dir_path
        self.on_warning = on_warning

    def load_maintenance_state(self) -> MaintenanceStateSnapshot:
        payload = self._load_json(self._maintenance_state_path())
        if payload is None:
            return self._default_maintenance_state()

        try:
            last_full_charge_at = self._optional_datetime(
                payload.get("last_full_charge_at")
            )
            return MaintenanceStateSnapshot(
                maintenance_active=bool(payload.get("maintenance_active", False)),
                full_charge_elapsed_s=float(payload.get("full_charge_elapsed_s", 0.0)),
                last_full_charge_at=last_full_charge_at,
            )
        except (TypeError, ValueError) as exc:
            self._warn(
                "Ignoring malformed maintenance state file"
                f" {self._maintenance_state_path()}: {exc}"
            )
            return self._default_maintenance_state()

    def save_maintenance_state(self, snapshot: MaintenanceStateSnapshot) -> None:
        self._save_json_atomic(
            self._maintenance_state_path(),
            {
                "format_version": 1,
                "saved_at": datetime.now(UTC).isoformat(),
                "maintenance_active": snapshot.maintenance_active,
                "full_charge_elapsed_s": snapshot.full_charge_elapsed_s,
                "last_full_charge_at": self._encode_datetime(
                    snapshot.last_full_charge_at
                ),
            },
        )

    def load_runtime_snapshot(self) -> tuple[datetime, dict[str, Any]] | None:
        document = self._load_json(self._runtime_snapshot_path())
        if document is None:
            return None

        try:
            saved_at = self._required_datetime(document.get("saved_at"))
            snapshot = self._runtime_snapshot_from_document(document)
        except (TypeError, ValueError) as exc:
            self._warn(
                "Ignoring malformed runtime snapshot file"
                f" {self._runtime_snapshot_path()}: {exc}"
            )
            return None

        return saved_at, snapshot

    def save_runtime_snapshot(
        self,
        *,
        saved_at: datetime,
        snapshot: dict[str, Any],
    ) -> None:
        document = dict(snapshot)
        document["format_version"] = 1
        document["saved_at"] = saved_at.astimezone(UTC).isoformat()
        self._save_json_atomic(
            self._runtime_snapshot_path(),
            document,
        )

    def _default_maintenance_state(self) -> MaintenanceStateSnapshot:
        return MaintenanceStateSnapshot(
            maintenance_active=False,
            full_charge_elapsed_s=0.0,
            last_full_charge_at=None,
        )

    def _maintenance_state_path(self) -> Path:
        return self.dir_path / "maintenance_state.json"

    def _runtime_snapshot_path(self) -> Path:
        return self.dir_path / "control_runtime_state.json"

    def _runtime_snapshot_from_document(
        self,
        document: dict[str, Any],
    ) -> dict[str, Any]:
        if "payload" in document:
            raise ValueError("payload wrapper is not supported")

        return {
            key: value
            for key, value in document.items()
            if key not in {"format_version", "saved_at"}
        }

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        self._ensure_dir()
        if not path.exists():
            return None

        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            self._warn(f"Ignoring unreadable persistence file {path}: {exc}")
            return None

        if not isinstance(payload, dict):
            self._warn(
                f"Ignoring persistence file {path}: root value must be a mapping"
            )
            return None
        return payload

    def _save_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        self._ensure_dir()
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            self._fsync_dir(path.parent)
        except Exception:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _ensure_dir(self) -> None:
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def _fsync_dir(self, path: Path) -> None:
        dir_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _warn(self, message: str) -> None:
        if self.on_warning is not None:
            self.on_warning(message)

    def _required_datetime(self, value: object) -> datetime:
        timestamp = self._optional_datetime(value)
        if timestamp is None:
            raise ValueError("expected ISO datetime")
        return timestamp

    def _optional_datetime(self, value: object) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("expected ISO datetime string")
        return datetime.fromisoformat(value).astimezone(UTC)

    def _encode_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).isoformat()
