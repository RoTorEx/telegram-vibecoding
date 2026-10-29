import json
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import Update
from test_bot import TelegramFake, update

from telegram_vibecoding.client import ReadOnlyCoreClient
from telegram_vibecoding.notifier import Notifier


class ReadSource:
    def __init__(self):
        self.events = []
        self.calls = []
        self.sessions = [
            {
                "id": "a" * 16,
                "name": "Workspace",
                "cwd": "/work",
                "status": "idle",
                "model": "native-model",
                "effort": "high",
                "collaboration_mode": "plan",
            }
        ]

    async def call(self, path, body=None):
        assert body is None
        self.calls.append(path)
        if path == "/health":
            return {"version": "fixture"}
        if path == "/sessions":
            return self.sessions
        if path == "/live":
            return {}
        if path.startswith("/events?after="):
            after = int(path.split("=", 1)[1])
            return [event for event in self.events if event["id"] > after]
        raise AssertionError(path)

    async def close(self):
        pass


@pytest.fixture
async def notifier(host):
    settings, core, native, client = host
    transport = TelegramFake()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=transport)
    app = Notifier(settings, bot=bot, engine=client)
    yield app, transport, core, native
    app.store.close()
    await bot.session.close()


@pytest.mark.parametrize(
    "path,body",
    [
        ("/messages", {}),
        ("/messages", None),
        ("/sessions", {}),
        ("/sessions/aaaaaaaaaaaaaaaa/stop", {}),
        ("/questions/abc", {}),
        ("/drain", {}),
        ("/sessions/../drain", None),
        ("/events?after=0&extra=1", None),
    ],
)
async def test_read_only_client_denies_before_transport(path, body):
    source = ReadSource()
    client = ReadOnlyCoreClient(source)
    with pytest.raises(PermissionError):
        await client.call(path, body)
    assert source.calls == []


async def test_owner_messages_media_and_legacy_buttons_never_dispatch(notifier):
    app, transport, core, native = notifier
    calls = len(native.calls)
    sessions = core.store.rows("SELECT * FROM sessions")
    app.store.receive(777, update(uid=777, text="Legacy unsent executable input"))
    for index, text in enumerate(
        ["Run rm", "/stop", "/new", "/plan", "/settings", "/menu", "/start", "../../host", "/stats"]
    ):
        await app.handle(Update.model_validate(update(uid=index + 1, text=text)))
    for index, media in enumerate(
        [
            {"photo": [{"file_id": "x", "file_unique_id": "x", "width": 1, "height": 1}]},
            {"voice": {"file_id": "x", "file_unique_id": "x", "duration": 1}},
            {"document": {"file_id": "x", "file_unique_id": "x"}},
        ]
    ):
        await app.handle(Update.model_validate(update(uid=20 + index, text=None, **media)))
    for action in ["open:aaaaaaaaaaaaaaaa", "stop", "mode:plan", "model:test", "confirm:anything"]:
        await app.handle(
            Update.model_validate(
                {
                    "update_id": 50,
                    "callback_query": {
                        "id": action,
                        "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
                        "chat_instance": "private",
                        "data": action,
                        "message": update()["message"],
                    },
                }
            )
        )
    assert len(native.calls) == calls
    assert core.store.rows("SELECT * FROM sessions") == sessions
    assert app.store.one("SELECT status FROM inbox WHERE id=777")["status"] == "received"
    for method in transport.calls:
        if isinstance(method, SendMessage):
            assert method.reply_markup.inline_keyboard[0][0].url.startswith("https://vibecoding.com/")
            assert method.reply_markup.inline_keyboard[0][0].callback_data is None
    assert not list(app.settings.data_dir.glob("uploads/*"))


async def test_unauthorized_private_group_edited_messages_are_ignored(notifier):
    app, transport, *_ = notifier
    await app.handle(Update.model_validate(update(owner=99, text="/stats")))
    group = update(text="/stats")
    group["message"]["chat"] = {"id": -42, "type": "group", "title": "Untrusted"}
    await app.handle(Update.model_validate(group))
    await app.handle(
        Update.model_validate({"update_id": 10, "edited_message": update(text="/new")["message"]})
    )
    assert transport.calls == []


