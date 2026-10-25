import json
import os
import sqlite3
import time

from test_bot import app as app
from test_bot import command, update

from telegram_vibecoding.store import BotStore


async def test_bot_retention_scrubs_saved_content_keeps_pending_input_and_bounds_media(app, tmp_path):
    runtime, transport, engine, native = app
    now = time.time()
    cutoff = now - 7 * 86400
    root = runtime.settings.data_dir / "uploads"
    root.mkdir(exist_ok=True)
    stale = root / "old.voice"
    stale.write_bytes(b"old")
    fresh = root / "fresh.png"
    fresh.write_bytes(b"new")
    os.utime(stale, (cutoff, cutoff))
    os.utime(fresh, (cutoff + 1, cutoff + 1))
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")
    (root / "link.png").symlink_to(outside)
    session = engine.store.create_session(str(tmp_path), "Active", "medium")
    engine.store.update_session(session["id"], turn_id="active", status="working")
    busy = root / session["id"] / "old.voice"
    busy.parent.mkdir()
    busy.write_bytes(b"in use")
    os.utime(busy, (cutoff, cutoff))
    pending = root / "pending.voice"
    pending.write_bytes(b"pending")
    os.utime(pending, (cutoff, cutoff))
    runtime.store.accept(8000, update(8000, "Private old text"), None, "chat")
    runtime.store.processed(8000)
    runtime.store.accept(8001, update(8001, "Still pending"), None, "chat")
    runtime.store.prepare_request([8001], "pending", {"audio": [str(pending)]})
    with runtime.store.db:
        runtime.store.db.execute("UPDATE inbox SET created=? WHERE id IN (8000,8001)", (cutoff,))
    eid = engine.store.event(session["id"], "message", {"text": "Old result"})
    runtime.store.queue_event(eid, ["Old result"], None, cutoff)
    with runtime.store.db:
        runtime.store.db.execute(
            "INSERT INTO notifications(event_id,session_id,kind,payload,created) VALUES(?,?,?,?,?)",
            (eid, session["id"], "completed", '{"status":"completed"}', cutoff),
        )
    result = await runtime.expire_history(now)
    assert result["files"] == 1 and result["inbox"] == 1
    assert not stale.exists() and fresh.exists() and busy.exists() and pending.exists()
    assert outside.read_bytes() == b"keep"
    assert runtime.store.one("SELECT body,payload FROM inbox WHERE id=8000") == {
        "body": "{}",
        "payload": None,
    }
    assert (
        json.loads(runtime.store.one("SELECT body FROM inbox WHERE id=8001")["body"])["message"]["text"]
        == "Still pending"
    )
    assert not runtime.store.accept(8000, update(8000), None, "chat")
    assert runtime.store.get("event_cursor") == str(eid)
    assert not runtime.store.rows("SELECT * FROM outbox")
    assert not runtime.store.rows("SELECT * FROM notifications")


async def test_legacy_delivery_times_follow_core_events_and_read_cursors_survive(app):
    runtime, transport, engine, native = app
    now = time.time()
    session = engine.store.create_session(str(runtime.settings.data_dir.parent), "History", "medium")
    old = engine.store.event(session["id"], "message", {"text": "Old"})
    fresh = engine.store.event(session["id"], "message", {"text": "Fresh"})
    with engine.store.db:
        engine.store.db.execute("UPDATE events SET created=? WHERE id=?", (now - 7 * 86400, old))
    runtime.store.queue_event(old, ["Old"], None, 0)
    runtime.store.queue_event(fresh, ["Fresh"], None, 0)
    runtime.store.mark_viewed(session["id"], fresh)
    await runtime.expire_history(now)
    assert [r["body"] for r in runtime.store.rows("SELECT * FROM outbox")] == ["Fresh"]
    assert runtime.store.viewed(session["id"]) == fresh


def test_existing_database_migrates_delivery_timestamps_without_dropping_rows(tmp_path):
    path = tmp_path / "bot.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,event_id INTEGER,part INTEGER,
              body TEXT,markup TEXT,status TEXT DEFAULT 'pending',telegram_id INTEGER,UNIQUE(event_id,part));
            INSERT INTO outbox(event_id,part,body) VALUES(12,0,'Retained');
            CREATE TABLE notifications(event_id INTEGER PRIMARY KEY,session_id TEXT,kind TEXT,payload TEXT,
              status TEXT DEFAULT 'pending',telegram_id INTEGER);
        """)
    store = BotStore(path)
    assert store.one("SELECT body,created FROM outbox") == {"body": "Retained", "created": 0}
    store.close()


async def test_valid_input_clears_old_format_error_and_compact_chat_has_no_repeated_prompt(app):
    from test_bot import click, panel

    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    runtime.store.set("notice", "Old unsupported attachment error")
    await command(app, "Unique task text")
    assert runtime.store.get("notice") == ""
    text = panel(transport).text
    assert text.count("Unique task text") == 1  # Only the session title.
    assert "Test (medium) ·" in text and "Working" in text
    assert "Waiting for a response" not in text and "Send text" not in text
    engine.store.event(
        runtime.store.get("selected"), "message", {"text": "Working on the task", "phase": "commentary"}
    )
    await runtime.refresh_panel()
    assert panel(transport).text.endswith("\n\nWorking on the task")
    engine.store.event(runtime.store.get("selected"), "message", {"text": "Final output"})
    await runtime.refresh_panel()
    assert panel(transport).text.endswith("\n\nFinal output")
    assert "Working on the task" not in panel(transport).text
