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

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Relay", username="GardenSandbox_bot")
        if isinstance(method, (SendMessage, EditMessageText, SendDocument)):
            self.counter += 1
            return Message(
                message_id=getattr(method, "message_id", None) or self.counter,
                date=datetime.now(UTC),
                chat=Chat(id=42, type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Relay"),
                text=getattr(method, "text", None) or "document",
                reply_markup=getattr(method, "reply_markup", None),
            )
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage, EditMessageReplyMarkup)):
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
    assert [b.text for b in markup.inline_keyboard[-1]] == ["🏠 Deck", "⬅️ Back"]
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
    runtime, *_ = app
    uid = int(runtime.store.get("offset", "1000"))
    runtime.capture(update(uid, text))
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


def exits(transport):
    assert [b.text for b in panel(transport).reply_markup.inline_keyboard[-1]] == ["🏠 Deck", "⬅️ Back"]


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
    assert "Send a message" in panel(transport).text
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
    await command(app, "A clear session title")
    assert engine.store.session(sid)["name"] == "A clear session title"
    assert "Details" in panel(transport).text
    await click(app, "⬅️ Back")
    assert "A clear session title" in panel(transport).text
    await click(app, "🏠 Deck")
    await click(app, "⬅️ Back")
    assert "Main Deck" in panel(transport).text
    assert runtime.store.get("panel_id") == first_id
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1


async def test_stream_delivery_history_and_navigation_preserve_one_panel(app, host):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New session")
    sid = runtime.store.get("selected")
    first_id = runtime.store.get("panel_id")
    for index in range(2):
        uid = 2000 + index
        runtime.capture(update(uid, f"Original request {index}"))
        await runtime.process_messages([runtime.store.one("SELECT * FROM inbox WHERE id=?", (uid,))])
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
    assert runtime.store.get("panel_id") == first_id
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1
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
    await click(app, "🗃 Close session")
    assert engine.store.session(sid)["archived"] == 1
    await click(app, "🗃 Archived")
    assert "Work 09" in panel(transport).text and "Work 08" not in panel(transport).text
    await click(app, "1")
    assert engine.store.session(sid)["archived"] == 0


async def test_other_location_cancel_and_save_do_not_create_sessions(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "📂 Other location")
    assert runtime.store.get("mode") == "input"
    await click(app, "⬅️ Back")
    assert runtime.store.get("mode") == "menu"
    await click(app, "📂 Other location")
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
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1


async def test_invalid_location_is_an_inline_error_with_back_and_retry(app, tmp_path):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "📂 Other location")
    await command(app, "relative/path")
    assert "absolute" in panel(transport).text
    exits(transport)
    assert runtime.store.get("mode") == "input"
    await command(app, str(tmp_path))
    assert runtime.store.get("location") == str(tmp_path)
    assert "absolute" not in panel(transport).text
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1


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


async def test_server_publishes_fresh_deck_and_repeated_start_reuses_it(app):
    runtime, transport, engine, native = app
    await runtime.initialize_panel()
    first = runtime.store.get("panel_id")
    assert "Main Deck" in panel(transport).text
    await command(app, "/start")
    await click(app, "📍 Location")
    await command(app, "/menu")
    assert "Main Deck" in panel(transport).text
    assert runtime.store.get("panel_id") == first
    assert sum(isinstance(m, SendMessage) for m in transport.calls) == 1
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