def event(identifier, kind, created, **payload):
    return {"id": identifier, "kind": kind, "created": created, "session_id": "a" * 16, "payload": payload}


async def test_atomic_cursor_stats_and_durable_notification_restart(tmp_path):
    from telegram_vibecoding.config import Settings

    source = ReadSource()
    transport = TelegramFake()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=transport)
    settings = Settings(tmp_path, tmp_path / "readonly-socket", tmp_path / "token", allowed_user_id=42)
    app = Notifier(settings, bot=bot, engine=source)
    app.store.set("notifier_since", "100")
    app.sessions = source.sessions
    source.events = [
        event(1, "user", 101, text="Do not forward this prompt"),
        event(2, "user", 105, text="Steering"),
        event(3, "completed", 121, status="completed"),
    ]
    original_capture = app.capture

    def crash(event):
        original_capture(event)
        raise RuntimeError("Simulated interruption before cursor commit")

    app.capture = crash
    with pytest.raises(RuntimeError):
        await app.collect()
    assert app.store.get("notifier_inputs", "0") == "0"
    assert app.store.get("notifier_cursor", "0") == "0"
    app.capture = original_capture
    await app.collect()
    await app.collect()
    assert app.store.get("notifier_inputs") == "2"
    assert app.store.get("notifier_outcomes") == "1"
    assert app.store.get("notifier_seconds") == "20.0"
    await app.deliver()
    messages = [call for call in transport.calls if isinstance(call, SendMessage)]
    assert len(messages) == 1
    message = messages[0]
    assert "20s · 2 retained inputs" in message.text
    assert "native-model · high · plan" in message.text
    assert "Do not forward" not in message.text
    assert message.reply_markup.inline_keyboard[0][0].url == "https://vibecoding.com/#" + "a" * 16
    app.store.close()
    restored = Notifier(settings, bot=bot, engine=source)
    await restored.collect()
    await restored.deliver()
    assert len([call for call in transport.calls if isinstance(call, SendMessage)]) == 1
    restored.store.close()
    await bot.session.close()


async def test_no_historical_backfill_question_notice_and_missing_duration(tmp_path):
    from telegram_vibecoding.config import Settings

    source = ReadSource()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=TelegramFake())
    app = Notifier(
        Settings(tmp_path, tmp_path / "run", tmp_path / "token", allowed_user_id=42), bot=bot, engine=source
    )
    app.store.set("notifier_since", "100")
    source.events = [
        event(1, "completed", 90, status="failed"),
        event(2, "question", 110, text="private question"),
        event(3, "completed", 120, status="interrupted"),
    ]
    await app.collect()
    rows = app.store.rows("SELECT * FROM notifier_notices")
    assert [row["event_id"] for row in rows] == [2, 3]
    assert "input required" in rows[0]["body"]
    assert "unavailable" in rows[1]["body"]
    assert "private question" not in json.dumps(rows)
    assert not (tmp_path / "run").exists()
    app.store.close()
    await bot.session.close()


def test_production_cli_uses_notifier_only(monkeypatch, tmp_path):
    from telegram_vibecoding import cli, notifier

    calls = []

    async def run(settings):
        calls.append(settings)

    monkeypatch.setattr(notifier, "run", run)
    monkeypatch.setattr(cli.Settings, "load", lambda *args: SimpleNamespace())
    monkeypatch.setattr("sys.argv", ["telegram-vibecoding"])
    cli.main()
    assert len(calls) == 1


async def test_truncated_history_does_not_invent_work_duration(tmp_path):
    from telegram_vibecoding.config import Settings

    source = ReadSource()
    source.events = [event(50, "user", 101), event(51, "completed", 121, status="completed")]
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=TelegramFake())
    app = Notifier(
        Settings(tmp_path, tmp_path / "run", tmp_path / "token", allowed_user_id=42), bot=bot, engine=source
    )
    app.store.set("notifier_since", "100")
    await app.collect()
    assert "unavailable" in app.store.one("SELECT body FROM notifier_notices")["body"]
    assert app.store.get("notifier_seconds", "0") == "0"
    app.store.close()
    await bot.session.close()
