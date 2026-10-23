import time
from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendDocument,
    SendMessage,
)
from aiogram.types import Chat, Message, User
from conftest import settle

from telegram_vibecoding.bot import BotRuntime, SQLiteFSM, authorized
from telegram_vibecoding.presentation import split_text


class TelegramFake(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.counter = 100
        self.messages = {}

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Relay", username="GardenSandbox_bot")
        if isinstance(method, (SendMessage, EditMessageText, SendDocument)):
            if isinstance(method, (SendMessage, SendDocument)):
                self.counter += 1
            result = Message(
                message_id=getattr(method, "message_id", None) or self.counter,
                date=datetime.now(UTC),
                chat=Chat(id=42, type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Relay"),
                text=getattr(method, "text", None) or "document",
                reply_markup=getattr(method, "reply_markup", None),
            )
            self.messages[result.message_id] = result
            return result
        if isinstance(method, DeleteMessage):
            self.messages.pop(method.message_id, None)
            return True
        if isinstance(method, (AnswerCallbackQuery, EditMessageReplyMarkup)):
            return True
        raise AssertionError(type(method).__name__)

    async def stream_content(self, *args, **kwargs):
        yield b""


def update(uid=1, text="hello", owner=42, **extra):
    return {
        "update_id": uid,
        "message": {
            "message_id": uid,
            "date": int(time.time()),
            "from": {"id": owner, "is_bot": False, "first_name": "Operator"},
            "chat": {"id": owner, "type": "private"},
            "text": text,
            **extra,
        },
    }


@pytest.fixture
async def app(host):
    settings, engine, native, client = host
    transport = TelegramFake()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=transport)
    app = BotRuntime(settings, bot=bot, engine=client)

    async def throttle():
        pass

    app.throttle = throttle
    capture = app.capture

    def capture_with_chat_clock(body):
        transport.counter = max(transport.counter, body.get("message", {}).get("message_id", 0))
        return capture(body)

    app.capture = capture_with_chat_clock
    yield app, transport, engine, native
    await bot.session.close()
    app.store.close()


def test_unicode_split_is_lossless_and_within_telegram_limit():
    original = "Привет 🚀\n<code>& 🎉 " * 900
    parts = split_text(original)
    assert "".join(parts) == original
    assert all(len(p.encode("utf-16-le")) // 2 <= 3500 for p in parts)


def test_authorization_covers_callbacks_missing_senders_and_groups():
    assert authorized(update(), 42)
    assert not authorized(update(owner=7), 42)
    u = update()
    u["message"]["chat"]["type"] = "group"
    assert not authorized(u, 42)
    c = {"callback_query": {"from": {"id": 42}, "message": {"chat": {"id": 42, "type": "private"}}}}
    assert authorized(c, 42)
    c["callback_query"]["from"]["id"] = 7
    assert not authorized(c, 42)
    assert not authorized({"channel_post": {}}, 42)


async def test_message_target_is_captured_before_switching_and_restart(app, host):
    runtime, transport, engine, native = app
    a = engine.store.create_session(str(host[0].data_dir.parent), "A", "medium")
    b = engine.store.create_session(str(host[0].data_dir.parent), "B", "medium")
    runtime.store.set("selected", a["id"])
    runtime.store.set("mode", "chat")
    runtime.capture(update(1, "message for A"))
    runtime.store.set("selected", b["id"])
    row = runtime.store.one("SELECT * FROM inbox WHERE id=1")
    await runtime.process_messages([row])
    await settle(engine)
    assert engine.store.request("telegram:1")["session_id"] == a["id"]
    assert engine.store.session(b["id"])["thread_id"] is None
    assert runtime.store.get("offset") == "2"
    assert not runtime.capture(update(1, "message for A"))


async def test_menu_text_does_not_reach_previous_agent(app):
    runtime, transport, engine, native = app
    runtime.store.set("mode", "menu")
    runtime.capture(update(10, "this is not a prompt"))
    await runtime.process_messages([runtime.store.one("SELECT * FROM inbox WHERE id=10")])
    assert not native.calls
    assert any(isinstance(m, SendMessage) and "Location" in m.text for m in transport.calls)


async def test_album_remains_bound_to_first_session(app, host):
    runtime, transport, engine, native = app
    a = engine.store.create_session(str(host[0].data_dir.parent), "A", "medium")
    b = engine.store.create_session(str(host[0].data_dir.parent), "B", "medium")
    runtime.store.set("mode", "chat")
    runtime.store.set("selected", a["id"])
    first = update(20, caption="look", media_group_id="album")
    first["message"].pop("text")
    first["message"]["photo"] = [{"file_id": "a", "file_unique_id": "a", "width": 5, "height": 5}]
    runtime.capture(first)
    runtime.store.set("selected", b["id"])
    second = update(21, media_group_id="album")
    second["message"].pop("text")
    second["message"]["photo"] = [{"file_id": "b", "file_unique_id": "b", "width": 5, "height": 5}]
    runtime.capture(second)

    async def fake_download(message, sid):
        p = runtime.settings.data_dir / "uploads" / f"{message['message_id']}.png"
        p.write_bytes(b"fixture")
        return str(p)

    runtime.download_image = fake_download
    rows = runtime.store.rows("SELECT * FROM inbox ORDER BY id")
    assert all(r["session_id"] == a["id"] for r in rows)
    await runtime.process_messages(rows)
    await settle(engine)
    turn = next(p for m, p in native.calls if m == "turn/start")
    assert [x["type"] for x in turn["input"]] == ["text", "localImage", "localImage"]
    assert engine.store.session(b["id"])["thread_id"] is None


async def test_real_dialog_deck_and_navigation_do_not_start_native_work(app):
    runtime, transport, engine, native = app
    runtime.capture(update(30, "/menu"))
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=30"))
    messages = [m for m in transport.calls if isinstance(m, SendMessage)]
    assert messages
    markup = messages[-1].reply_markup
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert [b.text for b in markup.inline_keyboard[0]] == ["⚙️ Settings"]
    assert "📍 Location" in texts
    assert "💬 Sessions" not in texts and "➕ New session" not in texts
    assert [b.text for b in markup.inline_keyboard[-1]] == ["⬅️ Back", "🏠 Deck"]
    assert runtime.store.get("mode") == "menu"
    assert not native.calls


async def test_fsm_survives_new_storage_instance(app):
    from aiogram.fsm.storage.base import StorageKey

    from telegram_vibecoding.dialogs import Screens

    runtime, *_ = app
    key = StorageKey(bot_id=123456, chat_id=42, user_id=42)
    a = SQLiteFSM(runtime.store)
    await a.set_state(key, Screens.chat)
    await a.set_data(key, {"stack": {"session": "test"}})
    b = SQLiteFSM(runtime.store)
    assert await b.get_state(key) == Screens.chat.state
    assert await b.get_data(key) == {"stack": {"session": "test"}}


async def test_unauthorized_input_never_enters_durable_inbox(app):
    runtime, *_ = app
    assert not runtime.capture(update(40, "run commands", owner=8))
    assert runtime.store.rows("SELECT * FROM inbox") == []
    assert runtime.store.get("offset") == "41"


async def test_download_rejects_oversized_and_mislabeled_images(app):
    runtime, *_ = app
    with pytest.raises(ValueError, match="20 MB"):
        await runtime.download_image(
            {
                "message_id": 50,
                "document": {"mime_type": "image/png", "file_id": "x", "file_size": 21_000_000},
            },
            "session",
        )

    async def download(file_id, destination):
        destination.write(b"this is not a PNG")

    runtime.bot.download = download
    with pytest.raises(ValueError, match="not a supported image"):
        await runtime.download_image(
            {"message_id": 51, "document": {"mime_type": "image/png", "file_id": "x"}}, "session"
        )


async def test_session_picker_uses_real_dialog_callbacks(app, host):
    runtime, transport, engine, native = app
    target = engine.store.create_session(str(host[0].data_dir.parent), "Pick me", "medium")
    runtime.store.set("location", target["cwd"])
    engine.store.register_project("Fixture", target["cwd"])
    runtime.capture(update(70, "/sessions"))
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=70"))
    panel = next(m for m in reversed(transport.calls) if isinstance(m, SendMessage))
    assert "1. Pick me" in panel.text
    button = next(b for row in panel.reply_markup.inline_keyboard for b in row if b.text == "1")
    callback = {
        "update_id": 71,
        "callback_query": {
            "id": "cb-71",
            "chat_instance": "test",
            "from": {"id": 42, "is_bot": False, "first_name": "Operator"},
            "data": button.callback_data,
            "message": {
                "message_id": transport.counter,
                "date": int(time.time()),
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 123456, "is_bot": True, "first_name": "Relay"},
                "text": panel.text,
            },
        },
    }
    runtime.capture(callback)
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=71"))
    assert runtime.store.get("selected") == target["id"]
    assert runtime.store.get("mode") == "chat"
    assert not native.calls


async def test_valid_image_download_persists_once_and_keeps_permissions(app):
    runtime, *_ = app
    raw = b"\x89PNG\r\n\x1a\nfixture-image-content"
    calls = []

    async def download(file_id, destination):
        calls.append(file_id)
        destination.write(raw)

    runtime.bot.download = download
    message = {"message_id": 80, "document": {"mime_type": "image/png", "file_id": "native-image"}}
    first = await runtime.download_image(message, "session")
    second = await runtime.download_image(message, "session")
    from pathlib import Path

    assert first == second
    assert Path(first).read_bytes() == raw
    assert Path(first).stat().st_mode & 0o077 == 0
    assert calls == ["native-image"]


async def test_partial_image_file_is_not_reused_as_a_complete_attachment(app):
    runtime, *_ = app
    folder = runtime.settings.data_dir / "uploads" / "recover"
    folder.mkdir()
    (folder / "90.part").write_bytes(b"incomplete old download")
    raw = b"\x89PNG\r\n\x1a\ncomplete-download"

    async def download(file_id, destination):
        destination.write(raw)

    runtime.bot.download = download
    result = await runtime.download_image(
        {"message_id": 90, "document": {"mime_type": "image/png", "file_id": "retry"}}, "recover"
    )
    from pathlib import Path

    assert Path(result).suffix == ".png" and Path(result).read_bytes() == raw


def panel(transport):
    return next(m for m in reversed(transport.calls) if isinstance(m, (SendMessage, EditMessageText)))


async def command(app, text):
    runtime, transport, *_ = app
    uid = int(runtime.store.get("offset", "1000"))
    transport.counter += 1
    body = update(uid, text)
    body["message"]["message_id"] = transport.counter
    runtime.capture(body)
    row = runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,))
    await runtime.process_navigation(row)


