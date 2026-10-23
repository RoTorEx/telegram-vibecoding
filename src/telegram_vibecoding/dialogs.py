"""One editable panel: Main Deck → location → session, with consistent exits."""

import json
from pathlib import Path
from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.fsm.state import State, StatesGroup
from aiogram_dialog import Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.widgets.kbd import Button, Group, Row, Select
from aiogram_dialog.widgets.style import Style
from aiogram_dialog.widgets.text import Const, Format

from telegram_vibecoding import __version__
from telegram_vibecoding.presentation import activity_label, conversation_parts, curated_models, timestamp


class Screens(StatesGroup):
    deck = State()
    locations = State()
    sessions = State()
    chat = State()
    config = State()
    details = State()
    settings = State()
    input = State()
    archived = State()
    models = State()


def runtime(manager: DialogManager):
    return manager.middleware_data["runtime"]


async def location(app) -> dict:
    projects = await app.engine.call("/projects")
    home = next((p for p in projects if p["name"] == "Home"), projects[0])
    selected = next((p for p in projects if p["path"] == app.store.get("location")), home)
    app.store.set("location", selected["path"])
    return selected


def numbered(app, screen, entries, describe) -> tuple[str, list, bool, bool]:
    key = "page:" + screen.state
    page = min(int(app.store.get(key, "0")), max(0, (len(entries) - 1) // 10))
    app.store.set(key, str(page))
    visible = entries[page * 10 : page * 10 + 10]
    text = "\n\n".join(f"{i}. {describe(p)}" for i, p in enumerate(visible, 1))
    if len(entries) > 10:
        text += f"\n\nPage {page + 1}/{(len(entries) + 9) // 10}"
    rows = [(str(i), p["id"]) for i, p in enumerate(visible, 1)]
    return text, rows, page > 0, (page + 1) * 10 < len(entries)


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
        "has_selected": bool(session),
        "previous_page": False,
        "next_page": False,
        "can_stop": bool(session and session["turn_id"]),
        "history_previous": False,
        "history_next": False,
        "question_rows": [],
        "mcp_question": False,
    }
    if screen == Screens.deck:
        sessions = await app.engine.call("/sessions")
        working = sum(bool(s["turn_id"]) for s in sessions)
        waiting = sum(s["status"] == "waiting" for s in sessions)
        v["text"] = (
            f"🏠 Main Deck\n\nMachine: {app.settings.host_id}\nLocation: {place['name']}\n{place['path']}"
        )
        if working or waiting:
            v["text"] += f"\n\nWorking: {working} · Waiting: {waiting}"
    elif screen == Screens.locations:
        projects = await app.engine.call("/projects")
        projects.sort(key=lambda p: (p["name"] != "Home", p["name"].lower()))
        listing, v["rows"], v["previous_page"], v["next_page"] = numbered(
            app, screen, projects, lambda p: f"{p['name']}\n{p['path']}"
        )
        v["text"] = "📍 Location\n\nChoose where to work.\n\n" + listing
    elif screen in {Screens.sessions, Screens.archived}:
        archived = screen == Screens.archived
        sessions = await app.engine.call("/sessions" + ("?archived=1" if archived else ""))
        sessions = [s for s in sessions if s["cwd"] == place["path"]]
        listing, v["rows"], v["previous_page"], v["next_page"] = numbered(
            app, screen, sessions, lambda s: f"{s['name']} · {s['status']}"
        )
        v["text"] = (
            f"📍 {place['name']}\n{place['path']}\n\n"
            + ("Archived sessions" if archived else "Sessions")
            + "\n\n"
            + (listing or ("No archived sessions." if archived else "No sessions here yet. Start one below."))
        )
    elif screen == Screens.chat and session:
        cursor = app.store.get("history_anchor")
        conversation = await app.engine.call(
            f"/sessions/{sid}/conversation" + (f"?anchor={cursor}" if cursor else "")
        )
        live = (await app.engine.call("/live")).get(sid) if not conversation["next"] else None
        if live and session["status"] == "waiting":
            live = {**live, "activity": "Waiting for your answer"}
        parts = conversation_parts(conversation, live)
        part = int(app.store.get("history_part", "-1"))
        part = len(parts) - 1 if part < 0 else min(part, len(parts) - 1)
        app.store.set(
            "history_view",
            json.dumps(
                {
                    **{k: conversation[k] for k in ["previous", "next"]},
                    "anchor": conversation["user"]["id"] if conversation["user"] else None,
                    "part": part,
                    "parts": len(parts),
                }
            ),
        )
        v["history_previous"] = part > 0 or conversation["previous"] is not None
        v["history_next"] = part + 1 < len(parts) or conversation["next"] is not None
        header = f"💬 {session['name'][:100]} · {session['status']}"
        if live:
            header += "\n" + activity_label(live, session["effort"])
        if conversation["total"]:
            header += f"\nExchange {conversation['index']}/{conversation['total']}"
        if len(parts) > 1:
            header += f" · Part {part + 1}/{len(parts)}"
        v["text"] = header + "\n\n" + parts[part]
        questions = await app.engine.call(f"/sessions/{sid}/questions")
        if questions and not conversation["next"]:
            q = questions[0]
            app.store.set("question_session:" + q["id"], sid)
            if q["method"] == "item/tool/requestUserInput":
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
        v["text"] = (
            f"⚙️ Config · {session['name']}\n\nAgent: Codex\n"
            f"{v['model_label']}\n{v['effort_label']}\n{v['plan_label']}\n\n"
            "Reasoning cycles with each tap. Changes apply to the next turn."
        )
    elif screen == Screens.details and session:
        details = await app.engine.call(f"/sessions/{sid}/details")
        projects = await app.engine.call("/projects")
        name = next((p["name"] for p in projects if p["path"] == session["cwd"]), Path(session["cwd"]).name)
        v["text"] = (
            f"ℹ️ Details\n\nName: {session['name']}\nLocation: {name}\nMachine: {details['host_id']}\n"
            f"Directory: {session['cwd']}\nStatus: {session['status']}\n"
            f"Created: {timestamp(session['created'])}\nLast request: {timestamp(details['last_request'])}\n"
            f"Last response: {timestamp(details['last_response'])}\nLast finished: {timestamp(details['last_finished'])}\n"
            f"Disk free: {details['disk_free'] / 1024**3:.1f} / {details['disk_total'] / 1024**3:.1f} GiB"
        )
    elif screen == Screens.settings:
        health = await app.engine.call("/health")
        v["text"] = (
            f"⚙️ Settings\n\nMachine: {app.settings.host_id}\nDefault location: Home\nAgent: Codex"
            f"\n\nTelegram: {__version__}\nCore: {health['version']}"
        )
        if session:
            v["text"] += (
                f"\n\nSelected session: {session['name']}\nModel, reasoning and Plan mode are in its Config."
            )
        else:
            v["text"] += "\n\nChoose a location and open a session to configure Codex."
    elif screen == Screens.input:
        v["text"] = app.store.get("input_prompt", "Send a value.")
    elif screen == Screens.models and session:
        models = curated_models((await app.engine.call("/models")).get("data", []))
        app.store.set("model_catalog", json.dumps(models))
        v["rows"] = [(m.get("displayName") or m["id"], m["id"]) for m in models]
        v["text"] = f"🧠 Model · {session['name']}\n\nLatest available Sol and up to two latest Astra models."
    if notice := app.store.get("notice"):
        combined = v["text"] + "\n\n" + notice
        if len(combined.encode("utf-16-le")) // 2 <= 4000:
            v["text"] = combined
        else:
            v["text"] = "⚠️ " + notice + "\n\nUse Latest or Back to continue. Your conversation is retained."
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
        "mode", "input" if screen == Screens.input else "chat" if screen == Screens.chat else "menu"
    )
    app.store.set("screen", screen.state)
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


