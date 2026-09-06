"""Rendering DPlanner's markdown subset as safe HTML, with nothing but the standard library.

Descriptions, handoffs, decisions and test bodies are markdown, and a single-file HTML
report needs them as HTML on a machine with no Qt and no markdown library — the CLI's
rule. The window renders the same text through Qt's ``QTextDocument``
(``framework/markdown_view.py``); this is its headless twin, written for a page that a
browser will open, so the output has to be safe to paste in verbatim. **Every piece of
user text is escaped**, in attributes too; a link is a link only for ``http:``, ``https:``
and ``mailto:``, and anything else — a relative asset path, ``javascript:``, ``file:`` —
renders as its text alone; an image is asked for through a callback and omitted when the
caller has none. Deterministic: the same text renders the same bytes. It never raises:
what it cannot read is a paragraph, escaped.

The subset is what the fields actually hold: fenced code, ATX headings, rules,
blockquotes, lists nested one level, GFM tables and paragraphs with hard breaks; inline
code, strong, emphasis, strikethrough, images, links, autolinks and backslash escapes.
Indented (four-space) code blocks are deliberately not supported — an indented line is
paragraph text — because in prose typed into a text field an indent is far more often an
accident than a listing, and a fence says what it means. HTML in the source is text, and
so is an entity: ``&copy;`` renders as those six characters, never as the sign.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape
from typing import Final

ImageSource = Callable[[str], str | None]
"""Asked for every ``![alt](src)``: the ``src`` to emit — a data URI, typically — or None
to omit the image."""

# Deeper than any prose quotes; the guard is what lets a wall of ">" not recurse to death.
_MAX_QUOTE_DEPTH: Final = 16

# Block openers, each matched against one line.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"[ \t]+#+$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*))?$")
_OPENERS: Final = (_FENCE, _HEADING, _RULE, _QUOTE, _ITEM)
_DELIMITER_CELL = re.compile(r"^:?-+:?$")
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")

# Inline. Code, escapes, images and links are lifted out first (see _inline); the emphasis
# family runs over what is left, in this order, so ** is never read as two *.
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.DOTALL)
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|<>])")
# A destination allows one level of balanced parentheses, then an optional "title".
_DESTINATION = r'((?:[^()\s]|\([^()\s]*\))*)(?:\s+"[^"]*")?\)'
_IMAGE = re.compile(r"!\[([^\]]*)\]\(" + _DESTINATION)
_LINK = re.compile(r"\[([^\]]*)\]\(" + _DESTINATION)
_AUTOLINK = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.-]*:[^\s<>]*)>")
_SAFE_URL = re.compile(r"^(https?|mailto):", re.IGNORECASE)
_HARD_BREAK = re.compile(r"(?: {2,}|\\)\n")
_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")
_TAG = re.compile(r"<[^>]*>")  # In rendered text every "<" opens one of our own tags.
_SPANS: Final = (
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.DOTALL), "strong"),
    (re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)", re.DOTALL), "strong"),
    (re.compile(r"\*(?=[^\s*])(.+?)(?<=[^\s*])\*", re.DOTALL), "em"),
    # An underscore inside a word, as in snake_case, is a letter.
    (re.compile(r"(?<!\w)_(?=[^\s_])(.+?)(?<=[^\s_])_(?!\w)", re.DOTALL), "em"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL), "del"),
)


def render(text: str, *, image_src: ImageSource | None = None) -> str:
    """``text`` as HTML; ``""`` when there is nothing to say."""
    if not text.strip():
        return ""
    # U+0000 cannot appear in HTML, which is what lets the inline pass use it as a marker.
    clean = text.replace("\x00", "\ufffd").replace("\r\n", "\n").replace("\r", "\n")
    return _blocks(clean.split("\n"), image_src)


def _blocks(lines: list[str], image_src: ImageSource | None, depth: int = 0) -> str:
    out: list[str] = []
    at = 0
    while at < len(lines):
        line = lines[at]
        if not line.strip():
            at += 1
            continue
        if fence := _FENCE.match(line):
            html, at = _code_block(lines, at, fence)
        elif heading := _HEADING.match(line):
            html, at = _heading(heading, image_src), at + 1
        elif _RULE.match(line):
            html, at = "<hr>", at + 1
        elif _QUOTE.match(line):
            html, at = _blockquote(lines, at, image_src, depth)
        elif item := _ITEM.match(line):
            html, at = _list(lines, at, item, image_src)
        elif _table_at(lines, at):
            html, at = _table(lines, at, image_src)
        else:
            html, at = _paragraph(lines, at, image_src)
        out.append(html)
    return "\n".join(out)


def _opens_block(lines: list[str], at: int) -> bool:
    """Whether the line starts something a paragraph, a list or a table must yield to."""
    line = lines[at]
    if not line.strip():
        return True
    return any(pattern.match(line) for pattern in _OPENERS) or _table_at(lines, at)


def _code_block(lines: list[str], at: int, fence: re.Match[str]) -> tuple[str, int]:
    marker, info = fence[1], fence[2]
    end = at + 1
    while end < len(lines) and not _closes(lines[end], marker):
        end += 1
    body = "".join(escape(line) + "\n" for line in lines[at + 1 : end])
    language = f' class="language-{escape(info)}"' if info else ""
    return f"<pre><code{language}>{body}</code></pre>", min(end + 1, len(lines))


def _closes(line: str, marker: str) -> bool:
    """A closing fence: the opener's character, at least as many of it, and nothing else."""
    candidate = line.strip()
    return candidate.startswith(marker) and not candidate.strip(marker[0])


