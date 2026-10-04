"""Where the coverage picture's facts come from: every module's Qt-free half, read once.

The spec, the feature steps, the collectors, the tests and the docs meet here and nowhere
else; ``trace.py`` only arranges what :func:`readers` hands it. What this package may import
— the planning tier and other modules' ``aspect.py`` — it imports. The rest arrives from the
composition root as plain-typed callables: the spec's anchoring and documents, the test
runs, the docs collection, and the canvas's own status, glyph and milestone shades.
"""

from collections.abc import Callable, Sequence

from dplanner.core.anchors import Anchor
from dplanner.domain.model import Library, Project, Step, StepId
from dplanner.domain.store import FilesFor
from dplanner.modules.coverage.trace import Citation, Document, Feature, Readers, TestRow
from dplanner.modules.docs.aspect import read as docs_read
from dplanner.modules.testing.aspect import covered
from dplanner.planning.feature import is_feature
from dplanner.planning.feature import read as feature_read
from dplanner.planning.kinds import key_of
from dplanner.planning.milestone import read as milestone_read
from dplanner.planning.scope import ScopeKind
from dplanner.planning.status import Status, Unknown

# (files, project, [(document, quote, digest)]) → one anchor per passage, in order.
type Anchoring = Callable[[FilesFor, Project, Sequence[tuple[str, str, str]]], Sequence[Anchor]]
# (kinds, library, project, step) → an answer about that collector's compiled document.
type DocsReader[T] = Callable[[Sequence[ScopeKind], Library, Project, StepId], T]


def covered_tests(
    library: Library,
    project: Project,
    step_id: str,
    stops_at: Callable[[Step], bool] | None = None,
) -> list[tuple[str, str, str]]:
    """What a collector stands for: (test id, test title, owning step's title).

    The one place the collector aspects and the tests aspect meet. None imports another; the
    walk is the domain's and the filtering is testing's, and this hands the pair over as the
    tuple a report can print. ``stops_at`` is where that walk gives way to the next collector
    — passed through rather than interpreted here. Derived on every read: a stored coverage
    list could disagree with the graph the moment ``dplanner step link`` runs with no window
    open to notice.
    """
    return [
        (test.id, test.title, step.title)
        for step, test in covered(library, project, step_id, stops_at=stops_at)
    ]


def readers(
    *,
    kinds: Sequence[ScopeKind],
    anchor: Anchoring,
    documents: Callable[[Project, FilesFor], Sequence[tuple[str, str, str | None]]],
    results: Callable[[Project], dict[str, str]],
    docs_state: DocsReader[str],
    docs_sources: DocsReader[Sequence[object]],
    status: Callable[[Step], Status | Unknown],
    glyph: Callable[[Step], tuple[str, str]],
    milestone_colors: Callable[[Library, Project], dict[StepId, str]],
) -> Readers:
    """The trace's readers, from what each owner answers.

    ``kinds`` are the collectors as the root wires them; ``documents`` is every spec
    document as (name, kind, text); ``results`` is each test's last status word;
    ``docs_state`` and ``docs_sources`` are the docs module's compiled state and what
    compiling would read.
    """
    by_id = {kind.id: kind for kind in kinds}

    def features(library: Library, project: Project, files: FilesFor) -> list[Feature]:
        steps = [step for step in project.steps if is_feature(step)]
        cited = {step.id: feature_read(step) or () for step in steps}
        refs = [(s.document, s.quote, s.digest) for step in steps for s in cited[step.id]]
        anchors = iter(anchor(files, project, refs))
        return [
            Feature(
                step.id,
                step.title,
                step.id,
                tuple(Citation(s.document, s.quote, s.page, next(anchors)) for s in cited[step.id]),
            )
            for step in steps
        ]

    def texts(project: Project, files: FilesFor) -> list[Document]:
        return [Document(name, kind, text) for name, kind, text in documents(project, files)]

    def tests(
        library: Library,
        project: Project,
        step_id: str,
        stops_at: Callable[[Step], bool] | None,
    ) -> list[TestRow]:
        return [
            TestRow(test.id, test.title, step.id, step.title)
            for step, test in covered(library, project, step_id, stops_at=stops_at)
        ]

    def docs(library: Library, project: Project, step_id: str) -> str:
        step = project.step(step_id)
        if step is None:
            return ""
        state = docs_state(kinds, library, project, step_id)
        if state != "never":
            return state
        # Never compiled, but there is something to compile — or a note of its own.
        has_notes = bool(docs_read(step)) or bool(docs_sources(kinds, library, project, step_id))
        return "never" if has_notes else ""

    return Readers(
        features=features,
        documents=texts,
        feature_kind=by_id["feature"],
        milestone_kind=by_id["step_milestone"],
        milestone_label=milestone_read,
        step_key=key_of,
        status=status,
        tests=tests,
        results=results,
        docs=docs,
        # The milestone lane wears the same shades the canvas and the calendar do, and a
        # card that is a step the canvas's glyph in its key block.
        milestone_colors=milestone_colors,
        glyph=glyph,
    )
