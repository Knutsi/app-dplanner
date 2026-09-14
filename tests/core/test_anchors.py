"""Where a quote sits in a document, judged again on every read — the pure text half."""

from functools import cache

from dplanner.core import anchors
from dplanner.core.anchors import (
    Anchor,
    anchor_in,
    blocks,
    covered_by,
    fuzzy_locate,
    locate,
    locate_many,
    normalised,
    page_at,
    touched,
)

SPEC = """# Auth

## Login

Operators MUST be able to import a CSV
of readings in one go.

Every login is logged, with the operator's
name and the time.

## Rules

Passwords expire after ninety days.
"""


def test_normalised_maps_every_character_back_to_its_raw_offset() -> None:
    text = "  Hello,\n\tWorld  "
    flat, back = normalised(text)
    assert flat == "hello, world"
    assert text[back[0]] == "H"
    assert text[back[flat.index("w")]] == "W"
    assert back[-1] == len(text)


def test_locate_finds_a_quote_across_line_breaks_and_case() -> None:
    span = locate(SPEC, "import a csv OF READINGS")
    assert span is not None
    assert SPEC[span[0] : span[1]] == "import a CSV\nof readings"


def test_locate_answers_none_for_a_blank_or_absent_quote() -> None:
    assert locate(SPEC, "   ") is None
    assert locate(SPEC, "Operators MAY export") is None


def test_a_reworded_passage_is_found_fuzzily_with_its_ratio() -> None:
    hit = fuzzy_locate(SPEC, "Operators MUST be able to import a spreadsheet of readings quickly.")
    assert hit is not None
    start, end, ratio = hit
    assert "import a CSV" in SPEC[start:end]
    assert 0.6 <= ratio < 1.0


def test_an_unrelated_quote_is_not_found_fuzzily() -> None:
    assert fuzzy_locate(SPEC, "The dashboard shows a graph of every sensor's readings.") is None


def test_a_short_quote_is_never_matched_fuzzily() -> None:
    assert fuzzy_locate(SPEC, "MUST be") is None


def test_blocks_are_paragraphs_under_their_heading_path() -> None:
    found = blocks(SPEC, "markdown")
    prose = [block for block in found if not block.is_heading]
    assert [SPEC[b.start : b.end].split("\n")[0] for b in prose] == [
        "Operators MUST be able to import a CSV",
        "Every login is logged, with the operator's",
        "Passwords expire after ninety days.",
    ]
    assert [b.heading for b in prose] == ["Auth > Login", "Auth > Login", "Auth > Rules"]
    headings = [block for block in found if block.is_heading]
    assert [SPEC[b.start : b.end] for b in headings] == ["# Auth", "## Login", "## Rules"]


def test_pdf_blocks_carry_their_page_and_page_at_agrees() -> None:
    layer = (
        "--- page 1 ---\nFirst page text.\n\n--- page 2 ---\n"
        "Second page,\nfirst paragraph.\n\nSecond paragraph.\n"
    )
    found = blocks(layer, "pdf")
    assert [(b.page, layer[b.start : b.end]) for b in found] == [
        (1, "First page text."),
        (2, "Second page,\nfirst paragraph."),
        (2, "Second paragraph."),
    ]
    assert page_at(layer, layer.index("Second paragraph")) == 2
    assert page_at(layer, 0) == 1


def test_touched_sees_a_change_in_the_quotes_paragraph_and_ignores_one_elsewhere() -> None:
    span = locate(SPEC, "Every login is logged")
    assert span is not None
    elsewhere = SPEC.replace("ninety days", "thirty days")
    nearby = SPEC.replace("name and the time", "name, the time and the address")
    assert not touched(SPEC, elsewhere, *span)
    assert touched(SPEC, nearby, *span)
    assert touched(SPEC, SPEC.replace("with the operator's", "with the operator's full"), *span)