def _heading(heading: re.Match[str], image_src: ImageSource | None) -> str:
    level = len(heading[1])
    title = _CLOSING_HASHES.sub("", heading[2] or "")
    return f"<h{level}>{_inline(title, image_src)}</h{level}>"


def _blockquote(
    lines: list[str], at: int, image_src: ImageSource | None, depth: int
) -> tuple[str, int]:
    inner: list[str] = []
    while at < len(lines) and (quoted := _QUOTE.match(lines[at])):
        inner.append(quoted[1])
        at += 1
    if depth < _MAX_QUOTE_DEPTH:
        body = _blocks(inner, image_src, depth + 1)
    else:
        body = f"<p>{escape(' '.join(inner).strip())}</p>"
    return f"<blockquote>\n{body}\n</blockquote>", at


@dataclass
class _Item:
    marker: str
    text: list[str]
    nested: list["_Item"] = field(default_factory=list)


def _list(
    lines: list[str], at: int, first: re.Match[str], image_src: ImageSource | None
) -> tuple[str, int]:
    """Items at the first item's indent, each carrying the items indented two or more
    spaces under it as one nested list. A blank line ends the list unless another item
    follows; a different marker starts a new list."""
    base = len(first[1])
    items: list[_Item] = []
    while at < len(lines):
        line = lines[at]
        if not line.strip():
            following = next((i for i in range(at, len(lines)) if lines[i].strip()), None)
            if following is None or not _ITEM.match(lines[following]):
                break
            at = following
            continue
        item = _ITEM.match(line)
        if item and len(item[1]) < base + 2:
            if items and item[2][-1] != items[0].marker[-1]:
                break
            items.append(_Item(item[2], [item[3] or ""]))
        elif item:
            items[-1].nested.append(_Item(item[2], [item[3] or ""]))
        elif _opens_block(lines, at):
            break
        else:
            last = items[-1].nested[-1] if items[-1].nested else items[-1]
            last.text.append(line.lstrip())
        at += 1
    return _list_html(items, image_src), at


def _list_html(items: list[_Item], image_src: ImageSource | None) -> str:
    marker = items[0].marker
    ordered = marker[0].isdigit()
    tag = "ol" if ordered else "ul"
    start = int(marker[:-1]) if ordered else 1
    parts = [f'<ol start="{start}">' if start != 1 else f"<{tag}>"]
    for item in items:
        body = _inline("\n".join(item.text).rstrip(), image_src)
        if item.nested:
            body += "\n" + _list_html(item.nested, image_src)
        parts.append(f"<li>{body}</li>")
    parts.append(f"</{tag}>")
    return "\n".join(parts)


def _table_at(lines: list[str], at: int) -> bool:
    """A header row over a delimiter row with the same number of cells."""
    if at + 1 >= len(lines) or "|" not in lines[at]:
        return False
    delimiters = _cells(lines[at + 1])
    return len(delimiters) == len(_cells(lines[at])) and all(
        _DELIMITER_CELL.match(cell) for cell in delimiters
    )


