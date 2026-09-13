"""Where a quoted passage sits in a spec document — judged again on every read.

A feature cites a spec by **quoting** it: the quote is the anchor, and its place in the
document is never stored. Offsets would go stale on every keystroke of the in-app editor,
and a stored "found" would be wrong the moment `dplanner spec import` replaced the file
with no window running to notice — the same reason the topological order is computed and
not written down. So this module re-anchors on demand, in three tiers:

1. **exact** — the quote appears, case and whitespace aside (PDF extraction rewraps
   lines and loses ligatures; a check that failed on a line break would teach people to
   stop quoting). The hit maps back to raw offsets, which is what a viewer highlights.
2. **fuzzy** — it does not, but a passage *like* it does: seeded by the longest run the
   two share, sized like the quote, kept when it is at least :data:`DRIFT_RATIO` similar.
   That is the sentence somebody reworded, offered back as the candidate to accept.
3. **nothing** — the passage is gone.

A source may also carry the **digest** of the document it was read against. When the
document has changed since, an exact hit is only *anchored* if the paragraph holding the
quote is untouched between the two versions; otherwise it is *behind* — the passage is
there, but what surrounds it moved, and somebody should read it again. That comparison
is what keeps a typo fixed in §9 from flagging every citation in the document.

Everything here is pure text; the spec module reads the blobs and hands the strings in,
and the feature and coverage modules read the verdicts — which is why it lives in ``core``
beside ``text_diff.py`` rather than in any one of them.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from dplanner.core.text_diff import diff_hunks

type AnchorState = Literal["anchored", "behind", "drifted", "lost", "missing"]

# The shortest quote worth matching fuzzily — below this, any two sentences of English
# "match" — and what seeds the search: a word this long, the few rarest of them, and at
# most this many places to try.
FUZZY_MIN = 12
SEED_WORD = 4
SEED_WORDS = 3
SEEDS_AT_MOST = 60
# How similar a reworded passage must be to be offered as the drifted candidate.
DRIFT_RATIO = 0.6
# How far either end of the fuzzy window is tried out from its seeded place, as a share
# of the quote's length — a reworded sentence gains or loses a few words, not a paragraph.
WINDOW_PLAY = 0.25

PAGE_MARKER = "--- page "


@dataclass(frozen=True)
class Anchor:
    """One source's place in its document, as it reads now."""

    state: AnchorState
    start: int = -1  # Raw offsets into the document's text; -1 when there is no hit.
    end: int = -1
    page: int | None = None  # 1-based, PDFs only: where the hit is.
    candidate: str = ""  # drifted: the passage as it reads now, whitespace collapsed.
    ratio: float = 0.0  # drifted: how alike the candidate and the quote are.
    digest: str = ""  # The document as it is now — what a re-stamp would write.
    # Every page an exact hit recurs on: the same sentence can appear twice, and a
    # ``--page`` naming any occurrence is right, not a mismatch.
    pages: tuple[int, ...] = ()

    @property
    def found(self) -> bool:
        return self.state in ("anchored", "behind")


@dataclass(frozen=True)
class Block:
    """A paragraph, a heading, or a page's worth of text: the grain coverage is judged at."""

    start: int
    end: int
    heading: str  # The heading path above it, "Login > Rules"; "" at the top.
    page: int | None = None
    is_heading: bool = False


def normalised(text: str) -> tuple[str, list[int]]:
    """``text`` lower-cased with whitespace runs collapsed to one space, and for every
    character of the result the raw offset it came from (plus one past the end)."""
    out: list[str] = []
    back: list[int] = []
    pending_space = False
    for index, char in enumerate(text):
        if char.isspace():
            pending_space = bool(out)
            continue
        if pending_space:
            out.append(" ")
            back.append(index)
            pending_space = False
        for lowered in char.lower():
            out.append(lowered)
            back.append(index)
    back.append(len(text))
    return "".join(out), back


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """The raw ``(start, end)`` of the first place ``quote`` appears in ``text``, case and
    whitespace aside — None when it does not, or when the quote is blank."""
    needle, _ = normalised(quote)
    if not needle:
        return None
    haystack, back = normalised(text)
    hit = haystack.find(needle)
    if hit < 0:
        return None
    return back[hit], back[hit + len(needle) - 1] + 1


