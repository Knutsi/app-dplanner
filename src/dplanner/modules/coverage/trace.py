"""The trace: spec passages → features → milestones → tests and docs, as one picture.

Nothing here is stored. A feature record says which passages it was read from, the graph
says which milestone gathers its step and which tests sit in its cone, and the docs
module says whether its compiled document is current — four facts four modules own, and
this file only *arranges* them into columns and the links between neighbours. It reads
every one through a callable on :class:`Readers`, handed in by the composition root, so
the coverage module imports no other module and the picture cannot disagree with the
verbs that wrote it.

**The path rule is feature membership.** Every item carries the features it serves: a
passage the features citing it, a feature itself, a milestone the features it gathers, a
test or a docs card the feature whose cone holds its step. Asking what lights up when
one item is picked is then one set intersection — a feature lights exactly its chain, a
milestone everything behind it, a passage two features cite both — with no special case
per kind. A milestone also carries a token of its own, so the tests and docs it holds
*directly* (work under it that no feature gathers) belong to it and to nothing else.

Two readers: the Coverage tab draws it, ``dplanner coverage …`` prints it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from dplanner.core.anchors import Anchor, blocks, covered_by
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import StepPredicate, gatherers
from dplanner.domain.store import FilesFor

SPEC, FEATURES, MILESTONES, OUTCOMES = 0, 1, 2, 3
COLUMN_TITLES = ("Spec", "Features", "Milestones", "Tests & Docs")
NO_MILESTONE = "bucket:none"
UNTITLED = "Untitled"


# -- what the readers hand in --------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """One passage a feature was read from, judged against the document as it is now."""

    document: str
    quote: str
    page: int | None
    anchor: Anchor


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    step: StepId | None  # The step realising it; None while it is unplaced.
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Document:
    name: str
    kind: str  # "markdown" | "pdf" | "text"
    text: str | None  # None when the blob cannot be read.


@dataclass(frozen=True)
class TestRow:
    __test__ = False  # Not a pytest class, whatever the name says.

    id: str
    title: str
    step: StepId
    step_title: str


def _no_colors(_library: Library, _project: Project) -> dict[StepId, str]:
    """No colour map reaches this build; every milestone keeps the constant tone."""
    return {}


@dataclass(frozen=True)
class Readers:
    """Every fact the trace is built from, as the module owning it answers it."""

    features: Callable[[Library, Project, FilesFor], Sequence[Feature]]
    documents: Callable[[Project, FilesFor], Sequence[Document]]
    is_feature: StepPredicate
    is_milestone: StepPredicate
    milestone_label: Callable[[Step], str]
    is_done: StepPredicate
    # (library, project, step, stops_at) → the tests at and behind a step.
    tests: Callable[[Library, Project, StepId, StepPredicate | None], Sequence[TestRow]]
    results: Callable[[Project], dict[str, str]]  # test id → how it last did.
    # (library, project, step) → "current" | "stale" | "never", or "" for nothing to show.
    docs: Callable[[Library, Project, StepId], str]
    # Every milestone's own shade of the project's colour map, by step id — one deal per
    # project, the same one the canvas and the calendar read.
    milestone_colors: Callable[[Library, Project], dict[StepId, str]] = _no_colors


# -- the picture ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    # "doc:<name>" | "passage:<name>:<n>" | "feature:<id>" | "milestone:<step>" |
    # NO_MILESTONE | "test:<id>" | "docs:<step>"
    id: str
    column: int
    title: str
    detail: str = ""  # The secondary line.
    tone: str = ""  # A body tone from theme/tones.py, "" for plain.
    # A milestone's own shade of the project's colour map, recolouring ``tone`` at its
    # own alphas (``theme/tones.py``'s ``toned``). "" leaves the tone the constant it is.
    color: str = ""
    state: str = ""  # An anchor state, a docs state, a test result — one word, drawn as a mark.
    features: frozenset[str] = frozenset()
    target: tuple[str, str] = ("", "")  # What double-clicking opens: (kind, key).
    muted: bool = False


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    features: frozenset[str]


@dataclass(frozen=True)
class CoveredBlock:
    start: int
    end: int
    heading: str
    page: int | None
    is_heading: bool
    text: str
    features: tuple[str, ...]  # The features whose passages overlap it.


@dataclass(frozen=True)
class DocumentCoverage:
    name: str
    kind: str
    readable: bool
    blocks: tuple[CoveredBlock, ...]
    review: int  # Passages of this document not anchored: behind, drifted, lost.

    @property
    def paragraphs(self) -> int:
        return sum(1 for block in self.blocks if not block.is_heading)

    @property
    def cited(self) -> int:
        return sum(1 for block in self.blocks if not block.is_heading and block.features)

    @property
    def summary(self) -> str:
        if not self.readable:
            return "cannot be read"
        said = f"{self.cited} of {self.paragraphs} paragraphs cited"
        if self.review:
            said += f" · {self.review} to review"
        return said


@dataclass(frozen=True)
class Path:
    items: frozenset[str]
    links: frozenset[int]  # Indexes into ``Trace.links``.


@dataclass(frozen=True)
class Trace:
    items: tuple[Item, ...]
    links: tuple[Link, ...]
    documents: tuple[DocumentCoverage, ...]
    unsourced: tuple[Feature, ...]  # Features that cite nothing.

    def item(self, item_id: str) -> Item | None:
        return next((item for item in self.items if item.id == item_id), None)

    def column(self, column: int) -> list[Item]:
        return [item for item in self.items if item.column == column]

    def path(self, item_id: str) -> Path:
        """Everything sharing a feature with ``item_id`` — its upstream and downstream."""
        picked = self.item(item_id)
        if picked is None:
            return Path(frozenset(), frozenset())
        tokens = picked.features
        if not tokens:
            return Path(frozenset({item_id}), frozenset())
        return Path(
            frozenset(item.id for item in self.items if item.features & tokens),
            frozenset(index for index, link in enumerate(self.links) if link.features & tokens),
        )


def milestone_token(step_id: StepId) -> str:
    return f"milestone:{step_id}"


def flat(quote: str) -> str:
    return " ".join(quote.lower().split())


def build(readers: Readers, library: Library, project: Project, files: FilesFor) -> Trace:
    """The trace of one project, from what the readers say now."""
    features = list(readers.features(library, project, files))
    documents = list(readers.documents(project, files))
    order = {step.id: index for index, step in enumerate(project.steps)}
    milestones = [step for step in project.steps if readers.is_milestone(step)]
    owners = gatherers(
        library, project, carried_by=readers.is_milestone, stops_at=readers.is_milestone
    )
    known = {milestone.id for milestone in milestones}

    def milestones_of(feature: Feature) -> list[StepId]:
        if feature.step is None:
            return []
        found = [held for held in owners.get(feature.step, ()) if held in known]
        return sorted(found, key=lambda held: order[held])

    def rank(feature: Feature) -> tuple[int, int]:
        held = milestones_of(feature)
        first = order[held[0]] if held else len(order) + 1
        return first, features.index(feature)

    ordered = sorted(features, key=rank)
    items: list[Item] = []
    links: list[Link] = []

    # Column 0: every document, its passages under it.
    coverage: list[DocumentCoverage] = []
    for document in documents:
        cited: dict[str, tuple[Citation, list[str]]] = {}
        for feature in ordered:
            for citation in feature.citations:
                if citation.document != document.name:
                    continue
                key = flat(citation.quote)
                if key not in cited:
                    cited[key] = (citation, [])
                cited[key][1].append(feature.id)
        passages = sorted(
            cited.values(),
            key=lambda pair: (
                not pair[0].anchor.found,
                pair[0].anchor.start if pair[0].anchor.found else 0,
            ),
        )
        anchored = [(fid, cit.anchor) for cit, fids in cited.values() for fid in fids]
        covered = _coverage(document, anchored)
        coverage.append(covered)
        every = frozenset(fid for _cit, fids in passages for fid in fids)
        items.append(
            Item(
                f"doc:{document.name}",
                SPEC,
                document.name,
                covered.summary,
                features=every,
                target=("document", document.name),
                muted=not passages,
            )
        )
        for number, (citation, fids) in enumerate(passages):
            page = f"p.{citation.page}" if citation.page is not None else ""
            items.append(
                Item(
                    f"passage:{document.name}:{number}",
                    SPEC,
                    _first_line(citation.quote) or "the whole document",
                    page,
                    state=citation.anchor.state,
                    features=frozenset(fids),
                    target=("passage", f"{document.name}\0{citation.quote}"),
                )
            )
            for fid in fids:
                links.append(
                    Link(f"passage:{document.name}:{number}", f"feature:{fid}", frozenset({fid}))
                )

    # Column 1: the features, milestone-first so the lines to column 2 rarely cross.
    steps = {step.id: step for step in project.steps}
    for feature in ordered:
        step = steps.get(feature.step) if feature.step else None
        done = step is not None and readers.is_done(step)
        items.append(
            Item(
                f"feature:{feature.id}",
                FEATURES,
                feature.title or UNTITLED,
                "" if step is not None else "not placed",
                tone="good" if done else "feature",
                features=frozenset({feature.id}),
                target=("step", step.id) if step is not None else ("feature", feature.id),
                muted=step is None,
            )
        )

    # Column 2: the milestones, and a bucket for what none gathers.
    gathered: dict[StepId, list[Feature]] = {milestone.id: [] for milestone in milestones}
    loose: list[Feature] = []
    for feature in ordered:
        held = milestones_of(feature)
        if feature.step is not None and not held:
            loose.append(feature)
        for milestone_id in held:
            gathered[milestone_id].append(feature)
            links.append(
                Link(
                    f"feature:{feature.id}", milestone_token(milestone_id), frozenset({feature.id})
                )
            )
    colors = readers.milestone_colors(library, project)
    for milestone in milestones:
        members = gathered[milestone.id]
        label = readers.milestone_label(milestone)
        count = f"{len(members)} feature{'' if len(members) == 1 else 's'}"
        items.append(
            Item(
                milestone_token(milestone.id),
                MILESTONES,
                milestone.title or UNTITLED,
                f"{label} · {count}" if label else count,
                tone="highlight",
                color=colors.get(milestone.id, ""),
                features=frozenset({f.id for f in members} | {milestone_token(milestone.id)}),
                target=("step", milestone.id),
            )
        )
    if loose:
        items.append(
            Item(
                NO_MILESTONE,
                MILESTONES,
                "Not in a milestone",
                f"{len(loose)} feature{'' if len(loose) == 1 else 's'}",
                features=frozenset(f.id for f in loose),
                muted=True,
            )
        )
        for feature in loose:
            links.append(Link(f"feature:{feature.id}", NO_MILESTONE, frozenset({feature.id})))

    # Column 3: each feature's tests and docs, then what a milestone holds directly.
    results = readers.results(project)
    placed_tests: dict[str, int] = {}  # test id → index in items, to union a shared one.

    def feature_stop(step: Step) -> bool:
        return readers.is_feature(step) or readers.is_milestone(step)

    def add_tests(rows: Sequence[TestRow], tokens: frozenset[str], sources: Sequence[str]) -> None:
        for row in rows:
            if row.id in placed_tests:
                index = placed_tests[row.id]
                held = items[index]
                # One field changes; naming the other nine positionally is how a new field
                # lands in the wrong one.
                items[index] = replace(held, features=held.features | tokens)
            else:
                placed_tests[row.id] = len(items)
                items.append(
                    Item(
                        f"test:{row.id}",
                        OUTCOMES,
                        row.title or UNTITLED,
                        f"{row.id} · {row.step_title or UNTITLED}",
                        state=results.get(row.id, "pending"),
                        features=tokens,
                        target=("test", f"{row.step}\0{row.id}"),
                    )
                )
            for source in sources:
                links.append(Link(source, f"test:{row.id}", tokens))

    def add_docs(
        step_id: StepId, title: str, tokens: frozenset[str], sources: Sequence[str]
    ) -> None:
        state = readers.docs(library, project, step_id)
        if not state:
            return
        items.append(
            Item(
                f"docs:{step_id}",
                OUTCOMES,
                title or UNTITLED,
                "docs",
                state=state,
                features=tokens,
                target=("docs", step_id),
            )
        )
        for source in sources:
            links.append(Link(source, f"docs:{step_id}", tokens))

    for feature in ordered:
        if feature.step is None:
            continue
        held = milestones_of(feature)
        sources = [milestone_token(m) for m in held] or [NO_MILESTONE]
        tokens = frozenset({feature.id})
        add_tests(readers.tests(library, project, feature.step, feature_stop), tokens, sources)
        add_docs(feature.step, feature.title, tokens, sources)
    for milestone in milestones:
        token = milestone_token(milestone.id)
        direct = [
            row
            for row in readers.tests(library, project, milestone.id, readers.is_milestone)
            if row.id not in placed_tests
        ]
        add_tests(direct, frozenset({token}), [token])
        tokens = frozenset({f.id for f in gathered[milestone.id]} | {token})
        add_docs(milestone.id, milestone.title, tokens, [token])

    unsourced = tuple(feature for feature in features if not feature.citations)
    return Trace(tuple(items), tuple(links), tuple(coverage), unsourced)


def _coverage(document: Document, anchored: Sequence[tuple[str, Anchor]]) -> DocumentCoverage:
    review = sum(1 for _fid, anchor in anchored if anchor.state != "anchored")
    if document.text is None:
        return DocumentCoverage(document.name, document.kind, False, (), review)
    found = []
    for block in blocks(document.text, document.kind):
        cited = list(dict.fromkeys(covered_by(anchored, block)))
        found.append(
            CoveredBlock(
                block.start,
                block.end,
                block.heading,
                block.page,
                block.is_heading,
                document.text[block.start : block.end],
                tuple(cited),
            )
        )
    return DocumentCoverage(document.name, document.kind, True, tuple(found), review)


def _first_line(quote: str) -> str:
    lines = quote.strip().splitlines()
    return lines[0].strip() if lines else ""
