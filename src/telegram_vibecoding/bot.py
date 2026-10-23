"""Durable private Telegram transport. Agent execution belongs to Engine."""

import asyncio
import io
import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramConflictError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from aiogram_dialog import DialogManager, ShowMode, setup_dialogs
from aiogram_dialog.api.exceptions import UnknownIntent, UnknownState
from aiogram_dialog.manager.message_manager import MessageManager

from telegram_vibecoding import BOT_NAME
from telegram_vibecoding.client import CoreClient
from telegram_vibecoding.config import Settings
from telegram_vibecoding.dialogs import Screens, back, go, make_dialog, open_screen
from telegram_vibecoding.presentation import split_text
from telegram_vibecoding.store import BotStore

log = logging.getLogger(__name__)


@asynccontextmanager
async def foreground(bg):
    # aiogram-dialog 2.6.0 skips awaiting its dispatcher task if its fg body raises.
    # Finish the context normally, then propagate the error to our durable retry loop.
    failure = None
    async with bg.fg() as manager:
        try:
            yield manager
        except BaseException as exc:
            failure = exc
    if failure is not None:
        raise failure


def authorized(body: dict, owner: int) -> bool:
    event = body.get("message") or body.get("callback_query")
    if not event or event.get("from", {}).get("id") != owner:
        return False
    message = event.get("message", event)
    chat = message.get("chat", {})
    return chat.get("type") == "private" and chat.get("id") == owner


class SQLiteFSM(BaseStorage):
    def __init__(self, store: BotStore):
        self.store = store

    def key(self, key: StorageKey, field: str) -> str:
        return "fsm:" + json.dumps(asdict(key), sort_keys=True) + ":" + field

    async def set_state(self, key: StorageKey, state=None) -> None:
        self.store.set(
            self.key(key, "state"), (state.state or "") if isinstance(state, State) else state or ""
        )

    async def get_state(self, key: StorageKey) -> str | None:
        return self.store.get(self.key(key, "state")) or None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        self.store.set(self.key(key, "data"), json.dumps(dict(data)))

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        return json.loads(self.store.get(self.key(key, "data"), "{}"))

    async def close(self) -> None:
        pass


class PanelMessages(MessageManager):
    def __init__(self, app):
        self.app = app

    async def show_message(self, bot, new_message, old_message):
        async with self.app.send_lock:
            if old_message is None or self._message_changed(new_message, old_message):
                await self.app.throttle()
            sent = await super().show_message(bot, new_message, old_message)
            self.app.store.set("panel_id", str(sent.message_id))
            return sent


