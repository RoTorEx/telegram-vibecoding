import json
import time

from aiogram.methods import EditMessageMedia, SendMessage
from conftest import settle
from test_bot import app as app
from test_bot import click, command, panel
from test_markdown import CheckedHTML

from telegram_vibecoding.book import chapter_pages
from telegram_vibecoding.markdown import html_length


def test_chapter_keeps_user_at_start_and_preserves_oversized_input_and_answer(tmp_path):
    user = "Original <literal> 🚀\n" * 800
    answer = "Native **answer** 🚀\n" * 800
    conversation = {
        "user": {"payload": {"text": user}},
        "replies": [{"kind": "message", "payload": {"text": answer}}],
    }
    pages = chapter_pages(conversation, [], tmp_path)
    user_pages = [p for p in pages if "👤 You" in p["text"]]
    agent_pages = [p for p in pages if "🤖 Codex" in p["text"]]
    assert pages[: len(user_pages)] == user_pages
    assert "".join(CheckedHTML(p["text"].split("\n\n", 1)[1]).text for p in user_pages) == user
    assert "".join(CheckedHTML(p["text"].split("\n\n", 1)[1]).text for p in agent_pages) == answer.replace(
        "**", ""
    )
    assert all(html_length(p["text"]) < 3200 for p in pages)
    short = {**conversation, "user": {"payload": {"text": "A whole user message"}}}
    first = chapter_pages(short, [], tmp_path)[0]["text"]
    assert "A whole user message" in first and "Native" not in first
    fitting = {**conversation, "user": {"payload": {"text": "x" * 3500}}}
    first = chapter_pages(fitting, [], tmp_path, user_limit=3700)[0]["text"]
    assert "x" * 3500 in first and "continued" not in first


async def test_smooth_pages_cross_chapters_and_jumps_always_land_at_user(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    for text in ["Chapter one", "Chapter two"]:
        await command(app, text)
        await settle(engine)
        native.finish(engine.store.session(sid)["thread_id"], text="Answer to " + text)
    await runtime.refresh_panel()
    await click(app, "📖 Chat history")
    assert "Chapter two" in panel(transport).text and "Answer to" not in panel(transport).text
    await click(app, "◀ Page")
    assert "Answer to Chapter one" in panel(transport).text
    await click(app, "Page ▶")
    assert "Chapter two" in panel(transport).text and "Answer to" not in panel(transport).text
    await click(app, "Page ▶")
    await click(app, "⏮ Chapter")
    assert json.loads(runtime.store.get("history_view"))["part"] == 0
    assert "Chapter one" in panel(transport).text and "Answer to" not in panel(transport).text
    await click(app, "Chapter ⏭")
    assert json.loads(runtime.store.get("history_view"))["part"] == 0


async def test_images_are_page_scoped_and_disappear_on_the_next_text_page(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    user = engine.store.event(sid, "user", {"text": "Draw here"})
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    attachment = engine.attach(sid, {"path": str(image), "anchor": user})
    engine.store.event(sid, "message", {"text": "After the image"})
    await runtime.refresh_panel()
    await click(app, "📖 Chat history")
    await click(app, "Page ▶")
    media = panel(transport).method
    assert isinstance(media, EditMessageMedia) and str(media.media.media.path) == attachment["path"]
    assert html_length(media.media.caption) <= 1024
    runtime.store.set("notice", "Long media error " * 1000)
    await runtime.refresh_panel()
    assert html_length(panel(transport).text) <= 1024
    runtime.store.set("notice", "")
    old_panel = int(runtime.store.get("panel_id"))
    await click(app, "Page ▶")
    assert "After the image" in panel(transport).text
    assert int(runtime.store.get("panel_id")) != old_panel and old_panel not in transport.messages
    assert not hasattr(panel(transport), "method")
    assert not any("Images" in b.text for row in panel(transport).reply_markup.inline_keyboard for b in row)


async def test_completion_notice_has_duration_open_button_and_panel_stays_below_it(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    session = engine.store.create_session(str(tmp_path), "Other session <safe>", "medium")
    sid = session["id"]
    old_run = engine.store.event(sid, "completed", {"status": "completed"})
    user = engine.store.event(sid, "user", {"text": "Current run"})
    engine.store.event(sid, "user", {"text": "Steering must not reset duration"})
    engine.store.event(sid, "message", {"text": "Result"})
    completed = engine.store.event(sid, "completed", {"status": "completed"})
    now = time.time()
    with engine.store.db:
        engine.store.db.execute("UPDATE events SET created=? WHERE id=?", (now - 300, old_run))
        engine.store.db.execute("UPDATE events SET created=? WHERE id=?", (now - 125, user))
        engine.store.db.execute("UPDATE events SET created=? WHERE id=?", (now, completed))
    event = next(e for e in engine.store.events(0) if e["id"] == completed)
    runtime.queue_update(event)
    await runtime.deliver_notifications()
    notice = next(m for m in transport.calls if isinstance(m, SendMessage) and "✅ Finished" in m.text)
    assert "<i>(~2m 5s)</i>" in notice.text and "&lt;safe&gt;" in notice.text
    assert len(notice.reply_markup.inline_keyboard) == 1
    assert notice.reply_markup.inline_keyboard[0][0].callback_data == "open:" + sid
    notice_id = runtime.store.one("SELECT telegram_id FROM notifications WHERE event_id=?", (completed,))[
        "telegram_id"
    ]
    assert int(runtime.store.get("panel_id")) > notice_id
    await click(app, "⚙️ Settings")
    assert int(runtime.store.get("panel_id")) > notice_id
    assert notice_id in transport.messages and runtime.store.viewed(sid) == 0
    # The notice opens its own session, even when another project/menu is active.
    uid = int(runtime.store.get("offset"))
    runtime.capture(
        {
            "update_id": uid,
            "callback_query": {
                "id": "notice-open",
                "chat_instance": "x",
                "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
                "data": "open:" + sid,
                "message": {
                    "message_id": notice_id,
                    "date": int(now),
                    "chat": {"id": 42, "type": "private"},
                    "text": notice.text,
                },
            },
        }
    )
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,)))
    assert runtime.store.get("selected") == sid and runtime.store.get("mode") == "chat"
    assert "Result" in panel(transport).text and int(runtime.store.get("panel_id")) > notice_id