def test_anchor_in_grades_the_four_states() -> None:
    quote = "Every login is logged, with the operator's name and the time."
    assert anchor_in(None, "markdown", quote, digest="b", stamped="", stamped_text=None).state == (
        "missing"
    )
    fresh = anchor_in(SPEC, "markdown", quote, digest="a", stamped="", stamped_text=None)
    assert fresh.state == "anchored" and fresh.digest == "a"
    assert SPEC[fresh.start : fresh.end].startswith("Every login")
    same = anchor_in(SPEC, "markdown", quote, digest="a", stamped="a", stamped_text=SPEC)
    assert same.state == "anchored"
    elsewhere = SPEC.replace("ninety days", "thirty days")
    quiet = anchor_in(elsewhere, "markdown", quote, digest="b", stamped="a", stamped_text=SPEC)
    assert quiet.state == "anchored"
    nearby = SPEC.replace("Every login is logged", "Every login attempt is logged")
    behind = anchor_in(
        nearby, "markdown", "with the operator's name", digest="b", stamped="a", stamped_text=SPEC
    )
    assert behind.state == "behind"
    gone = anchor_in(nearby, "markdown", quote, digest="b", stamped="a", stamped_text=None)
    assert gone.state == "drifted" and "attempt" in gone.candidate
    lost = anchor_in(
        SPEC,
        "markdown",
        "Nothing like this was ever written down here.",
        digest="a",
        stamped="",
        stamped_text=None,
    )
    assert lost.state == "lost"


def test_a_stamp_whose_blob_is_gone_reads_as_behind() -> None:
    quote = "Passwords expire after ninety days."
    anchor = anchor_in(SPEC, "markdown", quote, digest="b", stamped="a", stamped_text=None)
    assert anchor.state == "behind"


def test_covered_by_names_the_anchors_overlapping_a_block() -> None:
    found = blocks(SPEC, "markdown")
    prose = [block for block in found if not block.is_heading]
    span = locate(SPEC, "import a CSV")
    assert span is not None
    anchors = [
        ("f1", Anchor("anchored", *span)),
        ("f2", Anchor("lost")),
        ("f3", Anchor("drifted", *span, candidate="…")),
    ]
    assert covered_by(anchors, prose[0]) == ["f1"]
    assert covered_by(anchors, prose[1]) == []


def test_locate_many_agrees_with_locate_and_walks_the_document_once(monkeypatch):
    """The Specs tab's wash asks for every cited passage at once. It must give the same
    answer as asking one at a time, and it must normalise the haystack once however many
    quotes there are — that is the whole reason it exists."""
    text = "# Auth\n\nThe user signs in with an e-mail.\n\nSessions expire after a day.\n"
    quotes = ["the user signs in", "sessions  expire", "", "nothing like this"]

    one_at_a_time = [
        (*span, quote) for quote in quotes if (span := locate(text, quote)) is not None
    ]
    assert locate_many(text, quotes) == one_at_a_time

    calls: list[str] = []
    real = anchors.normalised

    def counted(value):
        calls.append(value)
        return real(value)

    monkeypatch.setattr(anchors, "normalised", counted)
    locate_many(text, quotes)
    assert calls.count(text) == 1


def test_a_pass_handed_one_fold_walks_its_document_once_and_judges_the_same() -> None:
    """Normalising the document is what a judgement costs, so a pass over many citations
    hands every one the same memo — and must get exactly the verdicts a fresh walk gives,
    exact, drifted and lost alike."""
    quotes = [
        "Every login is logged",
        "Every login attempt is logged, with the operator's name",
        "Nothing like this was ever written down here.",
        "",
    ]
    walked: list[str] = []

    def fold(text: str) -> tuple[str, list[int]]:
        walked.append(text)
        return normalised(text)

    memo = cache(fold)
    judged = [
        anchor_in(SPEC, "markdown", quote, digest="b", stamped="a", stamped_text=SPEC, fold=memo)
        for quote in quotes
    ]
    fresh = [
        anchor_in(SPEC, "markdown", quote, digest="b", stamped="a", stamped_text=SPEC)
        for quote in quotes
    ]
    assert judged == fresh
    assert [anchor.state for anchor in judged] == ["anchored", "drifted", "lost", "anchored"]
    assert walked == [SPEC]
