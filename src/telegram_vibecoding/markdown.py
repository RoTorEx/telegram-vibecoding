"""Parse agent Markdown and page safe Telegram HTML without breaking entities."""

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from markdown_it import MarkdownIt

PARSER = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def inline(tokens) -> str:
    result = []
    links = []
    tags = {"strong": "b", "em": "i", "s": "s"}
    for token in tokens or []:
        kind = token.type
        if kind == "text":
            result.append(escape(token.content, quote=False))
        elif kind == "code_inline":
            result.append("<code>" + escape(token.content, quote=False) + "</code>")
        elif kind in {"softbreak", "hardbreak"}:
            result.append("\n")
        elif kind == "link_open":
            url = token.attrGet("href") or ""
            try:
                allowed = urlsplit(url).scheme.lower() in {"http", "https", "tg", "mailto"}
            except ValueError:
                allowed = False
            links.append((allowed, url))
            if allowed:
                result.append('<a href="' + escape(url, quote=True) + '">')
        elif kind == "link_close":
            allowed, url = links.pop()
            result.append("</a>" if allowed else " (" + escape(url, quote=False) + ")")
        elif kind == "image":
            result.append("[Image: " + escape(token.content, quote=False) + "]")
        elif kind.rsplit("_", 1)[0] in tags:
            name, action = kind.rsplit("_", 1)
            result.append(("</" if action == "close" else "<") + tags[name] + ">")
        elif token.content:
            result.append(escape(token.content, quote=False))
    return "".join(result)


def table(tokens) -> str:
    rows: list[list[str]] = []
    cells: list[str] = []
    for token in tokens:
        if token.type == "tr_open":
            cells = []
        elif token.type == "inline":
            cells.append(inline(token.children))
        elif token.type == "tr_close":
            rows.append(cells)
    if not rows:
        return ""
    headers, *body = rows
    result = [" · ".join(headers)]
    for cells in body:
        if not cells:
            continue
        if len(cells) == 2:
            result.append("• " + cells[0] + " — " + cells[1])
        else:
            lines = ["• " + cells[0]]
            lines += [
                "  " + (headers[i] + ": " if i < len(headers) else "") + value
                for i, value in enumerate(cells[1:], 1)
            ]
            result.append("\n".join(lines))
    return "\n\n".join(result) + "\n\n"


def render_markdown(text: str) -> str:
    tokens = PARSER.parse(text)
    result = []
    lists: list[int | None] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        kind = token.type
        if kind == "table_open":
            end = next(i for i in range(index + 1, len(tokens)) if tokens[i].type == "table_close")
            result.append(table(tokens[index + 1 : end]))
            index = end
        elif kind == "inline":
            result.append(inline(token.children))
        elif kind == "heading_open":
            result.append("<b>")
        elif kind == "heading_close":
            result.append("</b>\n\n")
        elif kind == "paragraph_close":
            result.append("\n" if lists else "\n\n")
        elif kind in {"bullet_list_open", "ordered_list_open"}:
            lists.append(int(token.attrGet("start") or 1) if kind == "ordered_list_open" else None)
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            lists.pop()
            result.append("\n")
        elif kind == "list_item_open":
            number = lists[-1]
            result.append("  " * (len(lists) - 1) + ("• " if number is None else f"{number}. "))
            if number is not None:
                lists[-1] = number + 1
        elif kind in {"fence", "code_block"}:
            result.append("<pre>" + escape(token.content, quote=False) + "</pre>\n\n")
        elif kind == "blockquote_open":
            result.append("<blockquote>")
        elif kind == "blockquote_close":
            result.append("</blockquote>\n\n")
        elif kind == "hr":
            result.append("────────\n\n")
        elif token.content:
            result.append(escape(token.content, quote=False))
        index += 1
    return "".join(result).strip() + ("\n" if text.endswith("\n") else "")


class HTMLRuns(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str]] = []
        self.runs: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    def handle_starttag(self, tag, attrs):
        source = self.get_starttag_text()
        assert source is not None
        self.stack.append((tag, source))

    def handle_endtag(self, tag):
        assert self.stack and self.stack[-1][0] == tag
        self.stack.pop()

    def handle_data(self, data):
        tags = self.stack
        if any(tag in {"pre", "code"} for tag, _ in tags):
            tags = [(tag, source) for tag, source in tags if tag in {"pre", "code"}]
        # Telegram blockquotes cannot nest; preserve their contents in one quote.
        seen_quote = False
        normalized = []
        for tag, source in tags:
            if tag == "blockquote":
                if seen_quote:
                    continue
                seen_quote = True
            normalized.append((tag, source))
        self.runs.append((data, tuple(normalized)))


def html_length(text: str) -> int:
    parser = HTMLRuns()
    parser.feed(text)
    return sum(len(value.encode("utf-16-le")) // 2 for value, _ in parser.runs)


def split_html(text: str, limit: int = 3200) -> list[str]:
    parser = HTMLRuns()
    parser.feed(text)
    pages = []
    pieces: list[str] = []
    active: tuple[tuple[str, str], ...] = ()
    used = 0

    def close_tags():
        pieces.extend("</" + tag + ">" for tag, _ in reversed(active))

    for value, tags in parser.runs:
        for char in value:
            units = 2 if ord(char) > 0xFFFF else 1
            if used + units > limit:
                close_tags()
                pages.append("".join(pieces))
                pieces = []
                active = ()
                used = 0
            if tags != active:
                close_tags()
                pieces.extend(source for _, source in tags)
                active = tags
            pieces.append(escape(char, quote=False))
            used += units
    if used:
        close_tags()
        pages.append("".join(pieces))
    return pages or [""]
