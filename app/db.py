from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import get_db_path


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL;")
    return connection


@contextmanager
def connection_context() -> sqlite3.Connection:
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def initialize_db() -> None:
    with connection_context() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entity_type TEXT NOT NULL,
              slug TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft',
              data_json TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1,
              effective_at TEXT,
              published_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              updated_by TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_type_slug_version
            ON entities(entity_type, slug, version);

            CREATE INDEX IF NOT EXISTS idx_entities_status
            ON entities(status);

            CREATE TABLE IF NOT EXISTS chat_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              question TEXT NOT NULL,
              answer_text TEXT NOT NULL,
              answer_mode TEXT NOT NULL,
              matched_entity_type TEXT,
              matched_entity_id INTEGER,
              confidence_level TEXT NOT NULL,
              source_records_json TEXT NOT NULL,
              debug_trace_json TEXT NOT NULL DEFAULT '{}',
              needs_verification INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS unmatched_questions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              question TEXT NOT NULL,
              reason TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS entity_embeddings (
              entity_id INTEGER NOT NULL,
              entity_type TEXT NOT NULL,
              version INTEGER NOT NULL,
              source_text_hash TEXT NOT NULL,
              embedding_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (entity_id, entity_type, version)
            );

            CREATE TABLE IF NOT EXISTS session_state (
              session_id TEXT PRIMARY KEY,
              focused_entity_type TEXT,
              focused_entity_id INTEGER,
              focus_source_records_json TEXT NOT NULL DEFAULT '[]',
              conversation_mode TEXT,
              updated_at TEXT NOT NULL
            );
            """
        )
        chat_log_columns = {row["name"] for row in connection.execute("PRAGMA table_info(chat_logs)").fetchall()}
        if "debug_trace_json" not in chat_log_columns:
            connection.execute("ALTER TABLE chat_logs ADD COLUMN debug_trace_json TEXT NOT NULL DEFAULT '{}'")
        connection.commit()