async def click(app, text):
    runtime, transport, *_ = app
    current = panel(transport)
    button = next(b for row in current.reply_markup.inline_keyboard for b in row if b.text == text)
    uid = int(runtime.store.get("offset", "1000"))
    body = {
        "update_id": uid,
        "callback_query": {
            "id": f"cb-{uid}",
            "chat_instance": "test",
            "from": {"id": 42, "is_bot": False, "first_name": "Operator"},
            "data": button.callback_data,
            "message": {
                "message_id": int(runtime.store.get("panel_id")),
                "date": int(time.time()),
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 123456, "is_bot": True, "first_name": "Relay"},
                "text": current.text,
            },
        },
    }
    runtime.capture(body)
    await runtime.process_control(runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,)))


async def resume_legacy_location_input(app):
    # Complete already-captured directory input after removing its menu entrypoint.
    from types import SimpleNamespace

    from telegram_vibecoding.bot import foreground
    from telegram_vibecoding.dialogs import prompt

    runtime, *_ = app
    bg = runtime.background.bg(
        runtime.bot, runtime.settings.allowed_user_id, runtime.settings.allowed_user_id
    )
    async with foreground(bg) as manager:
        await prompt(None, SimpleNamespace(widget_id="location"), manager)


def exits(transport):
    assert [b.text for b in panel(transport).reply_markup.inline_keyboard[-1]] == ["⬅️ Back", "🏠 Deck"]


