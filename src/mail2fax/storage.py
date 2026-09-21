"""Persistenz der Faxauftraege (SQLite).

Die Datenbank dient als Warteschlange, als Nachweis (wer hat wann was an wen
gefaxt) und als Schutz gegen Doppelversand ueber die Message-ID.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import DB_PATH

STATUS_QUEUED = "queued"
STATUS_SENDING = "sending"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_REJECTED = "rejected"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    message_id      TEXT,
    sender          TEXT NOT NULL DEFAULT '',
    subject         TEXT NOT NULL DEFAULT '',
    number          TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'mail',
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    pages           INTEGER,
    documents       TEXT NOT NULL DEFAULT '[]',
    error           TEXT,
    backend         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_message_id
    ON jobs (message_id) WHERE message_id IS NOT NULL AND message_id != '';

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    job_id     INTEGER,
    level      TEXT NOT NULL DEFAULT 'info',
    message    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events (job_id, id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at DESC);
"""


@dataclass
class Job:
    """Ein Faxauftrag."""

    id: int
    created_at: float
    updated_at: float
    message_id: str | None
    sender: str
    subject: str
    number: str
    source: str
    status: str
    attempts: int
    next_attempt_at: float
    pages: int | None
    documents: list[str] = field(default_factory=list)
    error: str | None = None
    backend: str = ""

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Job:
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_id=row["message_id"],
            sender=row["sender"],
            subject=row["subject"],
            number=row["number"],
            source=row["source"],
            status=row["status"],
            attempts=row["attempts"],
            next_attempt_at=row["next_attempt_at"],
            pages=row["pages"],
            documents=json.loads(row["documents"] or "[]"),
            error=row["error"],
            backend=row["backend"],
        )


class Storage:
    """Duenner Wrapper um SQLite - bewusst ohne ORM."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self._connection:
            self._connection.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._connection:
            yield self._connection

    # -- Auftraege ---------------------------------------------------------

    def message_seen(self, message_id: str | None) -> bool:
        """Prueft, ob zu dieser Message-ID bereits ein Auftrag existiert."""
        if not message_id:
            return False
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM jobs WHERE message_id = ? LIMIT 1", (message_id,)
            ).fetchone()
        return row is not None

    def create_job(
        self,
        *,
        sender: str,
        subject: str,
        number: str,
        documents: list[str] | None = None,
        message_id: str | None = None,
        status: str = STATUS_QUEUED,
        source: str = "mail",
        pages: int | None = None,
        error: str | None = None,
        backend: str = "",
    ) -> Job:
        now = time.time()
        with self._tx() as connection:
            cursor = connection.execute(
                """
                INSERT INTO jobs (created_at, updated_at, message_id, sender, subject,
                                  number, source, status, attempts, next_attempt_at,
                                  pages, documents, error, backend)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    now, now, message_id or None, sender, subject, number, source, status,
                    now, pages, json.dumps(documents or []), error, backend,
                ),
            )
            job_id = int(cursor.lastrowid or 0)
        job = self.get_job(job_id)
        assert job is not None
        return job

    def get_job(self, job_id: int) -> Job | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return Job.from_row(row) if row else None

    def list_jobs(self, *, limit: int = 100, status: str | None = None) -> list[Job]:
        query = "SELECT * FROM jobs"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [Job.from_row(row) for row in rows]

    def due_jobs(self, *, limit: int = 10) -> list[Job]:
        """Auftraege, die jetzt (erneut) versendet werden duerfen."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = ? AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, id ASC LIMIT ?
                """,
                (STATUS_QUEUED, time.time(), limit),
            ).fetchall()
        return [Job.from_row(row) for row in rows]

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        if "documents" in fields and not isinstance(fields["documents"], str):
            fields["documents"] = json.dumps(fields["documents"])
        fields["updated_at"] = time.time()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._tx() as connection:
            connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 - Keys sind intern
                [*fields.values(), job_id],
            )

    def count_recent(self, *, since: float, sender: str | None = None) -> int:
        """Zaehlt angenommene Auftraege seit einem Zeitpunkt (fuer Ratelimits)."""
        query = "SELECT COUNT(*) FROM jobs WHERE created_at >= ? AND status != ?"
        params: list[Any] = [since, STATUS_REJECTED]
        if sender:
            query += " AND sender = ?"
            params.append(sender.lower())
        with self._lock:
            row = self._connection.execute(query, params).fetchone()
        return int(row[0])

    def stats(self) -> dict[str, int]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS anzahl FROM jobs GROUP BY status"
            ).fetchall()
        result = {
            STATUS_QUEUED: 0,
            STATUS_SENDING: 0,
            STATUS_SENT: 0,
            STATUS_FAILED: 0,
            STATUS_REJECTED: 0,
        }
        for row in rows:
            result[row["status"]] = row["anzahl"]
        return result

    # -- Ereignisse --------------------------------------------------------

    def log_event(self, message: str, *, job_id: int | None = None, level: str = "info") -> None:
        with self._tx() as connection:
            connection.execute(
                "INSERT INTO events (created_at, job_id, level, message) VALUES (?, ?, ?, ?)",
                (time.time(), job_id, level, message[:2000]),
            )

    def list_events(self, *, job_id: int | None = None, limit: int = 200) -> list[sqlite3.Row]:
        query = "SELECT * FROM events"
        params: list[Any] = []
        if job_id is not None:
            query += " WHERE job_id = ?"
            params.append(job_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return list(self._connection.execute(query, params).fetchall())

    # -- Aufbewahrung ------------------------------------------------------

    def purge_old(self, retention_days: int) -> int:
        """Loescht Historie aelter als ``retention_days`` (0 = deaktiviert)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        with self._tx() as connection:
            cursor = connection.execute(
                "DELETE FROM jobs WHERE created_at < ? AND status IN (?, ?, ?)",
                (cutoff, STATUS_SENT, STATUS_FAILED, STATUS_REJECTED),
            )
            connection.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
            return cursor.rowcount or 0
