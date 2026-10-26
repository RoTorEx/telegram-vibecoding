import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage
from conftest import settle
from test_bot import app as app
from test_bot import click, command, panel
from test_markdown import CheckedHTML

from telegram_vibecoding.bot import BotRuntime
from telegram_vibecoding.markdown import html_length, render_markdown


def answer_messages(transport):
    return [m for m in transport.calls if isinstance(m, SendMessage) and " · <i>Answer " in m.text]


async def completed_answer(app):
    runtime, transport, engine, native = app
    await command(app, "/start")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "➕ New")
    sid = runtime.store.get("selected")
    await command(app, "Original request")
    await settle(engine)
    answer = "**Complete** <literal> 🚀 answer\n" * 600
    native.finish(engine.store.session(sid)["thread_id"], text=answer)
    return sid, answer


async def test_entire_answer_arrives_in_order_and_survives_followups_and_navigation(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    await runtime.refresh_panel()
    await runtime.deliver_answers()
    messages = answer_messages(transport)
    assert len(messages) > 2
    assert (
        "".join(CheckedHTML(m.text.split("\n\n", 1)[1]).text for m in messages)
        == CheckedHTML(render_markdown(answer)).text
    )
    assert all(
        html_length(m.text) <= 4096 and m.reply_markup is None and m.disable_notification is True
        for m in messages
    )
    rows = runtime.store.rows("SELECT * FROM answer_parts ORDER BY part")
    ids = [r["telegram_id"] for r in rows]
    assert all(r["status"] == "sent" for r in rows)
    assert int(runtime.store.get("panel_id")) > max(ids)
    assert "Complete" not in panel(transport).text
    assert runtime.store.viewed(sid) == 0
    await runtime.refresh_panel()
    await runtime.deliver_answers()
    assert len(answer_messages(transport)) == len(messages)
    await command(app, "Follow-up")
    await settle(engine)
    assert all(i in transport.messages for i in ids)
    await click(app, "📖 History")
    assert all(i in transport.messages for i in ids)
    await click(app, "🏠 Deck")
    await runtime.deliver_answers()
    assert all(i in transport.messages for i in ids)


async def test_partial_delivery_resumes_after_restart_without_repeating_accepted_parts(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    await runtime.refresh_panel()
    original = transport.make_request
    failed = False

    async def fail_second(bot, method, timeout=None):
        nonlocal failed
        if isinstance(method, SendMessage) and " · <i>Answer 2/" in method.text and not failed:
            failed = True
            raise TelegramNetworkError(method=method, message="Offline")
        return await original(bot, method, timeout)

    transport.make_request = fail_second
    with pytest.raises(TelegramNetworkError):
        await runtime.deliver_answers()
    assert len(answer_messages(transport)) == 1
    transport.make_request = original
    await click(app, "🏠 Deck")
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    replacement.pacer.interval = 0
    try:
        await replacement.deliver_answers()
        await replacement.deliver_answers()
        messages = answer_messages(transport)
        assert sum(" · <i>Answer 1/" in m.text for m in messages) == 1
        assert (
            "".join(CheckedHTML(m.text.split("\n\n", 1)[1]).text for m in messages)
            == CheckedHTML(render_markdown(answer)).text
        )
        assert replacement.store.viewed(sid) == 0
    finally:
        replacement.store.close()


async def test_explicit_session_open_replays_full_answer_and_acknowledges_after_last_part(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    completion = next(e["id"] for e in reversed(engine.store.events(0)) if e["kind"] == "completed")
    await runtime.refresh_panel()
    await runtime.deliver_answers()
    initial = len(answer_messages(transport))
    await click(app, "🏠 Deck")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "1")
    assert runtime.store.viewed(sid) == 0
    await runtime.deliver_answers()
    assert len(answer_messages(transport)) == initial * 2
    assert runtime.store.viewed(sid) == completion


async def test_leaving_during_throttle_preserves_pending_answer_and_old_parts_expire(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    await runtime.refresh_panel()

    async def leave():
        runtime.store.set("screen", "Screens:deck")

    runtime.throttle = leave
    await runtime.deliver_answers()
    assert not answer_messages(transport)
    assert runtime.store.one("SELECT COUNT(*) AS n FROM answer_parts WHERE status='pending'")["n"] > 0
    with runtime.store.db:
        runtime.store.db.execute("UPDATE answer_parts SET created=0")
    result = runtime.store.expire_history(1)
    assert result["answer_parts"] > 0
    assert not runtime.store.rows("SELECT * FROM answer_parts")


async def test_new_completion_during_full_answer_publication_stays_unread(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    old = next(e["id"] for e in reversed(engine.store.events(0)) if e["kind"] == "completed")
    await click(app, "🏠 Deck")
    await click(app, "📍 Location")
    await click(app, "1")
    await click(app, "1")
    original = transport.make_request
    newer = []

    async def complete_again(bot, method, timeout=None):
        result = await original(bot, method, timeout)
        if isinstance(method, SendMessage) and " · <i>Answer 1/" in method.text and not newer:
            engine.store.event(sid, "user", {"text": "A newer request"})
            engine.store.event(sid, "message", {"text": "A newer result"})
            newer.append(engine.store.event(sid, "completed", {"status": "completed"}))
        return result

    transport.make_request = complete_again
    await runtime.deliver_answers()
    assert newer and runtime.store.viewed(sid) == old < newer[0]
    assert "A newer result" in panel(transport).text


@pytest.mark.parametrize("same_session", [False, True])
async def test_navigation_during_first_send_finishes_whole_answer(app, same_session):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    await runtime.refresh_panel()
    visit = runtime.store.get("answer_visit")
    other = engine.store.create_session(engine.store.session(sid)["cwd"], "Other", "medium")["id"]
    original = transport.make_request
    switched = False

    async def navigate(bot, method, timeout=None):
        nonlocal switched
        result = await original(bot, method, timeout)
        if isinstance(method, SendMessage) and " · <i>Answer 1/" in method.text and not switched:
            switched = True
            if not same_session:
                runtime.store.set("selected", other)
                runtime.store.set("screen", "Screens:deck")
            runtime.store.answer_visit(new=True)
        return result

    transport.make_request = navigate
    await runtime.deliver_answers()
    await runtime.deliver_answers()
    messages = answer_messages(transport)
    assert switched and len(messages) > 2
    assert sum(" · <i>Answer 1/" in m.text for m in messages) == 1
    assert (
        "".join(CheckedHTML(m.text.split("\n\n", 1)[1]).text for m in messages)
        == CheckedHTML(render_markdown(answer)).text
    )
    assert all(r["status"] == "sent" for r in runtime.store.rows("SELECT * FROM answer_parts"))
    assert runtime.store.viewed(sid) == 0
    if same_session:
        assert runtime.store.get("answer_visit") == visit
    else:
        assert runtime.store.get("selected") == other
    assert int(runtime.store.get("panel_id")) > max(
        r["telegram_id"] for r in runtime.store.rows("SELECT * FROM answer_parts")
    )


async def test_restart_recovers_legacy_cancelled_tail(app):
    runtime, transport, engine, native = app
    sid, answer = await completed_answer(app)
    await runtime.refresh_panel()
    original = transport.make_request

    async def fail_second(bot, method, timeout=None):
        if isinstance(method, SendMessage) and " · <i>Answer 2/" in method.text:
            raise TelegramNetworkError(method=method, message="Offline")
        return await original(bot, method, timeout)

    transport.make_request = fail_second
    with pytest.raises(TelegramNetworkError):
        await runtime.deliver_answers()
    with runtime.store.db:
        runtime.store.db.execute("UPDATE answer_parts SET status='cancelled' WHERE status!='sent'")
        runtime.store.db.execute(
            "INSERT INTO answer_parts SELECT 'never-started',event_id,part,session_id,body,created,'cancelled',NULL,completion_id FROM answer_parts"
        )
        runtime.store.db.execute(
            "INSERT INTO answer_parts SELECT 'expired',event_id,part,session_id,body,0,status,telegram_id,completion_id FROM answer_parts WHERE visit!='never-started'"
        )
    await click(app, "🏠 Deck")
    transport.make_request = original
    replacement = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine)
    replacement.throttle = runtime.throttle
    replacement.pacer.interval = 0
    try:
        await replacement.deliver_answers()
        messages = answer_messages(transport)
        assert sum(" · <i>Answer 1/" in m.text for m in messages) == 1
        assert (
            "".join(CheckedHTML(m.text.split("\n\n", 1)[1]).text for m in messages)
            == CheckedHTML(render_markdown(answer)).text
        )
        assert not replacement.store.one(
            "SELECT 1 FROM answer_parts WHERE visit IN ('never-started','expired') AND status IN ('pending','sending')"
        )
    finally:
        replacement.store.close()


async def test_stop_row_tracks_work_lifecycle(app):
    runtime, transport, engine, native = app
    sid, _ = await completed_answer(app)

    def rows():
        return [[b.text for b in row] for row in panel(transport).reply_markup.inline_keyboard]

    await runtime.refresh_panel()
    idle = [["⚙️ Config", "ℹ️ Details", "📖 History"], ["⬅️ Back", "🏠 Deck"]]
    assert rows() == idle
    await command(app, "Continue")
    await settle(engine)
    await runtime.refresh_panel()
    assert rows() == [idle[0], ["⏹ Stop"], idle[1]]
    native.finish(engine.store.session(sid)["thread_id"], text="Done")
    await runtime.refresh_panel()
    assert rows() == idle
