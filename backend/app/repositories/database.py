from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from backend.app.core.config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "backend" / "data"
DB_PATH = DATA_DIR / "qcmaker.sqlite3"


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def transaction(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_database() -> None:
    with transaction(immediate=True) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets(dataset_id TEXT PRIMARY KEY,filename TEXT NOT NULL,revision INTEGER NOT NULL,confirmed_revision INTEGER,raw_rows_json TEXT NOT NULL,current_rows_json TEXT NOT NULL,columns_json TEXT NOT NULL,report_json TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,reserved_usd TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,request_id TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,input_tokens INTEGER NOT NULL,output_tokens INTEGER NOT NULL,embedding_tokens INTEGER NOT NULL,cost_usd TEXT NOT NULL,price_effective_from TEXT,created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files(file_id TEXT PRIMARY KEY,display_name TEXT NOT NULL,disk_path TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS discussion_sessions(session_id TEXT PRIMARY KEY,status TEXT NOT NULL,state_json TEXT NOT NULL,next_event_seq INTEGER NOT NULL,lease_owner TEXT,lease_generation INTEGER NOT NULL DEFAULT 0,lease_until TEXT,expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS discussion_commands(session_id TEXT NOT NULL,client_message_id TEXT NOT NULL,payload_json TEXT NOT NULL,status TEXT NOT NULL,picked_at TEXT,completed_at TEXT,error_json TEXT,PRIMARY KEY(session_id,client_message_id));
            CREATE TABLE IF NOT EXISTS discussion_events(session_id TEXT NOT NULL,event_seq INTEGER NOT NULL,client_message_id TEXT,event_type TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(session_id,event_seq));
            CREATE TABLE IF NOT EXISTS llm_operations(operation_id TEXT PRIMARY KEY,status TEXT NOT NULL,response_json TEXT,usage_id TEXT);
            """
        )

