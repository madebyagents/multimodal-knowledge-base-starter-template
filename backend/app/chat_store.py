"""Local SQLite persistence for DanteDash chat workspace state."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_NAME = "Dante"
DEFAULT_THREAD_TITLE = "New chat"
SCHEMA_VERSION = 1


class ChatStoreError(RuntimeError):
    """Base error for chat workspace persistence failures."""


class ChatStoreNotFound(ChatStoreError):
    """Raised when a requested project, thread, or message does not exist."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def title_from_question(question: str) -> str:
    title = " ".join(question.split())
    if not title:
        return DEFAULT_THREAD_TITLE
    return title[:56].rstrip() + ("..." if len(title) > 56 else "")


class ChatStore:
    """Small SQLite store for product chat state.

    This database intentionally stores app/workspace state only. Chroma remains
    the source of truth for indexed KB documents and embeddings.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    memory TEXT NOT NULL DEFAULT '',
                    instructions TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    chat_model TEXT,
                    top_k INTEGER,
                    archived INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL DEFAULT '',
                    chat_model TEXT,
                    top_k INTEGER,
                    status TEXT NOT NULL DEFAULT 'complete',
                    visual_attachments INTEGER NOT NULL DEFAULT 0,
                    citation_validation_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS message_sources (
                    id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    source_index INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(message_id, source_index)
                );

                CREATE INDEX IF NOT EXISTS idx_threads_project_updated
                    ON threads(project_id, archived, pinned DESC, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_thread_created
                    ON messages(thread_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_sources_message_index
                    ON message_sources(message_id, source_index);
                """
            )
            conn.execute(
                """
                INSERT INTO schema_meta(key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def create_project(
        self,
        *,
        name: str = DEFAULT_PROJECT_NAME,
        memory: str = "",
        instructions: str = "",
    ) -> dict[str, Any]:
        stamp = now_iso()
        project_id = new_id("proj")
        clean_name = name.strip() or DEFAULT_PROJECT_NAME
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects(id, name, memory, instructions, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, clean_name, memory, instructions, stamp, stamp),
            )
        return self.get_project(project_id)

    def get_or_create_default_project(self) -> dict[str, Any]:
        projects = self.list_projects()
        if projects:
            return projects[0]
        return self.create_project()

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*,
                       COUNT(t.id) AS thread_count,
                       MAX(t.updated_at) AS latest_thread_at
                FROM projects p
                LEFT JOIN threads t ON t.project_id = p.id
                GROUP BY p.id
                ORDER BY COALESCE(latest_thread_at, p.updated_at) DESC, p.name ASC
                """
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.*,
                       COUNT(t.id) AS thread_count,
                       MAX(t.updated_at) AS latest_thread_at
                FROM projects p
                LEFT JOIN threads t ON t.project_id = p.id
                WHERE p.id = ?
                GROUP BY p.id
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise ChatStoreNotFound(f"Project not found: {project_id}")
        return self._project_from_row(row)

    def update_project(
        self,
        project_id: str,
        *,
        name: str | None = None,
        memory: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_project(project_id)
        next_name = (name.strip() if name is not None else current["name"]) or DEFAULT_PROJECT_NAME
        next_memory = memory if memory is not None else current["memory"]
        next_instructions = (
            instructions if instructions is not None else current["instructions"]
        )
        stamp = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET name = ?, memory = ?, instructions = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_name, next_memory, next_instructions, stamp, project_id),
            )
        return self.get_project(project_id)

    def create_thread(
        self,
        *,
        project_id: str,
        title: str | None = None,
        chat_model: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        stamp = now_iso()
        thread_id = new_id("thread")
        clean_title = (title or "").strip() or DEFAULT_THREAD_TITLE
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO threads(
                    id, project_id, title, chat_model, top_k, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (thread_id, project_id, clean_title, chat_model, top_k, stamp, stamp),
            )
        return self.get_thread(thread_id)

    def list_threads(
        self,
        project_id: str,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self.get_project(project_id)
        where_archived = "" if include_archived else "AND t.archived = 0"
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT t.*,
                       COUNT(m.id) AS message_count
                FROM threads t
                LEFT JOIN messages m ON m.thread_id = t.id
                WHERE t.project_id = ? {where_archived}
                GROUP BY t.id
                ORDER BY t.pinned DESC, t.updated_at DESC, t.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._thread_from_row(row) for row in rows]

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT t.*,
                       COUNT(m.id) AS message_count
                FROM threads t
                LEFT JOIN messages m ON m.thread_id = t.id
                WHERE t.id = ?
                GROUP BY t.id
                """,
                (thread_id,),
            ).fetchone()
        if row is None:
            raise ChatStoreNotFound(f"Thread not found: {thread_id}")
        return self._thread_from_row(row)

    def get_thread_detail(self, thread_id: str) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        project = self.get_project(thread["project_id"])
        return {
            **thread,
            "project": project,
            "messages": self.list_messages(thread_id),
        }

    def update_thread(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        chat_model: str | None = None,
        top_k: int | None = None,
        archived: bool | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get_thread(thread_id)
        next_title = (title.strip() if title is not None else current["title"]) or DEFAULT_THREAD_TITLE
        stamp = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE threads
                SET title = ?,
                    summary = ?,
                    chat_model = ?,
                    top_k = ?,
                    archived = ?,
                    pinned = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    next_title,
                    summary if summary is not None else current["summary"],
                    chat_model if chat_model is not None else current["chat_model"],
                    top_k if top_k is not None else current["top_k"],
                    self._bool_to_int(archived) if archived is not None else self._bool_to_int(current["archived"]),
                    self._bool_to_int(pinned) if pinned is not None else self._bool_to_int(current["pinned"]),
                    stamp,
                    thread_id,
                ),
            )
        return self.get_thread(thread_id)

    def append_message(
        self,
        thread_id: str,
        *,
        role: str,
        content: str,
        chat_model: str | None = None,
        top_k: int | None = None,
        status: str = "complete",
        visual_attachments: int = 0,
        citation_validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thread = self.get_thread(thread_id)
        if role not in {"user", "assistant"}:
            raise ChatStoreError(f"Unsupported message role: {role}")
        stamp = now_iso()
        message_id = new_id("msg")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages(
                    id, thread_id, role, content, chat_model, top_k, status,
                    visual_attachments, citation_validation_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    thread_id,
                    role,
                    content,
                    chat_model,
                    top_k,
                    status,
                    visual_attachments,
                    self._json_dumps(citation_validation),
                    stamp,
                    stamp,
                ),
            )
            if role == "user" and thread["title"] == DEFAULT_THREAD_TITLE:
                conn.execute(
                    "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                    (title_from_question(content), stamp, thread_id),
                )
            else:
                conn.execute(
                    "UPDATE threads SET updated_at = ? WHERE id = ?",
                    (stamp, thread_id),
                )
        return self.get_message(message_id)

    def update_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        status: str | None = None,
        visual_attachments: int | None = None,
        citation_validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.get_message(message_id)
        stamp = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE messages
                SET content = ?,
                    status = ?,
                    visual_attachments = ?,
                    citation_validation_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    content if content is not None else current["content"],
                    status if status is not None else current["status"],
                    visual_attachments
                    if visual_attachments is not None
                    else current["visual_attachments"],
                    self._json_dumps(citation_validation)
                    if citation_validation is not None
                    else self._json_dumps(current["citation_validation"]),
                    stamp,
                    message_id,
                ),
            )
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (stamp, current["thread_id"]),
            )
        return self.get_message(message_id)

    def save_message_sources(
        self,
        message_id: str,
        sources: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.get_message(message_id)
        stamp = now_iso()
        source_list = list(sources)
        with self._connect() as conn:
            conn.execute("DELETE FROM message_sources WHERE message_id = ?", (message_id,))
            for index, payload in enumerate(source_list):
                conn.execute(
                    """
                    INSERT INTO message_sources(
                        id, message_id, source_index, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("src"),
                        message_id,
                        index,
                        self._json_dumps(payload),
                        stamp,
                    ),
                )
        return self.list_message_sources(message_id)

    def list_messages(self, thread_id: str) -> list[dict[str, Any]]:
        self.get_thread(thread_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM messages
                WHERE thread_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (thread_id,),
            ).fetchall()
        messages = [self._message_from_row(row) for row in rows]
        for message in messages:
            message["sources"] = self.list_message_sources(message["id"])
        return messages

    def get_message(self, message_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise ChatStoreNotFound(f"Message not found: {message_id}")
        message = self._message_from_row(row)
        message["sources"] = self.list_message_sources(message_id)
        return message

    def list_message_sources(self, message_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM message_sources
                WHERE message_id = ?
                ORDER BY source_index ASC
                """,
                (message_id,),
            ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _json_dumps(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _json_loads(value: str | None) -> Any:
        if not value:
            return None
        return json.loads(value)

    @staticmethod
    def _bool_to_int(value: bool | int) -> int:
        return 1 if bool(value) else 0

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "memory": row["memory"],
            "instructions": row["instructions"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "thread_count": int(row["thread_count"] or 0)
            if "thread_count" in row.keys()
            else 0,
            "latest_thread_at": row["latest_thread_at"]
            if "latest_thread_at" in row.keys()
            else None,
        }

    @staticmethod
    def _thread_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "summary": row["summary"],
            "chat_model": row["chat_model"],
            "top_k": row["top_k"],
            "archived": bool(row["archived"]),
            "pinned": bool(row["pinned"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": int(row["message_count"] or 0)
            if "message_count" in row.keys()
            else 0,
        }

    def _message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "thread_id": row["thread_id"],
            "role": row["role"],
            "content": row["content"],
            "chat_model": row["chat_model"],
            "top_k": row["top_k"],
            "status": row["status"],
            "visual_attachments": row["visual_attachments"],
            "citation_validation": self._json_loads(row["citation_validation_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _source_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._json_loads(row["payload_json"]) or {}
        return {
            "id": row["id"],
            "message_id": row["message_id"],
            "source_index": row["source_index"],
            "created_at": row["created_at"],
            "payload": payload,
        }