def _table(lines: list[str], at: int, image_src: ImageSource | None) -> tuple[str, int]:
    aligns = [_alignment(cell) for cell in _cells(lines[at + 1])]
    head = _row(_cells(lines[at]), aligns, "th", image_src)
    at += 2
    body: list[str] = []
    while at < len(lines) and "|" in lines[at] and not _opens_block(lines, at):
        body.append(_row(_cells(lines[at]), aligns, "td", image_src))
        at += 1
    parts = ["<table>", "<thead>", head, "</thead>"]
    if body:
        parts += ["<tbody>", *body, "</tbody>"]
    parts.append("</table>")
    return "\n".join(parts), at


def _cells(line: str) -> list[str]:
    row = line.strip().removeprefix("|")
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(row)]


def _alignment(delimiter: str) -> str:
    """The class a column's cells carry; left alignment is the default and carries none."""
    left, right = delimiter.startswith(":"), delimiter.endswith(":")
    if left and right:
        return "center"
    return "right" if right else ""


def _row(cells: list[str], aligns: list[str], tag: str, image_src: ImageSource | None) -> str:
    padded = (cells + [""] * len(aligns))[: len(aligns)]
    parts: list[str] = []
    for cell, align in zip(padded, aligns, strict=True):
        attribute = f' class="{align}"' if align else ""
        parts.append(f"<{tag}{attribute}>{_inline(cell, image_src)}</{tag}>")
    return f"<tr>{''.join(parts)}</tr>"


def _paragraph(lines: list[str], at: int, image_src: ImageSource | None) -> tuple[str, int]:
    end = at + 1
    while end < len(lines) and not _opens_block(lines, end):
        end += 1
    text = "\n".join(line.lstrip() for line in lines[at:end]).rstrip()
    return f"<p>{_inline(text, image_src)}</p>", end


def _inline(text: str, image_src: ImageSource | None) -> str:
    """Inline markdown as HTML. Code spans, escapes, images and links are lifted out in
    that order — nothing applies inside them, and their HTML must not be escaped again —
    each leaving a placeholder that stands for both what was typed and what it renders
    as; the emphasis pass runs over what remains, and the placeholders are put back."""
    lifted: list[tuple[str, str]] = []

    def typed(text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: lifted[int(m[1])][0], text)

    def rendered(text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: lifted[int(m[1])][1], text)

    def keep(match: re.Match[str], html: str) -> str:
        lifted.append((typed(match[0]), html))
        return f"\x00{len(lifted) - 1}\x00"

    def destination(text: str) -> str:
        return _ESCAPED.sub(r"\1", typed(text))  # As typed, minus its backslash escapes.

    def image(m: re.Match[str]) -> str:
        alt = _TAG.sub("", rendered(_markup(m[1])))  # An alt is its content's plain text.
        return keep(m, _image_html(alt, destination(m[2]), image_src))

    def link(m: re.Match[str]) -> str:
        return keep(m, _link_html(rendered(_markup(m[1])), destination(m[2])))

    def autolink(m: re.Match[str]) -> str:
        url = destination(m[1])
        return keep(m, _link_html(escape(url), url))

    text = _CODE_SPAN.sub(lambda m: keep(m, f"<code>{escape(m[2].strip())}</code>"), text)
    text = _ESCAPED.sub(lambda m: keep(m, escape(m[1])), text)
    text = _IMAGE.sub(image, text)
    text = _LINK.sub(link, text)
    text = _AUTOLINK.sub(autolink, text)
    return rendered(_markup(text))


def _markup(text: str) -> str:
    """Escaped text with the emphasis family and hard breaks applied."""
    text = escape(text)
    for pattern, tag in _SPANS:
        text = pattern.sub(rf"<{tag}>\1</{tag}>", text)
    return _HARD_BREAK.sub("<br>\n", text)


def _image_html(alt: str, src: str, image_src: ImageSource | None) -> str:
    """``alt`` is rendered text already; ``src`` is the raw destination."""
    resolved = image_src(src) if image_src else None
    if resolved is None:
        label = f"{alt} (image omitted)".strip()
        return f'<span class="md-image-missing">{label}</span>'
    return f'<img alt="{alt}" src="{escape(resolved)}">'


def _link_html(text: str, url: str) -> str:
    """``text`` is rendered HTML already; ``url`` is the raw destination."""
    if _SAFE_URL.match(url):
        return f'<a href="{escape(url)}" rel="noopener" target="_blank">{text}</a>'
    return f'<span class="md-link-inert">{text}</span>'
