"""Lossless Telegram splitting and compact, host-aware session labels."""

import re
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram_vibecoding.markdown import html_length, render_markdown, split_html

PART_UNITS = 3500


def relative_age(value: float | None, now: float | None = None) -> str:
    if value is None:
        return "—"
    seconds = max(0, int((time.time() if now is None else now) - value))
    for duration, suffix in [(86400, "d"), (3600, "h"), (60, "m")]:
        if seconds >= duration:
            return f"{seconds // duration}{suffix}"
    return f"{seconds}s"


def session_label(session: dict, viewed: int = 0, *, rich: bool = False, with_name: bool = True) -> str:
    status = session["status"]
    pending = session.get("pending_requests", 0)
    completion = session.get("last_completed_event") or 0
    if session.get("pending_questions") or status == "waiting":
        marker = "❔ Question · Waiting for you"
    elif status == "transcribing":
        marker = "🎙 Transcribing"
    elif status == "connecting":
        marker = "⏳ Connecting"
    elif session.get("turn_id") or status == "working":
        marker = "⏳ " + (session.get("activity") or "Working")
    elif pending:
        marker = "⏳ Queued"
    elif status == "idle":
        if completion > viewed:
            marker = "📩 Unread · Finished · Waiting for you"
        elif completion:
            marker = "✓ Read · Idle"
        else:
            marker = "💬 Idle"
    else:
        marker = {"failed": "⚠️ Failed", "interrupted": "⏹ Interrupted", "uncertain": "⚠️ Uncertain"}.get(
            status, status
        )
        if completion:
            marker += " · " + ("Unread" if completion > viewed else "Read")
    if pending:
        marker += f" · Queued: {pending}"
    age = session.get("last_interaction", session.get("last_response"))
    suffix = f"(~{relative_age(age)})" if age is not None else ""
    label = f"{session['name']} · {marker}" if with_name else marker
    if rich:
        return escape(label) + (f" <i>{suffix}</i>" if suffix else "")
    return label + (f" {suffix}" if suffix else "")


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


def activity_label(live: dict, effort: str, now: float | None = None, *, rich: bool = False) -> str:
    clock = time.time() if now is None else now
    elapsed = max(0, int(clock - live.get("started", clock)))
    waiting = live.get("activity") == "Waiting for your answer"
    icon = "❔" if waiting else "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(clock / 2) % 10]
    label = (
        "Waiting for your answer"
        if waiting
        else ("Transcribing voice" if live.get("activity") == "Transcribing" else "Working")
    )
    duration = f"(~{elapsed // 60:02}:{elapsed % 60:02} elapsed)"
    if rich:
        return f"{icon} {label} · <i>{duration}</i> · Reasoning: {escape(effort)}"
    return f"{icon} {label} · {duration} · Reasoning: {effort}"


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


