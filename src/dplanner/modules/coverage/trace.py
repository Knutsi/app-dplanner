"""The trace: milestones → features → spec passages → steps → tests and docs, as one picture.

Nothing here is stored. A feature record says which passages it was read from, the graph
says which milestone gathers its step and which steps and tests sit in its cone, and the
docs module says whether its compiled document is current — four facts four modules own,
and this file only *arranges* them into columns and the links between neighbours. It reads
every one through a callable on :class:`Readers`, handed in by the composition root, so
the coverage module imports no other module and the picture cannot disagree with the
verbs that wrote it.

**The columns are a drill-down, and the plan leads it.** A milestone gathers features, a
feature was read from passages, holds steps and is proven by tests and documents — so the
picture opens on what a person has in their head (the milestones, and every feature) and
:meth:`Trace.shown` says what the picks stand up: the features the picked milestones
gather, and the spec, the steps and the outcomes of the picked features alone. A whole
plan's passages dealt out at once is a wall nobody reads.

**The path rule is feature membership.** Every item carries the features it serves: a
passage the features citing it, a feature itself, a milestone the features it gathers, a
step, a test or a docs card the feature whose cone holds it. Asking what lights up when
one item is picked is then one set intersection — a feature lights exactly its chain, a
milestone everything behind it, a passage two features cite both — with no special case
per kind. An item that *can* be picked also carries a ``token`` of its own: what it
contributes when it is, which is why a milestone stands up the work it holds directly
(work under it that no feature gathers) and never its features' whole spec.

**A link is recorded for every pair of columns that can stand side by side.** The steps
column is a lane the tab shows only when asked, so a document joins its features' tests
and documents directly *and* joins the steps they sit on, which join them in turn; the tab
draws whichever pairs are neighbours in the lanes it is showing.

Two readers: the Coverage tab draws it, ``dplanner coverage …`` prints it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from dplanner.core.anchors import Anchor, blocks, covered_by
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.scope import StepPredicate, cone, gatherers
from dplanner.domain.store import FilesFor

MILESTONES, FEATURES, SPEC, STEPS, OUTCOMES = 0, 1, 2, 3, 4
COLUMN_TITLES = ("Milestones", "Features", "Spec", "Steps", "Tests & Docs")
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
    id: str  # The step's — a feature *is* a step, so the two ids are one.
    title: str
    step: StepId
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
    step_key: Callable[[Step], str]  # How every surface names a step: "S7".
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
    # NO_MILESTONE | "step:<step>" | "test:<id>" | "docs:<step>"
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
    # What picking this item stands up: a feature's own id, a milestone's own token, ""
    # for an item that is an answer rather than a question (a passage, a test, a document).
    token: str = ""
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
class Trace:
    items: tuple[Item, ...]
    links: tuple[Link, ...]
    documents: tuple[DocumentCoverage, ...]
    unsourced: tuple[Feature, ...]  # Features that cite nothing.

    def item(self, item_id: str) -> Item | None:
        return next((item for item in self.items if item.id == item_id), None)

    def column(self, column: int) -> list[Item]:
        return [item for item in self.items if item.column == column]

    def shown(self, picked: frozenset[str]) -> frozenset[str]:
        """Which items stand while ``picked`` is picked — the lanes' drill-down.

        Every milestone, always: that is the question the picture opens on. The features
        the picked milestones gather, or every feature while no milestone is picked. And
        in the spec, steps and outcome lanes, what the picks *themselves* stand for — a
        picked feature's passages, steps, tests and documents, a picked milestone's own
        direct work — never what a milestone's features reach, which is the wall the
        drill-down avoids.
        """
        chosen = [item for item in self.items if item.id in picked]
        milestones = [item for item in chosen if item.column == MILESTONES]
        standing = {item.id for item in self.items if item.column == MILESTONES}
        gathered: set[str] = set()
        for item in milestones:
            gathered |= item.features
        for item in self.items:
            if item.column == FEATURES and (not milestones or item.features & gathered):
                standing.add(item.id)
        focus = {item.token for item in chosen if item.token and item.id in standing}
        if focus:
            for item in self.items:
                if item.column in (SPEC, STEPS, OUTCOMES) and item.features & focus:
                    standing.add(item.id)
        return frozenset(standing)

    def path(self, item_id: str) -> frozenset[str]:
        """Everything sharing a feature with ``item_id`` — its upstream and its
        downstream, which is what ``coverage show --feature`` cuts the report down to."""
        picked = self.item(item_id)
        if picked is None:
            return frozenset()
        if not picked.features:
            return frozenset({item_id})
        return frozenset(item.id for item in self.items if item.features & picked.features)


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
        found = [held for held in owners.get(feature.step, ()) if held in known]
        return sorted(found, key=lambda held: order[held])

    def rank(feature: Feature) -> tuple[int, int]:
        held = milestones_of(feature)
        first = order[held[0]] if held else len(order) + 1
        return first, features.index(feature)

    ordered = sorted(features, key=rank)
    items: list[Item] = []
    joined: dict[tuple[str, str], set[str]] = {}
    # Which document cards each feature was read from, in the order the documents come:
    # the spec lane's hubs, and where a test's or a document's line is drawn from.
    hubs: dict[str, list[str]] = {}

    def join(source: str, target: str, tokens: frozenset[str]) -> None:
        """One line per neighbouring pair, whatever says so — two features citing one
        passage out of one document is one line from that document to their shared test."""
        joined.setdefault((source, target), set()).update(tokens)

    def spec_hubs(tokens: frozenset[str]) -> list[str]:
        found: list[str] = []
        for feature in ordered:
            if feature.id in tokens:
                found += [hub for hub in hubs.get(feature.id, ()) if hub not in found]
        return found

    # The spec lane: every document, its passages under it.
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
        for feature in ordered:
            if feature.id in every:
                hubs.setdefault(feature.id, []).append(f"doc:{document.name}")
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
                join(f"feature:{fid}", f"passage:{document.name}:{number}", frozenset({fid}))

    # The features lane, milestone-first so the lines to the milestones rarely cross.
    steps = {step.id: step for step in project.steps}
    for feature in ordered:
        step = steps.get(feature.step)
        done = step is not None and readers.is_done(step)
        items.append(
            Item(
                f"feature:{feature.id}",
                FEATURES,
                feature.title or UNTITLED,
                "",
                tone="good" if done else "feature",
                features=frozenset({feature.id}),
                token=feature.id,
                target=("feature", feature.id),
            )
        )

    # The milestones lane, and a bucket for what none gathers.
    gathered: dict[StepId, list[Feature]] = {milestone.id: [] for milestone in milestones}
    loose: list[Feature] = []
    for feature in ordered:
        held = milestones_of(feature)
        if not held:
            loose.append(feature)
        for milestone_id in held:
            gathered[milestone_id].append(feature)
            join(milestone_token(milestone_id), f"feature:{feature.id}", frozenset({feature.id}))
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
                token=milestone_token(milestone.id),
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
                token=NO_MILESTONE,
                muted=True,
            )
        )
        for feature in loose:
            join(NO_MILESTONE, f"feature:{feature.id}", frozenset({feature.id}))

    # The steps and outcomes lanes: each feature's steps, tests and docs, then what a
    # milestone holds directly. A test or a document hangs off the document its feature was
    # read from — a line from every passage to every test of the same feature is one claim
    # drawn a dozen times over — and off the step it sits on, for the lanes with the steps
    # standing between the two.
    results = readers.results(project)
    placed_steps: dict[StepId, int] = {}  # step id → index in items, to union a shared one.
    placed_tests: dict[str, int] = {}  # test id → index in items, to union a shared one.

    def feature_stop(step: Step) -> bool:
        return readers.is_feature(step) or readers.is_milestone(step)

    def held_by(root: StepId, stops_at: StepPredicate) -> list[Step]:
        """The steps a collector holds: its cone, and its own step, where a test or a
        document of its own sits."""
        found = cone(library, project, root, stops_at=stops_at).steps
        own = steps.get(root)
        return [*found, *([own] if own is not None else [])]

    def step_hubs(tokens: frozenset[str]) -> list[str]:
        """The cards of the collectors' own steps behind ``tokens``: where a document sits."""
        found = [f"step:{feature.step}" for feature in ordered if feature.id in tokens]
        found += [f"step:{m.id}" for m in milestones if milestone_token(m.id) in tokens]
        return found

    def add_steps(held: Sequence[Step], tokens: frozenset[str], sources: Sequence[str]) -> None:
        for step in held:
            if step.id in placed_steps:
                index = placed_steps[step.id]
                items[index] = replace(items[index], features=items[index].features | tokens)
            else:
                placed_steps[step.id] = len(items)
                items.append(
                    Item(
                        f"step:{step.id}",
                        STEPS,
                        step.title or UNTITLED,
                        readers.step_key(step),
                        tone="good" if readers.is_done(step) else "",
                        features=tokens,
                        target=("step", step.id),
                    )
                )
            for source in sources:
                join(source, f"step:{step.id}", tokens)

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
                join(source, f"test:{row.id}", tokens)
            join(f"step:{row.step}", f"test:{row.id}", tokens)

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
            join(source, f"docs:{step_id}", tokens)

    for feature in ordered:
        tokens = frozenset({feature.id})
        sources = spec_hubs(tokens)
        add_steps(held_by(feature.step, feature_stop), tokens, sources)
        add_tests(readers.tests(library, project, feature.step, feature_stop), tokens, sources)
        add_docs(feature.step, feature.title, tokens, [*sources, *step_hubs(tokens)])
    for milestone in milestones:
        token = milestone_token(milestone.id)
        # Work a milestone holds directly was read from no passage: it stands under the
        # milestone's own pick, with nothing in the spec lane to come from.
        own = frozenset({token})
        work = held_by(milestone.id, readers.is_milestone)
        add_steps([step for step in work if step.id not in placed_steps], own, ())
        direct = [
            row
            for row in readers.tests(library, project, milestone.id, readers.is_milestone)
            if row.id not in placed_tests
        ]
        add_tests(direct, own, ())
        tokens = frozenset({f.id for f in gathered[milestone.id]} | {token})
        add_docs(milestone.id, milestone.title, tokens, [*spec_hubs(tokens), *step_hubs(tokens)])

    links = [Link(source, target, frozenset(tokens)) for (source, target), tokens in joined.items()]
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
