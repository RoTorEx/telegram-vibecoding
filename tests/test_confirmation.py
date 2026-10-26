import hmac
import json
import time
from dataclasses import replace
from urllib.parse import urlencode

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from conftest import settle
from test_bot import app as app
from test_bot import command, update

from telegram_vibecoding.bot import BotRuntime
from telegram_vibecoding.confirmation import (
    ConfirmationRequired,
    Confirmations,
    GuardedClient,
    application,
    canonical,
    digest,
    validate_init_data,
)
from telegram_vibecoding.store import BotStore


def signed_data(token="123456:test", owner=42, timestamp=None, **extra):
    values = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": canonical({"id": owner}),
        **extra,
    }
    key = hmac.new(b"WebAppData", token.encode(), "sha256").digest()
    values["hash"] = hmac.new(
        key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), "sha256"
    ).hexdigest()
    return urlencode(values)


def enroll(auth, device="phone-A"):
    return auth.enroll(auth.enrollment(), device)


def approve(auth, action, secret, device="phone-A", decision="approve"):
    proof = auth.proof(action["id"], device, decision=decision)
    signature = hmac.new(bytes.fromhex(secret), proof["challenge"].encode(), "sha256").hexdigest()
    return auth.confirm(proof["proof"], signature), proof, signature


def protect(runtime):
    runtime.settings = replace(
        runtime.settings, confirmation_required=True, confirmation_url="https://bot.example/confirm"
    )
    runtime.confirmations = Confirmations(runtime.store)
    runtime.engine = GuardedClient(runtime.engine, runtime.confirmations)
    return runtime.confirmations


def test_init_data_requires_signature_freshness_owner_and_unique_fields():
    raw = signed_data()
    validate_init_data(raw, "123456:test", 42)
    for bad in (
        raw.replace("auth_date=", "auth_date=1"),
        signed_data(owner=7),
        signed_data(timestamp=int(time.time()) - 301),
        signed_data(timestamp=int(time.time()) + 31),
        raw + "&user=%7B%22id%22%3A42%7D",
    ):
        with pytest.raises(ValueError):
            validate_init_data(bad, "123456:test", 42)


def test_enrollment_is_single_use_and_cannot_replace_trusted_phone(tmp_path):
    store = BotStore(tmp_path / "bot.db")
    auth = Confirmations(store)
    code = auth.enrollment()
    with pytest.raises(ValueError):
        auth.enroll("Telegram owner is not an enrollment code", "attacker")
    key = auth.enroll(code, "phone-A")
    assert len(key) == 64
    with pytest.raises(ValueError):
        auth.enroll(code, "attacker")
    with pytest.raises(ValueError):
        auth.enroll(auth.enrollment(), "phone-A")
    store.close()


def test_proofs_are_bound_to_device_request_and_decision_and_cannot_replay(tmp_path):
    store = BotStore(tmp_path / "bot.db")
    auth = Confirmations(store)
    key = enroll(auth)
    first = auth.stage("one", "operation", {"path": "/sessions/A/stop", "body": {}})
    second = auth.stage("two", "operation", {"path": "/sessions/B/stop", "body": {}})
    with pytest.raises(ValueError):
        auth.proof(first["id"], "attacker")
    proof = auth.proof(first["id"], "phone-A")
    with pytest.raises(ValueError):
        auth.confirm(proof["proof"], "true")
    signature = hmac.new(bytes.fromhex(key), proof["challenge"].encode(), "sha256").hexdigest()
    other = auth.proof(second["id"], "phone-A")
    with pytest.raises(ValueError):
        auth.confirm(other["proof"], signature)
    assert auth.confirm(proof["proof"], signature) == "approved"
    with pytest.raises(ValueError):
        auth.confirm(proof["proof"], signature)
    assert auth.action(second["id"])["status"] == "pending"
    store.close()