async def settings(c, b, manager):
    await go(manager, Screens.settings)


async def config(c, b, manager):
    await go(manager, Screens.config)


async def details(c, b, manager):
    await go(manager, Screens.details)


async def models(c, b, manager):
    await go(manager, Screens.models)


async def archived(c, b, manager):
    await go(manager, Screens.archived)


async def choose_location(c, widget, manager, item_id):
    app = runtime(manager)
    place = next(p for p in await app.engine.call("/projects") if p["id"] == item_id)
    app.store.set("location", place["path"])
    await go(manager, Screens.sessions)


async def choose_session(c, widget, manager, item_id):
    app = runtime(manager)
    session = await app.engine.call(f"/sessions/{item_id}")
    if session["archived"]:
        await app.engine.call(f"/sessions/{item_id}/reopen", {})
    app.store.set("selected", item_id)
    app.store.set("location", session["cwd"])
    app.store.set("history_anchor", "")
    app.store.set("history_part", "-1")
    await go(manager, Screens.chat)


async def new_session(c, b, manager):
    app = runtime(manager)
    place = await location(app)
    key = "created:" + c.id
    sid = app.store.get(key)
    session = (
        await app.engine.call(f"/sessions/{sid}")
        if sid
        else await app.engine.call("/sessions", {"cwd": place["path"]})
    )
    app.store.set(key, session["id"])
    await choose_session(c, b, manager, session["id"])


