from html.parser import HTMLParser

from telegram_vibecoding.markdown import html_length, render_markdown, split_html
from telegram_vibecoding.presentation import conversation_parts


class CheckedHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = ""
        self.tags = []
        self.feed(html)
        assert not self.stack

    def handle_starttag(self, tag, attrs):
        assert tag in {"b", "i", "s", "code", "pre", "a", "blockquote"}
        self.stack.append(tag)
        self.tags.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        assert self.stack.pop() == tag

    def handle_data(self, value):
        self.text += value


def test_screenshot_style_table_becomes_readable_rows_with_telegram_entities():
    source = """Now **16 containers** are running.

| Service | Purpose |
|---|---|
| `core`, `bot` | Agents & Telegram |
| VPN | **WireGuard** |

See [details](https://example.com/?x=1&y=2).
"""
    parsed = CheckedHTML("".join(split_html(render_markdown(source))))
    assert "**" not in parsed.text and "|" not in parsed.text and "`" not in parsed.text
    assert "• core, bot — Agents & Telegram" in parsed.text
    assert "• VPN — WireGuard" in parsed.text
    assert ("b", {}) in parsed.tags and ("code", {}) in parsed.tags
    assert ("a", {"href": "https://example.com/?x=1&y=2"}) in parsed.tags


def test_pages_balance_formatting_and_preserve_unicode_code_and_escaped_text():
    source = "**" + "Bold 🚀 & " * 700 + "**\n\n```python\n" + "print('<tag> & 🚀')\n" * 400 + "```"
    rendered = render_markdown(source)
    pages = split_html(rendered)
    assert len(pages) > 2
    assert "".join(CheckedHTML(page).text for page in pages) == CheckedHTML(rendered).text
    assert all(html_length(page) <= 3200 for page in pages)
    assert any("<pre>" in page for page in pages[1:])
    assert "print('<tag> & 🚀')" in CheckedHTML(rendered).text


def test_user_input_is_literal_and_raw_answer_is_unchanged():
    raw = "# Result\n\n**Done** <script>alert(1)</script>\n\n~~old~~ *new* `x < y`"
    conversation = {
        "user": {"payload": {"text": "**literal** <b>&</b>"}},
        "replies": [{"kind": "message", "payload": {"text": raw}}],
    }
    pages = conversation_parts(conversation, rich=True)
    parsed = CheckedHTML("".join(pages))
    assert "**literal** <b>&</b>" in parsed.text
    assert "<script>alert(1)</script>" in parsed.text
    assert "<script>" not in "".join(pages)
    assert conversation["replies"][0]["payload"]["text"] == raw
    assert {tag for tag, _ in parsed.tags} >= {"b", "i", "s", "code"}


def test_table_multiple_columns_lists_and_unfinished_stream_are_safe():
    source = """| Name | Model | State |
|---|---|---|
| A | Sol | Ready |

1. First
2. Second

> Quoted **text**

**unfinished
"""
    parsed = CheckedHTML("".join(split_html(render_markdown(source))))
    assert "Model: Sol" in parsed.text and "State: Ready" in parsed.text
    assert "1. First" in parsed.text and "2. Second" in parsed.text
    assert "Quoted text" in parsed.text and "unfinished" in parsed.text
