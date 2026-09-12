"""Confluence storage format (XHTML with ``ac:`` and ``ri:`` elements) to markdown.

The parser is the standard library's ``html.parser`` — no entity or DTD expansion, no
network, and a namespaced tag like ``ac:image`` is just a tag name to it. What it builds
is a small tree, capped in depth, that :func:`convert` walks once. The output is markdown
a person reads and an agent quotes, and it keeps three promises the tests pin:

- **No raw HTML.** Every character of text is escaped so it can never open a tag or an
  unintended construct; ``<script>`` and its kin are dropped with their contents.
- **A link is ``http(s)`` or ``mailto``, or it is text.** Sibling pages are linked by the
  absolute URL the caller hands in; ``javascript:`` and ``file:`` never survive.
- **An image is a name the caller will write.** ``ac:image`` resolves through the
  ``images`` map (attachment filename → ``assets/<sha16><suffix>``); an attachment not in
  the map, and every ``ri:url`` image, becomes words — nothing here fetches anything.

Macros that carry their content (code, panels, expand, excerpt, tasks) are rendered;
dynamic ones (jira, toc, include, children, drawio…) have no content in storage and
become a labelled placeholder, with the drawio/gliffy preview image embedded when the
page carries one. Everything unknown is rendered as its text, so nothing is lost silently.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html import escape as html_escape
from html.parser import HTMLParser

MAX_DEPTH = 64  # Elements nested deeper than this are read as text of their ancestor.

_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]\s*>", re.DOTALL)
_SAFE_LINK = re.compile(r"^(https?|mailto):", re.IGNORECASE)
_VOID = frozenset({"br", "hr", "img", "col", "input", "meta", "link", "wbr"})
_DROPPED = frozenset({"script", "style", "iframe", "object", "embed", "noscript", "ac:placeholder"})
_TRANSPARENT = frozenset(
    {
        "div",
        "span",
        "section",
        "article",
        "font",
        "ac:layout",
        "ac:layout-section",
        "ac:layout-cell",
        "ac:inline-comment-marker",
        "ac:rich-text-body",
        "ac:link-body",
        "ac:task-body",
        "tbody",
        "thead",
        "tfoot",
        "colgroup",
        "ac:adf-content",
        "ac:adf-node",
    }
)
_PANELS = {
    "info": "Info",
    "note": "Note",
    "warning": "Warning",
    "tip": "Tip",
    "panel": "Panel",
    "expand": "Expand",
}
_ESCAPED = str.maketrans({c: f"\\{c}" for c in "\\*`[]<>"})


@dataclass
class _Node:
    tag: str  # "" for text.
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node"] = field(default_factory=list)
    text: str = ""

    def find(self, tag: str) -> "_Node | None":
        for child in self.children:
            if child.tag == tag:
                return child
            found = child.find(tag)
            if found is not None:
                return found
        return None

    def parameter(self, name: str) -> str:
        for child in self.children:
            if child.tag == "ac:parameter" and child.attrs.get("ac:name") == name:
                return _plain(child)
        return ""


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {key: value or "" for key, value in attrs})
        if len(self._stack) > MAX_DEPTH:
            return  # Too deep to matter: what it holds still arrives as text.
        self._stack[-1].children.append(node)
        if tag not in _VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self._stack) > MAX_DEPTH:
            return
        self._stack[-1].children.append(_Node(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(_Node("", text=data))


def parse(storage: str) -> _Node:
    """The element tree of a storage body. CDATA is folded into text before parsing so
    the result does not depend on how this Python's parser treats it."""
    builder = _TreeBuilder()
    builder.feed(_CDATA.sub(lambda m: html_escape(m.group(1), quote=False), storage))
    builder.close()
    return builder.root


def attachment_names(storage: str) -> list[str]:
    """Every attachment filename the body shows as an image, in order — what a fetch
    downloads. Diagram macros count through their preview image (``<name>.png``)."""
    names: list[str] = []

    def walk(node: _Node) -> None:
        if node.tag == "ac:image":
            ref = node.find("ri:attachment")
            if ref is not None and ref.attrs.get("ri:filename"):
                names.append(ref.attrs["ri:filename"])
        elif node.tag == "ac:structured-macro":
            preview = _diagram_preview(node)
            if preview:
                names.append(preview)
        for child in node.children:
            walk(child)

    walk(parse(storage))
    return list(dict.fromkeys(names))