def locate_all(text: str, quote: str) -> list[tuple[int, int]]:
    """Every raw span where ``quote`` appears, case and whitespace aside, in order."""
    needle, _ = normalised(quote)
    if not needle:
        return []
    haystack, back = normalised(text)
    spans = []
    hit = haystack.find(needle)
    while hit >= 0:
        spans.append((back[hit], back[hit + len(needle) - 1] + 1))
        hit = haystack.find(needle, hit + 1)
    return spans


def locate_many(text: str, quotes: Sequence[str]) -> list[tuple[int, int, str]]:
    """Where each of ``quotes`` sits in ``text``, case and whitespace aside, in the order
    given; a quote that is blank or absent contributes nothing.

    :func:`locate` normalises the haystack inside itself, so asking it N times walks the
    document N times — a per-character Python loop each way. Every caller that had a list
    of quotes was paying that: the Specs tab washed its cited passages by looping over
    ``locate`` on every keystroke, which measured 15 ms a keystroke on a 24 KB document
    with eight citations. One normalisation, N finds.
    """
    haystack, back = normalised(text)
    found: list[tuple[int, int, str]] = []
    for quote in quotes:
        needle, _ = normalised(quote)
        if not needle:
            continue
        hit = haystack.find(needle)
        if hit < 0:
            continue
        found.append((back[hit], back[hit + len(needle) - 1] + 1, quote))
    return found


