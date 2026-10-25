import json
import re
import time

import pytest
from aiogram.methods import EditMessageMedia, SendMessage
from conftest import settle
from test_bot import app as app
from test_bot import click, command, panel, update
from test_markdown import CheckedHTML

from telegram_vibecoding.book import SessionBook, chapter_pages, iterations
from telegram_vibecoding.markdown import html_length


def role_bodies(pages):
    result = {}
    for page in pages:
        pieces = re.split(r"(?:\n\n)?<b>([^<]+)</b>\n\n", page["text"])
        for label, body in zip(pieces[1::2], pieces[2::2], strict=True):
            label = label.removesuffix(" · continued")
            result[label] = result.get(label, "") + CheckedHTML(body).text
    return result


def event(eid, kind, text="", **payload):
    return {"id": eid, "session_id": "s", "kind": kind, "payload": {"text": text, **payload}}


def test_chapter_preserves_oversized_input_and_answer_and_packs_roles(tmp_path):
    user = "Original <literal> 🚀\n" * 800
    answer = "Native **answer** 🚀\n" * 800
    conversation = {"user": event(1, "user", user), "replies": [event(2, "message", answer)]}
    pages = chapter_pages(conversation, [], tmp_path)
    bodies = role_bodies(pages)
    assert bodies["👤 You"] == user
    assert bodies["🤖 Codex · Answer"] == answer.replace("**", "")
    assert all(html_length(p["text"]) <= 3500 for p in pages)
    short = {"user": event(1, "user", "A whole user message"), "replies": [event(2, "message", "Answer")]}
    packed = chapter_pages(short, [], tmp_path)
    assert len(packed) == 1
    assert packed[0]["text"].index("A whole user message") < packed[0]["text"].index("Answer")
    assert packed[0]["events"] == [1, 2]
    fitting = {**conversation, "user": event(1, "user", "x" * 3400)}
    first = chapter_pages(fitting, [], tmp_path)[0]["text"]
    assert "x" * 3400 in first and "continued" not in first


async def test_complete_iteration_includes_steering_reasoning_questions_and_late_images(tmp_path):
    image = tmp_path / "output.png"
    image.write_bytes(b"image")
    source = [
        event(1, "user", "Initial request"),
        event(2, "message", "Progress", phase="commentary"),
        event(3, "user", "Additional instruction"),
        event(4, "reasoning_summary", "Published `code` reasoning"),
        event(5, "question", questions=[{"question": "Which one?", "options": [{"label": "First"}]}]),
        event(6, "user", "First please"),
        event(7, "message", "Final answer"),
        event(8, "completed", status="completed"),
        event(9, "user", "Next task"),
        event(10, "attachment", attachment_id="a", anchor=3),
        event(11, "message", "Next answer"),
    ]
    feed = [event(i, "tool", "PRIVATE") for i in range(1, 111)] + source

    class Engine:
        async def call(self, path):
            cursor = int(path.split("=")[1])
            return [e for e in feed if e["id"] > cursor][:100]

    for i, e in enumerate(feed, 1):
        e["id"] = i
    source[9]["payload"]["anchor"] = source[2]["id"]
    reader = SessionBook()
    chapter = await reader.read(Engine(), "s", str(source[2]["id"]))
    assert chapter["total"] == 2 and chapter["index"] == 1
    assert chapter["anchor"] == source[0]["id"]
    assert chapter["anchors"] == [source[i]["id"] for i in [0, 2, 5]]
    pages = chapter_pages(chapter, [{"id": "a", "path": str(image)}], tmp_path)
    displayed = {eid for page in pages for eid in page["events"]}
    assert {source[i]["id"] for i in [0, 1, 2, 3, 4, 5, 6, 9]} <= displayed
    plain = "\n".join(CheckedHTML(p["text"]).text for p in pages)
    for text in [
        "Initial request",
        "Progress",
        "Additional instruction",
        "Published code reasoning",
        "Which one?",
        "First please",
        "Final answer",
    ]:
        assert text in plain
    assert "Next task" not in plain and "PRIVATE" not in plain
    assert any(p["path"] == str(image) for p in pages)
    assert all(html_length(p["text"]) <= (800 if p["path"] else 3500) for p in pages)
    steering = event(len(feed) + 1, "user", "Still working")
    feed.append(steering)
    assert (await reader.read(Engine(), "s"))["total"] == 2
    assert (
        len(
            iterations(
                [
                    event(1, "message", "Retained orphan"),
                    event(2, "completed", status="completed"),
                    event(3, "user", "New"),
                ]
            )
        )
        == 2
    )