def convert(storage: str, images: Mapping[str, str], pages: Mapping[str, str]) -> str:
    """Markdown for ``storage``. ``images`` maps an attachment filename to the
    ``assets/…`` name the caller writes it under; ``pages`` maps a page title to the
    absolute URL a sibling link opens."""
    renderer = _Renderer(images, pages)
    blocks = renderer.blocks(parse(storage))
    text = "\n\n".join(block for block in blocks if block.strip())
    return text.rstrip() + "\n" if text.strip() else ""


class _Renderer:
    def __init__(self, images: Mapping[str, str], pages: Mapping[str, str]) -> None:
        self._images = images
        self._pages = pages

    # -- blocks ------------------------------------------------------------------------------

    def blocks(self, node: _Node) -> list[str]:
        """The children of ``node`` as markdown blocks: runs of inline content become
        paragraphs; block elements render on their own."""
        out: list[str] = []
        run: list[_Node] = []

        def flush() -> None:
            if run:
                paragraph = self.inline(run).strip()
                if paragraph:
                    out.append(_lead_safe(paragraph))
                run.clear()

        for child in node.children:
            if child.tag in _DROPPED:
                continue
            if child.tag in _TRANSPARENT and self._has_block(child):
                flush()
                out.extend(self.blocks(child))
            elif self._is_block(child):
                flush()
                out.extend(self._block(child))
            else:
                run.append(child)
        flush()
        return out

    def _is_block(self, node: _Node) -> bool:
        if node.tag == "ac:structured-macro":
            return node.attrs.get("ac:name") != "status"
        return node.tag in _BLOCKS

    def _has_block(self, node: _Node) -> bool:
        """Whether anything block-level sits under ``node``, looking through the
        wrappers that are transparent to layout."""
        return any(
            self._is_block(child) or (child.tag in _TRANSPARENT and self._has_block(child))
            for child in node.children
        )

    def _block(self, node: _Node) -> list[str]:
        tag = node.tag
        if tag == "p":
            return (
                self.blocks(node)
                if _has_block(node)
                else [_lead_safe(self.inline(node.children).strip())]
            )
        if tag in _HEADINGS:
            return [f"{'#' * _HEADINGS[tag]} {self.inline(node.children).strip()}"]
        if tag in ("ul", "ol"):
            return [self._list(node, ordered=tag == "ol")]
        if tag == "ac:task-list":
            return [self._tasks(node)]
        if tag == "table":
            return [self._table(node)]
        if tag == "pre":
            return [_fenced(_plain(node), "")]
        if tag == "blockquote":
            return [_quoted("\n\n".join(self.blocks(node)))]
        if tag == "hr":
            return ["---"]
        if tag == "ac:image":
            return [self._image(node)]
        if tag == "ac:structured-macro":
            return self._macro(node)
        if tag in ("ac:adf-extension",):
            return ["> **Confluence element — not exported**"]
        return self.blocks(node)  # li, td and the rest: their content.

    def _list(self, node: _Node, *, ordered: bool) -> str:
        lines: list[str] = []
        number = 0
        for item in node.children:
            if item.tag != "li":
                continue
            number += 1
            marker = f"{number}." if ordered else "-"
            lines.append(_item(marker, self.blocks(item)))
        return "\n".join(lines)

    def _tasks(self, node: _Node) -> str:
        lines: list[str] = []
        for task in node.children:
            if task.tag != "ac:task":
                continue
            status = task.find("ac:task-status")
            done = status is not None and _plain(status).strip() == "complete"
            body = task.find("ac:task-body")
            blocks = self.blocks(body) if body is not None else []
            lines.append(_item("- [x]" if done else "- [ ]", blocks))
        return "\n".join(lines)

    def _table(self, node: _Node) -> str:
        rows: list[list[str]] = []
        headed = False
        for row in _rows(node):
            cells = [child for child in row.children if child.tag in ("td", "th")]
            if not rows and cells and all(cell.tag == "th" for cell in cells):
                headed = True
            rows.append([self._cell(cell) for cell in cells])
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        head = rows[0] if headed else [""] * width
        body = rows[1:] if headed else rows
        lines = [_row(head), "| " + " | ".join("---" for _ in range(width)) + " |"]
        lines.extend(_row(row) for row in body)
        return "\n".join(lines)

    def _cell(self, cell: _Node) -> str:
        text = " ".join(self.blocks(cell)).replace("\n", " ")
        return text.replace("|", "\\|").strip()

    def _image(self, node: _Node) -> str:
        alt = _escape(node.attrs.get("ac:alt", "") or node.attrs.get("ac:title", ""))
        ref = node.find("ri:attachment")
        if ref is not None:
            filename = ref.attrs.get("ri:filename", "")
            name = self._images.get(filename)
            if name:
                return f"![{alt or 'image'}]({name})"
            return f"*[image {_escape(filename)} — not exported]*"
        url = node.find("ri:url")
        if url is not None:
            return self._external_image(url.attrs.get("ri:value", ""))
        return ""

    def _external_image(self, href: str) -> str:
        if _SAFE_LINK.match(href):
            return f"*[external image]({_link(href)})*"
        return "*[external image]*"

    def _macro(self, node: _Node) -> list[str]:
        name = node.attrs.get("ac:name", "")
        body = node.find("ac:rich-text-body")
        if name in ("code", "noformat"):
            plain = node.find("ac:plain-text-body")
            return [_fenced(_plain(plain) if plain is not None else "", node.parameter("language"))]
        if name in _PANELS:
            title = node.parameter("title")
            heading = f"**{_PANELS[name]}{': ' + _escape(title) if title else ''}**"
            inner = self.blocks(body) if body is not None else []
            return [_quoted("\n\n".join([heading, *inner]))]
        if name in ("excerpt", "section", "column"):
            return self.blocks(body) if body is not None else []
        if name in ("anchor", "toc", "table-of-contents"):
            return []
        preview = _diagram_preview(node)
        if preview and preview in self._images:
            return [f"![{_escape(name)} diagram]({self._images[preview]})"]
        placeholder = f"> **Confluence macro `{_escape(name)}` — not exported**"
        if body is not None:
            inner = self.blocks(body)
            if inner:
                return [placeholder, _quoted("\n\n".join(inner))]
        return [placeholder]

    # -- inline ----------------------------------------------------------------------------

    def inline(self, nodes: list[_Node]) -> str:
        return "".join(self._span(node) for node in nodes)

    def _span(self, node: _Node) -> str:
        tag = node.tag
        if tag == "":
            return _escape(_collapse(node.text))
        if tag in _DROPPED:
            return ""
        if tag in ("strong", "b"):
            return _wrap(self.inline(node.children), "**")
        if tag in ("em", "i"):
            return _wrap(self.inline(node.children), "*")
        if tag in ("s", "del", "strike"):
            return _wrap(self.inline(node.children), "~~")
        if tag == "code":
            return _code(_plain(node))
        if tag == "br":
            return "  \n"
        if tag == "a":
            return self._anchor(node)
        if tag == "ac:link":
            return self._ac_link(node)
        if tag == "ac:image":
            return self._image(node)
        if tag == "img":
            return self._external_image(node.attrs.get("src", ""))
        if tag == "ac:emoticon":
            name = node.attrs.get("ac:emoji-shortname") or f":{node.attrs.get('ac:name', 'emoji')}:"
            return _escape(name)
        if tag == "time":
            return _escape(node.attrs.get("datetime", "") or _plain(node))
        if tag == "ac:structured-macro":
            if node.attrs.get("ac:name") == "status":
                return f"**[{_escape(node.parameter('title').upper() or 'STATUS')}]**"
            return " ".join(self._macro(node))
        if tag in _HEADINGS or tag in ("p", "li", "td", "th", "tr", "table", "ul", "ol"):
            return (
                " ".join(self.blocks(node))
                if tag in ("table", "ul", "ol")
                else self.inline(node.children)
            )
        return self.inline(node.children)

    def _anchor(self, node: _Node) -> str:
        text = self.inline(node.children).strip()
        href = node.attrs.get("href", "")
        if _SAFE_LINK.match(href):
            return f"[{text or _escape(href)}]({_link(href)})"
        return text or _escape(href)

    def _ac_link(self, node: _Node) -> str:
        label = ""
        body = node.find("ac:link-body")
        plain = node.find("ac:plain-text-link-body")
        if body is not None:
            label = self.inline(body.children).strip()
        elif plain is not None:
            label = _escape(_plain(plain).strip())
        page = node.find("ri:page")
        if page is not None:
            title = page.attrs.get("ri:content-title", "")
            url = self._pages.get(title)
            text = label or _escape(title)
            return f"[{text}]({_link(url)})" if url and _SAFE_LINK.match(url) else text
        attachment = node.find("ri:attachment")
        if attachment is not None:
            return label or _escape(attachment.attrs.get("ri:filename", "attachment"))
        user = node.find("ri:user")
        if user is not None:
            return label or "@user"
        external = node.find("ri:url")
        if external is not None:
            href = external.attrs.get("ri:value", "")
            if _SAFE_LINK.match(href):
                return f"[{label or _escape(href)}]({_link(href)})"
        return label