async def page(c, b, manager):
    app = runtime(manager)
    key = "page:" + manager.current_context().state.state
    app.store.set(key, str(max(0, int(app.store.get(key, "0")) + (1 if b.widget_id == "page_next" else -1))))
    manager.show_mode = ShowMode.EDIT


async def history(c, b, manager):
    app = runtime(manager)
    view = json.loads(app.store.get("history_view", "{}"))
    if b.widget_id == "latest":
        app.store.set("history_anchor", "")
        app.store.set("history_part", "-1")
    elif b.widget_id == "history_prev":
        app.store.set("history_anchor", str(view["anchor"]))
        if view["part"] > 0:
            app.store.set("history_part", str(view["part"] - 1))
        elif view["previous"]:
            app.store.set("history_anchor", str(view["previous"]))
            app.store.set("history_part", "-1")
    elif view["part"] + 1 < view["parts"]:
        app.store.set("history_anchor", str(view["anchor"]))
        app.store.set("history_part", str(view["part"] + 1))
    elif view["next"]:
        app.store.set("history_anchor", str(view["next"]))
        app.store.set("history_part", "0")
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
    if with_config:
        buttons.append(Button(Const("⚙️ Config"), id="config", on_click=config, when="has_selected"))
    buttons.append(
        Row(
            Button(Const("🏠 Deck"), id="deck", on_click=deck),
            Button(Const("⬅️ Back"), id="back", on_click=back),
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
        width=5,
    )


def list_pages():
    return Row(
        Button(Const("◀"), id="page_prev", on_click=page, when="previous_page"),
        Button(Const("▶"), id="page_next", on_click=page, when="next_page"),
    )


def make_dialog() -> Dialog:
    return Dialog(
        Window(
            Format("{text}"),
            Button(Const("⚙️ Settings"), id="settings", on_click=settings, style=Style(ButtonStyle.PRIMARY)),
            Button(Const("📍 Location"), id="locations", on_click=locations),
            navigation(with_config=False),
            state=Screens.deck,
        ),
        Window(
            Format("{text}"),
            numbered_picker(choose_location),
            list_pages(),
            Button(Const("📂 Other location"), id="location", on_click=prompt),
            navigation(),
            state=Screens.locations,
        ),
        Window(
            Format("{text}"),
            Button(Const("➕ New session"), id="new", on_click=new_session),
            numbered_picker(choose_session),
            list_pages(),
            Button(Const("🗃 Archived"), id="archived", on_click=archived),
            navigation(),
            state=Screens.sessions,
        ),
        Window(
            Format("{text}"),
            numbered_picker(choose_session),
            list_pages(),
            navigation(),
            state=Screens.archived,
        ),
        Window(
            Format("{text}"),
            Row(
                Button(Const("◀"), id="history_prev", on_click=history, when="history_previous"),
                Button(Const("Latest"), id="latest", on_click=history),
                Button(Const("▶"), id="history_next", on_click=history, when="history_next"),
            ),
            Select(
                Format("{item[0]}"),
                id="answer",
                items="question_rows",
                item_id_getter=lambda x: x[1],
                on_click=answer,
            ),
            Row(
                Button(Const("Accept"), id="accept", on_click=mcp),
                Button(Const("Decline"), id="decline", on_click=mcp),
                when="mcp_question",
            ),
            Row(
                Button(Const("⚙️ Config"), id="config", on_click=config),
                Button(Const("ℹ️ Details"), id="details", on_click=details),
            ),
            Button(Const("⏹ Stop"), id="stop", on_click=stop, when="can_stop"),
            navigation(with_config=False),
            state=Screens.chat,
        ),
        Window(
            Format("{text}"),
            Button(Format("{model_label}"), id="models", on_click=models),
            Button(Format("{effort_label}"), id="reasoning", on_click=cycle_effort),
            Button(Format("{plan_label}"), id="plan", on_click=toggle_plan),
            navigation(with_config=False),
            state=Screens.config,
        ),
        Window(
            Format("{text}"),
            Row(
                Button(Const("✏️ Rename"), id="rename", on_click=prompt),
                Button(Const("🗃 Close session"), id="close", on_click=close_session),
            ),
            navigation(),
            state=Screens.details,
        ),
        Window(Format("{text}"), navigation(), state=Screens.settings),
        Window(Format("{text}"), navigation(), state=Screens.input),
        Window(
            Format("{text}"),
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
        ),
        getter=data,
    )


async def open_screen(manager: DialogManager, screen: State) -> None:
    app = runtime(manager)
    app.store.set("notice", "")
    app.store.set("mode", "chat" if screen == Screens.chat else "menu")
    app.store.set("screen", screen.state)
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
