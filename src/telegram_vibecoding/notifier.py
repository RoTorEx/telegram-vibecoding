"""Notification-only Telegram process. Incoming content can never become agent input."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import signal
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update

from telegram_vibecoding import __version__
from telegram_vibecoding.client import CoreClient, ReadOnlyCoreClient
from telegram_vibecoding.config import Settings
from telegram_vibecoding.pacing import ChatPacer
from telegram_vibecoding.store import BotStore

log = logging.getLogger(__name__)


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "unavailable"
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return (f"{hours}h " if hours else "") + (f"{minutes}m " if minutes or hours else "") + f"{seconds}s"


class Notifier:
    def __init__(self, settings: Settings, bot=None, engine=None):
        self.settings = settings
        settings.validate_web_url()
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = BotStore(settings.data_dir / "bot.db")
        self.store.db.executescript("""
            CREATE TABLE IF NOT EXISTS notifier_notices(
                event_id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, body TEXT NOT NULL,
                created REAL NOT NULL, telegram_id INTEGER);
        """)
        if not self.store.get("notifier_since"):
            self.store.set("notifier_since", str(time.time()))
        self.bot = bot or Bot(settings.read_token())
        if bot is None:
            self.bot.session.middleware.register(ChatPacer(self.store, settings.allowed_user_id))
        self.engine = ReadOnlyCoreClient(engine or CoreClient(settings))
        self.sessions: list[dict] = []
        self.live: dict = {}
        self.health: dict = {}
        self.stop = asyncio.Event()
        self.send_lock = asyncio.Lock()
        instance_file = Path("/tmp/telegram-vibecoding-instance")
        self.instance = instance_file.read_text().strip() if instance_file.exists() else uuid.uuid4().hex

    def markup(self, sid: str | None = None) -> InlineKeyboardMarkup:
        url = self.settings.web_url.rstrip("/") + ("/#" + quote(sid, safe="") if sid else "/")
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Open web chat" if sid else "Open workspace", url=url)]
            ]
        )

    async def send(self, text: str, sid: str | None = None):
        async with self.send_lock:
            return await self.bot.send_message(
                self.settings.allowed_user_id,
                text,
                parse_mode=None,
                reply_markup=self.markup(sid),
                disable_web_page_preview=True,
                disable_notification=False,
            )

    async def snapshot(self):
        self.health = await self.engine.call("/health")
        self.sessions = await self.engine.call("/sessions")
        self.live = await self.engine.call("/live")

    def overview(self) -> str:
        active = [
            s
            for s in self.sessions
            if s.get("turn_id") or s.get("status") in {"working", "connecting", "transcribing"}
        ]
        waiting = sum(bool(s.get("pending_questions")) for s in self.sessions)
        inputs = int(self.store.get("notifier_inputs", "0"))
        outcomes = int(self.store.get("notifier_outcomes", "0"))
        text = (
            f"Remote Vibecoding Notifier · {self.settings.host_id}\n"
            f"Notification-only · {len(active)} active · {waiting} waiting for input\n"
            f"Observed since notifier activation: {inputs} inputs · {outcomes} outcomes\n"
            f"Completed work: {duration(float(self.store.get('notifier_seconds', '0')))}\n"
            "Requests and all session controls are available only in the private web workspace."
        )
        for session in sorted(self.sessions, key=lambda s: s.get("last_interaction", 0), reverse=True)[:8]:
            sid = session["id"]
            started = self.live.get(sid, {}).get("started")
            age = " · " + duration(time.time() - started) if started else ""
            text += (
                f"\n\n{'❓' if session.get('pending_questions') else '⚙️' if session in active else '💬'} "
                f"{session['name'][:80]} · {session.get('status', 'unknown')}{age}\n"
                f"{session['cwd'][:160]}\n"
                f"{session.get('model') or 'Auto'} · {session.get('effort') or 'default effort'} · "
                f"{session.get('collaboration_mode') or 'default'}"
            )
        return text[:3900]

    async def handle(self, update: Update):
        message = update.message
        callback = update.callback_query
        if callback:
            origin = callback.message
            if (
                callback.from_user.id != self.settings.allowed_user_id
                or not origin
                or origin.chat.id != self.settings.allowed_user_id
                or origin.chat.type != "private"
            ):
                return
            try:
                await self.bot.answer_callback_query(
                    callback.id,
                    text="Telegram is notification-only. Use the private web workspace.",
                    show_alert=True,
                )
            except TelegramBadRequest:
                pass  # Expired legacy buttons must not block the polling cursor.
            return
        if (
            not message
            or not message.from_user
            or message.from_user.id != self.settings.allowed_user_id
            or message.chat.id != self.settings.allowed_user_id
            or message.chat.type != "private"
        ):
            return
        command = (message.text or "").split(maxsplit=1)[0].split("@", 1)[0].lower() if message.text else ""
        if command in {"/status", "/stats"}:
            await self.snapshot()
            await self.send(self.overview())
        else:
            await self.send(
                "Remote Vibecoding Notifier\n"
                "This bot only sends notifications and read-only activity statistics (/status, /stats). "
                "Text, commands, files, voice and old buttons cannot start, steer or control Codex. "
                "Open the private web workspace to work with agents."
            )

    def record(self, key: str, value: str):
        self.store.db.execute(
            "INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def capture(self, event: dict):
        sid = event.get("session_id")
        if not sid:
            return
        start = float(self.store.get("notifier_since"))
        created = float(event.get("created", 0))
        key = "notifier_work:" + sid
        if event["id"] == 1:
            self.record("notifier_history_complete", "true")
        work = json.loads(
            self.store.get(
                key,
                json.dumps(
                    {
                        "started": None,
                        "inputs": 0,
                        "known": self.store.get("notifier_history_complete") == "true",
                    }
                ),
            )
        )
        if event["kind"] == "user":
            if work["started"] is None:
                work["started"] = created
            work["inputs"] += 1
            if created >= start:
                self.record("notifier_inputs", str(int(self.store.get("notifier_inputs", "0")) + 1))
            self.record(key, json.dumps(work))
            return
        if event["kind"] not in {"completed", "question"}:
            return
        seconds = (
            max(0, created - work["started"])
            if work["started"] is not None and work.get("known", False)
            else None
        )
        session = next((s for s in self.sessions if s["id"] == sid), {})
        if created >= start:
            payload = event.get("payload", {})
            outcome = payload.get("status", "finished") if event["kind"] == "completed" else "input required"
            icon = "❓" if event["kind"] == "question" else "✅" if outcome == "completed" else "⚠️"
            text = (
                f"{icon} {outcome}\n{session.get('name', sid)[:120]}\n"
                f"📍 {self.settings.host_id} · {session.get('cwd', 'path unavailable')[:250]}\n"
                f"🤖 {session.get('model') or 'Auto'} · {session.get('effort') or 'default effort'} · "
                f"{session.get('collaboration_mode') or 'default'}\n"
                f"⏱ {duration(seconds)} · {work['inputs']} retained inputs in this run"
            )
            self.store.db.execute(
                "INSERT OR IGNORE INTO notifier_notices(event_id,session_id,body,created) VALUES(?,?,?,?)",
                (event["id"], sid, text, created),
            )
            if event["kind"] == "completed":
                self.record("notifier_outcomes", str(int(self.store.get("notifier_outcomes", "0")) + 1))
                if seconds is not None:
                    self.record(
                        "notifier_seconds", str(float(self.store.get("notifier_seconds", "0")) + seconds)
                    )
        if event["kind"] == "completed":
            self.record(key, '{"started":null,"inputs":0,"known":true}')

    async def collect(self):
        # Core v1 pages at 100 events. Drain a finite backlog without delaying notices indefinitely.
        for _ in range(10):
            events = await self.engine.call("/events?after=" + self.store.get("notifier_cursor", "0"))
            for event in events:
                # Capture and cursor commit together; a crash cannot count/queue an event twice.
                with self.store.db:
                    self.capture(event)
                    self.record("notifier_cursor", str(event["id"]))
            if len(events) < 100:
                break

    async def deliver(self):
        for row in self.store.rows(
            "SELECT * FROM notifier_notices WHERE telegram_id IS NULL ORDER BY event_id LIMIT 10"
        ):
            sent = await self.send(row["body"], row["session_id"])
            with self.store.db:
                self.store.db.execute(
                    "UPDATE notifier_notices SET telegram_id=? WHERE event_id=?",
                    (sent.message_id, row["event_id"]),
                )

    async def notifications(self):
        while not self.stop.is_set():
            try:
                await self.snapshot()
                if self.store.get("notifier_boot") != self.instance:
                    now = datetime.now(ZoneInfo("Europe/Warsaw"))
                    offset = now.strftime("%z")
                    stamp = f"{now:%Y-%m-%d %H:%M:%S} Warsaw ({now:%Z}, UTC{offset[:3]}:{offset[3:]})"
                    await self.send(
                        f"Remote Vibecoding Notifier {__version__} online\nCore {self.health.get('version', 'unknown')} · {self.settings.host_id}\n{stamp}\nNotification-only; agent access is available in the private web workspace."
                    )
                    self.store.set("notifier_boot", self.instance)
                await self.collect()
                await self.deliver()
                # Keep only seven days of metadata notices; cursor/counters have no message content.
                with self.store.db:
                    self.store.db.execute(
                        "DELETE FROM notifier_notices WHERE created<?",
                        (time.time() - 604800,),
                    )
            except Exception as error:
                log.warning("Notifier delivery will retry: %s", type(error).__name__)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=3)
            except TimeoutError:
                pass

    async def poll(self):
        while not self.stop.is_set():
            try:
                updates = await self.bot.get_updates(
                    offset=int(self.store.get("notifier_offset", "0")),
                    timeout=25,
                    request_timeout=35,
                    allowed_updates=["message", "callback_query"],
                )
                for update in updates:
                    await self.handle(update)
                    self.store.set("notifier_offset", str(update.update_id + 1))
                self.store.set("poll_heartbeat", str(time.time()))
            except Exception as error:
                log.warning("Notifier polling will retry: %s", type(error).__name__)
                await asyncio.sleep(3)

    async def run(self):
        lock = (self.settings.data_dir / "notifier.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Another notifier owns this state directory") from None
        self.store.set("bot_pid", str(os.getpid()))
        self.store.set("bot_instance", self.instance)
        self.store.set("poll_heartbeat", str(time.time()))
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, self.stop.set)
        tasks: list[asyncio.Task[Any]] = []
        try:
            identity = await self.bot.get_me()
            if self.settings.bot_username and identity.username != self.settings.bot_username:
                raise ValueError("Notifier token belongs to an unexpected bot")
            await self.bot.set_my_commands(
                [
                    BotCommand(command="status", description="Read-only activity"),
                    BotCommand(command="stats", description="Observed work statistics"),
                ]
            )
            tasks = [
                asyncio.create_task(self.poll()),
                asyncio.create_task(self.notifications()),
                asyncio.create_task(self.stop.wait()),
            ]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.engine.close()
            await self.bot.session.close()
            self.store.close()
            lock.close()


async def run(settings: Settings):
    await Notifier(settings).run()