def fuzzy_locate(text: str, quote: str) -> tuple[int, int, float] | None:
    """The raw span of the passage most like ``quote``, and how alike it is — None when
    nothing in ``text`` reaches :data:`DRIFT_RATIO`.

    The quote's rarest words say where to look: a reworded sentence keeps most of its
    nouns, so every place one of them occurs seeds a window the size of the quote, each
    end is tried a little either side of that guess, and the best ratio wins. Cheap,
    since every ratio is over a string the size of the quote, and a few rare words seed
    only a handful of windows even in a long document.
    """
    needle, _ = normalised(quote)
    haystack, back = normalised(text)
    if len(needle) < FUZZY_MIN or not haystack:
        return None
    play = max(1, round(len(needle) * WINDOW_PLAY))
    steps = (-play, -play // 2, 0, play // 2, play)
    best: tuple[float, int, int] | None = None
    for guess in _seeds(haystack, needle):
        for start_delta in steps:
            start = _word_edge(haystack, guess + start_delta)
            for end_delta in steps:
                end = _word_edge(haystack, guess + len(needle) + end_delta)
                if end <= start:
                    continue
                ratio = SequenceMatcher(None, haystack[start:end], needle, autojunk=False).ratio()
                if best is None or ratio > best[0]:
                    best = (ratio, start, end)
    if best is None or best[0] < DRIFT_RATIO:
        return None
    ratio, start, end = best
    raw_start, raw_end = back[start], back[end - 1] + 1
    # A window never runs on into the next paragraph: the passage is one paragraph's.
    paragraph_end = text.find("\n\n", raw_start)
    if 0 <= paragraph_end < raw_end:
        raw_end = paragraph_end
    return raw_start, raw_end, ratio


def _seeds(haystack: str, needle: str) -> list[int]:
    """Where a window might start: every occurrence of the quote's rarest long words,
    shifted back by where the word sits in the quote."""
    words = {word for word in needle.split() if len(word) >= SEED_WORD}
    rarest = sorted(words, key=lambda word: (haystack.count(word), word))[:SEED_WORDS]
    seeds: list[int] = []
    for word in rarest:
        offset = needle.find(word)
        found = haystack.find(word)
        while found >= 0 and len(seeds) < SEEDS_AT_MOST:
            seeds.append(found - offset)
            found = haystack.find(word, found + 1)
    return sorted(set(seeds))


def _word_edge(text: str, index: int) -> int:
    """``index`` clamped into ``text`` and moved off the middle of a word."""
    index = max(0, min(len(text), index))
    while 0 < index < len(text) and text[index - 1] != " " and text[index] != " ":
        index -= 1
    return index


def page_at(layer: str, offset: int) -> int | None:
    """Which 1-based page of a PDF's text layer ``offset`` falls on; None before the
    first marker (a layer always starts with one)."""
    page = None
    for line_start, line in _lines(layer):
        if line_start > offset:
            break
        number = _page_number(line)
        if number is not None:
            page = number
    return page


def blocks(text: str, kind: str) -> list[Block]:
    """The document as paragraphs: split on blank lines, a markdown heading its own block
    carrying the path above it, a PDF's page markers folded into ``page``."""
    found: list[Block] = []
    path: list[tuple[int, str]] = []  # (level, title) of the headings above the cursor.
    page: int | None = None
    run_start: int | None = None
    run_end = 0

    def flush() -> None:
        nonlocal run_start
        if run_start is not None:
            found.append(Block(run_start, run_end, _heading_path(path), page))
            run_start = None

    for line_start, line in _lines(text):
        stripped = line.strip()
        number = _page_number(line) if kind == "pdf" else None
        if not stripped or number is not None:
            flush()
            if number is not None:
                page = number
            continue
        level = _heading_level(stripped) if kind == "markdown" else 0
        if level:
            flush()
            while path and path[-1][0] >= level:
                path.pop()
            title = stripped[level:].strip()
            found.append(Block(line_start, line_start + len(line), _heading_path(path), page, True))
            path.append((level, title))
            continue
        if run_start is None:
            run_start = line_start
        run_end = line_start + len(line)
    flush()
    return found


def touched(before: str, after: str, start: int, end: int) -> bool:
    """Whether any change from ``before`` to ``after`` lands in the paragraph of
    ``before`` holding ``[start, end)`` — a pure insertion inside it counts."""
    low = before.rfind("\n\n", 0, start)
    low = 0 if low < 0 else low + 2
    high = before.find("\n\n", end)
    high = len(before) if high < 0 else high
    for hunk in diff_hunks(before, after):
        if hunk.removed:
            if hunk.pos < high and hunk.pos + len(hunk.removed) > low:
                return True
        elif low <= hunk.pos <= high:
            return True
    return False


def anchor_in(
    text: str | None,
    kind: str,
    quote: str,
    *,
    digest: str,
    stamped: str,
    stamped_text: str | None,
) -> Anchor:
    """Judge one quote against a document's text.

    ``digest`` is the document as it is now; ``stamped`` is what the source recorded when
    it was read (``""`` for never) and ``stamped_text`` that version's text, when it is
    still on disk. ``text`` None means the document cannot be read at all.
    """
    if text is None:
        return Anchor("missing", digest=digest)
    if not quote.strip():
        # A citation of the document as a whole: nothing to find, nothing to lose.
        return Anchor("anchored", digest=digest)
    hit = locate(text, quote)
    if hit is not None:
        start, end = hit
        page = None
        pages: tuple[int, ...] = ()
        if kind == "pdf":
            page = page_at(text, start)
            seen = {page_at(text, other) for other, _end in locate_all(text, quote)}
            pages = tuple(sorted(number for number in seen if number is not None))
        state: AnchorState = "anchored"
        if stamped and stamped != digest:
            old = locate(stamped_text, quote) if stamped_text is not None else None
            if old is None or touched(stamped_text or "", text, *old):
                state = "behind"
        return Anchor(state, start, end, page, digest=digest, pages=pages)
    drift = fuzzy_locate(text, quote)
    if drift is None:
        return Anchor("lost", digest=digest)
    start, end, ratio = drift
    page = page_at(text, start) if kind == "pdf" else None
    candidate = " ".join(text[start:end].split())
    return Anchor("drifted", start, end, page, candidate, ratio, digest)


def covered_by(anchors: Sequence[tuple[str, Anchor]], block: Block) -> list[str]:
    """The labels of every found anchor overlapping ``block``, in the order given."""
    return [
        label
        for label, anchor in anchors
        if anchor.found and anchor.start < block.end and anchor.end > block.start
    ]


# -- line walking -----------------------------------------------------------------------------


def _lines(text: str) -> list[tuple[int, str]]:
    found = []
    offset = 0
    for line in text.splitlines(keepends=True):
        found.append((offset, line.rstrip("\r\n")))
        offset += len(line)
    return found


def _page_number(line: str) -> int | None:
    stripped = line.strip()
    if stripped.startswith(PAGE_MARKER) and stripped.endswith(" ---"):
        digits = stripped[len(PAGE_MARKER) : -4]
        if digits.isdigit():
            return int(digits)
    return None


def _heading_level(stripped: str) -> int:
    level = len(stripped) - len(stripped.lstrip("#"))
    if 0 < level <= 6 and (len(stripped) == level or stripped[level] == " "):
        return level
    return 0


def _heading_path(path: Sequence[tuple[int, str]]) -> str:
    return " > ".join(title for _level, title in path)
