"""One editable panel: Main Deck → location → session, with consistent exits."""

import json
from html import escape
from pathlib import Path
from typing import Any

from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ContentType
from aiogram_dialog import Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.api.entities import MediaAttachment
from aiogram_dialog.widgets.kbd import Button, Group, Row, Select
from aiogram_dialog.widgets.link_preview import LinkPreview
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Const, Format

from telegram_vibecoding import __version__
from telegram_vibecoding.book import chapter_pages
from telegram_vibecoding.markdown import html_length, split_html
from telegram_vibecoding.presentation import (
    activity_label,
    conversation_parts,
    curated_models,
    quota_summary,
    session_label,
    timestamp,
)


class Screens(StatesGroup):
    deck = State()
    locations = State()
    journal = State()
    sessions = State()
    chat = State()
    history = State()
    config = State()
    details = State()
    settings = State()
    terminal = State()
    limits = State()
    images = State()
    edit_sessions = State()
    edit_session = State()
    input = State()
    models = State()


def runtime(manager: DialogManager):
    return manager.middleware_data["runtime"]


async def location(app) -> dict:
    projects = await app.engine.call("/projects")
    home = next((p for p in projects if p["name"] == "Home"), projects[0])
    selected = next((p for p in projects if p["path"] == app.store.get("location")), home)
    app.store.set("location", selected["path"])
    return selected


