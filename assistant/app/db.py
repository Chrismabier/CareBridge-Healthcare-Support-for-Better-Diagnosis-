"""SQLite storage layer (Python standard library only).

Tables: users, conversations, messages, documents, chunks (the vector-store
backing table), notes, tasks, reminders.

Every query is parameterised; every "list" helper is scoped by ``user_id`` so
one user can never see another user's data.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config

_lock = threading.Lock()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    """Thread-safe connection scope (single-process demo/workstation scale)."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    pw_salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'New chat',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    citations_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'pdf',
    num_pages INTEGER NOT NULL DEFAULT 1,
    num_chunks INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (source_type IN ('document','note')),
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    page INTEGER,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    terms_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chunks_user ON chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_note ON chunks(note_id);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    list_name TEXT NOT NULL DEFAULT 'Tasks',
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
    due_at TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    done INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_user_time ON reminders(user_id, remind_at);
"""


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    return dict(row) if row is not None else None


def rows_to_list(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------- users

def create_user(email: str, name: str, pw_hash: str, pw_salt: str) -> dict:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(email, name, pw_hash, pw_salt, created_at) VALUES(?,?,?,?,?)",
            (email, name, pw_hash, pw_salt, utcnow_iso()),
        )
        row = conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        return dict(row)


def get_user_by_email(email: str) -> Optional[dict]:
    with db() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db() as conn:
        return row_to_dict(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def public_user(user: dict) -> dict:
    return {"id": user["id"], "email": user["email"], "name": user["name"], "created_at": user["created_at"]}


# ------------------------------------------------------------- conversations

def create_conversation(user_id: int, title: str = "New chat") -> dict:
    now = utcnow_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO conversations(user_id, title, created_at, updated_at) VALUES(?,?,?,?)",
            (user_id, title, now, now),
        )
        return dict(conn.execute("SELECT * FROM conversations WHERE id=?", (cur.lastrowid,)).fetchone())


def get_conversation(user_id: int, conversation_id: int) -> Optional[dict]:
    with db() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        ).fetchone())


def list_conversations(user_id: int) -> list[dict]:
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall())


def delete_conversation(user_id: int, conversation_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        )
        return cur.rowcount > 0


def add_message(conversation_id: int, role: str, content: str,
                citations: list | None = None, tools: list | None = None) -> dict:
    now = utcnow_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(conversation_id, role, content, citations_json, tools_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (conversation_id, role, content, json.dumps(citations or []), json.dumps(tools or []), now),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        # Auto-title from the first user message.
        if role == "user":
            count = conn.execute(
                "SELECT COUNT(*) c FROM messages WHERE conversation_id=? AND role='user'",
                (conversation_id,),
            ).fetchone()["c"]
            if count == 1:
                title = (content.strip().splitlines()[0][:60] or "New chat")
                conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conversation_id))
        return dict(conn.execute("SELECT * FROM messages WHERE id=?", (cur.lastrowid,)).fetchone())


def list_messages(conversation_id: int, limit: int = 200) -> list[dict]:
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id ASC LIMIT ?",
            (conversation_id, limit),
        ).fetchall())
    for r in rows:
        r["citations"] = json.loads(r.pop("citations_json") or "[]")
        r["tools"] = json.loads(r.pop("tools_json") or "[]")
    return rows


def recent_history(conversation_id: int, limit: int = 10) -> list[dict]:
    """Last N messages as OpenAI-style {role, content} dicts (oldest first)."""
    msgs = list_messages(conversation_id, limit=1000)[-limit:]
    return [{"role": m["role"], "content": m["content"]} for m in msgs]


# ----------------------------------------------------------------- documents

def create_document(user_id: int, filename: str, title: str, kind: str,
                    num_pages: int, char_count: int) -> dict:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO documents(user_id, filename, title, kind, num_pages, char_count, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (user_id, filename, title, kind, num_pages, char_count, utcnow_iso()),
        )
        return dict(conn.execute("SELECT * FROM documents WHERE id=?", (cur.lastrowid,)).fetchone())


def update_document_chunks(document_id: int, num_chunks: int) -> None:
    with db() as conn:
        conn.execute("UPDATE documents SET num_chunks=? WHERE id=?", (num_chunks, document_id))


def set_document_summary(document_id: int, summary: str) -> None:
    with db() as conn:
        conn.execute("UPDATE documents SET summary=? WHERE id=?", (summary, document_id))


def get_document(user_id: int, document_id: int) -> Optional[dict]:
    with db() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM documents WHERE id=? AND user_id=?", (document_id, user_id)
        ).fetchone())


def list_documents(user_id: int) -> list[dict]:
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM documents WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall())


def delete_document(user_id: int, document_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM documents WHERE id=? AND user_id=?", (document_id, user_id)
        )
        return cur.rowcount > 0


# --------------------------------------------------------------------- notes

def create_note(user_id: int, title: str, body: str, tags: str = "") -> dict:
    now = utcnow_iso()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO notes(user_id, title, body, tags, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (user_id, title, body, tags, now, now),
        )
        return dict(conn.execute("SELECT * FROM notes WHERE id=?", (cur.lastrowid,)).fetchone())


def update_note(user_id: int, note_id: int, title: str, body: str, tags: str) -> Optional[dict]:
    with db() as conn:
        cur = conn.execute(
            "UPDATE notes SET title=?, body=?, tags=?, updated_at=? WHERE id=? AND user_id=?",
            (title, body, tags, utcnow_iso(), note_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        return dict(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())


def get_note(user_id: int, note_id: int) -> Optional[dict]:
    with db() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM notes WHERE id=? AND user_id=?", (note_id, user_id)
        ).fetchone())


def list_notes(user_id: int) -> list[dict]:
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM notes WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall())


def delete_note(user_id: int, note_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
        return cur.rowcount > 0


# -------------------------------------------------------------------- chunks

def insert_chunks(rows: list[dict]) -> None:
    with db() as conn:
        conn.executemany(
            "INSERT INTO chunks(user_id, source_type, document_id, note_id, page, chunk_index, text, terms_json)"
            " VALUES(:user_id, :source_type, :document_id, :note_id, :page, :chunk_index, :text, :terms_json)",
            rows,
        )


def delete_chunks_for_document(document_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))


def delete_chunks_for_note(note_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM chunks WHERE note_id=?", (note_id,))


def all_chunks_for_user(user_id: int) -> list[dict]:
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT c.*, d.title AS doc_title, d.filename AS doc_filename, n.title AS note_title"
            " FROM chunks c"
            " LEFT JOIN documents d ON d.id = c.document_id"
            " LEFT JOIN notes n ON n.id = c.note_id"
            " WHERE c.user_id=?",
            (user_id,),
        ).fetchall())


def chunks_for_document(document_id: int) -> list[dict]:
    with db() as conn:
        return rows_to_list(conn.execute(
            "SELECT * FROM chunks WHERE document_id=? ORDER BY chunk_index ASC", (document_id,)
        ).fetchall())


# --------------------------------------------------------------------- tasks

def create_task(user_id: int, title: str, details: str = "", list_name: str = "Tasks",
                priority: str = "normal", due_at: str | None = None) -> dict:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO tasks(user_id, title, details, list_name, priority, due_at, created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (user_id, title, details, list_name, priority, due_at, utcnow_iso()),
        )
        return _task_public(dict(conn.execute("SELECT * FROM tasks WHERE id=?", (cur.lastrowid,)).fetchone()))


def _task_public(task: dict) -> dict:
    task["done"] = bool(task["done"])
    return task


def get_task(user_id: int, task_id: int) -> Optional[dict]:
    with db() as conn:
        row = row_to_dict(conn.execute(
            "SELECT * FROM tasks WHERE id=? AND user_id=?", (task_id, user_id)
        ).fetchone())
        return _task_public(row) if row else None


def list_tasks(user_id: int, include_done: bool = True) -> list[dict]:
    sql = "SELECT * FROM tasks WHERE user_id=?"
    if not include_done:
        sql += " AND done=0"
    sql += " ORDER BY done ASC, (due_at IS NULL) ASC, due_at ASC, created_at ASC"
    with db() as conn:
        return [_task_public(r) for r in rows_to_list(conn.execute(sql, (user_id,)).fetchall())]


def update_task(user_id: int, task_id: int, **fields) -> Optional[dict]:
    allowed = {"title", "details", "list_name", "priority", "due_at", "done"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_task(user_id, task_id)
    if "done" in updates:
        updates["completed_at"] = utcnow_iso() if updates["done"] else None
        updates["done"] = 1 if updates["done"] else 0
    set_sql = ", ".join(f"{k}=?" for k in updates)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE tasks SET {set_sql} WHERE id=? AND user_id=?",  # keys are from `allowed`
            (*updates.values(), task_id, user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_task(user_id, task_id)


def delete_task(user_id: int, task_id: int) -> bool:
    with db() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id=? AND user_id=?", (task_id, user_id))
        return cur.rowcount > 0


def find_open_task_by_title(user_id: int, fragment: str) -> Optional[dict]:
    fragment = fragment.strip().lower()
    if not fragment:
        return None
    for task in list_tasks(user_id, include_done=False):
        if fragment in task["title"].lower():
            return task
    return None


# ----------------------------------------------------------------- reminders

def create_reminder(user_id: int, title: str, remind_at: str, task_id: int | None = None) -> dict:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO reminders(user_id, title, remind_at, task_id, created_at) VALUES(?,?,?,?,?)",
            (user_id, title, remind_at, task_id, utcnow_iso()),
        )
        return _reminder_public(dict(conn.execute(
            "SELECT * FROM reminders WHERE id=?", (cur.lastrowid,)).fetchone()))


def _reminder_public(r: dict) -> dict:
    r["done"] = bool(r["done"])
    r["notified"] = bool(r["notified"])
    return r


def get_reminder(user_id: int, reminder_id: int) -> Optional[dict]:
    with db() as conn:
        row = row_to_dict(conn.execute(
            "SELECT * FROM reminders WHERE id=? AND user_id=?", (reminder_id, user_id)
        ).fetchone())
        return _reminder_public(row) if row else None


def list_reminders(user_id: int, include_done: bool = False) -> list[dict]:
    sql = "SELECT * FROM reminders WHERE user_id=?"
    if not include_done:
        sql += " AND done=0"
    sql += " ORDER BY remind_at ASC"
    with db() as conn:
        return [_reminder_public(r) for r in rows_to_list(conn.execute(sql, (user_id,)).fetchall())]


def due_reminders(user_id: int, now_iso: str) -> list[dict]:
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT * FROM reminders WHERE user_id=? AND done=0 AND notified=0 AND remind_at<=?"
            " ORDER BY remind_at ASC",
            (user_id, now_iso),
        ).fetchall())
        if rows:
            conn.executemany("UPDATE reminders SET notified=1 WHERE id=?", [(r["id"],) for r in rows])
        return [_reminder_public(r) for r in rows]


def update_reminder(user_id: int, reminder_id: int, **fields) -> Optional[dict]:
    allowed = {"title", "remind_at", "done", "notified"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_reminder(user_id, reminder_id)
    for k in ("done", "notified"):
        if k in updates:
            updates[k] = 1 if updates[k] else 0
    if "remind_at" in updates:  # snoozing re-arms the notification
        updates["notified"] = 0
        updates["done"] = 0
    set_sql = ", ".join(f"{k}=?" for k in updates)
    with db() as conn:
        cur = conn.execute(
            f"UPDATE reminders SET {set_sql} WHERE id=? AND user_id=?",
            (*updates.values(), reminder_id, user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_reminder(user_id, reminder_id)


def delete_reminder(user_id: int, reminder_id: int) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM reminders WHERE id=? AND user_id=?", (reminder_id, user_id)
        )
        return cur.rowcount > 0


def stats(user_id: int) -> dict:
    with db() as conn:
        def count(sql, params=(user_id,)):
            return conn.execute(sql, params).fetchone()["c"]
        return {
            "documents": count("SELECT COUNT(*) c FROM documents WHERE user_id=?"),
            "notes": count("SELECT COUNT(*) c FROM notes WHERE user_id=?"),
            "open_tasks": count("SELECT COUNT(*) c FROM tasks WHERE user_id=? AND done=0"),
            "pending_reminders": count("SELECT COUNT(*) c FROM reminders WHERE user_id=? AND done=0"),
            "indexed_chunks": count("SELECT COUNT(*) c FROM chunks WHERE user_id=?"),
        }
