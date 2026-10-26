"""Exercise production queue boundaries with slow Telegram and real pacing."""

import asyncio
import json
import time
from contextlib import asynccontextmanager

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Update
from conftest import settle
from test_bot import TelegramFake, update

from telegram_vibecoding.bot import BotRuntime
from telegram_vibecoding.dialogs import Screens

pytestmark = pytest.mark.async_transport


@pytest.fixture
async def async_app(host):
    settings, engine, native, client = host
    transport = TelegramFake()
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi", session=transport)
    runtime = BotRuntime(settings, bot=bot, engine=client)
    yield runtime, transport, engine, native
    await bot.session.close()
    runtime.store.close()


@asynccontextmanager
async def workers(*functions):
    tasks = [asyncio.create_task(fn()) for fn in functions]
    try:
        yield tasks
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def eventually(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.001)


def callback(uid, data="deck"):
    return Update.model_validate(
        {
            "update_id": uid,
            "callback_query": {
                "id": f"cb-{uid}",
                "chat_instance": "test",
                "from": {"id": 42, "is_bot": False, "first_name": "Owner"},
                "data": data,
                "message": {
                    "message_id": 100,
                    "date": int(time.time()),
                    "chat": {"id": 42, "type": "private"},
                    "text": "Panel",
                },
            },
        }
    )


async def test_slow_panel_cannot_block_capture_callback_ack_or_ordered_navigation(async_app):
    runtime, transport, engine, native = async_app
    entered, release = asyncio.Event(), asyncio.Event()
    original = transport.make_request

    async def slow(bot, method, timeout=None):
        if isinstance(method, (SendMessage, EditMessageText)):
            entered.set()
            await release.wait()
        return await original(bot, method, timeout)

    transport.make_request = slow
    await runtime.initialize_panel()
    async with workers(runtime.panel_loop, runtime.navigation_loop, runtime.acknowledge_loop):
        await entered.wait()
        started = time.perf_counter()
        await runtime.receive_update(callback(1000))
        await runtime.receive_update(Update.model_validate(update(1001, "/menu")))
        await eventually(
            lambda: runtime.store.one("SELECT status FROM inbox WHERE id=1001")["status"] == "done"
        )
        await eventually(lambda: any(isinstance(c, AnswerCallbackQuery) for c in transport.calls))
        elapsed = time.perf_counter() - started
        assert elapsed < 0.2, f"Input and acknowledgement waited {elapsed:.3f}s for a blocked HTTP write"
        assert not release.is_set()
        assert runtime.store.get("offset") == "1002"
        assert runtime.store.get("screen") == Screens.deck.state
        assert not engine.store.sessions()
        assert not native.calls or not any(m == "turn/start" for m, _ in native.calls)
        release.set()
        await eventually(lambda: runtime.panels.pending is None)
        assert runtime.store.get("panel_id")