def conversation_parts(
    conversation: dict,
    live: dict | None = None,
    *,
    rich: bool = False,
    view: str = "all",
    compact: bool = False,
) -> list[str]:
    literal = escape if rich else str
    formatted = render_markdown if rich else str
    user = conversation.get("user")
    if not user:
        return [""] if compact else ["Send text, an image or a voice recording to begin."]
    payload = user["payload"]
    prompt = payload.get("text", "")
    images = len(payload.get("images", []))
    if images:
        prompt += f"\n[Images: {images}]"
    transcripts = [e["payload"]["text"] for e in conversation["replies"] if e["kind"] == "transcription"]
    if payload.get("audio"):
        prompt += "\n[Voice]\n" + ("\n".join(transcripts) or "Transcribing…")
    blocks = [("👤 You", "<blockquote>" + literal(prompt) + "</blockquote>" if rich else prompt)]

    def append_progress(text, label="Reasoning"):
        if prose := progress_prose(text):
            blocks.append(
                (("🧠 Codex · " if label == "Reasoning" else "💬 Codex · ") + label, formatted(prose))
            )

    for event in conversation["replies"]:
        p = event["payload"]
        if event["kind"] == "reasoning_summary":
            for part in p.get("parts") or [p.get("text", "")]:
                append_progress(part)
        elif event["kind"] == "message":
            if p.get("phase") == "commentary":
                append_progress(p.get("text", ""), "Progress")
            else:
                blocks.append(("🤖 Codex · Answer", formatted(p.get("text", ""))))
        elif event["kind"] == "attachment":
            blocks.append(
                ("🖼 Codex · Image", literal(p["name"]) + "\nOpen Images below to download the original.")
            )
        elif event["kind"] == "error":
            blocks.append(("⚠️ Core · Error", literal(p.get("text", "Unknown error"))))
        elif event["kind"] == "question":
            for question in p.get("questions", []):
                lines = [question["question"]]
                lines += [
                    f"• {o['label']}: {o.get('description', '')}" for o in question.get("options") or []
                ]
                blocks.append(("❔ Codex · Question", literal("\n".join(lines))))
            if not p.get("questions"):
                blocks.append(
                    ("❔ Codex · Question", literal(str(p.get("message") or p.get("url") or "MCP request")))
                )
        elif event["kind"] == "completed" and p.get("status") != "completed":
            error = p.get("error") or {}
            blocks.append(
                (
                    "⚠️ Core · Status",
                    literal(p.get("text") or error.get("message") or p["status"].capitalize()),
                )
            )
    if live:
        for parts in live.get("summaries", {}).values():
            for key in sorted(parts, key=int):
                append_progress(parts[key])
    if len(blocks) == 1:
        if not compact:
            blocks.append(("🤖 Codex", "Waiting for a response…"))
    if view == "request":
        blocks = blocks[:1]
    elif view == "answer":
        blocks = [block for block in blocks[1:] if "Progress" not in block[0] and "Reasoning" not in block[0]]
        if not blocks:
            if compact:
                commentary = [
                    e["payload"].get("text", "")
                    for e in conversation["replies"]
                    if e["kind"] == "message" and e["payload"].get("phase") == "commentary"
                ]
                if commentary:
                    body = formatted(commentary[-1])
                    return (split_html(body, 3000) if rich else split_text(body, 3000)) or [""]
                return [""]
            blocks = [
                (
                    "🤖 Codex · Answer",
                    "Working… The answer will appear here." if live else "No answer for this request yet.",
                )
            ]
    elif view == "progress":
        blocks = [block for block in blocks[1:] if "Progress" in block[0] or "Reasoning" in block[0]]
        if not blocks:
            if compact:
                return [""]
            blocks = [("💬 Codex · Progress", "No public progress for this request.")]
    pages = []
    page = ""
    divider = "\n\n━━━━━━━━━━━━━━━━\n\n"
    length = html_length if rich else lambda value: len(value.encode("utf-16-le")) // 2
    for label, body in blocks:
        chunks = (split_html(body, 3000) if rich else split_text(body, 3000)) or [""]
        for index, chunk in enumerate(chunks, 1):
            heading = f"<b>{label}</b>" if rich else label
            if len(chunks) > 1:
                heading += f" <i>({index}/{len(chunks)})</i>" if rich else f" ({index}/{len(chunks)})"
            block = chunk if compact and label == "🤖 Codex · Answer" else heading + "\n\n" + chunk
            combined = page + divider + block if page else block
            if page and length(combined) > 3200:
                pages.append(page)
                page = block
            else:
                page = combined
    if page:
        pages.append(page)
    return pages


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


def quota_summary(data: dict, *, compact: bool = False) -> str:
    if not data.get("available"):
        return "Limits are unavailable from Codex."
    buckets = data.get("rateLimitsByLimitId") or {"codex": data.get("rateLimits")}
    sections = []
    for key, bucket in buckets.items():
        if not bucket:
            continue
        windows = []
        for field in ("primary", "secondary"):
            window = bucket.get(field)
            if not window:
                continue
            minutes = window.get("windowDurationMins")
            duration = (
                (
                    f"{minutes // 1440}d"
                    if minutes % 1440 == 0
                    else f"{minutes // 60}h"
                    if minutes % 60 == 0
                    else f"{minutes}m"
                )
                if minutes
                else field.title()
            )
            used = window.get("usedPercent")
            remaining = (
                f"{max(0, min(100, 100 - used)):g}% left"
                if isinstance(used, (int, float))
                else "Usage unavailable"
            )
            reset = timestamp(window.get("resetsAt"))
            windows.append(f"{duration} · <b>{remaining}</b>\n↳ Reset: {escape(reset)}")
        if windows:
            title = bucket.get("limitName") or bucket.get("limitId") or key
            sections.append(f"<b>{escape(title)}</b>\n" + "\n".join(windows))
        if compact and sections:
            break
    return "\n\n".join(sections) or "No quota windows were returned by Codex."