_BLOCKS = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ul",
        "ol",
        "li",
        "table",
        "tr",
        "td",
        "th",
        "pre",
        "blockquote",
        "hr",
        "ac:image",
        "ac:task-list",
        "ac:adf-extension",
    }
)
_HEADINGS = {f"h{n}": n for n in range(1, 7)}


def _has_block(node: _Node) -> bool:
    return any(
        child.tag in _BLOCKS or child.tag == "ac:structured-macro" for child in node.children
    )


def _rows(table: _Node) -> list[_Node]:
    rows: list[_Node] = []
    for child in table.children:
        if child.tag == "tr":
            rows.append(child)
        elif child.tag in ("thead", "tbody", "tfoot"):
            rows.extend(grandchild for grandchild in child.children if grandchild.tag == "tr")
    return rows


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _item(marker: str, blocks: list[str]) -> str:
    if not blocks:
        return marker
    indent = " " * (len(marker) + 1)
    first, *rest = blocks
    text = f"{marker} {first}".replace("\n", "\n" + indent)
    for block in rest:
        # A nested list hugs its item; any other block stands a line apart.
        gap = "\n" if re.match(r"^(-|\d+\.) ", block) else "\n\n"
        text += gap + indent + block.replace("\n", "\n" + indent)
    return text


def _quoted(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


def _fenced(code: str, language: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
    fence = "`" * max(3, longest + 1)
    lang = re.sub(r"[^a-zA-Z0-9+#.-]", "", language)
    return f"{fence}{lang}\n{code.strip(chr(10))}\n{fence}"


def _code(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * (longest + 1)
    return f"{ticks}{text}{ticks}" if text else ""


def _wrap(text: str, mark: str) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()) :]
    return f"{lead}{mark}{stripped}{mark}{trail}"


def _plain(node: _Node) -> str:
    """The text under ``node``, unescaped — for code, where markdown has no meaning."""
    if node.tag == "":
        return node.text
    return "".join(_plain(child) for child in node.children)


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _escape(text: str) -> str:
    """Text that cannot open HTML, a link, code, emphasis or a list."""
    escaped = text.translate(_ESCAPED)
    return re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", r"\\_", escaped)


def _lead_safe(paragraph: str) -> str:
    """A paragraph whose first characters would otherwise start a heading, a rule, a
    quote or a list item."""
    if re.match(r"^(#{1,6}\s|[-+*]\s|\d{1,9}[.)]\s|>|---|\+\+\+|===)", paragraph):
        return "\\" + paragraph
    return paragraph


def _link(href: str) -> str:
    return href.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _diagram_preview(macro: _Node) -> str:
    name = macro.attrs.get("ac:name", "")
    if name in ("drawio", "drawio-sketch"):
        diagram = macro.parameter("diagramName")
        return f"{diagram}.png" if diagram else ""
    if name == "gliffy":
        diagram = macro.parameter("name")
        return f"{diagram}.png" if diagram else ""
    return ""