async def test_smooth_pages_cross_chapters_and_jumps_always_land_at_user(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    for text in ["Iteration one", "Iteration two"]:
        await command(app, text)
        await settle(engine)
        native.finish(engine.store.session(sid)["thread_id"], text="Answer to " + text)
    await runtime.refresh_panel()
    await click(app, "📖 Chat history")
    assert "Iteration two" in panel(transport).text and "Answer to Iteration two" in panel(transport).text
    await click(app, "◀ Page")
    assert "Answer to Iteration one" in panel(transport).text
    await click(app, "Page ▶")
    assert "Iteration two" in panel(transport).text and "Answer to Iteration two" in panel(transport).text
    await click(app, "⏮ Iteration")
    assert json.loads(runtime.store.get("history_view"))["part"] == 0
    assert "Iteration one" in panel(transport).text and "Answer to Iteration one" in panel(transport).text
    await click(app, "Iteration ⏭")
    assert json.loads(runtime.store.get("history_view"))["part"] == 0


async def test_history_screen_reads_all_roles_after_steering_and_returns_to_chapter_start(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    initial = engine.store.event(sid, "user", {"text": "Initial request"})
    engine.store.event(sid, "message", {"text": "Checking", "phase": "commentary"})
    steering = engine.store.event(sid, "user", {"text": "Additional instruction"})
    engine.store.event(sid, "reasoning_summary", {"parts": ["Published reasoning"]})
    engine.store.event(sid, "question", {"questions": [{"question": "Which option?"}]})
    engine.store.event(sid, "user", {"text": "Option one"})
    engine.store.event(sid, "message", {"text": "Complete answer " * 600})
    engine.store.event(sid, "completed", {"status": "completed"})
    await runtime.refresh_panel()
    await click(app, "📖 Chat history")
    # An already-open legacy cursor into a steering message resolves to the whole iteration.
    runtime.store.set("history_anchor", str(steering))
    await runtime.refresh_panel()
    first = panel(transport).text
    expected = [
        "Initial request",
        "Checking",
        "Additional instruction",
        "Published reasoning",
        "Which option?",
        "Option one",
        "Complete answer",
    ]
    positions = [first.index(t) for t in expected]
    assert positions == sorted(positions)
    assert "Iteration 1/1" in first
    assert json.loads(runtime.store.get("history_view"))["anchor"] == initial
    all_pages = [first]
    while "Page ▶" in [b.text for row in panel(transport).reply_markup.inline_keyboard for b in row]:
        await click(app, "Page ▶")
        all_pages.append(panel(transport).text)
    assert len(all_pages) > 1
    await click(app, "◀ Page")
    assert panel(transport).text == all_pages[-2]
    # A new completed iteration gets a fresh first page, never the previous answer's tail.
    engine.store.event(sid, "user", {"text": "Next request"})
    engine.store.event(sid, "message", {"text": "Next response"})
    engine.store.event(sid, "completed", {"status": "completed"})
    await runtime.refresh_panel()
    await click(app, "Iteration ⏭")
    assert "Next request" in panel(transport).text and "Complete answer" not in panel(transport).text
    await click(app, "⏮ Iteration")
    assert panel(transport).text.split("\n\n", 1)[1] == first.split("\n\n", 1)[1]
    assert json.loads(runtime.store.get("history_view"))["part"] == 0


async def test_images_are_page_scoped_and_disappear_on_the_next_text_page(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    user = engine.store.event(sid, "user", {"text": "Draw here " * 100})
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    attachment = engine.attach(sid, {"path": str(image), "anchor": user})
    engine.store.event(sid, "message", {"text": "After the image " * 100})
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


@pytest.mark.parametrize("finished", [False, True])
@pytest.mark.parametrize("kind", ["text", "photo", "voice"])
async def test_input_from_history_returns_to_session_dialog(app, finished, kind):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    await command(app, "Initial request")
    await settle(engine)
    thread = engine.store.session(sid)["thread_id"]
    if finished:
        native.finish(thread, text="Initial answer")
    await runtime.refresh_panel()
    await click(app, "📖 Chat history")
    assert "Test (medium) ·" in panel(transport).text

    async def download(file_id, destination):
        destination.write(b"\x89PNG\r\n\x1a\nimage" if kind == "photo" else b"OggS-voice")

    async def transcribe(path):
        return {"text": "Follow-up voice", "language": "en"}

    runtime.bot.download = download
    engine.speech.transcribe = transcribe
    extra = (
        {"photo": [{"file_id": "p", "file_unique_id": "p", "width": 10, "height": 10}]}
        if kind == "photo"
        else {"voice": {"file_id": "v", "file_unique_id": "v", "duration": 2}}
        if kind == "voice"
        else {}
    )
    uid = int(runtime.store.get("offset"))
    runtime.capture(update(uid, "Follow-up" if kind == "text" else "", **extra))
    await runtime.process_navigation(runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,)))
    await settle(engine)
    assert runtime.store.get("screen") == "Screens:chat"
    assert runtime.store.get("selected") == sid
    rows = [[b.text for b in row] for row in panel(transport).reply_markup.inline_keyboard]
    assert rows == [["⚙️ Config", "ℹ️ Details"], ["📖 Chat history", "⏹ Stop"], ["⬅️ Back", "🏠 Deck"]]
    await click(app, "📖 Chat history")
    assert f"Iteration {2 if finished else 1}/{2 if finished else 1}" in panel(transport).text
    assert engine.store.session(sid)["thread_id"] == thread


async def test_stop_ends_iteration_only_after_native_completion(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    await command(app, "Initial request")
    await settle(engine)
    thread = engine.store.session(sid)["thread_id"]
    request = native.request

    async def delayed_stop(method, params, **kwargs):
        if method == "turn/interrupt":
            native.calls.append((method, params))
            return {}
        return await request(method, params, **kwargs)

    native.request = delayed_stop
    await click(app, "⏹ Stop")
    await command(app, "While stopping")
    await settle(engine)
    await click(app, "📖 Chat history")
    assert "Iteration 1/1" in panel(transport).text
    assert "Initial request" in panel(transport).text and "While stopping" in panel(transport).text
    native.finish(thread, "interrupted", "Stopped")
    await command(app, "Continue after stop")
    await settle(engine)
    assert runtime.store.get("screen") == "Screens:chat"
    await click(app, "📖 Chat history")
    assert "Iteration 2/2" in panel(transport).text
    assert "Continue after stop" in panel(transport).text
    assert "Initial request" not in panel(transport).text.split("\n\n", 1)[1]


def test_reasoning_is_quoted_losslessly_across_pages(tmp_path):
    reasoning = "> Existing quote\n\n**Published** reasoning 🚀\n" * 400
    conversation = {
        "user": event(1, "user", "Request"),
        "replies": [event(2, "reasoning_summary", reasoning)],
    }
    pages = chapter_pages(conversation, [], tmp_path)
    from telegram_vibecoding.markdown import render_markdown

    assert role_bodies(pages)["🧠 Codex · Reasoning"] == CheckedHTML(render_markdown(reasoning)).text
    for page in pages:
        CheckedHTML(page["text"])
        assert "<blockquote><blockquote>" not in page["text"]
        assert "<b>🧠 Codex · Reasoning" in page["text"] and "<blockquote>" in page["text"]
        assert html_length(page["text"]) <= 3500