async def test_batched_switch_then_message_captures_new_target_and_never_retargets(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    await runtime.initialize_panel()
    a = engine.store.create_session(str(tmp_path), "A", "medium")
    b = engine.store.create_session(str(tmp_path), "B", "medium")
    runtime.store.set("selected", a["id"])
    await runtime.receive_update(callback(2000, "open:" + b["id"]))
    await runtime.receive_update(Update.model_validate(update(2001, "Original input")))
    assert runtime.store.one("SELECT status FROM inbox WHERE id=2001")["status"] == "received"
    await runtime.navigation_tick()
    row = runtime.store.one("SELECT * FROM inbox WHERE id=2001")
    assert row["session_id"] == b["id"]
    assert json.loads(row["body"])["message"]["text"] == "Original input"
    await runtime.receive_update(callback(2002, "open:" + a["id"]))
    await runtime.navigation_tick()
    await runtime.process_messages([row])
    await settle(engine)
    assert engine.store.session(b["id"])["thread_id"]
    assert engine.store.session(a["id"])["thread_id"] is None
    assert runtime.store.get("offset") == "2003"


async def test_pending_panels_coalesce_and_no_op_refresh_does_not_write_again(async_app):
    runtime, transport, engine, native = async_app
    await runtime.initialize_panel()
    for uid in range(3000, 3005):
        await runtime.receive_update(callback(uid))
    await runtime.navigation_tick()
    assert not any(isinstance(c, SendMessage) for c in transport.calls)
    await runtime.panels.publish_pending()
    assert len([c for c in transport.calls if isinstance(c, (SendMessage, EditMessageText))]) == 1
    before = len(transport.calls)
    await runtime.refresh_panel()
    await runtime.panels.publish_pending()
    assert len(transport.calls) == before


async def test_failed_panel_keeps_outbox_and_read_receipt_until_real_publication(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    s = engine.store.create_session(str(tmp_path), "Session", "medium")
    runtime.store.set("selected", s["id"])
    runtime.store.queue_event(123, ["Result"], None)
    await runtime.initialize_panel()
    runtime.panels.pending = (*runtime.panels.pending[:2], (s["id"], 123), runtime.panels.pending[3])
    original = transport.make_request

    async def fail(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            raise TelegramNetworkError(method=method, message="offline")
        return await original(bot, method, timeout)

    transport.make_request = fail
    with pytest.raises(TelegramNetworkError):
        await runtime.panels.publish_pending()
    assert runtime.panels.pending is not None
    assert runtime.store.viewed(s["id"]) == 0
    assert runtime.store.one("SELECT status FROM outbox WHERE event_id=123")["status"] == "pending"
    transport.make_request = original
    await runtime.panels.publish_pending()
    assert runtime.store.viewed(s["id"]) == 123
    assert runtime.store.one("SELECT status FROM outbox WHERE event_id=123")["status"] == "sent"


async def test_flood_wait_does_not_prevent_control_processing_or_callback_ack(async_app):
    runtime, transport, engine, native = async_app
    runtime.store.set("telegram_retry_until", str(time.time() + 3600))
    await runtime.receive_update(callback(4000))
    async with workers(runtime.acknowledge_loop):
        await runtime.navigation_tick()
        await eventually(lambda: any(isinstance(c, AnswerCallbackQuery) for c in transport.calls))
    assert runtime.store.one("SELECT status FROM inbox WHERE id=4000")["status"] == "done"
    with pytest.raises(TelegramRetryAfter):
        await runtime.panels.publish_pending()
    assert runtime.panels.pending is not None
    assert not any(isinstance(c, SendMessage) for c in transport.calls)


async def test_slow_media_in_one_session_does_not_hold_text_in_another(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    a = engine.store.create_session(str(tmp_path), "A", "medium")
    b = engine.store.create_session(str(tmp_path), "B", "medium")
    entered, release = asyncio.Event(), asyncio.Event()

    async def download(message, sid):
        if message.get("photo"):
            entered.set()
            await release.wait()
        return None

    runtime.download_image = download
    runtime.store.set("mode", "chat")
    runtime.store.set("selected", a["id"])
    runtime.capture(
        update(5000, "Photo", photo=[{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}])
    )
    runtime.store.set("selected", b["id"])
    runtime.capture(update(5001, "Independent text"))
    async with workers(runtime.inbox_loop):
        await entered.wait()
        await eventually(lambda: bool(engine.store.session(b["id"])["thread_id"]))
        assert engine.store.session(a["id"])["thread_id"] is None
        release.set()
        await eventually(
            lambda: runtime.store.one("SELECT status FROM inbox WHERE id=5000")["status"] == "done"
        )
    await settle(engine)


@pytest.mark.parametrize("new_session", [False, True])
async def test_stop_cancels_pending_media_without_a_late_native_dispatch(async_app, tmp_path, new_session):
    runtime, transport, engine, native = async_app
    session = engine.store.create_session(str(tmp_path), "A", "medium")
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def download(message, sid):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    runtime.download_image = download
    if new_session:
        await runtime.initialize_panel()
        runtime.store.set("screen", Screens.sessions.state)
        runtime.store.set("location", str(tmp_path))
    else:
        runtime.store.set("mode", "chat")
        runtime.store.set("selected", session["id"])
    runtime.capture(update(6000, "Pending picture"))
    runtime.capture(update(6001, "Queued followup"))
    async with workers(runtime.inbox_loop):
        await entered.wait()
        sid = runtime.store.get("selected")
        started = time.perf_counter()
        await runtime.engine.call(f"/sessions/{sid}/stop", {})
        assert time.perf_counter() - started < 0.2
        assert cancelled.is_set()
        assert not runtime.store.rows("SELECT id FROM inbox WHERE status='pending'")
        await asyncio.sleep(0.1)
        assert not any(m == "turn/start" for m, _ in native.calls)


async def test_received_updates_survive_restart_and_offset_never_moves_backwards(async_app):
    runtime, transport, engine, native = async_app
    await runtime.receive_update(Update.model_validate(update(7000, "/menu")))
    await runtime.receive_update(Update.model_validate(update(7001, "/start")))
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    try:
        await replacement.navigation_tick()
        assert replacement.store.get("screen") == Screens.deck.state
        assert not replacement.store.rows("SELECT id FROM inbox WHERE status='received'")
        replacement.capture(update(6999, "Old duplicate", owner=7))
        assert replacement.store.get("offset") == "7002"
        assert not any(m == "turn/start" for m, _ in native.calls)
        await replacement.panels.publish_pending()
        assert replacement.store.get("panel_id")
    finally:
        replacement.store.close()


async def test_superseded_display_does_not_acknowledge_a_result(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    session = engine.store.create_session(str(tmp_path), "A", "medium")
    engine.submit({"request_id": "result", "session_id": session["id"], "text": "Question", "images": []})
    await settle(engine)
    native.finish(engine.store.session(session["id"])["thread_id"], text="Short final answer")
    await runtime.initialize_panel()
    await runtime.panels.publish_pending()
    await runtime.receive_update(callback(8000, "open:" + session["id"]))
    await runtime.navigation_tick()
    assert runtime.panels.pending[2]
    entered, release = asyncio.Event(), asyncio.Event()
    original = transport.make_request

    async def delayed(bot, method, timeout=None):
        if isinstance(method, EditMessageText):
            entered.set()
            await release.wait()
        return await original(bot, method, timeout)

    transport.make_request = delayed
    async with workers(runtime.panel_loop):
        await entered.wait()
        await runtime.receive_update(callback(8001))
        await runtime.navigation_tick()
        release.set()
        await eventually(lambda: runtime.panels.pending is None)
    assert runtime.store.viewed(session["id"]) == 0
    assert runtime.store.get("screen") == Screens.deck.state


async def test_device_confirmation_still_precedes_local_stop_cancellation(async_app, tmp_path):
    from telegram_vibecoding.confirmation import ConfirmationRequired, Confirmations, GuardedClient

    runtime, transport, engine, native = async_app
    session = engine.store.create_session(str(tmp_path), "A", "medium")
    runtime.store.set("mode", "chat")
    runtime.store.set("selected", session["id"])
    runtime.capture(update(9000, "Unapproved input"))
    runtime.confirmations = Confirmations(runtime.store)
    runtime.engine = GuardedClient(runtime.engine, runtime.confirmations)
    marker = runtime.confirmations.source.set("control:stop")
    try:
        with pytest.raises(ConfirmationRequired):
            await runtime.engine.call(f"/sessions/{session['id']}/stop", {})
    finally:
        runtime.confirmations.source.reset(marker)
    assert runtime.store.one("SELECT status FROM inbox WHERE id=9000")["status"] == "pending"


async def test_real_dialog_buttons_and_history_work_with_queued_publication(async_app):
    from test_bot import click, panel

    runtime, transport, engine, native = async_app
    # This is a functional reader test with the real queue; rate timing is
    # exercised above, so drain immediately here to keep the transition test short.
    runtime.pacer.interval = 0
    await runtime.initialize_panel()
    await runtime.panels.publish_pending()
    for label in ["📍 Location", "1", "➕ New", "⚙️ Config", "⬅️ Back", "📖 History"]:
        if label == "📖 History":
            label = next(
                b.text
                for row in panel(transport).reply_markup.inline_keyboard
                for b in row
                if "History" in b.text
            )
        await click(async_app, label)
        await runtime.panels.publish_pending()
    assert runtime.store.get("screen") == Screens.history.state
    assert runtime.store.get("panel_id")
    assert not any(m == "turn/start" for m, _ in native.calls)


async def test_received_album_uses_first_captured_target_across_navigation(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    await runtime.initialize_panel()
    a = engine.store.create_session(str(tmp_path), "A", "medium")
    b = engine.store.create_session(str(tmp_path), "B", "medium")
    runtime.store.set("selected", a["id"])
    runtime.store.set("mode", "chat")
    photo = [{"file_id": "p", "file_unique_id": "p", "width": 1, "height": 1}]
    await runtime.receive_update(
        Update.model_validate(update(10000, "First", photo=photo, media_group_id="album"))
    )
    await runtime.receive_update(callback(10001, "open:" + b["id"]))
    await runtime.receive_update(
        Update.model_validate(update(10002, "Second", photo=photo, media_group_id="album"))
    )
    await runtime.navigation_tick()
    first = runtime.store.one("SELECT * FROM inbox WHERE id=10000")
    second = runtime.store.one("SELECT * FROM inbox WHERE id=10002")
    assert first["mode"] == second["mode"] == "chat"
    assert first["session_id"] == second["session_id"] == a["id"]
    assert runtime.store.get("selected") == b["id"]


async def test_publisher_chooses_latest_view_after_waiting_for_another_writer(async_app, tmp_path):
    runtime, transport, engine, native = async_app
    session = engine.store.create_session(str(tmp_path), "Latest view", "medium")
    await runtime.initialize_panel()
    async with runtime.send_lock:
        publishing = asyncio.create_task(runtime.panels.publish_pending())
        await asyncio.sleep(0.01)
        assert not publishing.done()
        await runtime.receive_update(callback(11000, "open:" + session["id"]))
        await runtime.navigation_tick()
    await publishing
    writes = [c for c in transport.calls if isinstance(c, (SendMessage, EditMessageText))]
    assert len(writes) == 1
    assert "Latest view" in writes[0].text


async def test_auth_service_reply_cannot_block_navigation_during_flood_wait(async_app):
    runtime, transport, engine, native = async_app
    await runtime.initialize_panel()
    runtime.store.set("telegram_retry_until", str(time.time() + 3600))
    await runtime.receive_update(Update.model_validate(update(12000, "/auth")))
    await runtime.receive_update(callback(12001))
    async with asyncio.timeout(0.2):
        await runtime.navigation_tick()
    assert runtime.store.one("SELECT status FROM inbox WHERE id=12000")["status"] == "done"
    assert runtime.store.one("SELECT status FROM inbox WHERE id=12001")["status"] == "done"
    assert runtime.store.one("SELECT status FROM service_messages")["status"] == "pending"
    with pytest.raises(TelegramRetryAfter):
        await runtime.deliver_service_messages()
    assert not any(isinstance(c, SendMessage) for c in transport.calls)


async def test_service_reply_survives_restart_and_failed_delivery_without_repeating_success(async_app):
    runtime, transport, engine, native = async_app
    await runtime.send("Service reply")
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    original = transport.make_request

    async def fail(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            raise TelegramNetworkError(method=method, message="offline")
        return await original(bot, method, timeout)

    try:
        transport.make_request = fail
        with pytest.raises(TelegramNetworkError):
            await replacement.deliver_service_messages()
        assert replacement.store.one("SELECT status FROM service_messages")["status"] == "pending"
        transport.make_request = original
        await replacement.deliver_service_messages()
        before = len([c for c in transport.calls if isinstance(c, SendMessage)])
        await replacement.deliver_service_messages()
        assert before == 1
        assert len([c for c in transport.calls if isinstance(c, SendMessage)]) == before
        assert replacement.store.one("SELECT status FROM service_messages")["status"] == "sent"
    finally:
        replacement.store.close()


async def test_stalled_startup_notice_does_not_hold_navigation_state(async_app):
    runtime, transport, engine, native = async_app
    entered, release = asyncio.Event(), asyncio.Event()
    original = transport.make_request

    async def delayed(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            entered.set()
            await release.wait()
        return await original(bot, method, timeout)

    transport.make_request = delayed
    startup = asyncio.create_task(runtime.startup_panel())
    try:
        await entered.wait()
        await runtime.receive_update(callback(13000))
        async with asyncio.timeout(0.2):
            await runtime.navigation_tick()
        assert runtime.store.get("screen") == Screens.deck.state
        release.set()
        await startup
    finally:
        startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)


async def test_failed_callback_ack_is_best_effort_and_cannot_poison_controls(async_app):
    from aiogram.exceptions import TelegramBadRequest

    runtime, transport, engine, native = async_app
    original = transport.make_request
    attempts = []

    async def expired(bot, method, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            attempts.append(method.callback_query_id)
            raise TelegramBadRequest(method=method, message="query is too old and response timeout expired")
        return await original(bot, method, timeout)

    transport.make_request = expired
    await runtime.receive_update(callback(14000))
    await runtime.receive_update(Update.model_validate(update(14001, "/menu")))
    async with workers(runtime.acknowledge_loop, runtime.navigation_loop):
        await eventually(
            lambda: runtime.store.one("SELECT status FROM inbox WHERE id=14001")["status"] == "done"
        )
        await eventually(lambda: bool(attempts))
    assert attempts == ["cb-14000"]
    assert runtime.store.get("screen") == Screens.deck.state