class BotRuntime:
    def __init__(self, settings: Settings, bot=None, engine=None):
        self.settings = settings
        instance_file = Path("/tmp/telegram-vibecoding-instance")
        self.instance = instance_file.read_text().strip() if instance_file.exists() else uuid.uuid4().hex
        settings.prepare()
        self.store = BotStore(settings.data_dir / "bot.db")
        if self.store.get("ui_version") != "2":
            with self.store.db:
                self.store.db.execute("DELETE FROM meta WHERE key LIKE 'fsm:%'")
            self.store.set("ui_version", "2")
            self.store.set("screen", "")
            self.store.set("mode", "menu")
        self.bot = bot or Bot(settings.read_token())
        self.engine = engine or CoreClient(settings)
        self.dp = Dispatcher(storage=SQLiteFSM(self.store))
        self.dp["runtime"] = self
        self.last_send = 0.0
        self.send_lock = asyncio.Lock()
        self.ui_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self._setup()

    def _setup(self):
        controls = Router()

        @controls.message(Command("start", "menu", "sessions", "new", "stop", "help"))
        async def command(message: Message, dialog_manager: DialogManager):
            command = (message.text or "").split()[0].split("@")[0]
            if command == "/stop":
                sid = self.store.get("selected")
                if sid:
                    await self.engine.call(f"/sessions/{sid}/stop", {})
                    self.store.set("notice", "Stop requested.")
                    if dialog_manager.has_context():
                        await dialog_manager.show(ShowMode.EDIT)
                    else:
                        await open_screen(dialog_manager, Screens.deck)
            elif command == "/help":
                await open_screen(dialog_manager, Screens.deck)
            else:
                screen = {"/sessions": Screens.sessions, "/new": Screens.sessions}.get(command, Screens.deck)
                await open_screen(dialog_manager, screen)

        @controls.callback_query(F.data.startswith("open:"))
        async def open_session(callback: CallbackQuery, dialog_manager: DialogManager):
            sid = (callback.data or "").split(":", 1)[1]
            session = await self.engine.call(f"/sessions/{sid}")
            if session["archived"]:
                await callback.answer("This session is archived. Reopen it from Archived.")
                return
            self.store.set("selected", sid)
            self.store.set("location", session["cwd"])
            self.store.set("history_anchor", "")
            self.store.set("history_part", "-1")
            await open_screen(dialog_manager, Screens.chat)
            await callback.answer()

        @controls.callback_query(F.data.in_({"deck", "back"}))
        async def recover_deck(callback: CallbackQuery, dialog_manager: DialogManager):
            await open_screen(dialog_manager, Screens.deck)
            await callback.answer()

        @controls.callback_query(F.data.startswith("answer:"))
        async def answer(callback: CallbackQuery):
            _, qid, question_index, option_index = (callback.data or "").split(":")
            q = await self.question(qid)
            questions = q["payload"].get("questions", [])
            question = questions[int(question_index)]
            option = question["options"][int(option_index)]
            await self.answer_question(q, question["id"], option["label"])
            await callback.answer("Answer recorded")

        @controls.callback_query(F.data.startswith("mcp:"))
        async def answer_mcp(callback: CallbackQuery):
            _, qid, action = (callback.data or "").split(":")
            await self.engine.call(f"/questions/{qid}", {"answers": {"action": action}})
            await callback.answer("Response sent")

        self.dp.include_router(controls)
        self.dp.include_router(make_dialog())
        self.background = setup_dialogs(self.dp, message_manager=PanelMessages(self))

    async def refresh_panel(self) -> bool:
        if not self.store.get("screen"):
            return False
        async with self.ui_lock:
            await self.render_panel()
        return True

    async def initialize_panel(self):
        async with self.ui_lock:
            bg = self.background.bg(self.bot, self.settings.allowed_user_id, self.settings.allowed_user_id)
            async with foreground(bg) as manager:
                if not manager.has_context() and self.store.get("panel_id"):
                    manager.current_stack().last_message_id = int(self.store.get("panel_id"))
                await open_screen(manager, Screens.deck)

    async def render_panel(self):
        bg = self.background.bg(self.bot, self.settings.allowed_user_id, self.settings.allowed_user_id)
        async with foreground(bg) as manager:
            await manager.show(ShowMode.EDIT)

    @staticmethod
    def open_markup(sid: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Open session", callback_data="open:" + sid)],
                [
                    InlineKeyboardButton(text="🏠 Deck", callback_data="deck"),
                    InlineKeyboardButton(text="⬅️ Back", callback_data="back"),
                ],
            ]
        )

    async def throttle(self):
        await asyncio.sleep(max(0, self.last_send + 1.05 - time.monotonic()))
        self.last_send = time.monotonic()

    async def send(self, text: str, markup=None):
        if markup is None:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="🏠 Deck", callback_data="deck"),
                        InlineKeyboardButton(text="⬅️ Back", callback_data="back"),
                    ]
                ]
            )
        last = None
        async with self.send_lock:
            for part in split_text(text):
                while True:
                    await self.throttle()
                    try:
                        last = await self.bot.send_message(
                            self.settings.allowed_user_id, part, reply_markup=markup, parse_mode=None
                        )
                        break
                    except TelegramRetryAfter as exc:
                        await asyncio.sleep(exc.retry_after)
        return last

    async def question(self, qid: str) -> dict:
        # Persisted delivery metadata binds a button to its original session.
        sid = self.store.get("question_session:" + qid)
        if not sid:
            raise ValueError("Question no longer exists")
        qs = await self.engine.call(f"/sessions/{sid}/questions")
        q = next((q for q in qs if q["id"] == qid), None)
        if not q:
            raise ValueError("This question is no longer pending")
        return q

    async def answer_question(self, q: dict, key: str, value: str):
        qid = q["id"]
        answers = json.loads(self.store.get("answers:" + qid, "{}"))
        answers[key] = value
        self.store.set("answers:" + qid, json.dumps(answers))
        questions = q["payload"].get("questions", [])
        remaining = [x for x in questions if x["id"] not in answers]
        if not remaining:
            await self.engine.call(f"/questions/{qid}", {"answers": answers})

    def capture(self, update: dict):
        if not authorized(update, self.settings.allowed_user_id):
            # Still advance the transport cursor so unauthorized updates do not loop.
            self.store.set("offset", str(update["update_id"] + 1))
            return False
        sid, mode = self.store.get("selected") or None, self.store.get("mode", "menu")
        message = update.get("message", {})
        if group := message.get("media_group_id"):
            first = self.store.one(
                "SELECT session_id,mode FROM inbox WHERE json_extract(body,'$.message.media_group_id')=? ORDER BY id LIMIT 1",
                (group,),
            )
            if first:
                sid, mode = first["session_id"], first["mode"]
        body = {
            **update,
            "_relay": {
                "input_action": self.store.get("input_action"),
                "input_session": self.store.get("input_session"),
            },
        }
        return self.store.accept(update["update_id"], body, sid, mode)

    @staticmethod
    def is_control(body: dict) -> bool:
        return bool(body.get("callback_query")) or (
            body.get("message", {}).get("text", "").split(" ", 1)[0].split("@")[0]
            in {"/start", "/menu", "/sessions", "/new", "/stop", "/help"}
        )

    async def process_control(self, row: dict):
        body = json.loads(row["body"])
        if not authorized(body, self.settings.allowed_user_id):
            self.store.processed(row["id"])
            return
        async with self.ui_lock:
            self.store.set("notice", "")
            try:
                await self.dp.feed_update(
                    self.bot,
                    Update.model_validate({k: v for k, v in body.items() if k != "_relay"}),
                    runtime=self,
                )
            except (UnknownIntent, UnknownState):
                await self.send("That menu expired. Use /menu for fresh controls.")
            except (ValueError, IndexError, KeyError) as exc:
                self.store.set("notice", str(exc)[:1000])
                if self.store.get("screen"):
                    await self.render_panel()
                else:
                    await self.send(str(exc)[:1000] + "\nUse /menu to continue.")
            self.store.processed(row["id"])

    async def process_input(self, row: dict, body: dict):
        message = body.get("message", {})
        text = (message.get("text") or "").strip()
        action = body.get("_relay", {}).get("input_action", "")
        sid = body.get("_relay", {}).get("input_session")
        if not text:
            raise ValueError("Send text for this step, or use /menu to cancel.")
        if action == "rename":
            await self.engine.call(f"/sessions/{sid}/rename", {"name": text})
        elif action == "folder":
            await self.engine.call(f"/sessions/{sid}/settings", {"cwd": text})
        elif action == "path":
            s = await self.engine.call("/sessions", {"cwd": text})
            self.store.set("selected", s["id"])
        elif action == "register":
            parts = text.splitlines()
            if len(parts) != 2:
                raise ValueError("Use two lines: project name, then existing directory path.")
            await self.engine.call("/projects", {"name": parts[0], "path": parts[1]})
        elif action == "location":
            from pathlib import Path

            if not Path(text).is_absolute():
                raise ValueError("Use an absolute directory path")
            project = await self.engine.call("/projects", {"name": Path(text).name or "/", "path": text})
            self.store.set("location", project["path"])
        else:
            raise ValueError("That input step expired. Use /menu.")
        bg = self.background.bg(self.bot, self.settings.allowed_user_id, self.settings.allowed_user_id)
        async with foreground(bg) as manager:
            if action == "location":
                await back(None, None, manager)
                await go(manager, Screens.sessions)
            else:
                await back(None, None, manager)
            await manager.show(ShowMode.EDIT)

    async def download_image(self, message: dict, sid: str) -> str | None:
        image = None
        if message.get("photo"):
            image = max(
                message["photo"],
                key=lambda p: (p.get("width", 0) * p.get("height", 0), p.get("file_size", 0)),
            )
        elif message.get("document"):
            image = message["document"]
            if image.get("mime_type") not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
                raise ValueError("MVP accepts text and JPEG, PNG, WebP or GIF images. Voice comes later.")
        elif any(k in message for k in ["voice", "audio", "video", "sticker", "animation"]):
            raise ValueError("MVP accepts text and images. Voice and other attachments come later.")
        if image is None:
            return None
        if image.get("file_size", 0) > 20_000_000:
            raise ValueError("Telegram cloud downloads support files up to 20 MB.")
        folder = self.settings.data_dir / "uploads" / sid
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Stable Telegram message identity prevents duplicate downloads across retries.
        existing = [
            p
            for p in folder.glob(str(message["message_id"]) + ".*")
            if p.suffix in {".png", ".jpg", ".gif", ".webp"}
        ]
        if existing:
            return str(existing[0])
        data = io.BytesIO()
        await self.bot.download(image["file_id"], destination=data)
        raw = data.getvalue()
        if len(raw) > 20_000_000:
            raise ValueError("Image exceeds 20 MB.")
        suffix = (
            ".png"
            if raw.startswith(b"\x89PNG\r\n\x1a\n")
            else ".jpg"
            if raw.startswith(b"\xff\xd8\xff")
            else ".gif"
            if raw.startswith((b"GIF87a", b"GIF89a"))
            else ".webp"
            if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
            else None
        )
        if suffix is None:
            raise ValueError("The downloaded file is not a supported image.")
        dest = folder / (str(message["message_id"]) + suffix)
        temp = folder / (str(message["message_id"]) + ".part")
        temp.write_bytes(raw)
        temp.chmod(0o600)
        temp.replace(dest)
        return str(dest)

    async def process_messages(self, rows: list[dict]):
        row = rows[0]
        bodies = [json.loads(r["body"]) for r in rows]
        if not all(authorized(b, self.settings.allowed_user_id) for b in bodies):
            for r in rows:
                self.store.processed(r["id"])
            return
        if row["mode"] == "input":
            await self.process_input(row, bodies[0])
        elif row["mode"] != "chat" or not row["session_id"]:
            self.store.set("notice", "Open Location from Main Deck, then choose or start a session.")
            if not await self.refresh_panel():
                await self.send("Open Location from Main Deck, then choose or start a session.")
        else:
            sid = row["session_id"]
            messages = [b["message"] for b in bodies]
            text = "\n\n".join(m.get("text") or m.get("caption") or "" for m in messages)
            questions = await self.engine.call(f"/sessions/{sid}/questions")
            if questions and len(messages) == 1 and messages[0].get("text"):
                q = questions[0]
                if q["method"] != "item/tool/requestUserInput":
                    raise ValueError("Use the MCP request buttons to respond.")
                answers = json.loads(self.store.get("answers:" + q["id"], "{}"))
                next_question = next(x for x in q["payload"]["questions"] if x["id"] not in answers)
                await self.answer_question(q, next_question["id"], text)
            else:
                rid = row["request_id"] or f"telegram:{row['id']}"
                if row["payload"]:
                    payload = json.loads(row["payload"])
                else:
                    images = []
                    for message in messages:
                        if image := await self.download_image(message, sid):
                            images.append(image)
                    payload = {"request_id": rid, "session_id": sid, "text": text, "images": images}
                    self.store.prepare_request([r["id"] for r in rows], rid, payload)
                await self.engine.call("/messages", payload)
                if self.store.get("selected") == sid:
                    self.store.set("history_anchor", "")
                    self.store.set("history_part", "-1")
        for r in rows:
            self.store.processed(r["id"])

    async def inbox_loop(self):
        while not self.stop_event.is_set():
            rows = self.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY id LIMIT 100")
            used: set[int] = set()
            blocked: set[str] = set()
            for row in rows:
                if row["id"] in used or row["session_id"] in blocked:
                    continue
                body = json.loads(row["body"])
                if self.is_control(body) or row["mode"] == "input":
                    # Controls are owned by the polling loop and serialized with dialog input.
                    continue
                group = body.get("message", {}).get("media_group_id")
                batch = (
                    [
                        r
                        for r in rows
                        if group and json.loads(r["body"]).get("message", {}).get("media_group_id") == group
                    ]
                    if group
                    else [row]
                )
                if group and time.time() - max(r["created"] for r in batch) < 1:
                    blocked.add(row["session_id"])
                    continue
                try:
                    await self.process_messages(batch)
                    used.update(r["id"] for r in batch)
                except ValueError as exc:
                    self.store.set("notice", str(exc)[:1000])
                    if not await self.refresh_panel():
                        await self.send(str(exc)[:1000])
                    for r in batch:
                        self.store.processed(r["id"])
                except Exception as exc:
                    log.warning("Inbox retained for retry: %s", type(exc).__name__)
                    blocked.add(row["session_id"])
            await asyncio.sleep(0.3)

    def queue_update(self, event: dict):
        if event["kind"] == "question":
            qid = event["payload"]["question_id"]
            self.store.set("question_session:" + qid, event["session_id"])
        # Normal delivery edits the panel. Keep a readable body for older bot releases on rollback.
        payload = event["payload"]
        text = payload.get("text") or payload.get("status") or json.dumps(payload, ensure_ascii=False)
        markup = (
            self.open_markup(event["session_id"]).model_dump(exclude_none=True)
            if event.get("session_id")
            else None
        )
        self.store.queue_event(event["id"], [text or "Session updated."], markup)

    async def events_loop(self):
        while not self.stop_event.is_set():
            try:
                events = await self.engine.call("/events?after=" + self.store.get("event_cursor", "0"))
                for event in events:
                    if event["kind"] in {"user", "message", "error", "completed", "question"}:
                        self.queue_update(event)
                    else:
                        self.store.queue_event(event["id"], [], None)
            except Exception as exc:
                log.warning("Event poll will retry: %s", type(exc).__name__)
            await asyncio.sleep(0.7)

    async def deliver_pending(self):
        rows = self.store.rows("SELECT id FROM outbox WHERE status='pending' ORDER BY id LIMIT 100")
        if not rows or not await self.refresh_panel():
            return False
        # Acknowledge only the captured batch: newer events remain pending.
        with self.store.db:
            self.store.db.executemany(
                "UPDATE outbox SET status='sent',telegram_id=? WHERE id=?",
                [(self.store.get("panel_id"), row["id"]) for row in rows],
            )
        return True

    async def delivery_loop(self):
        while not self.stop_event.is_set():
            try:
                await self.deliver_pending()
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                log.warning("Panel update retained: %s", type(exc).__name__)
                await asyncio.sleep(3)
            await asyncio.sleep(0.3)

    async def preview_loop(self):
        while not self.stop_event.is_set():
            try:
                live = await self.engine.call("/live")
                if self.store.get("mode") == "chat" and self.store.get("selected") in live:
                    await self.refresh_panel()
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                log.warning("Panel preview deferred: %s", type(exc).__name__)
            await asyncio.sleep(1.5)

    async def poll(self):
        me = await self.bot.get_me()
        if (
            self.settings.bot_username
            and (me.username or "").lower() != self.settings.bot_username.lstrip("@").lower()
        ):
            raise RuntimeError("Configured token belongs to another Telegram bot")
        webhook = await self.bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError(
                "This bot already has a webhook. Resolve the existing consumer before polling."
            )
        core_health = await self.engine.call("/health")
        if core_health.get("protocol_version", 1) != 1:
            raise RuntimeError("Unsupported Vibecoding Core API version")
        for language in ("", "en", "ru"):
            current_name = await self.bot.get_my_name(language_code=language)
            if current_name.name != BOT_NAME:
                await self.bot.set_my_name(name=BOT_NAME, language_code=language)
        commands = [
            BotCommand(command="start", description="Open Main Deck"),
            BotCommand(command="menu", description="Open Main Deck"),
            BotCommand(command="stop", description="Stop the selected task"),
        ]
        for language in ("", "en", "ru"):
            await self.bot.set_my_commands(commands, language_code=language)
            try:
                await self.bot.set_my_commands(
                    commands,
                    scope=BotCommandScopeChat(chat_id=self.settings.allowed_user_id),
                    language_code=language,
                )
            except TelegramBadRequest as exc:
                if "chat not found" not in str(exc).lower():
                    raise
        if not self.store.get("screen"):
            try:
                await self.initialize_panel()
            except TelegramForbiddenError:
                # A fresh bot cannot initiate a chat before its owner presses Start.
                log.info("Waiting for the owner to start the private chat")
        self.store.set("bot_pid", str(os.getpid()))
        self.store.set("bot_instance", self.instance)
        log.info("Bot connected: @%s; owner=%s", me.username, self.settings.allowed_user_id)
        while not self.stop_event.is_set():
            try:
                # UI/input operations must finish before a newer selection can overtake them.
                for pending_row in self.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY id"):
                    if self.is_control(json.loads(pending_row["body"])) or pending_row["mode"] == "input":
                        await self.process_navigation(pending_row)
                updates = await self.bot.get_updates(
                    offset=int(self.store.get("offset", "0")),
                    timeout=25,
                    allowed_updates=["message", "callback_query"],
                    request_timeout=35,
                )
                for update in updates:
                    body = update.model_dump(mode="json", exclude_none=True, by_alias=True)
                    if self.capture(body):
                        current_row = self.store.one("SELECT * FROM inbox WHERE id=?", (update.update_id,))
                        if current_row and (self.is_control(body) or current_row["mode"] == "input"):
                            await self.process_navigation(current_row)
            except TelegramConflictError:
                raise RuntimeError(
                    "Another process is polling this dev bot. Stop that consumer before continuing."
                ) from None
            except TelegramNetworkError:
                log.warning("Telegram unavailable; retrying without discarding updates")
                await asyncio.sleep(3)
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after)
            except Exception as exc:
                log.warning("Polling retained state: %s", type(exc).__name__)
                await asyncio.sleep(3)

    async def process_navigation(self, row: dict):
        if self.is_control(json.loads(row["body"])):
            await self.process_control(row)
        else:
            async with self.ui_lock:
                try:
                    await self.process_messages([row])
                except ValueError as exc:
                    self.store.set("notice", str(exc)[:1000])
                    if self.store.get("screen"):
                        await self.render_panel()
                    else:
                        await self.send(str(exc)[:1000] + "\nUse /menu to continue.")
                    self.store.processed(row["id"])

    async def run(self):
        import fcntl

        lock = (self.settings.runtime_dir / "bot.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            raise RuntimeError("Another bot already owns this runtime directory") from None
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)
        tasks = [
            asyncio.create_task(fn())
            for fn in [self.poll, self.inbox_loop, self.events_loop, self.delivery_loop, self.preview_loop]
        ]
        stopped = asyncio.create_task(self.stop_event.wait())
        try:
            done, _ = await asyncio.wait([*tasks, stopped], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopped:
                    await task
        finally:
            for task in [*tasks, stopped]:
                task.cancel()
            await asyncio.gather(*tasks, stopped, return_exceptions=True)
            await self.engine.close()
            await self.bot.session.close()
            self.store.close()
            lock.close()


async def run(settings: Settings):
    await BotRuntime(settings).run()