def test_changed_expired_and_revoked_requests_fail_closed(tmp_path):
    store = BotStore(tmp_path / "bot.db")
    auth = Confirmations(store)
    key = enroll(auth)
    action = auth.stage("one", "operation", {"text": "original"})
    proof = auth.proof(action["id"], "phone-A")
    signature = hmac.new(bytes.fromhex(key), proof["challenge"].encode(), "sha256").hexdigest()
    changed = {"text": "changed"}
    with store.db:
        store.db.execute(
            "UPDATE auth_actions SET payload=?,digest=? WHERE id=?",
            (canonical(changed), digest(changed), action["id"]),
        )
    with pytest.raises(ValueError):
        auth.confirm(proof["proof"], signature)
    expired = auth.stage("expired", "operation", {})
    with store.db:
        store.db.execute("UPDATE auth_actions SET expires=0 WHERE id=?", (expired["id"],))
    with pytest.raises(ValueError):
        auth.proof(expired["id"], "phone-A")
    active = auth.stage("active", "operation", {})
    approve(auth, active, key)
    auth.revoke("phone-A")
    assert auth.action(active["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        auth.proof(auth.stage("next", "operation", {})["id"], "phone-A")
    store.close()


async def test_text_waits_for_proof_preserves_target_and_is_not_account_unlock(app, host):
    runtime, _, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    a = engine.store.create_session(str(host[0].data_dir.parent), "A", "medium")
    b = engine.store.create_session(str(host[0].data_dir.parent), "B", "medium")
    runtime.store.set("selected", a["id"])
    runtime.store.set("mode", "chat")
    runtime.capture(update(400, "approved text"))
    rows = runtime.store.rows("SELECT * FROM inbox WHERE id=400")
    await runtime.process_messages(rows)
    assert not native.calls
    action = runtime.store.one("SELECT * FROM auth_actions")
    assert runtime.store.one("SELECT status FROM inbox WHERE id=400")["status"] == "auth_pending"
    runtime.store.set("selected", b["id"])
    approve(auth, action, key)
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=400"))
    await settle(engine)
    assert engine.store.request("telegram:400")["session_id"] == a["id"]
    runtime.capture(update(401, "unconfirmed text"))
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=401"))
    assert not engine.store.request("telegram:401")
    assert engine.store.session(b["id"])["thread_id"] is None


async def test_new_session_is_not_created_before_confirmation_and_rejection_survives_restart(app):
    runtime, _, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    body = update(410, "start a project")
    runtime.capture(body)
    with runtime.store.db:
        saved = json.loads(runtime.store.one("SELECT body FROM inbox WHERE id=410")["body"])
        saved["_relay"]["new_session_path"] = str(runtime.settings.data_dir.parent)
        saved["_relay"]["new_session_key"] = "telegram:new:410"
        runtime.store.db.execute("UPDATE inbox SET body=? WHERE id=410", (json.dumps(saved),))
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=410"))
    assert engine.store.sessions() == []
    action = runtime.store.one("SELECT * FROM auth_actions")
    approve(auth, action, key, decision="cancel")
    reopened = Confirmations(runtime.store)
    assert reopened.action(action["id"])["status"] == "cancelled"
    assert runtime.store.one("SELECT status FROM inbox WHERE id=410")["status"] == "done"
    assert not native.calls


async def test_controls_and_partial_question_answers_are_guarded(app, host):
    runtime, _, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    session = engine.store.create_session(str(host[0].data_dir.parent), "A", "medium")
    runtime.store.set("selected", session["id"])
    await command(app, "/stop")
    action = runtime.store.one("SELECT * FROM auth_actions WHERE kind='operation'")
    assert action and json.loads(action["payload"])["path"] == f"/sessions/{session['id']}/stop"
    assert not native.calls
    approve(auth, action, key)
    await runtime.confirmation_tick()
    assert auth.action(action["id"])["status"] == "done"
    q = {"id": "q1", "payload": {"questions": [{"id": "x"}, {"id": "y"}]}}
    marker = auth.source.set("control:question")
    try:
        with pytest.raises(ConfirmationRequired):
            await runtime.answer_question(q, "x", "Yes")
    finally:
        auth.source.reset(marker)
    assert runtime.store.get("answers:q1") == ""


async def test_http_requires_real_telegram_owner_origin_and_device_proof(app, tmp_path):
    runtime, _, _, _ = app
    auth = protect(runtime)
    token = "123456:test"
    runtime.settings.token_file.write_text(token)
    runtime.settings.token_file.chmod(0o600)
    action = auth.stage("request", "operation", {"path": "/sessions/A/stop", "body": {}})
    server = TestServer(application(runtime))
    await server.start_server()
    try:
        async with ClientSession() as client:
            endpoint = server.make_url("/confirm/api/view")
            headers = {"Origin": "https://bot.example", "X-Telegram-Init-Data": signed_data(token)}
            for bad in (
                {},
                {**headers, "Origin": "https://attacker.example"},
                {**headers, "X-Telegram-Init-Data": signed_data(token, owner=7)},
            ):
                async with client.post(endpoint, json={"request": action["id"]}, headers=bad) as response:
                    assert response.status == 403
            async with client.post(endpoint, json={"request": action["id"]}, headers=headers) as response:
                assert response.status == 200
                assert (await response.json())["digest"] == action["digest"]
                assert response.headers["Cache-Control"] == "no-store"
            async with client.post(
                server.make_url("/confirm/api/proof"),
                json={"request": action["id"], "device": "attacker"},
                headers=headers,
            ) as response:
                assert response.status == 403
            async with client.get(server.make_url("/confirm/")) as response:
                assert response.status == 200
                assert "telegram-web-app.js" in await response.text()
                assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    finally:
        await server.close()


async def test_guard_fails_closed_without_captured_request(app):
    runtime, _, _, _ = app
    protect(runtime)
    with pytest.raises(ValueError, match="captured user request"):
        await runtime.engine.call("/sessions", {"cwd": "/tmp"})


async def test_pending_input_survives_runtime_restart_and_cannot_change_body(app, host):
    runtime, transport, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    target = engine.store.create_session(str(host[0].data_dir.parent), "Restart", "medium")
    runtime.store.set("selected", target["id"])
    runtime.store.set("mode", "chat")
    runtime.capture(update(450, "retain this exact input"))
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=450"))
    action = runtime.store.one("SELECT * FROM auth_actions")
    restarted = BotRuntime(runtime.settings, bot=runtime.bot, engine=runtime.engine.client)
    restarted.pacer.interval = 0
    restarted.throttle = runtime.throttle
    try:
        assert restarted.store.one("SELECT status FROM inbox WHERE id=450")["status"] == "auth_pending"
        assert not native.calls
        approve(restarted.confirmations, action, key)
        changed = restarted.store.rows("SELECT * FROM inbox WHERE id=450")
        body = json.loads(changed[0]["body"])
        body["message"]["text"] = "unapproved replacement"
        changed[0]["body"] = json.dumps(body)
        with pytest.raises(ValueError, match="changed"):
            await restarted.process_messages(changed)
        assert not native.calls
        await restarted.process_messages(restarted.store.rows("SELECT * FROM inbox WHERE id=450"))
        await settle(engine)
        assert engine.store.request("telegram:450")["session_id"] == target["id"]
    finally:
        restarted.store.close()


async def test_media_is_not_downloaded_or_dispatched_before_approval(app, host):
    runtime, _, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    target = engine.store.create_session(str(host[0].data_dir.parent), "Media", "medium")
    runtime.store.set("selected", target["id"])
    runtime.store.set("mode", "chat")
    downloads = []

    async def image(message, sid):
        downloads.append(message["message_id"])
        path = runtime.settings.data_dir / "uploads" / "picture.png"
        path.write_bytes(b"fixture")
        return str(path)

    runtime.download_image = image
    runtime.capture(
        update(460, text="", photo=[{"file_id": "photo", "file_unique_id": "photo", "width": 1, "height": 1}])
    )
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=460"))
    assert downloads == [] and not native.calls
    action = runtime.store.one("SELECT * FROM auth_actions")
    approve(auth, action, key)
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=460"))
    await settle(engine)
    assert downloads == [460]
    assert any(
        x["type"] == "localImage"
        for method, params in native.calls
        if method == "turn/start"
        for x in params["input"]
    )
    native.calls.clear()
    runtime.capture(
        update(461, text="", voice={"file_id": "voice", "file_unique_id": "voice", "duration": 4})
    )
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=461"))
    rejected = runtime.store.one("SELECT * FROM auth_actions WHERE source='input:461'")
    approve(auth, rejected, key, decision="cancel")
    assert not native.calls and not engine.store.request("telegram:461")


async def test_expired_input_and_late_album_parts_never_gain_authority(app, host):
    runtime, _, engine, native = app
    auth = protect(runtime)
    key = enroll(auth)
    target = engine.store.create_session(str(host[0].data_dir.parent), "Album", "medium")
    runtime.store.set("selected", target["id"])
    runtime.store.set("mode", "chat")
    for uid in (470, 471):
        runtime.capture(
            update(
                uid,
                text="",
                media_group_id="album",
                photo=[{"file_id": str(uid), "file_unique_id": str(uid), "width": 1, "height": 1}],
            )
        )
    await runtime.process_messages(
        runtime.store.rows("SELECT * FROM inbox WHERE id IN (470,471) ORDER BY id")
    )
    action = runtime.store.one("SELECT * FROM auth_actions")
    approve(auth, action, key)
    runtime.capture(
        update(
            472,
            text="",
            media_group_id="album",
            photo=[{"file_id": "late", "file_unique_id": "late", "width": 1, "height": 1}],
        )
    )
    with pytest.raises(ValueError, match="media group changed"):
        await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox ORDER BY id"))
    assert not native.calls
    runtime.capture(update(473, "expire me"))
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=473"))
    with runtime.store.db:
        runtime.store.db.execute("UPDATE auth_actions SET expires=0 WHERE source='input:473'")
    auth.expire()
    assert runtime.store.one("SELECT status FROM inbox WHERE id=473")["status"] == "done"
    assert not engine.store.request("telegram:473")


async def test_confirmed_new_session_ignores_previous_selection(app, host):
    runtime, _, engine, _ = app
    auth = protect(runtime)
    key = enroll(auth)
    old_path = host[0].data_dir.parent / "old"
    old_path.mkdir()
    previous = engine.store.create_session(str(old_path), "Previous", "medium")
    runtime.store.set("selected", previous["id"])
    runtime.store.set("mode", "menu")
    runtime.capture(update(480, "work in the new directory"))
    body = json.loads(runtime.store.one("SELECT body FROM inbox WHERE id=480")["body"])
    body["_relay"].update(new_session_path=str(host[0].data_dir.parent), new_session_key="telegram:new:480")
    with runtime.store.db:
        runtime.store.db.execute("UPDATE inbox SET body=? WHERE id=480", (json.dumps(body),))
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=480"))
    action = runtime.store.one("SELECT * FROM auth_actions")
    assert json.loads(action["payload"])["context"]["target"]["session_id"] is None
    assert len(engine.store.sessions()) == 1
    approve(auth, action, key)
    await runtime.process_messages(runtime.store.rows("SELECT * FROM inbox WHERE id=480"))
    await settle(engine)
    target = engine.store.request("telegram:480")["session_id"]
    assert target != previous["id"]
    assert engine.store.session(target)["cwd"] == str(host[0].data_dir.parent)
    assert engine.store.session(previous["id"])["thread_id"] is None


async def test_stale_question_choices_cannot_overwrite_newer_answers(app):
    runtime, _, _, _ = app
    auth = protect(runtime)
    q = {"id": "q1", "payload": {"questions": [{"id": "x"}, {"id": "y"}]}}
    runtime.store.set("answers:q1", json.dumps({"x": "newer choice"}))
    marker = auth.grant.set(True)
    try:
        with pytest.raises(ValueError, match="answers changed"):
            await runtime.answer_question(q, "y", "yes", base_answers={"x": "old choice"})
    finally:
        auth.grant.reset(marker)
    assert json.loads(runtime.store.get("answers:q1")) == {"x": "newer choice"}
