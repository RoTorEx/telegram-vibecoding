import asyncio
import time

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import DeleteMessage, GetMe, SendMessage
from aiogram.types import Update
from test_bot import app as app
from test_bot import update


async def test_chat_cooldown_is_durable_and_reads_continue_without_api_write_retries(app):
    runtime, transport, engine, native = app
    original = transport.make_request
    attempts = []

    async def flood(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            attempts.append(method)
            raise TelegramRetryAfter(method=method, message="flood wait", retry_after=3600)
        return await original(bot, method, timeout)

    transport.make_request = flood
    with pytest.raises(TelegramRetryAfter):
        await runtime.bot.send_message(42, "First")
    assert runtime.pacer.remaining > 3500
    with pytest.raises(TelegramRetryAfter):
        await runtime.bot.send_message(42, "Retried")
    with pytest.raises(TelegramRetryAfter):
        await runtime.bot.delete_message(42, 1)
    assert len(attempts) == 1
    assert (await runtime.bot.get_me()).username == "GardenSandbox_bot"
    from telegram_vibecoding.pacing import ChatPacer

    assert ChatPacer(runtime.store, 42).remaining > 3500
    await runtime.receive_update(Update.model_validate(update(500, "/menu")))
    assert runtime.store.one("SELECT status FROM inbox WHERE id=500")["status"] == "received"
    assert runtime.store.get("offset") == "501"


async def test_chat_pacing_includes_deletes_and_does_not_serialize_get_me(app):
    runtime, transport, engine, native = app
    runtime.pacer.interval = 0.05
    await runtime.bot.delete_message(42, 1)
    runtime.pacer.last_write = time.monotonic() + 0.1
    pending = asyncio.create_task(runtime.bot.delete_message(42, 2))
    await asyncio.sleep(0)
    assert not pending.done()
    assert (await runtime.bot.get_me()).username == "GardenSandbox_bot"
    assert not pending.done()
    await pending
    assert [type(c) for c in transport.calls] == [DeleteMessage, GetMe, DeleteMessage]


async def test_successful_startup_task_stays_alive_until_shutdown(app):
    runtime, transport, engine, native = app
    done = asyncio.Event()

    async def ready():
        done.set()

    runtime.startup_ready = ready
    task = asyncio.create_task(runtime.startup_loop())
    await done.wait()
    assert not task.done()
    runtime.stop_event.set()
    await task
