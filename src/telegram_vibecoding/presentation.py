"""Lossless Telegram splitting and compact, host-aware session labels."""

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

PART_UNITS = 3500


def progress_prose(text: str) -> str:
    """Render public progress prose without code blocks, inline code or shell output."""
    lines = []
    fence = None
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
            continue
        if fence or line.startswith(("    ", "\t")):
            continue
        if re.match(
            r"^(?:[$%>]\s|>>>|@@|diff --git|[+][^ ]|#!|"
            r"(?:sudo|cd|ls|rg|git|npm|pnpm|yarn|uv|pip|python\d*|bash|sh|curl|docker)\s|"
            r"(?:def|class|import|from|function|const|let|var|return)\s|[{}];?$)",
            stripped,
        ):
            continue
        lines.append(re.sub(r"`+[^`\n]*(?:`+|$)", "", line))
    return "\n".join(lines).strip()


def activity_label(live: dict, effort: str, now: float | None = None) -> str:
    clock = time.time() if now is None else now
    elapsed = max(0, int(clock - live.get("started", clock)))
    waiting = live.get("activity") == "Waiting for your answer"
    icon = "❔" if waiting else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(clock / 2) % 10]
    label = "Waiting for your answer" if waiting else "Working"
    return f"{icon} {label} · {elapsed // 60:02}:{elapsed % 60:02} elapsed · Reasoning: {effort}"


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
    progress = False

    def append_progress(text, label="Reasoning"):
        nonlocal progress
        if prose := progress_prose(text):
            replies.append("────────\n" + label + "\n" + prose)
            progress = True

    for event in conversation["replies"]:
        p = event["payload"]
        if event["kind"] == "reasoning_summary":
            for part in p.get("parts") or [p.get("text", "")]:
                append_progress(part)
        elif event["kind"] == "message":
            if p.get("phase") == "commentary":
                append_progress(p.get("text", ""), "Progress")
            else:
                replies.append(("────────\nAnswer\n" if progress else "") + p.get("text", ""))
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
        for parts in live.get("summaries", {}).values():
            for key in sorted(parts, key=int):
                append_progress(parts[key])
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
