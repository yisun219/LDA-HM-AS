from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from lda.models import RunState


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sequence: int
    run_id: str
    kind: str
    payload: dict[str, Any]
    created_at: datetime


class EventStore:
    """Transactional SQLite state plus append-only JSONL audit log."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "state.sqlite3"
        self.jsonl_path = self.root / "events.jsonl"
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sandbox_id TEXT,
                    metadata_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_threads (
                    agent_key TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    checkpoint_ref TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def save_run(self, state: RunState, kind: str, payload: dict[str, Any] | None = None) -> Event:
        state.touch()
        now = datetime.now(timezone.utc)
        state_json = state.model_dump_json()
        payload_json = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO runs(run_id,state_json,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(run_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at",
                (state.run_id, state_json, now.isoformat()),
            )
            cursor = db.execute(
                "INSERT INTO events(run_id,kind,payload_json,created_at) VALUES(?,?,?,?)",
                (state.run_id, kind, payload_json, now.isoformat()),
            )
            sequence = int(cursor.lastrowid)
            db.commit()
            event = Event(
                sequence=sequence,
                run_id=state.run_id,
                kind=kind,
                payload=payload or {},
                created_at=now,
            )
            with self.jsonl_path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
                stream.flush()
            run_file = self.root / "runs" / f"{state.run_id}.json"
            run_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = run_file.with_suffix(".json.tmp")
            temporary.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.replace(run_file)
            return event

    def load_run(self, run_id: str) -> RunState:
        with self._connect() as db:
            row = db.execute("SELECT state_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return RunState.model_validate_json(row[0])

    def list_events(self, run_id: str) -> list[Event]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT sequence,kind,payload_json,created_at FROM events WHERE run_id=? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return [
            Event(
                sequence=row[0],
                run_id=run_id,
                kind=row[1],
                payload=json.loads(row[2]),
                created_at=datetime.fromisoformat(row[3]),
            )
            for row in rows
        ]

    def record_lease(self, lease_id: str, run_id: str, metadata: dict[str, str], status: str, sandbox_id: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO leases(lease_id,run_id,sandbox_id,metadata_json,status,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(lease_id) DO UPDATE SET sandbox_id=excluded.sandbox_id,status=excluded.status,updated_at=excluded.updated_at",
                (lease_id, run_id, sandbox_id, json.dumps(metadata, sort_keys=True), status, now),
            )

    def lease(self, lease_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id,sandbox_id,metadata_json,status,updated_at FROM leases WHERE lease_id=?",
                (lease_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0],
            "sandbox_id": row[1],
            "metadata": json.loads(row[2]),
            "status": row[3],
            "updated_at": row[4],
        }

    def save_thread(self, agent_key: str, thread_id: str, checkpoint_ref: str | None) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO agent_threads(agent_key,thread_id,checkpoint_ref,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(agent_key) DO UPDATE SET thread_id=excluded.thread_id,checkpoint_ref=excluded.checkpoint_ref,updated_at=excluded.updated_at",
                (agent_key, thread_id, checkpoint_ref, datetime.now(timezone.utc).isoformat()),
            )

    def load_thread(self, agent_key: str) -> tuple[str, str | None] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT thread_id,checkpoint_ref FROM agent_threads WHERE agent_key=?",
                (agent_key,),
            ).fetchone()
        return (row[0], row[1]) if row else None