def numbered(app, screen, entries, describe, *, size=8) -> tuple[str, list, bool, bool]:
    key = "page:" + screen.state
    page = max(0, min(int(app.store.get(key, "0")), max(0, (len(entries) - 1) // size)))
    app.store.set(key, str(page))
    visible = entries[page * size : page * size + size]
    text = "\n\n".join(f"{i}. {describe(p)}" for i, p in enumerate(visible, 1))
    if len(entries) > size:
        text += f"\n\nPage {page + 1}/{(len(entries) + size - 1) // size}"
    rows = [(str(i), p["id"]) for i, p in enumerate(visible, 1)]
    return text, rows, page > 0, (page + 1) * size < len(entries)


def working(session: dict) -> bool:
    return bool(
        session.get("turn_id") or session.get("pending_questions") or session.get("pending_requests")
    ) or session["status"] in {
        "connecting",
        "working",
        "transcribing",
        "waiting",
    }


def unread(app, sessions: list[dict]) -> list[dict]:
    return sorted(
        [
            s
            for s in sessions
            if not working(s) and (s.get("last_completed_event") or 0) > app.store.viewed(s["id"])
        ],
        key=lambda s: s["last_completed_event"],
        reverse=True,
    )


async def data(dialog_manager: DialogManager, **_) -> dict:
    app = runtime(dialog_manager)
    screen = dialog_manager.current_context().state
    app.store.set("screen", screen.state)
    sid = app.store.get("selected")
    session = await app.engine.call(f"/sessions/{sid}") if sid else None
    place = await location(app)
    v: dict[str, Any] = {
        "text": "",
        "rows": [],
        "journal_label": "📒 Journal",
        "has_session_context": bool(session)
        and (
            screen in {Screens.chat, Screens.history, Screens.config, Screens.details, Screens.models}
            or (screen == Screens.input and app.store.get("input_action") in {"rename", "folder"})
        ),
        "previous_page": False,
        "next_page": False,
        "can_stop": bool(
            session and (session["turn_id"] or session["status"] in {"connecting", "transcribing"})
        ),
        "history_previous": False,
        "history_next": False,
        "exchange_previous": False,
        "exchange_next": False,
        "question_rows": [],
        "has_images": False,
        "mcp_question": False,
        "media": None,
    }
    if screen == Screens.deck:
        sessions = await app.engine.call("/sessions")
        active = sum(
            working(s) and not s.get("pending_questions") and s["status"] != "waiting" for s in sessions
        )
        pending = len(unread(app, sessions))
        v["journal_label"] = f"📒 Journal ({pending})"
        waiting = sum(bool(s.get("pending_questions")) or s["status"] == "waiting" for s in sessions)
        try:
            limits_data = await app.engine.call("/limits")
        except (ConnectionError, ValueError):
            limits_data = {"available": False}
        v["text"] = (
            f"<b>🏠 Main Deck</b>\n\n⏳ Working: <b>{active}</b> · ❔ Questions: <b>{waiting}</b>"
            f"\n📩 Unread: <b>{pending}</b>\n\n<b>⏱ Account limits</b>\n"
            + quota_summary(limits_data, compact=True)
        )
    elif screen in {Screens.journal, Screens.sessions, Screens.edit_sessions}:
        sessions = await app.engine.call("/sessions")
        all_projects = screen == Screens.journal or (
            screen == Screens.edit_sessions and app.store.get("edit_scope") == "all"
        )
        if not all_projects:
            sessions = [s for s in sessions if s["cwd"] == place["path"]]
        visible = []
        for candidate in sessions:
            if (
                screen != Screens.edit_sessions
                and candidate["name"] == "New session"
                and not candidate["thread_id"]
                and not candidate["turn_id"]
                and candidate["status"] == "idle"
                and not candidate.get("pending_requests")
            ):
                conversation = await app.engine.call(f"/sessions/{candidate['id']}/conversation")
                if not conversation["total"]:
                    continue
            visible.append(candidate)
        sessions = sorted(
            visible,
            key=lambda s: (s.get("last_interaction", s["updated"]), s["id"]),
            reverse=True,
        )
        live = await app.engine.call("/live")
        projects = {p["path"]: p["name"] for p in await app.engine.call("/projects")}

        def describe(s):
            label = session_label(
                {**s, "activity": live.get(s["id"], {}).get("activity")},
                app.store.viewed(s["id"]),
                rich=True,
                with_name=False,
            )
            return (
                f"<b>{escape(s['name'])}</b>\n"
                + label
                + ("\n📍 " + escape(projects.get(s["cwd"], Path(s["cwd"]).name)) if all_projects else "")
            )

        listing, v["rows"], v["previous_page"], v["next_page"] = numbered(app, screen, sessions, describe)
        if screen == Screens.journal:
            v["text"] = f"📒 Journal\n\nUnread results: {len(unread(app, sessions))}\n\n" + (
                listing or "No sessions yet."
            )
        elif screen == Screens.edit_sessions:
            v["text"] = (
                "✏️ Edit sessions\n\nChoose a session to archive. History and project files are retained.\n\n"
                + (listing or "No sessions to edit.")
            )
        else:
            v["text"] = f"📍 {escape(place['name'])}\n{escape(place['path'])}\n\nSessions\n\n" + (
                listing or "No sessions here yet. Start one below."
            )
    elif screen == Screens.edit_session:
        target = await app.engine.call(f"/sessions/{app.store.get('edit_target')}")
        v["text"] = (
            f"✏️ {target['name']}\n\nDirectory: {target['cwd']}\nStatus: {target['status']}\n\nArchive removes this session from active lists and retains its history and files."
        )
        if working(target):
            v["text"] += "\nArchiving also stops its active work."
    elif screen == Screens.locations:
        projects = await app.engine.call("/projects")
        projects.sort(key=lambda p: (p["name"] != "Home", p["name"].lower()))
        listing, v["rows"], v["previous_page"], v["next_page"] = numbered(
            app, screen, projects, lambda p: f"<b>{escape(p['name'])}</b> ({escape(p['path'])})"
        )
        v["text"] = "📍 Location\n\nChoose where to work.\n\n" + listing
    elif screen in {Screens.chat, Screens.history} and session:
        cursor = app.store.get("history_anchor") if screen == Screens.history else ""
        conversation = (
            await app.history_book.read(app.engine, sid, cursor)
            if screen == Screens.history
            else await app.engine.call(f"/sessions/{sid}/conversation")
        )
        current_live = (await app.engine.call("/live")).get(sid)
        if current_live and session["status"] == "waiting":
            current_live = {**current_live, "activity": "Waiting for your answer"}
        live = current_live if not conversation["next"] else None
        v["activity_button"] = (
            activity_label(current_live, session["effort"]).split(" · Reasoning:", 1)[0]
            if current_live
            else session["status"].title()
        )
        content = "answer"
        v["request_tab"] = ("• " if content == "request" else "") + "👤 You"
        v["answer_tab"] = ("• " if content == "answer" else "") + "🤖 Codex"
        v["progress_tab"] = ("• " if content == "progress" else "") + "💭 Updates"
        models = (await app.engine.call("/models")).get("data", [])
        model = effective_model(models, session)
        v.update(
            model_label="🤖 " + (model.get("displayName") or model["id"]),
            effort_label="🧠 " + session["effort"],
            plan_label="📝 Plan: " + ("On" if session["collaboration_mode"] == "plan" else "Off"),
        )
        questions = await app.engine.call(f"/sessions/{sid}/questions")
        if questions and not conversation["next"]:
            replies = list(conversation["replies"])
            for question in questions:
                if not any(
                    e["kind"] == "question" and e["payload"].get("question_id") == question["id"]
                    for e in replies
                ):
                    replies.append(
                        {
                            "kind": "question",
                            "payload": {"question_id": question["id"], **question["payload"]},
                        }
                    )
            conversation = {**conversation, "replies": replies}
        output = {
            **conversation,
            "replies": [e for e in conversation["replies"] if e["kind"] != "attachment"],
        }
        parts = conversation_parts(output, live, rich=True, view=content, compact=True)
        attachments: list[dict] = []
        if screen == Screens.chat and len(parts) > 1:
            answers = [
                e
                for e in conversation["replies"]
                if e["kind"] == "message"
                and e["payload"].get("phase") != "commentary"
                and e["payload"].get("text")
            ]
            completion = max(
                (e["id"] for e in conversation["replies"] if e["kind"] == "completed"), default=0
            )
            delivered = [
                app.store.queue_answer(e, session, completion if app.read_requested else 0) for e in answers
            ]
            if (
                delivered
                and all(delivered)
                and not questions
                and not any(
                    e["kind"] == "error"
                    or (e["kind"] == "completed" and e["payload"].get("status") != "completed")
                    for e in conversation["replies"]
                )
            ):
                parts = [""]
        if screen == Screens.history:
            if live:
                conversation = {
                    **conversation,
                    "replies": [
                        *conversation["replies"],
                        *[
                            {
                                "kind": "reasoning_summary",
                                "payload": {"parts": [parts[k] for k in sorted(parts, key=int)]},
                            }
                            for parts in live.get("summaries", {}).values()
                        ],
                    ],
                }
            try:
                records = await app.engine.call(f"/sessions/{sid}/attachments")
                aids = {
                    e["payload"]["attachment_id"]
                    for e in conversation["replies"]
                    if e["kind"] == "attachment"
                }
                attachments = [
                    a for a in records if a["user_event_id"] in conversation["anchors"] or a["id"] in aids
                ]
            except ValueError:
                pass
            book = chapter_pages(
                conversation, attachments, app.settings.data_dir / "uploads", page_limit=3500
            )
            parts = [p["text"] for p in book]
        part = int(app.store.get("history_part", "0")) if screen == Screens.history else 0
        part = len(parts) - 1 if part < 0 else min(part, len(parts) - 1)
        app.store.set(
            "history_view",
            json.dumps(
                {
                    **{k: conversation[k] for k in ["previous", "next"]},
                    "anchor": conversation.get("anchor")
                    or (conversation["user"]["id"] if conversation["user"] else None),
                    "part": part,
                    "parts": len(parts),
                }
            ),
        )
        v["history_previous"] = part > 0 or conversation["previous"] is not None
        v["history_next"] = part + 1 < len(parts) or conversation["next"] is not None
        v["exchange_previous"] = conversation["previous"] is not None
        v["exchange_next"] = conversation["next"] is not None
        header = "<b>💬 " + escape(session["name"][:55]) + "</b>"
        state = (
            activity_label(current_live, session["effort"], rich=True).split(" · Reasoning:", 1)[0]
            if current_live
            else escape(session["status"].title())
        )
        header += (
            "\n"
            + escape(model.get("displayName") or model["id"])
            + " ("
            + escape(session["effort"])
            + ") · "
            + state
        )
        if screen == Screens.chat and len(parts) > 1:
            header += f"\n<i>Answer · Page 1/{len(parts)}</i>"
        if screen == Screens.history:
            header += f"\n<i>Iteration {conversation['index']}/{conversation['total']} · Page {part + 1}/{len(parts)}</i>"
            source = book[part]["path"]
            v["media"] = (
                MediaAttachment(
                    ContentType.DOCUMENT
                    if Path(source).stat().st_size > 10_000_000
                    else ContentType.ANIMATION
                    if Path(source).suffix == ".gif"
                    else ContentType.PHOTO,
                    path=source,
                )
                if source
                else None
            )
        v["text"] = header + ("\n\n" + parts[part] if parts[part] else "")
        if questions and screen == Screens.chat:
            q = questions[0]
            app.store.set("question_session:" + q["id"], sid)
            if q["method"] in {"item/tool/requestUserInput", "item/agentMessage/asyncUserInput"}:
                answers = json.loads(app.store.get("answers:" + q["id"], "{}"))
                unanswered = [
                    (i, x) for i, x in enumerate(q["payload"]["questions"]) if x["id"] not in answers
                ]
                if unanswered:
                    qi, question = unanswered[0]
                    v["question_rows"] = [
                        (o["label"][:60], f"{q['id']}:{qi}:{i}")
                        for i, o in enumerate(question.get("options") or [])
                    ]
            else:
                v["mcp_question"] = True
    elif screen == Screens.config and session:
        models = (await app.engine.call("/models")).get("data", [])
        model = effective_model(models, session)
        v.update(
            model_label="Model: " + (model.get("displayName") or model["id"]),
            effort_label="Reasoning: " + session["effort"],
            plan_label="Plan mode: " + ("On" if session["collaboration_mode"] == "plan" else "Off"),
        )
        v["text"] = "<b>⚙️ Config</b>\n" + escape(session["name"]) + "\n\nChanges apply to the next turn."
    elif screen == Screens.details and session:
        details = await app.engine.call(f"/sessions/{sid}/details")
        projects = await app.engine.call("/projects")
        name = next((p["name"] for p in projects if p["path"] == session["cwd"]), Path(session["cwd"]).name)
        v["text"] = (
            f"<b>ℹ️ Session details</b>\n\n<b>{escape(session['name'])}</b>\n"
            + session_label(session, rich=True, with_name=False)
            + f"\n\n<b>📍 Location</b>\n{escape(name)} · {escape(details['host_id'])}\n<code>{escape(session['cwd'])}</code>"
            + "\n\n<b>🕒 Timeline</b>"
        )
        for label, value in [
            ("Created", session["created"]),
            ("Last request", details["last_request"]),
            ("Last response", details["last_response"]),
            ("Last finished", details["last_finished"]),
        ]:
            v["text"] += f"\n<b>{label}</b>\n<i>{escape(timestamp(value))}</i>"
        v["text"] += (
            f"\n\n<b>💾 Storage</b>\nFree: <b>{details['disk_free'] / 1024**3:.1f} GiB</b> / {details['disk_total'] / 1024**3:.1f} GiB"
        )
    elif screen == Screens.images and session:
        anchor = json.loads(app.store.get("history_view", "{}")).get("anchor")
        attachments = await app.engine.call(
            f"/sessions/{sid}/attachments" + (f"?anchor={anchor}" if anchor else "")
        )
        listing, v["rows"], v["previous_page"], v["next_page"] = numbered(
            app, screen, attachments, lambda item: item["name"]
        )
        v["text"] = "📎 Session images\n\nChoose an image to download its original file.\n\n" + (
            listing or "No images for this request."
        )
    elif screen == Screens.limits:
        try:
            limits_data = await app.engine.call("/limits")
        except (ConnectionError, ValueError):
            limits_data = {"available": False}
        v["text"] = "<b>⏱ Account limits</b>\n\n" + quota_summary(limits_data)
        if limits_data.get("checked_at"):
            v["text"] += "\n\n<i>Updated: " + escape(timestamp(limits_data["checked_at"])) + "</i>"
    elif screen == Screens.settings:
        v["text"] = (
            "<b>⚙️ Settings</b>\n\n<b>🤖 Session controls</b>\nOpen session Config for model, reasoning and Plan mode.\n\n<b>💻 Service information</b>\nOpen Terminal for versions and health, or Limits for account usage."
        )
    elif screen == Screens.terminal:
        health = await app.engine.call("/health")
        sessions = await app.engine.call("/sessions")
        v["text"] = (
            f"<b>💻 Terminal</b>\n\n<b>📦 Versions</b>\nTelegram: <b>{__version__}</b>\nCore: <b>{escape(health['version'])}</b>"
            f"\nProtocol: {health.get('protocol_version', 1)}"
            f"\n\n<b>🖥 Host · {escape(health['host_id'])}</b>\n"
            f"Core: {'🟢 Healthy' if health.get('ok') else '🔴 Unavailable'}\n"
            f"Native agent: {'🟢 Running' if health.get('codex_running') else '⚪ Stopped'}\n"
            f"Intake: {'🟢 Accepting' if health.get('accepting') else '⏳ Draining'}"
            f"\nDevice confirmation: {'🔐 Required' if app.confirmations else '⚪ Not enabled'}"
            f"\n\n<b>📊 Workload</b>\nSessions: {len(sessions)} · Active: {sum(working(s) for s in sessions)}"
            f"\nQueued inputs: {health.get('pending_requests', 0)}"
            f"\nQuestions: {sum(s.get('pending_questions', int(s['status'] == 'waiting')) for s in sessions)}"
            f"\nUnread results: {len(unread(app, sessions))}"
            f"\n\n<b>Revision</b>\n<code>{escape(health.get('revision', 'Unknown'))}</code>"
        )
    elif screen == Screens.input:
        v["text"] = app.store.get("input_prompt", "Send a value.")
    elif screen == Screens.models and session:
        models = curated_models((await app.engine.call("/models")).get("data", []))
        app.store.set("model_catalog", json.dumps(models))
        v["rows"] = [(m.get("displayName") or m["id"], m["id"]) for m in models]
        v["text"] = f"🧠 Model · {session['name']}\n\nLatest available Sol and up to two latest Astra models."
    app.view_receipt = None
    if (
        app.read_requested
        and screen in {Screens.chat, Screens.history}
        and content == "answer"
        and session
        and not conversation["next"]
        and part == len(parts) - 1
    ):
        completion = max((e["id"] for e in conversation["replies"] if e["kind"] == "completed"), default=0)
        if completion:
            app.view_receipt = (sid, completion)
    if screen not in {
        Screens.deck,
        Screens.settings,
        Screens.terminal,
        Screens.details,
        Screens.limits,
        Screens.locations,
        Screens.sessions,
        Screens.journal,
        Screens.edit_sessions,
        Screens.config,
        Screens.history,
    } and (screen != Screens.chat or not session):
        v["text"] = escape(v["text"])
    v["has_pages"] = v["previous_page"] or v["next_page"]
    if notice := app.store.get("notice"):
        combined = v["text"] + "\n\n" + escape(notice)
        limit = 1024 if v.get("media") else 4000
        if html_length(combined) <= limit:
            v["text"] = combined
        else:
            v["text"] = split_html("⚠️ " + escape(notice), limit - 32)[0]
    app.receipt_text = v["text"]
    return v


def effective_model(models: list[dict], session: dict) -> dict:
    return next(
        (m for m in models if session["model"] in {m["id"], m.get("model", m["id"])}),
        next((m for m in models if m.get("isDefault")), models[0] if models else {"id": "Codex default"}),
    )


async def go(manager: DialogManager, screen: State, *, remember=True) -> None:
    app = runtime(manager)
    app.store.set("notice", "")
    current = manager.current_context().state
    if remember and current != screen:
        trail = json.loads(app.store.get("trail", "[]"))
        trail.append(current.state)
        app.store.set("trail", json.dumps(trail[-16:]))
    app.store.set(
        "mode",
        "input"
        if screen == Screens.input
        else "chat"
        if screen in {Screens.chat, Screens.history}
        else "menu",
    )
    app.store.set("screen", screen.state)
    if screen == Screens.sessions:
        app.store.set("starting_session_key", "")
    app.read_requested = screen in {Screens.chat, Screens.history}
    app.store.set("input_action", app.store.get("input_kind") if screen == Screens.input else "")
    await manager.switch_to(screen, show_mode=ShowMode.EDIT)


async def deck(c, b, manager):
    runtime(manager).store.set("trail", "[]")
    await go(manager, Screens.deck, remember=False)


async def back(c, b, manager):
    app = runtime(manager)
    trail = json.loads(app.store.get("trail", "[]"))
    target = trail.pop() if trail else Screens.deck.state
    app.store.set("trail", json.dumps(trail))
    screen = next((s for s in Screens.__all_states__ if s.state == target), Screens.deck)
    await go(manager, screen, remember=False)


async def locations(c, b, manager):
    await go(manager, Screens.locations)


async def journal(c, b, manager):
    await go(manager, Screens.journal)


async def images(c, b, manager):
    await go(manager, Screens.images)


async def download_attachment(c, widget, manager, item_id):
    app = runtime(manager)
    await app.send_attachment(app.store.get("selected"), item_id)
    await c.answer("Image sent")
    manager.show_mode = ShowMode.EDIT


async def limits(c, b, manager):
    await go(manager, Screens.limits)


async def content_tab(c, b, manager):
    app = runtime(manager)
    app.store.set("history_content", b.widget_id.removeprefix("tab_"))
    app.store.set("history_part", "0")
    app.read_requested = True
    manager.show_mode = ShowMode.EDIT


async def terminal(c, b, manager):
    await go(manager, Screens.terminal)


async def edit_sessions(c, b, manager):
    app = runtime(manager)
    app.store.set("edit_scope", "all" if manager.current_context().state == Screens.journal else "location")
    app.store.set(f"page:{Screens.edit_sessions.state}", "0")
    await go(manager, Screens.edit_sessions)


async def choose_edit_session(c, widget, manager, item_id):
    runtime(manager).store.set("edit_target", item_id)
    await go(manager, Screens.edit_session)


async def archive_session(c, b, manager):
    app = runtime(manager)
    target = app.store.get("edit_target")
    await app.engine.call(f"/sessions/{target}/archive", {})
    if app.store.get("selected") == target:
        app.store.set("selected", "")
    await back(c, b, manager)


async def settings(c, b, manager):
    await go(manager, Screens.settings)


async def config(c, b, manager):
    await go(manager, Screens.config)


async def details(c, b, manager):
    await go(manager, Screens.details)


async def models(c, b, manager):
    await go(manager, Screens.models)


async def choose_location(c, widget, manager, item_id):
    app = runtime(manager)
    place = next(p for p in await app.engine.call("/projects") if p["id"] == item_id)
    app.store.set("location", place["path"])
    app.store.set(f"page:{Screens.sessions.state}", "0")
    await go(manager, Screens.sessions)


async def choose_session(c, widget, manager, item_id):
    app = runtime(manager)
    session = await app.engine.call(f"/sessions/{item_id}")
    if session["archived"]:
        await c.answer("This session is closed.")
        return
    app.store.set("selected", item_id)
    app.store.answer_visit(new=True)
    app.store.set("location", session["cwd"])
    app.store.set("history_anchor", "")
    app.store.set("history_part", "-1")
    app.store.set("history_content", "answer")
    await go(manager, Screens.chat)


async def new_session(c, b, manager):
    app = runtime(manager)
    place = await location(app)
    key = "created:" + c.id
    sid = app.store.get(key)
    session = (
        await app.engine.call(f"/sessions/{sid}")
        if sid
        else await app.engine.call("/sessions", {"cwd": place["path"], "request_id": key})
    )
    app.store.set(key, session["id"])
    await choose_session(c, b, manager, session["id"])


async def page(c, b, manager):
    app = runtime(manager)
    key = "page:" + manager.current_context().state.state
    app.store.set(key, str(max(0, int(app.store.get(key, "0")) + (1 if b.widget_id == "page_next" else -1))))
    manager.show_mode = ShowMode.EDIT


async def open_history(c, b, manager):
    app = runtime(manager)
    app.store.set("history_anchor", "")
    app.store.set("history_part", "0")
    await go(manager, Screens.history)


async def history(c, b, manager):
    app = runtime(manager)
    app.read_requested = True
    view = json.loads(app.store.get("history_view", "{}"))
    target = None
    part = view.get("part", 0)
    if b.widget_id in {"exchange_prev", "exchange_next"}:
        target = view["previous"] if b.widget_id == "exchange_prev" else view["next"]
        part = 0
    elif b.widget_id == "history_prev":
        if part > 0:
            part -= 1
        else:
            target, part = view["previous"], -1
    elif b.widget_id == "history_next":
        if part + 1 < view["parts"]:
            part += 1
        else:
            target, part = view["next"], 0
    app.store.set("history_anchor", str(target or view.get("anchor") or ""))
    app.store.set("history_part", str(part))
    manager.show_mode = ShowMode.EDIT


async def cycle_effort(c, b, manager):
    app = runtime(manager)
    if app.store.get("applied:" + c.id):
        manager.show_mode = ShowMode.EDIT
        return
    sid = app.store.get("selected")
    session = await app.engine.call(f"/sessions/{sid}")
    model = effective_model((await app.engine.call("/models")).get("data", []), session)
    efforts = [x["reasoningEffort"] for x in model.get("supportedReasoningEfforts", [])]
    if not efforts:
        await c.answer("This model has no reasoning choices")
        return
    current = efforts.index(session["effort"]) if session["effort"] in efforts else -1
    await app.engine.call(f"/sessions/{sid}/settings", {"effort": efforts[(current + 1) % len(efforts)]})
    app.store.set("applied:" + c.id, "1")
    manager.show_mode = ShowMode.EDIT


async def toggle_plan(c, b, manager):
    app = runtime(manager)
    if app.store.get("applied:" + c.id):
        manager.show_mode = ShowMode.EDIT
        return
    sid = app.store.get("selected")
    session = await app.engine.call(f"/sessions/{sid}")
    mode = "default" if session["collaboration_mode"] == "plan" else "plan"
    await app.engine.call(f"/sessions/{sid}/settings", {"collaboration_mode": mode})
    app.store.set("applied:" + c.id, "1")
    manager.show_mode = ShowMode.EDIT


async def choose_model(c, widget, manager, item_id):
    app = runtime(manager)
    model = next(m for m in json.loads(app.store.get("model_catalog", "[]")) if m["id"] == item_id)
    session = await app.engine.call(f"/sessions/{app.store.get('selected')}")
    efforts = [x["reasoningEffort"] for x in model.get("supportedReasoningEfforts", [])]
    effort = (
        session["effort"] if session["effort"] in efforts else model.get("defaultReasoningEffort", "medium")
    )
    await app.engine.call(
        f"/sessions/{session['id']}/settings",
        {"model": model.get("model") or model["id"], "effort": effort},
    )
    await back(c, widget, manager)


async def stop(c, b, manager):
    app = runtime(manager)
    await app.engine.call(f"/sessions/{app.store.get('selected')}/stop", {})
    await c.answer("Stop requested")
    manager.show_mode = ShowMode.EDIT


async def close_session(c, b, manager):
    app = runtime(manager)
    await app.engine.call(f"/sessions/{app.store.get('selected')}/archive", {})
    app.store.set("selected", "")
    app.store.set("trail", json.dumps([Screens.deck.state, Screens.locations.state]))
    await go(manager, Screens.sessions, remember=False)


async def prompt(c, b, manager):
    app = runtime(manager)
    app.store.set("input_kind", b.widget_id)
    app.store.set(
        "input_prompt",
        "Send the new session name."
        if b.widget_id == "rename"
        else "Send an existing absolute directory path.",
    )
    app.store.set("input_session", app.store.get("selected"))
    await go(manager, Screens.input)
    app.store.set("mode", "input")
    app.store.set("input_action", b.widget_id)


async def answer(c, widget, manager, item_id):
    app = runtime(manager)
    qid, qi, oi = item_id.split(":")
    q = await app.question(qid)
    question = q["payload"]["questions"][int(qi)]
    await app.answer_question(q, question["id"], question["options"][int(oi)]["label"])
    manager.show_mode = ShowMode.EDIT


async def mcp(c, widget, manager):
    app = runtime(manager)
    pending = await app.engine.call(f"/sessions/{app.store.get('selected')}/questions")
    await app.engine.call(f"/questions/{pending[0]['id']}", {"answers": {"action": widget.widget_id}})
    manager.show_mode = ShowMode.EDIT


def navigation(*, with_config=True):
    buttons: list[Any] = []
    buttons.append(
        Row(
            Button(Const("⬅️ Back"), id="back", on_click=back),
            Button(Const("🏠 Deck"), id="deck", on_click=deck),
        )
    )
    return Group(*buttons)


def numbered_picker(callback):
    return Group(
        Select(
            Format("{item[0]}"),
            id="pick",
            items="rows",
            item_id_getter=lambda x: x[1],
            on_click=callback,
        ),
        width=4,
    )


def list_pages():
    return Row(
        Button(Const("◀"), id="page_prev", on_click=page),
        Button(Const("▶"), id="page_next", on_click=page),
        when="has_pages",
    )


def make_dialog() -> Dialog:
    return Dialog(
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Row(
                Button(Const("⚙️ Settings"), id="settings", on_click=settings),
                Button(Const("💻 Terminal"), id="terminal", on_click=terminal),
            ),
            Button(Const("📍 Location"), id="locations", on_click=locations),
            Row(
                Button(Format("{journal_label}"), id="journal", on_click=journal),
                Button(Const("⏱ Limits"), id="limits", on_click=limits),
            ),
            navigation(with_config=False),
            state=Screens.deck,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Button(Const("✏️ Edit"), id="edit", on_click=edit_sessions),
            numbered_picker(choose_session),
            list_pages(),
            navigation(with_config=False),
            state=Screens.journal,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            numbered_picker(choose_location),
            list_pages(),
            navigation(with_config=False),
            state=Screens.locations,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Row(
                Button(Const("➕ New"), id="new", on_click=new_session),
                Button(Const("✏️ Edit"), id="edit", on_click=edit_sessions),
            ),
            numbered_picker(choose_session),
            list_pages(),
            navigation(with_config=False),
            state=Screens.sessions,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Row(
                Button(Const("⚙️ Config"), id="config", on_click=config),
                Button(Const("ℹ️ Details"), id="details", on_click=details),
            ),
            Row(
                Button(Const("📖 Chat history"), id="history", on_click=open_history),
                Button(Const("⏹ Stop"), id="stop", on_click=stop),
            ),
            Select(
                Format("{item[0]}"),
                id="answer",
                items="question_rows",
                when="question_rows",
                item_id_getter=lambda x: x[1],
                on_click=answer,
            ),
            Row(
                Button(Const("Accept"), id="accept", on_click=mcp),
                Button(Const("Decline"), id="decline", on_click=mcp),
                when="mcp_question",
            ),
            navigation(with_config=False),
            state=Screens.chat,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            DynamicMedia("media"),
            LinkPreview(is_disabled=True),
            Row(
                Button(Const("◀ Page"), id="history_prev", on_click=history, when="history_previous"),
                Button(Const("Page ▶"), id="history_next", on_click=history, when="history_next"),
            ),
            Row(
                Button(Const("⏮ Iteration"), id="exchange_prev", on_click=history, when="exchange_previous"),
                Button(Const("Iteration ⏭"), id="exchange_next", on_click=history, when="exchange_next"),
            ),
            navigation(with_config=False),
            state=Screens.history,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Button(Format("{model_label}"), id="models", on_click=models),
            Button(Format("{effort_label}"), id="reasoning", on_click=cycle_effort),
            Button(Format("{plan_label}"), id="plan", on_click=toggle_plan),
            navigation(with_config=False),
            state=Screens.config,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Row(
                Button(Const("✏️ Rename"), id="rename", on_click=prompt),
                Button(Const("✖ Close session"), id="close", on_click=close_session),
            ),
            navigation(),
            state=Screens.details,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            numbered_picker(choose_edit_session),
            list_pages(),
            navigation(with_config=False),
            state=Screens.edit_sessions,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Button(Const("🗃 Archive"), id="archive", on_click=archive_session),
            navigation(with_config=False),
            state=Screens.edit_session,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            numbered_picker(download_attachment),
            list_pages(),
            navigation(with_config=False),
            state=Screens.images,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            navigation(with_config=False),
            state=Screens.limits,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            navigation(with_config=False),
            state=Screens.terminal,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            navigation(with_config=False),
            state=Screens.settings,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            navigation(),
            state=Screens.input,
            parse_mode="HTML",
        ),
        Window(
            Format("{text}"),
            LinkPreview(is_disabled=True),
            Group(
                Select(
                    Format("{item[0]}"),
                    id="model",
                    items="rows",
                    item_id_getter=lambda x: x[1],
                    on_click=choose_model,
                ),
                width=1,
            ),
            navigation(with_config=False),
            state=Screens.models,
            parse_mode="HTML",
        ),
        getter=data,
    )


async def open_screen(manager: DialogManager, screen: State, *, read: bool = True) -> None:
    app = runtime(manager)
    app.store.set("notice", "")
    if screen == Screens.chat and read:
        app.store.answer_visit(new=True)
    app.store.set("mode", "chat" if screen in {Screens.chat, Screens.history} else "menu")
    app.store.set("screen", screen.state)
    if screen == Screens.sessions:
        app.store.set("starting_session_key", "")
    app.read_requested = read and screen in {Screens.chat, Screens.history}
    app.store.set("input_action", "")
    app.store.set(
        "trail",
        json.dumps(
            [Screens.deck.state, Screens.locations.state, Screens.sessions.state]
            if screen == Screens.chat
            else []
        ),
    )
    if manager.has_context():
        await manager.switch_to(screen, show_mode=ShowMode.EDIT)
        await manager.show(ShowMode.EDIT)
    else:
        await manager.start(screen, mode=StartMode.RESET_STACK, show_mode=ShowMode.EDIT)
