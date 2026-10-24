"""A chapter starts with original user input; reading pages never crosses roles."""

from html import escape
from pathlib import Path

from telegram_vibecoding.markdown import render_markdown, split_html
from telegram_vibecoding.presentation import progress_prose


def chapter_pages(
    conversation: dict, attachments: list[dict], uploads: Path, *, user_limit: int = 3000
) -> list[dict]:
    pages: list[dict] = []

    def text(label: str, body: str, limit: int = 3000):
        for i, chunk in enumerate(split_html(body, limit), 1):
            heading = label + (" · continued" if i > 1 else "")
            pages.append({"text": f"<b>{heading}</b>\n\n{chunk}", "path": None})

    def image(label: str, source: str):
        path = Path(source)
        if (
            path.is_file()
            and path.resolve().is_relative_to(uploads.resolve())
            and path.stat().st_size <= 20_000_000
        ):
            pages.append({"text": f"<b>{label}</b>", "path": str(path)})

    user = conversation.get("user")
    if not user:
        return [{"text": "No retained history.", "path": None}]
    payload = user["payload"]
    original = payload.get("text", "")
    if payload.get("audio"):
        transcripts = [e["payload"]["text"] for e in conversation["replies"] if e["kind"] == "transcription"]
        original += ("\n\n" if original else "") + "🎙 " + ("\n".join(transcripts) or "Transcribing…")
    text("👤 You", "<blockquote>" + escape(original or "[Image]") + "</blockquote>", user_limit)
    for source in payload.get("images", []):
        image("👤 You · Image", source)
    remaining = {a["id"]: a for a in attachments}
    for event in conversation["replies"]:
        p = event["payload"]
        kind = event["kind"]
        if kind == "message":
            text("🤖 Codex", render_markdown(p.get("text", "")))
        elif kind == "reasoning_summary":
            for part in p.get("parts") or [p.get("text", "")]:
                if prose := progress_prose(part):
                    text("🧠 Codex", render_markdown(prose))
        elif kind == "attachment" and p["attachment_id"] in remaining:
            image("🤖 Codex · Image", remaining.pop(p["attachment_id"])["path"])
        elif kind == "error":
            text("⚠️ Error", escape(p.get("text", "Unknown error")))
        elif kind == "question":
            for q in p.get("questions", []):
                lines = [
                    q["question"],
                    *[
                        "• " + o["label"] + (": " + o["description"] if o.get("description") else "")
                        for o in q.get("options") or []
                    ],
                ]
                text("❔ Codex", escape("\n".join(lines)))
            if not p.get("questions"):
                text("❔ Codex", escape(str(p.get("message") or p.get("url") or "MCP request")))
        elif kind == "completed" and p.get("status") != "completed":
            text("⚠️ Status", escape(str(p.get("text") or p.get("error") or p["status"])))
    for attachment in remaining.values():
        image("🤖 Codex · Image", attachment["path"])
    return pages
