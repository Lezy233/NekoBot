"""SQLite 会话历史存储层。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "chat.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            session_key TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()
    return connection


def append(session_key: str, role: str, content: str) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages (session_key, role, content) VALUES (?, ?, ?)",
            (session_key, role, content),
        )


def get_recent(session_key: str, limit: int) -> list[dict[str, str]]:
    limit = max(1, int(limit))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT role, content
            FROM (
                SELECT id, role, content
                FROM messages
                WHERE session_key = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_key, limit),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]

