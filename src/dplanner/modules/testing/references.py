"""What a test body means when it says ``T101``, and how that becomes something to click.

A test is written in prose and prose points at other tests — *run this after T101*, *the
fixture T104 leaves behind*. Until this existed the reader had the id and nothing to do
with it: ids are minted per project and were printed nowhere in the roster, so following a
reference meant opening tests until the right one turned up.

**A reference is a bare id that the project actually has.** ``T`` and digits, on its own
word boundaries (``aspect.TEST_ID_PREFIX``, and the shape ``aspect.next_numbered`` mints),
and linked only when a test of that id is in the **same project** — an id is unique inside
a project and means nothing outside it, so there is no such thing as a reference to a test
in another plan. ``T999`` that nobody minted stays plain words, which is the honest answer:
a dead link is worse than no link, and a body may legitimately quote an id from a spec
whose tests have not been written yet.

**The linking is done to the rendered HTML, not to the markdown.** ``core/markdown.py``
escapes every piece of user text and lifts code spans, links and images out before anything
else runs, so by the time a body is HTML the only ``<`` in it opens one of our own tags —
which is exactly what makes walking it safe. Doing it to the source instead would put an
anchor inside a fenced block, inside a URL, and inside the text of a link that already goes
somewhere else. So this leaves every tag alone and skips the text inside ``<a>``, ``<code>``
and ``<pre>``: an id in a code span is a *quotation* of an id, which is how a body writes
about the shape of one rather than about a test.

Qt-free on purpose (``tests/test_architecture.py``'s ``HEADLESS_FILES``): it is text in and
text out, and the export is the next reader that would want it.
"""

import re
from collections.abc import Iterable
from html import escape

from dplanner.modules.testing.aspect import TEST_ID_PREFIX

# A bare id, on word boundaries: "XT100" and "T100a" are words of their own, not references.
REFERENCE = re.compile(rf"\b{TEST_ID_PREFIX}\d+\b")
# The scheme a reference is linked with. Its own, so a viewer can tell one from the http
# links in the same body by asking the URL rather than by matching the text again.
LINK_SCHEME = "dplanner-test"
# Text inside these is left alone: a link already points somewhere, and code quotes an id
# rather than using one.
INERT_TAGS = ("a", "code", "pre")
_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>|<[^>]*>")


def mentions(body: str) -> bool:
    """Whether ``body`` says anything shaped like a test id.

    The cheap question, asked before the expensive one: resolving references means knowing
    every id in the project, and most bodies name none, so a reader walks the project only
    for the bodies that could use the answer.
    """
    return REFERENCE.search(body) is not None


def link_url(test_id: str) -> str:
    return f"{LINK_SCHEME}:{test_id}"


def linked_test(url: str) -> str:
    """The test a link made here names, or "" for a link that was not made here."""
    scheme, _, rest = url.partition(":")
    return rest if scheme == LINK_SCHEME and REFERENCE.fullmatch(rest) else ""


def link_tests(html: str, known: Iterable[str]) -> str:
    """``html`` with every reference to one of ``known`` turned into an anchor."""
    ids = {found for found in known if REFERENCE.fullmatch(found)}
    if not ids:
        return html

    def anchor(match: re.Match[str]) -> str:
        found = match[0]
        if found not in ids:
            return found
        return f'<a href="{escape(link_url(found), quote=True)}">{found}</a>'

    out: list[str] = []
    at = 0
    inert = 0  # How deep inside an element whose text is left alone.
    for tag in _TAG.finditer(html):
        text = html[at : tag.start()]
        out.append(text if inert else REFERENCE.sub(anchor, text))
        out.append(tag[0])
        at = tag.end()
        if tag[2] and tag[2].lower() in INERT_TAGS:
            # Never below nought: an unbalanced closing tag would otherwise leave the rest
            # of the document linkable inside its own code spans.
            inert = max(0, inert - 1) if tag[1] else inert + 1
    tail = html[at:]
    out.append(tail if inert else REFERENCE.sub(anchor, tail))
    return "".join(out)
