"""Persistencia en SQLite (archivo en un volumen de Docker)."""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

ESQUEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
-- id es PRIMARY KEY: la base misma impide guardar dos veces el mismo mensaje (deduplicación).
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    from_user TEXT NOT NULL,
    origin TEXT NOT NULL,
    lamport INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    body TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_orden ON messages (lamport, origin);
-- Cola de salida persistente: sobrevive a reinicios y caídas.
CREATE TABLE IF NOT EXISTS pending (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, path: str) -> None:
        carpeta = os.path.dirname(path)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(ESQUEMA)

    # ---- usuarios -------------------------------------------------------
    def create_user(self, name: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO users (name, created_at) VALUES (?, ?)", (name, utc_now())
            )
            return cur.rowcount == 1

    def has_user(self, name: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM users WHERE name = ?", (name,)).fetchone()
        return row is not None

    def list_users(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT name FROM users ORDER BY name").fetchall()
        return [r["name"] for r in rows]

    # ---- mensajes -------------------------------------------------------
    def insert_message(self, m: dict, source: str) -> bool:
        """Inserta el mensaje. Devuelve False si el id ya existía (duplicado)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO messages "
                "(id, from_user, origin, lamport, sent_at, body, source, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], m["from"], m["origin"], m["lamport"], m["sent_at"], m["body"], source, utc_now()),
            )
            return cur.rowcount == 1

    def add_local_message(self, m: dict) -> None:
        """Guarda el mensaje local y lo encola para el central en UNA sola transacción."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages "
                "(id, from_user, origin, lamport, sent_at, body, source, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'local', ?)",
                (m["id"], m["from"], m["origin"], m["lamport"], m["sent_at"], m["body"], utc_now()),
            )
            self._conn.execute(
                "INSERT INTO pending (id, payload, attempts, next_attempt_at, created_at) "
                "VALUES (?, ?, 0, 0, ?)",
                (m["id"], json.dumps(m), time.time()),
            )

    def list_messages(self, since: int | None = None) -> list[dict]:
        sql = "SELECT id, from_user, origin, lamport, sent_at, body FROM messages"
        args: tuple = ()
        if since is not None:
            sql += " WHERE lamport > ?"
            args = (since,)
        sql += " ORDER BY lamport, origin"          # orden lógico: (lamport, origin)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [
            {"id": r["id"], "from": r["from_user"], "origin": r["origin"],
             "lamport": r["lamport"], "sent_at": r["sent_at"], "body": r["body"]}
            for r in rows
        ]

    def max_lamport(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COALESCE(MAX(lamport), 0) AS m FROM messages").fetchone()
        return row["m"]

    def max_remote_lamport(self, local_origin: str) -> int:
        """Mayor lamport entre mensajes de OTROS servidores: es el cursor para pedir /history."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(lamport), 0) AS m FROM messages WHERE origin != ?", (local_origin,)
            ).fetchone()
        return row["m"]

    def count_messages(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]

    # ---- cola de salida -------------------------------------------------
    def due_pending(self, now: float, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload, attempts FROM pending WHERE next_attempt_at <= ? "
                "ORDER BY created_at LIMIT ?", (now, limit),
            ).fetchall()
        return [{"id": r["id"], "payload": json.loads(r["payload"]), "attempts": r["attempts"]} for r in rows]

    def seconds_until_next_pending(self, now: float) -> float | None:
        with self._lock:
            row = self._conn.execute("SELECT MIN(next_attempt_at) AS t FROM pending").fetchone()
        if row["t"] is None:
            return None
        return max(0.0, row["t"] - now)

    def mark_attempt(self, message_id: str, attempts: int, next_attempt_at: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE pending SET attempts = ?, next_attempt_at = ? WHERE id = ?",
                (attempts, next_attempt_at, message_id),
            )

    def remove_pending(self, message_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM pending WHERE id = ?", (message_id,))

    def pending_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM pending").fetchone()["c"]
