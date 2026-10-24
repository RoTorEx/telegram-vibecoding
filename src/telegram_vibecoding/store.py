"""Small transactional stores. No database transaction crosses an await."""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any


def identifier() -> str:
    return uuid.uuid4().hex[:16]


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def backup(self, path: Path) -> None:
        with closing(sqlite3.connect(path)) as dest:
            self.db.backup(dest)
            if dest.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Snapshot integrity check failed")
        path.chmod(0o600)


class BotStore(Database):
    def __init__(self, path: Path):
        super().__init__(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS notifications(
                event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', telegram_id INTEGER);
            CREATE TABLE IF NOT EXISTS session_reads(
                session_id TEXT PRIMARY KEY, completion_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox(
                id INTEGER PRIMARY KEY, body TEXT NOT NULL, session_id TEXT, mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', request_id TEXT, payload TEXT,
                error TEXT, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox(
                id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL,
                part INTEGER NOT NULL, body TEXT NOT NULL, markup TEXT, status TEXT NOT NULL DEFAULT 'pending',
                telegram_id INTEGER, UNIQUE(event_id,part));
        """)

    def get(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def accept(self, update_id: int, body: dict, sid: str | None, mode: str) -> bool:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO inbox(id,body,session_id,mode,created) VALUES(?,?,?,?,?)",
                (update_id, json.dumps(body), sid, mode, time.time()),
            )
            self.db.execute(
                "INSERT INTO meta VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(update_id + 1),),
            )
        return cur.rowcount == 1

    def processed(self, update_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE inbox SET status='done' WHERE id=?", (update_id,))

    def prepare_request(self, update_ids: list[int], rid: str, payload: dict) -> None:
        with self.db:
            self.db.executemany(
                "UPDATE inbox SET request_id=?,payload=? WHERE id=?",
                [(rid, json.dumps(payload), uid) for uid in update_ids],
            )

    def queue_event(self, event_id: int, parts: list[str], markup: dict | None) -> None:
        with self.db:
            for i, body in enumerate(parts):
                self.db.execute(
                    "INSERT OR IGNORE INTO outbox(event_id,part,body,markup) VALUES(?,?,?,?)",
                    (event_id, i, body, json.dumps(markup) if markup and i == len(parts) - 1 else None),
                )
            self.db.execute(
                "INSERT INTO meta VALUES('event_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(event_id),),
            )

    def viewed(self, sid: str) -> int:
        row = self.one("SELECT completion_id FROM session_reads WHERE session_id=?", (sid,))
        return row["completion_id"] if row else 0

    def mark_viewed(self, sid: str, completion_id: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO session_reads VALUES (?,?) ON CONFLICT(session_id) DO UPDATE "
                "SET completion_id=MAX(session_reads.completion_id,excluded.completion_id)",
                (sid, completion_id),
            )
