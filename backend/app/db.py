from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
DATA_DIR = Path(os.environ.get("DL_MANAGER_DATA_DIR", APP_DIR / "data")).expanduser().resolve()
RUNS_DIR = DATA_DIR / "runs"
DB_PATH = DATA_DIR / "manager.db"
_lock = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    with _lock, connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                framework TEXT NOT NULL,
                entrypoint TEXT NOT NULL,
                adapter_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                values_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
                pid INTEGER,
                status TEXT NOT NULL,
                command_json TEXT NOT NULL,
                run_dir TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                epoch REAL,
                step REAL,
                recorded_at TEXT NOT NULL
            );
            """
        )


def execute(sql: str, params: tuple[Any, ...] = ()) -> int:
    with _lock, connect() as db:
        cursor = db.execute(sql, params)
        db.commit()
        return int(cursor.lastrowid)


def query(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _lock, connect() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def decode(row: dict[str, Any] | None, *fields: str) -> dict[str, Any] | None:
    if not row:
        return None
    result = dict(row)
    for field in fields:
        if result.get(field):
            result[field.removesuffix("_json")] = json.loads(result.pop(field))
    return result