async def test_location_session_config_details_are_one_editable_panel(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    first_id = runtime.store.get("panel_id")
    await click(app, "⚙️ Settings")
    exits(transport)
    await click(app, "⬅️ Back")
    await click(app, "📍 Location")
    assert "1. Home" in panel(transport).text
    exits(transport)
    await click(app, "1")
    assert "No sessions here yet" in panel(transport).text
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    assert "voice recording" in panel(transport).text
    assert not any(m == "turn/start" for m, p in native.calls)
    await click(app, "⚙️ Config")
    exits(transport)
    await click(app, "Reasoning: medium")
    assert engine.store.session(sid)["effort"] == "high"
    await click(app, "Reasoning: high")
    assert engine.store.session(sid)["effort"] == "medium"
    await click(app, "Plan mode: Off")
    assert engine.store.session(sid)["collaboration_mode"] == "plan"
    await click(app, "Model: Test")
    exits(transport)
    await click(app, "Test")
    assert "Config" in panel(transport).text
    await click(app, "⬅️ Back")
    assert runtime.store.get("mode") == "chat"
    await click(app, "ℹ️ Details")
    assert "Created:" in panel(transport).text and "Last request: —" in panel(transport).text
    await click(app, "✏️ Rename")
    exits(transport)
    await click(app, "⚙️ Config")
    await click(app, "⬅️ Back")
    assert runtime.store.get("mode") == "input"
    assert runtime.store.get("panel_id") == first_id
    await command(app, "A clear session title")
    assert engine.store.session(sid)["name"] == "A clear session title"
    assert "Details" in panel(transport).text
    await click(app, "⬅️ Back")
    assert "A clear session title" in panel(transport).text
    await click(app, "🏠 Deck")
    await click(app, "⬅️ Back")
    assert "Main Deck" in panel(transport).text
    assert runtime.store.get("panel_id") != first_id
    assert len(transport.messages) == 1


async def test_stream_delivery_history_and_navigation_preserve_one_panel(app, host):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    first_id = runtime.store.get("panel_id")
    for index in range(2):
        await command(app, f"Original request {index}")
        await settle(engine)
        session = engine.store.session(sid)
        await runtime.refresh_panel()
        assert f"Original request {index}" in panel(transport).text
        native.finish(session["thread_id"], text=f"Exact native answer {index}")
        for event in await runtime.engine.call("/events?after=" + runtime.store.get("event_cursor", "0")):
            runtime.queue_update(event)
        assert await runtime.deliver_pending()
        assert f"Exact native answer {index}" in panel(transport).text
    await click(app, "◀")
    assert "Original request 0" in panel(transport).text and "Exact native answer 0" in panel(transport).text
    await click(app, "Latest")
    assert "Exact native answer 1" in panel(transport).text
    assert runtime.store.get("panel_id") != first_id
    assert len(transport.messages) == 1
    assert runtime.store.one("SELECT COUNT(*) AS n FROM outbox WHERE status='pending'")["n"] == 0
    # Leaving the session does not stop work or let later output overwrite the menu.
    runtime.capture(update(2010, "Run"))
    await runtime.process_messages([runtime.store.one("SELECT * FROM inbox WHERE id=2010")])
    await settle(engine)
    await click(app, "🏠 Deck")
    native.finish(engine.store.session(sid)["thread_id"], text="Background result")
    for event in await runtime.engine.call("/events?after=" + runtime.store.get("event_cursor", "0")):
        runtime.queue_update(event)
    await runtime.deliver_pending()
    assert "Main Deck" in panel(transport).text
    assert "Background result" not in panel(transport).text
    assert not any(m == "turn/interrupt" for m, p in native.calls)


async def test_numbered_location_pages_filter_sessions_and_keep_home_first(app, tmp_path):
    runtime, transport, engine, native = app
    for i in range(12):
        folder = tmp_path / f"place-{i:02d}"
        folder.mkdir()
        engine.store.register_project(f"Place {i:02d}", str(folder))
        engine.store.create_session(str(folder), f"Work {i:02d}", "medium")
    await command(app, "/start")
    await click(app, "📍 Location")
    assert "1. Home" in panel(transport).text and "Page 1/2" in panel(transport).text
    await click(app, "▶")
    assert "Page 2/2" in panel(transport).text
    await click(app, "1")
    assert "Work 09" in panel(transport).text
    assert "Work 08" not in panel(transport).text
    exits(transport)
    await click(app, "1")
    sid = runtime.store.get("selected")
    assert engine.store.session(sid)["name"] == "Work 09"
    await click(app, "ℹ️ Details")
    await click(app, "✖ Close session")
    assert engine.store.session(sid)["archived"] == 1
    labels = [b.text for row in panel(transport).reply_markup.inline_keyboard for b in row]
    assert "🗃 Archived" not in labels and "⚙️ Config" not in labels
    assert "Work 09" not in panel(transport).text
    assert not any(method == "thread/unarchive" for method, params in native.calls)


async def test_existing_legacy_location_input_can_finish_without_exposing_a_new_path_button(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await resume_legacy_location_input(app)
    assert runtime.store.get("mode") == "input"
    await click(app, "⬅️ Back")
    assert runtime.store.get("mode") == "menu"
    await resume_legacy_location_input(app)
    await command(app, str(tmp_path))
    assert runtime.store.get("location") == str(tmp_path)
    assert "No sessions here" in panel(transport).text
    assert engine.store.sessions() == []
    assert not any(m == "turn/start" for m, p in native.calls)


async def test_panel_state_survives_runtime_restart_and_native_questions_stay_in_panel(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    uid = 4000
    runtime.capture(update(uid, "Plan this"))
    await runtime.process_messages([runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,))])
    await settle(engine)
    session = engine.store.session(sid)
    engine.on_request(
        77,
        "item/tool/requestUserInput",
        {
            "threadId": session["thread_id"],
            "questions": [
                {
                    "id": "goal",
                    "question": "Which direction?",
                    "options": [
                        {"label": "Simple", "description": "Keep the workflow small"},
                        {"label": "Advanced", "description": "Add more settings"},
                    ],
                }
            ],
        },
    )
    await runtime.refresh_panel()
    assert "Which direction?" in panel(transport).text
    await click(app, "Simple")
    assert native.calls[-1][0] == "response"
    first_id = runtime.store.get("panel_id")
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    try:
        assert replacement.store.get("selected") == sid
        assert await replacement.refresh_panel()
        assert replacement.store.get("panel_id") == first_id
        assert "Simple" in panel(transport).text
    finally:
        replacement.store.close()
    assert len(transport.messages) == 1


async def test_invalid_location_is_an_inline_error_with_back_and_retry(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await resume_legacy_location_input(app)
    await command(app, "relative/path")
    assert "absolute" in panel(transport).text
    exits(transport)
    assert runtime.store.get("mode") == "input"
    await command(app, str(tmp_path))
    assert runtime.store.get("location") == str(tmp_path)
    assert "absolute" not in panel(transport).text
    assert len(transport.messages) == 1


def test_curated_model_selection_and_long_conversation_parts_are_lossless():
    from telegram_vibecoding.presentation import conversation_parts, curated_models

    ids = ["gpt-6-sol", "gpt-6-astra", "gpt-5.6-astra", "gpt-6.1-sol", "gpt-5.1-astra", "gpt-6-luna"]
    assert [m["id"] for m in curated_models([{"id": mid} for mid in ids])] == [
        "gpt-6.1-sol",
        "gpt-6-astra",
        "gpt-5.6-astra",
    ]
    fence = chr(96) * 3
    text = ("Привет 🚀\n" + fence + "python\nprint('kept')\n" + fence) * 500
    parts = conversation_parts(
        {
            "user": {"payload": {"text": "Original prompt", "images": []}},
            "replies": [{"kind": "message", "payload": {"text": text}}],
        }
    )
    assert "".join(parts) == "You\nOriginal prompt\n\nCodex\n" + text
    assert all(len(p.encode("utf-16-le")) // 2 <= 3200 for p in parts)


async def test_repeated_start_promotes_the_panel_below_commands_and_buttons_edit_it(app):
    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    first = runtime.store.get("panel_id")
    assert "Main Deck" in panel(transport).text
    await command(app, "/start")
    await click(app, "📍 Location")
    await command(app, "/menu")
    assert "Main Deck" in panel(transport).text
    assert int(runtime.store.get("panel_id")) > int(runtime.store.get("last_user_message_id"))
    assert int(first) not in transport.messages
    assert len(transport.messages) == 1
    exits(transport)


async def test_failed_panel_edit_keeps_delivery_pending_without_new_answer_messages(app):
    from aiogram.exceptions import TelegramNetworkError

    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    engine.store.event(sid, "user", {"text": "A request"})
    event_id = engine.store.event(sid, "message", {"text": "Retained answer"})
    runtime.queue_update({"id": event_id, "kind": "message", "session_id": sid, "payload": {}})
    original = transport.make_request

    async def unavailable(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            raise TelegramNetworkError(method=method, message="test transport outage")
        return await original(bot, method, timeout)

    transport.make_request = unavailable
    with pytest.raises(TelegramNetworkError):
        await runtime.deliver_pending()
    assert runtime.store.one("SELECT status FROM outbox WHERE event_id=?", (event_id,))["status"] == "pending"
    transport.make_request = original
    assert await runtime.deliver_pending()
    assert "Retained answer" in panel(transport).text
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1


async def test_long_answer_is_browsable_in_one_panel_without_dropping_text(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    engine.store.event(sid, "user", {"text": "Original prompt"})
    answer = "Native answer 🚀\n" * 800
    engine.store.event(sid, "message", {"text": answer})
    await runtime.refresh_panel()
    bodies = []
    while True:
        current = panel(transport)
        assert len(current.text.encode("utf-16-le")) // 2 <= 4096
        bodies.append(current.text.split("\n\n", 1)[1])
        labels = [b.text for row in current.reply_markup.inline_keyboard for b in row]
        if "◀" not in labels:
            break
        await click(app, "◀")
    assert "".join(reversed(bodies)) == "You\nOriginal prompt\n\nCodex\n" + answer
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1


async def test_incompatible_fsm_reset_reuses_the_published_panel(app):
    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    first = runtime.store.get("panel_id")
    with runtime.store.db:
        runtime.store.db.execute("DELETE FROM meta WHERE key LIKE 'fsm:%'")
    runtime.store.set("ui_version", "1")
    runtime.store.set("screen", "")
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    try:
        await replacement.initialize_panel()
        assert replacement.store.get("panel_id") == first
        assert "Main Deck" in panel(transport).text
        assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1
    finally:
        replacement.store.close()


def test_container_readiness_rejects_previous_boot_even_when_pid_is_reused(tmp_path):
    import os

    from telegram_vibecoding.cli import healthy
    from telegram_vibecoding.config import Settings
    from telegram_vibecoding.store import BotStore

    settings = Settings(
        data_dir=tmp_path / "state", runtime_dir=tmp_path / "run", token_file=tmp_path / "token"
    )
    store = BotStore(settings.data_dir / "bot.db")
    store.set("bot_pid", str(os.getpid()))
    store.set("bot_instance", "old-container")
    instance = tmp_path / "instance"
    instance.write_text("new-container")
    assert not healthy(settings, instance)
    store.set("bot_instance", "new-container")
    assert healthy(settings, instance)
    store.close()


async def test_settings_reports_each_running_component_version_independently(app):
    from telegram_vibecoding import __version__

    runtime, transport, engine, native = app
    original = runtime.engine.call

    async def call(path, body=None):
        if path == "/health":
            return {"version": "2.7.4"}
        return await original(path, body)

    runtime.engine.call = call
    await command(app, "/start")
    identity = runtime.store.get("panel_id")
    await click(app, "⚙️ Settings")
    assert f"Telegram: {__version__}" in panel(transport).text
    assert "Core: 2.7.4" in panel(transport).text
    exits(transport)
    await click(app, "⬅️ Back")
    assert runtime.store.get("panel_id") == identity


async def test_upgrade_recovers_latest_input_from_existing_inbox_and_moves_panel(app):
    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    old = int(runtime.store.get("panel_id"))
    body = update(9000, "/start")
    body["message"]["message_id"] = 185
    runtime.capture(body)
    runtime.store.processed(9000)
    with runtime.store.db:
        runtime.store.db.execute("DELETE FROM meta WHERE key='last_user_message_id'")
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    try:
        await replacement.refresh_panel()
        assert int(replacement.store.get("panel_id")) > 185
        assert old not in transport.messages
        assert len(transport.messages) == 1
        assert not native.calls
    finally:
        replacement.store.close()


async def test_failed_replacement_send_preserves_old_panel_until_retry_succeeds(app):
    from aiogram.exceptions import TelegramNetworkError

    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    old = int(runtime.store.get("panel_id"))
    original = transport.make_request

    async def fail_send(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            raise TelegramNetworkError(method=method, message="test outage")
        return await original(bot, method, timeout)

    transport.make_request = fail_send
    with pytest.raises(TelegramNetworkError):
        await command(app, "/start")
    assert int(runtime.store.get("panel_id")) == old
    assert old in transport.messages
    row = runtime.store.one("SELECT * FROM inbox WHERE status='pending'")
    transport.make_request = original
    await runtime.process_navigation(row)
    assert int(runtime.store.get("panel_id")) > int(runtime.store.get("last_user_message_id"))
    assert old not in transport.messages
    assert len(transport.messages) == 1


async def test_failed_old_panel_cleanup_does_not_repeat_successful_send(app):
    from aiogram.exceptions import TelegramNetworkError

    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    old = int(runtime.store.get("panel_id"))
    original = transport.make_request

    async def fail_delete(bot, method, timeout=None):
        if isinstance(method, DeleteMessage):
            raise TelegramNetworkError(method=method, message="test outage")
        return await original(bot, method, timeout)

    transport.make_request = fail_delete
    await command(app, "/start")
    published = runtime.store.get("panel_id")
    sends = sum(isinstance(m, SendMessage) for m in transport.calls)
    await runtime.refresh_panel()
    assert runtime.store.get("panel_id") == published
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == sends
    transport.make_request = original
    await runtime.clean_retired_panels()
    assert old not in transport.messages
    assert len(transport.messages) == 1
    assert runtime.store.get("retired_panels") == "[]"


async def test_every_command_and_plain_menu_input_moves_the_current_panel(app):
    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    for text in ["/menu", "/help", "/sessions", "/new", "/stop", "/unknown", "ordinary menu input"]:
        previous = int(runtime.store.get("panel_id"))
        await command(app, text)
        current = int(runtime.store.get("panel_id"))
        assert current > int(runtime.store.get("last_user_message_id"))
        assert previous not in transport.messages
        assert len(transport.messages) == 1
        exits(transport)
    assert not native.calls


async def test_absolute_directory_input_is_not_mistaken_for_an_unknown_command(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await resume_legacy_location_input(app)
    await command(app, "/tmp")
    assert runtime.store.get("location") == "/private/tmp" or runtime.store.get("location") == "/tmp"
    assert "Unknown command" not in panel(transport).text
    assert not native.calls


async def test_live_feedback_animates_public_summaries_without_tool_or_code_output(app, monkeypatch):
    from telegram_vibecoding import presentation

    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    await command(app, "Perform the task")
    await settle(engine)
    session = engine.store.session(sid)
    thread = session["thread_id"]
    engine.live[sid]["started"] = 100
    engine.on_event("item/agentMessage/delta", {"threadId": thread, "delta": "LIVE_CODE_MUST_BE_HIDDEN"})
    engine.on_event("item/commandExecution/outputDelta", {"threadId": thread, "delta": "TOOL_OUTPUT_PRIVATE"})
    engine.on_event(
        "item/reasoning/summaryTextDelta",
        {
            "threadId": thread,
            "itemId": "r1",
            "summaryIndex": 0,
            "delta": "Checking behavior.\n```sh\nprintf SECRET_CODE\n```\nThen verifying recovery.\n$ sudo SECRET_COMMAND",
        },
    )
    monkeypatch.setattr(presentation.time, "time", lambda: 110)
    await runtime.refresh_panel()
    identity = runtime.store.get("panel_id")
    before = panel(transport).text
    assert "00:10 elapsed" in before
    assert "Reasoning: medium" in before
    assert "Checking behavior." in before and "Then verifying recovery." in before
    assert all(s not in before for s in ["SECRET_CODE", "SECRET_COMMAND", "LIVE_CODE", "TOOL_OUTPUT"])
    monkeypatch.setattr(presentation.time, "time", lambda: 112)
    await runtime.refresh_panel()
    after = panel(transport).text
    assert after != before and "00:12 elapsed" in after
    assert runtime.store.get("panel_id") == identity
    engine.on_event(
        "item/completed",
        {"threadId": thread, "item": {"id": "r1", "type": "reasoning", "summary": ["Checked behavior."]}},
    )
    native.finish(thread, text="Final answer")
    await runtime.refresh_panel()
    completed = panel(transport).text
    assert "elapsed" not in completed
    assert completed.index("Reasoning\nChecked behavior.") < completed.index("Answer\nFinal answer")
    assert "────────" in completed
    assert len(transport.messages) == 1


async def test_top_level_menus_do_not_expose_configuration_from_a_remembered_session(app, tmp_path):
    runtime, transport, engine, native = app
    other = tmp_path / "another-project"
    other.mkdir()
    selected = engine.store.create_session(str(other), "Remembered session", "medium")
    runtime.store.set("selected", selected["id"])
    await command(app, "/start")
    await click(app, "⚙️ Settings")
    assert "⚙️ Config" not in [b.text for row in panel(transport).reply_markup.inline_keyboard for b in row]
    exits(transport)
    await click(app, "🏠 Deck")
    await click(app, "📍 Location")
    labels = [b.text for row in panel(transport).reply_markup.inline_keyboard for b in row]
    assert not {"⚙️ Config", "📂 Other location", "🗃 Archived"}.intersection(labels)
    exits(transport)
    await click(app, "1")
    assert "No sessions here yet" in panel(transport).text
    labels = [b.text for row in panel(transport).reply_markup.inline_keyboard for b in row]
    assert not {"⚙️ Config", "🗃 Archived"}.intersection(labels)
    exits(transport)
    assert engine.store.session(selected["id"])["name"] == "Remembered session"
    assert not native.calls


@pytest.mark.parametrize(
    "screen,action", [("Screens:archived", ""), ("Screens:input", "location"), ("Screens:config", "")]
)
async def test_retired_views_recover_without_deleting_session_history(app, tmp_path, screen, action):
    runtime, transport, engine, native = app
    retained = engine.store.create_session(str(tmp_path), "Retained closed session", "medium")
    engine.store.update_session(retained["id"], archived=1)
    engine.store.event(retained["id"], "user", {"text": "Keep this request"})
    engine.store.event(retained["id"], "message", {"text": "Keep this response"})
    original_history = engine.store.history(retained["id"])
    await runtime.initialize_panel()
    runtime.store.set("screen", screen)
    runtime.store.set("input_action", action)
    original_count = len(engine.store.sessions(True)) + len(engine.store.sessions())
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    try:
        await replacement.initialize_panel()
        assert "Main Deck" in panel(transport).text
        assert len(engine.store.sessions(True)) + len(engine.store.sessions()) == original_count
        assert engine.store.history(retained["id"]) == original_history
        assert "🗃 Archived" not in [
            b.text for row in panel(transport).reply_markup.inline_keyboard for b in row
        ]
        exits(transport)
    finally:
        replacement.store.close()


def test_compact_response_age_uses_elapsed_time_and_handles_missing_replies():
    from telegram_vibecoding.presentation import relative_age

    assert relative_age(None, now=100000) == "—"
    assert relative_age(99999, now=100000) == "1s"
    assert relative_age(99941, now=100000) == "59s"
    assert relative_age(99940, now=100000) == "1m"
    assert relative_age(92800, now=100000) == "2h"
    assert relative_age(0, now=259200) == "3d"
    assert relative_age(100001, now=100000) == "0s"


async def test_session_pages_show_ten_entries_and_paired_arrows_with_working_marker(app, tmp_path):
    runtime, transport, engine, native = app
    for index in range(12):
        s = engine.store.create_session(str(tmp_path), f"Work {index:02}", "medium")
        with engine.store.db:
            engine.store.db.execute("UPDATE sessions SET updated=? WHERE id=?", (index, s["id"]))
        engine.store.event(s["id"], "message", {"text": "Answer", "phase": "final_answer"})
    engine.store.update_session(s["id"], status="working", turn_id="working-turn")
    runtime.store.set("location", str(tmp_path))
    await command(app, "/sessions")
    current = panel(transport)
    assert "1. Work 11 · ⏳" in current.text
    assert "10. Work 02 · 💬" in current.text
    assert "Work 01" not in current.text
    assert any([button.text for button in row] == ["◀", "▶"] for row in current.reply_markup.inline_keyboard)
    await click(app, "◀")
    assert "Page 1/2" in panel(transport).text
    await click(app, "▶")
    assert "1. Work 01" in panel(transport).text and "2. Work 00" in panel(transport).text
    assert "Work 02" not in panel(transport).text
    assert any(
        [button.text for button in row] == ["◀", "▶"] for row in panel(transport).reply_markup.inline_keyboard
    )
    await click(app, "▶")
    assert "Page 2/2" in panel(transport).text
    await click(app, "⬅️ Back")
    exits(transport)


async def test_voice_download_target_retry_and_transcript_rendering(app, host):
    from telegram_vibecoding.presentation import conversation_parts

    runtime, transport, engine, native = app
    a = engine.store.create_session(str(host[0].data_dir.parent), "Voice", "medium")
    b = engine.store.create_session(str(host[0].data_dir.parent), "Other", "medium")
    runtime.store.set("selected", a["id"])
    runtime.store.set("mode", "chat")
    message = update(3100, "", voice={"file_id": "voice", "file_unique_id": "voice", "duration": 3})
    runtime.capture(message)
    runtime.store.set("selected", b["id"])
    downloads = []

    async def download(file_id, destination):
        downloads.append(file_id)
        destination.write(b"OggS-test-recording")

    async def transcribe(path):
        return {"text": "Проверь картинки и голос", "language": "ru"}

    runtime.bot.download = download
    engine.speech.transcribe = transcribe
    row = runtime.store.one("SELECT * FROM inbox WHERE id=3100")
    await runtime.process_messages([row])
    await settle(engine)
    assert engine.store.request("telegram:3100")["session_id"] == a["id"]
    assert engine.store.session(b["id"])["thread_id"] is None
    path = await runtime.download_voice(message["message"], a["id"])
    from pathlib import Path

    assert Path(path).read_bytes() == b"OggS-test-recording"
    assert Path(path).stat().st_mode & 0o777 == 0o600
    assert downloads == ["voice"]
    rendered = "".join(conversation_parts(engine.store.conversation(a["id"])))
    assert "You\n\n[Voice]\nПроверь картинки и голос" in rendered
    assert [p["input"] for m, p in native.calls if m == "turn/start"] == [
        [{"type": "text", "text": "Проверь картинки и голос"}]
    ]
    with pytest.raises(ValueError, match="five minutes"):
        await runtime.download_voice({"voice": {"duration": 301}}, a["id"])
    with pytest.raises(ValueError, match="Video is not supported"):
        await runtime.download_image({"video": {}}, a["id"])
