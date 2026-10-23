"""Lossless Telegram splitting and compact, host-aware session labels."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

PART_UNITS = 3500


def timestamp(value: float | None) -> str:
    if value is None:
        return "—"
    moment = datetime.fromtimestamp(value, ZoneInfo("Europe/Warsaw"))
    offset = moment.strftime("%z")
    return moment.strftime("%d %b %Y %H:%M Warsaw (%Z, UTC") + offset[:3] + ":" + offset[3:] + ")"


def curated_models(models: list[dict]) -> list[dict]:
    def version(model):
        return tuple(int(n) for n in re.findall(r"\d+", model.get("model") or model["id"]))

    visible = [m for m in models if not m.get("hidden")]
    sol = sorted((m for m in visible if "sol" in m["id"].lower()), key=version, reverse=True)
    astra = sorted((m for m in visible if "astra" in m["id"].lower()), key=version, reverse=True)
    result = sol[:1] + astra[:2]
    return result or visible[:3]


def conversation_parts(conversation: dict, live: dict | None = None) -> list[str]:
    user = conversation.get("user")
    if not user:
        return ["Send a message or an image to begin."]
    payload = user["payload"]
    prompt = payload.get("text", "")
    images = len(payload.get("images", []))
    if images:
        prompt += f"\n[Images: {images}]"
    replies = []
    for event in conversation["replies"]:
        p = event["payload"]
        if event["kind"] == "message":
            replies.append(p.get("text", ""))
        elif event["kind"] == "error":
            replies.append("⚠️ " + p.get("text", "Unknown error"))
        elif event["kind"] == "question":
            for question in p.get("questions", []):
                lines = ["Question", question["question"]]
                lines += [
                    f"• {o['label']}: {o.get('description', '')}" for o in question.get("options") or []
                ]
                replies.append("\n".join(lines))
            if not p.get("questions"):
                replies.append(str(p.get("message") or p.get("url") or "MCP request"))
        elif event["kind"] == "completed" and p.get("status") != "completed":
            error = p.get("error") or {}
            replies.append(p.get("text") or error.get("message") or p["status"].capitalize())
    if live:
        replies.append(live.get("text") or live.get("activity", "Working…"))
    body = "You\n" + prompt + "\n\nCodex\n" + ("\n\n".join(replies) or "Waiting for a response…")
    return split_text(body, 3200)


def split_text(text: str, limit: int = PART_UNITS) -> list[str]:
    """Bound UTF-16 units and retain every source character, including newlines."""
    if not text:
        return []
    result: list[str] = []
    current: list[str] = []
    used = 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if used + units > limit:
            result.append("".join(current))
            current, used = [], 0
        current.append(char)
        used += units
    if current:
        result.append("".join(current))
    return result
