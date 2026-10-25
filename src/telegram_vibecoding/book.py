"""Chronological, role-aware reading of complete execution iterations."""

import time
from html import escape
from pathlib import Path

from telegram_vibecoding.markdown import html_length, render_markdown, split_html

KINDS = {
    "user",
    "message",
    "reasoning_summary",
    "question",
    "transcription",
    "attachment",
    "completed",
    "error",
}


def iterations(events: list[dict]) -> list[list[dict]]:
    chapters: list[list[dict]] = []
    ended = True
    owners: dict[int, list[dict]] = {}
    for event in events:
        kind = event["kind"]
        if kind not in KINDS:
            continue
        if kind == "attachment" and event["payload"].get("anchor") in owners:
            owners[event["payload"]["anchor"]].append(event)
            continue
        if not chapters or (kind == "user" and ended):
            chapters.append([])
            ended = False
        chapters[-1].append(event)
        if kind == "user":
            owners[event["id"]] = chapters[-1]
        elif kind == "completed":
            ended = True
    return chapters


class SessionBook:
    """Incremental read-only view; refresh retained data every minute for expiry."""

    def __init__(self):
        self.events: list[dict] = []
        self.cursor = 0
        self.refreshed = 0.0

    async def read(self, engine, sid: str, anchor: str = "") -> dict:
        if time.monotonic() - self.refreshed >= 60:
            self.events, self.cursor = [], 0
            self.refreshed = time.monotonic()
        while True:
            batch = await engine.call(f"/events?after={self.cursor}")
            if not batch:
                break
            self.events.extend(e for e in batch if e["kind"] in KINDS)
            self.cursor = batch[-1]["id"]
            if len(batch) < 100:
                break
        chapters = iterations([e for e in self.events if e.get("session_id") == sid])
        if not chapters:
            return {
                "user": None,
                "replies": [],
                "previous": None,
                "next": None,
                "index": 0,
                "total": 0,
                "anchors": [],
                "anchor": None,
            }
        selected = next(
            (i for i, c in enumerate(chapters) if any(str(e["id"]) == anchor for e in c)), len(chapters) - 1
        )
        chapter = chapters[selected]
        user = chapter[0] if chapter[0]["kind"] == "user" else None
        return {
            "user": user,
            "replies": chapter[1:] if user else chapter,
            "previous": chapters[selected - 1][0]["id"] if selected else None,
            "next": chapters[selected + 1][0]["id"] if selected + 1 < len(chapters) else None,
            "index": selected + 1,
            "total": len(chapters),
            "anchor": chapter[0]["id"],
            "anchors": [e["id"] for e in chapter if e["kind"] == "user"],
        }


def chapter_pages(
    conversation: dict, attachments: list[dict], uploads: Path, *, page_limit: int = 3500
) -> list[dict]:
    pages: list[dict] = []
    page: dict = {"text": "", "path": None, "events": []}

    def flush():
        nonlocal page
        if page["text"] or page["path"]:
            pages.append(page)
        page = {"text": "", "path": None, "events": []}

    def text(label: str, body: str, event_id=None, *, whole=False):
        continued = False
        while body:
            heading = f"<b>{label}{' · continued' if continued else ''}</b>\n\n"
            separator = "\n\n" if page["text"] else ""
            capacity = 800 if page["path"] else page_limit
            available = capacity - html_length(page["text"] + separator + heading)
            full = html_length(body)
            if page["text"] and (
                (whole and full <= page_limit - html_length(heading) and full > available)
                or available < min(128, full)
            ):
                flush()
                continue
            chunks = split_html(body, max(1, available))
            page["text"] += separator + heading + chunks[0]
            if event_id is not None and event_id not in page["events"]:
                page["events"].append(event_id)
            body = "".join(chunks[1:])
            if body:
                flush()
                continued = True

    def image(label: str, source: str, event_id=None):
        path = Path(source)
        if (
            not path.is_file()
            or not path.resolve().is_relative_to(uploads.resolve())
            or path.stat().st_size > 20_000_000
        ):
            return
        caption = f"<b>{label}</b>"
        if page["path"] or html_length(page["text"] + caption) + 2 > 800:
            flush()
        page["text"] += ("\n\n" if page["text"] else "") + caption
        page["path"] = str(path)
        if event_id is not None and event_id not in page["events"]:
            page["events"].append(event_id)

    user = conversation.get("user")
    events = ([user] if user else []) + conversation["replies"]
    transcripts: dict = {}
    for event in events:
        if event["kind"] == "transcription":
            transcripts.setdefault(event["payload"].get("request_id"), []).append(event["payload"]["text"])
    remaining = {a["id"]: a for a in attachments}
    user_requests = {e["payload"].get("request_id") for e in events if e["kind"] == "user"}
    for event in events:
        p, kind, eid = event["payload"], event["kind"], event.get("id")
        if kind == "user":
            original = p.get("text", "")
            if p.get("audio"):
                original += (
                    ("\n\n" if original else "")
                    + "🎙 "
                    + ("\n".join(transcripts.get(p.get("request_id"), [])) or "Transcribing…")
                )
            text("👤 You", "<blockquote>" + escape(original or "[Image]") + "</blockquote>", eid, whole=True)
            for source in p.get("images", []):
                image("👤 You · Image", source, eid)
        elif kind == "message":
            text(
                "💬 Codex · Progress" if p.get("phase") == "commentary" else "🤖 Codex · Answer",
                render_markdown(p.get("text", "")),
                eid,
            )
        elif kind == "reasoning_summary":
            for part in p.get("parts") or [p.get("text", "")]:
                text("🧠 Codex · Reasoning", "<blockquote>" + render_markdown(part) + "</blockquote>", eid)
        elif kind == "transcription" and p.get("request_id") not in user_requests:
            text("👤 You · Transcript", escape(p["text"]), eid)
        elif kind == "attachment" and p["attachment_id"] in remaining:
            image("🤖 Codex · Image", remaining.pop(p["attachment_id"])["path"], eid)
        elif kind == "error":
            text("⚠️ Error", escape(p.get("text", "Unknown error")), eid)
        elif kind == "question":
            for q in p.get("questions", []):
                lines = [
                    q["question"],
                    *[
                        "• " + o["label"] + (": " + o["description"] if o.get("description") else "")
                        for o in q.get("options") or []
                    ],
                ]
                text("❔ Codex · Question", escape("\n".join(lines)), eid)
            if not p.get("questions"):
                text(
                    "❔ Codex · Question", escape(str(p.get("message") or p.get("url") or "MCP request")), eid
                )
        elif kind == "completed" and p.get("status") != "completed":
            text("⚠️ Status", escape(str(p.get("text") or p.get("error") or p["status"])), eid)
    for attachment in remaining.values():
        image("🤖 Codex · Image", attachment["path"])
    flush()
    return pages or [{"text": "No retained history.", "path": None, "events": []}]
