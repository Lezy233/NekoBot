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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS summaries (
            session_key TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            compressed_until INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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


def clear_history(session_key: str) -> None:
    """删除指定会话的全部聊天记录与摘要。"""
    with _connect() as connection:
        connection.execute("DELETE FROM messages WHERE session_key = ?", (session_key,))
        connection.execute("DELETE FROM summaries WHERE session_key = ?", (session_key,))


def count_messages(session_key: str) -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE session_key = ?",
            (session_key,),
        ).fetchone()
    return row["count"]


def get_summary(session_key: str) -> str:
    with _connect() as connection:
        row = connection.execute(
            "SELECT summary FROM summaries WHERE session_key = ?",
            (session_key,),
        ).fetchone()
    return row["summary"] if row else ""


def save_summary(session_key: str, summary: str, compressed_until: int) -> None:
    """写入或更新会话摘要，compressed_until 为已压缩消息的最大 id。"""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO summaries (session_key, summary, compressed_until, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_key) DO UPDATE SET
                summary = excluded.summary,
                compressed_until = excluded.compressed_until,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_key, summary, compressed_until),
        )


def get_compressible(session_key: str, keep_recent: int) -> list[dict]:
    """返回滑动窗口之外且尚未压缩的消息（含 id），按时间升序。"""
    with _connect() as connection:
        boundary = connection.execute(
            "SELECT id FROM messages WHERE session_key = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
            (session_key, keep_recent),
        ).fetchone()
        if boundary is None:
            return []
        rows = connection.execute(
            """
            SELECT id, role, content FROM messages
            WHERE session_key = ?
              AND id < ?
              AND id > COALESCE((SELECT compressed_until FROM summaries WHERE session_key = ?), 0)
            ORDER BY id ASC
            """,
            (session_key, boundary["id"], session_key),
        ).fetchall()
    return [{"id": row["id"], "role": row["role"], "content": row["content"]} for row in rows]

