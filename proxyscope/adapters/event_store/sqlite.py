from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import cast

from proxyscope.application.event_store import StoredEvent
from proxyscope.application.events import RequestObserved, ResponseObserved, RuntimeEvent

PAYLOAD_VERSION = 1


class SQLiteEventStore:
    def __init__(
        self,
        path: str | Path,
        *,
        max_body_bytes: int = 4096,
        max_events: int | None = None,
        max_age_days: int | None = None,
        max_storage_bytes: int | None = None,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be greater than zero.")
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._max_body_bytes = max_body_bytes
        self._max_events = max_events
        self._max_age_days = max_age_days
        self._max_storage_bytes = max_storage_bytes
        self._create_schema()

    def append(self, event: RuntimeEvent) -> None:
        payload = _event_payload(event, max_body_bytes=self._max_body_bytes)
        metadata = _metadata(event)
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO events (
                    event_id, event_type, occurred_at, request_id, component_id,
                    target_host, method, status_code, payload_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.occurred_at.timestamp(),
                    event.request_id,
                    event.component_id,
                    metadata["target_host"],
                    metadata["method"],
                    metadata["status_code"],
                    PAYLOAD_VERSION,
                    json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                ),
            )
            self._apply_retention()
            self._connection.commit()

    def list_events(
        self,
        *,
        request_id: int | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
    ) -> tuple[StoredEvent, ...]:
        clauses: list[str] = []
        values: list[object] = []
        if request_id is not None:
            clauses.append("request_id = ?")
            values.append(request_id)
        if occurred_after is not None:
            clauses.append("occurred_at >= ?")
            values.append(occurred_after.timestamp())
        if occurred_before is not None:
            clauses.append("occurred_at <= ?")
            values.append(occurred_before.timestamp())
        where = "" if not clauses else f" WHERE {' AND '.join(clauses)}"
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM events" + where + " ORDER BY occurred_at ASC, row_id ASC", values
            ).fetchall()
        return tuple(_stored_event(row) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    row_id INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    request_id INTEGER,
                    component_id TEXT,
                    target_host TEXT,
                    method TEXT,
                    status_code INTEGER,
                    payload_version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_occurred_at_idx ON events (occurred_at);
                CREATE INDEX IF NOT EXISTS events_event_type_idx ON events (event_type);
                CREATE INDEX IF NOT EXISTS events_request_id_idx ON events (request_id);
                CREATE INDEX IF NOT EXISTS events_component_id_idx ON events (component_id);
                CREATE INDEX IF NOT EXISTS events_target_host_idx ON events (target_host);
                CREATE INDEX IF NOT EXISTS events_method_idx ON events (method);
                CREATE INDEX IF NOT EXISTS events_status_code_idx ON events (status_code);
                """
            )
            self._connection.commit()

    def _apply_retention(self) -> None:
        if self._max_age_days is not None:
            threshold = datetime.now(UTC).timestamp() - self._max_age_days * 86_400
            self._connection.execute("DELETE FROM events WHERE occurred_at < ?", (threshold,))
        if self._max_events is not None:
            self._connection.execute(
                "DELETE FROM events WHERE row_id NOT IN (SELECT row_id FROM events ORDER BY row_id DESC LIMIT ?)",
                (self._max_events,),
            )
        if self._max_storage_bytes is not None:
            rows = self._connection.execute(
                "SELECT row_id, length(payload_json) AS payload_size FROM events ORDER BY row_id DESC"
            ).fetchall()
            total = 0
            expired: list[int] = []
            for row in rows:
                total += int(row["payload_size"])
                if total > self._max_storage_bytes:
                    expired.append(int(row["row_id"]))
            if expired:
                self._connection.executemany("DELETE FROM events WHERE row_id = ?", ((row_id,) for row_id in expired))


def _metadata(event: RuntimeEvent) -> dict[str, str | int | None]:
    return {
        "target_host": event.target_host if isinstance(event, RequestObserved) else None,
        "method": event.method if isinstance(event, RequestObserved) else None,
        "status_code": event.status_code if isinstance(event, ResponseObserved) else None,
    }


def _event_payload(event: RuntimeEvent, *, max_body_bytes: int) -> dict[str, object]:
    return cast(dict[str, object], _json_value(asdict(event), max_body_bytes=max_body_bytes))


def _json_value(value: object, *, max_body_bytes: int) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        preview = value[:max_body_bytes]
        return {
            "encoding": "base64",
            "content": base64.b64encode(preview).decode("ascii"),
            "size": len(value),
            "truncated": len(value) > len(preview),
        }
    if isinstance(value, dict):
        return {str(key): _json_value(item, max_body_bytes=max_body_bytes) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item, max_body_bytes=max_body_bytes) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item, max_body_bytes=max_body_bytes) for item in value]
    return value


def _stored_event(row: sqlite3.Row) -> StoredEvent:
    return StoredEvent(
        event_id=str(row["event_id"]),
        event_type=str(row["event_type"]),
        occurred_at=datetime.fromtimestamp(float(row["occurred_at"]), tz=UTC),
        request_id=cast(int | None, row["request_id"]),
        component_id=cast(str | None, row["component_id"]),
        target_host=cast(str | None, row["target_host"]),
        method=cast(str | None, row["method"]),
        status_code=cast(int | None, row["status_code"]),
        payload_version=int(row["payload_version"]),
        payload=cast(dict[str, object], json.loads(str(row["payload_json"]))),
    )
